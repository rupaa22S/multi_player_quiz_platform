# routes/room.py - Room creation and management endpoints

import random
import string
import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import Room, User, Question
from ai_service import generate_questions
from websocket_manager import manager

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class CreateRoomRequest(BaseModel):
    admin_name: str
    quiz_topic: str
    difficulty: str       # easy / medium / hard
    num_questions: int
    question_type: str    # mcq / blank


class StartQuizRequest(BaseModel):
    room_code: str
    admin_id: int


class EndQuizRequest(BaseModel):
    room_code: str
    admin_id: int


# ── Helpers ───────────────────────────────────────────────────────────────────

def generate_room_code(db: Session) -> str:
    """Generate a unique 6-character alphanumeric room code."""
    while True:
        code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not db.query(Room).filter(Room.room_code == code).first():
            return code


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/create-room")
async def create_room(request: CreateRoomRequest, db: Session = Depends(get_db)):
    """
    1. Validate input
    2. Generate a unique room code
    3. Create admin user
    4. Call AI to generate questions
    5. Store everything in the database
    6. Return room_code and admin user_id to the frontend
    """
    # Basic validation
    if request.num_questions < 1 or request.num_questions > 20:
        raise HTTPException(status_code=400, detail="Number of questions must be between 1 and 20.")
    if request.difficulty not in ("easy", "medium", "hard"):
        raise HTTPException(status_code=400, detail="Difficulty must be easy, medium, or hard.")
    if request.question_type not in ("mcq", "blank"):
        raise HTTPException(status_code=400, detail="Question type must be mcq or blank.")

    try:
        # Generate AI questions BEFORE writing to DB (fail fast if AI is down)
        logger.info(f"Generating {request.num_questions} {request.question_type} questions on '{request.quiz_topic}'")
        ai_questions = await generate_questions(
            topic=request.quiz_topic,
            difficulty=request.difficulty,
            num_questions=request.num_questions,
            question_type=request.question_type,
        )
    except Exception as e:
        logger.error(f"AI question generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate questions: {str(e)}")

    # Create room record
    room_code = generate_room_code(db)
    room = Room(
        room_code=room_code,
        admin_name=request.admin_name,
        quiz_topic=request.quiz_topic,
        difficulty=request.difficulty,
        num_questions=request.num_questions,
        question_type=request.question_type,
        status="waiting",
    )
    db.add(room)
    db.flush()  # get room.id without committing

    # Create admin user entry
    admin_user = User(
        name=request.admin_name,
        room_id=room.id,
        is_admin=True,
    )
    db.add(admin_user)
    db.flush()

    # Store generated questions
    for q in ai_questions:
        question = Question(
            room_id=room.id,
            question_text=q.get("question", ""),
            type=q.get("type", request.question_type),
            correct_answer=q.get("correct_answer", ""),
        )
        question.options = q.get("options", [])
        db.add(question)

    db.commit()
    db.refresh(room)
    db.refresh(admin_user)

    logger.info(f"Room {room_code} created by {request.admin_name} with {len(ai_questions)} questions")

    return {
        "room_code": room_code,
        "admin_id": admin_user.id,
        "num_questions": len(ai_questions),
        "message": "Room created successfully!",
    }


@router.post("/start-quiz")
async def start_quiz(request: StartQuizRequest, db: Session = Depends(get_db)):
    """Change room status to 'started' and broadcast all questions via WebSocket."""
    room = db.query(Room).filter(Room.room_code == request.room_code).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    admin = db.query(User).filter(User.id == request.admin_id, User.is_admin == True).first()
    if not admin:
        raise HTTPException(status_code=403, detail="Only the admin can start the quiz.")

    if room.status != "waiting":
        raise HTTPException(status_code=400, detail=f"Quiz is already {room.status}.")

    # Update room status
    room.status = "started"
    db.commit()

    # Serialize questions to send via WebSocket
    questions_payload = []
    for q in room.questions:
        questions_payload.append({
            "id": q.id,
            "question_text": q.question_text,
            "type": q.type,
            "options": q.options,
            # Never send correct_answer to users!
        })

    # Broadcast quiz start + questions to all users in the room
    await manager.broadcast(request.room_code, {
        "event": "quiz_started",
        "questions": questions_payload,
    })

    logger.info(f"Quiz started in room {request.room_code}")
    return {"message": "Quiz started!", "num_questions": len(questions_payload)}


@router.post("/end-quiz")
async def end_quiz(request: EndQuizRequest, db: Session = Depends(get_db)):
    """End the quiz, calculate scores, and broadcast results."""
    room = db.query(Room).filter(Room.room_code == request.room_code).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    admin = db.query(User).filter(User.id == request.admin_id, User.is_admin == True).first()
    if not admin:
        raise HTTPException(status_code=403, detail="Only the admin can end the quiz.")

    room.status = "closed"
    db.commit()

    # Build leaderboard
    participants = db.query(User).filter(
        User.room_id == room.id,
        User.is_admin == False
    ).order_by(User.score.desc()).all()

    leaderboard = [
        {"rank": i + 1, "name": u.name, "score": u.score}
        for i, u in enumerate(participants)
    ]

    # Broadcast results to everyone
    await manager.broadcast(request.room_code, {
        "event": "quiz_ended",
        "leaderboard": leaderboard,
    })

    logger.info(f"Quiz ended in room {request.room_code}")
    return {"message": "Quiz ended!", "leaderboard": leaderboard}


@router.delete("/remove-user/{user_id}")
async def remove_user(user_id: int, room_code: str, db: Session = Depends(get_db)):
    """Admin removes/kicks a user from the room."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.is_admin:
        raise HTTPException(status_code=400, detail="Cannot remove the admin.")

    room = db.query(Room).filter(Room.id == user.room_id).first()
    user_name = user.name

    db.delete(user)
    db.commit()

    # Notify the kicked user and everyone else
    await manager.send_to_user(room_code, user_id, {"event": "kicked"})
    await manager.broadcast(room_code, {
        "event": "user_left",
        "user_id": user_id,
        "user_name": user_name,
        "users": manager.get_user_list(room_code),
    })

    return {"message": f"{user_name} has been removed."}
