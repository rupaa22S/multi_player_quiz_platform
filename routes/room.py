import random
import string
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from database import get_db
from models import Room, User, Question
from ai_service import generate_questions
from websocket_manager import manager

router = APIRouter()


class CreateRoomRequest(BaseModel):
    admin_name: str
    admin_email: str | None = None
    auth_email: str | None = None
    quiz_topic: str
    difficulty: str
    num_questions: int
    question_type: str


class RoomActionRequest(BaseModel):
    room_code: str
    admin_id: int


def generate_room_code(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


@router.post("/create-room")
async def create_room(payload: CreateRoomRequest, db: Session = Depends(get_db)):
    if not payload.admin_name.strip():
        raise HTTPException(status_code=400, detail="Admin name is required.")

    admin_email = (payload.admin_email or payload.auth_email or "").strip().lower()
    if not admin_email:
        raise HTTPException(status_code=400, detail="Admin email is required.")

    if payload.difficulty not in ["easy", "medium", "hard"]:
        raise HTTPException(status_code=400, detail="Difficulty must be easy, medium, or hard.")

    if payload.question_type not in ["mcq", "blank"]:
        raise HTTPException(status_code=400, detail="Question type must be mcq or blank.")

    if payload.num_questions < 1 or payload.num_questions > 12:
        raise HTTPException(status_code=400, detail="Number of questions must be between 1 and 12.")

    room_code = generate_room_code()
    while db.query(Room).filter(Room.room_code == room_code).first():
        room_code = generate_room_code()

    try:
        questions_data = await generate_questions(
            payload.quiz_topic,
            payload.difficulty,
            payload.num_questions,
            payload.question_type,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to generate questions: {exc}")

    if len(questions_data) != payload.num_questions:
        raise HTTPException(
            status_code=500,
            detail=f"AI returned {len(questions_data)} questions, expected {payload.num_questions}.",
        )

    room = Room(
        room_code=room_code,
        admin_name=payload.admin_name.strip(),
        created_at=datetime.utcnow().isoformat(timespec="seconds"),
        quiz_topic=payload.quiz_topic.strip(),
        difficulty=payload.difficulty,
        num_questions=payload.num_questions,
        question_type=payload.question_type,
        status="waiting",
    )
    db.add(room)
    db.commit()
    db.refresh(room)

    for question_item in questions_data:
        question = Question(
            room_id=room.id,
            question_text=question_item.get("question", "Untitled question"),
            type=question_item.get("type", payload.question_type),
            correct_answer=str(question_item.get("correct_answer", "")).strip(),
        )
        question.options = question_item.get("options", [])
        db.add(question)

    admin_user = User(
        name=payload.admin_name.strip(),
        email=admin_email,
        room_id=room.id,
        is_admin=True,
        score=0,
    )
    db.add(admin_user)
    db.commit()
    db.refresh(admin_user)

    return {
        "room_code": room.room_code,
        "room_id": room.id,
        "admin_id": admin_user.id,
        "admin_name": admin_user.name,
        "admin_email": admin_user.email,
        "status": room.status,
    }


@router.post("/start-quiz")
async def start_quiz(payload: RoomActionRequest, db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.room_code == payload.room_code).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    admin = db.query(User).filter(User.id == payload.admin_id, User.room_id == room.id, User.is_admin.is_(True)).first()
    if not admin:
        raise HTTPException(status_code=403, detail="Only the room admin can start the quiz.")

    if room.status != "waiting":
        raise HTTPException(status_code=400, detail="Quiz has already started or the room is closed.")

    room.status = "started"
    db.commit()

    questions = [
        {
            "id": question.id,
            "question_text": question.question_text,
            "type": question.type,
            "options": question.options,
        }
        for question in room.questions
    ]

    await manager.broadcast(room.room_code, {
        "event": "quiz_started",
        "room_code": room.room_code,
        "questions": questions,
    })

    return {"message": "Quiz started.", "room_code": room.room_code}


@router.post("/end-quiz")
async def end_quiz(payload: RoomActionRequest, db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.room_code == payload.room_code).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    admin = db.query(User).filter(User.id == payload.admin_id, User.room_id == room.id, User.is_admin.is_(True)).first()
    if not admin:
        raise HTTPException(status_code=403, detail="Only the room admin can end the quiz.")

    if room.status == "closed":
        raise HTTPException(status_code=400, detail="Room is already closed.")

    room.status = "closed"
    db.commit()

    leaderboard = [
        {
            "user_id": user.id,
            "name": user.name,
            "score": user.score,
        }
        for user in sorted(room.users, key=lambda u: u.score, reverse=True)
        if not user.is_admin
    ]

    await manager.broadcast(room.room_code, {
        "event": "quiz_ended",
        "room_code": room.room_code,
        "leaderboard": leaderboard,
    })

    return {"message": "Quiz ended.", "leaderboard": leaderboard}


@router.get("/admin/questions/{room_code}")
async def get_admin_questions(room_code: str, admin_id: int, db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.room_code == room_code.strip().upper()).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    admin = db.query(User).filter(
        User.id == admin_id,
        User.room_id == room.id,
        User.is_admin.is_(True),
    ).first()
    if not admin:
        raise HTTPException(status_code=403, detail="Only the room admin can view questions.")

    questions = [
        {
            "id": question.id,
            "question_text": question.question_text,
            "type": question.type,
            "options": question.options,
            "correct_answer": question.correct_answer,
        }
        for question in room.questions
    ]

    return {
        "room_code": room.room_code,
        "questions": questions,
    }


@router.delete("/remove-user/{user_id}")
async def remove_user(user_id: int, admin_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    room = db.query(Room).filter(Room.id == user.room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    admin = db.query(User).filter(
        User.id == admin_id,
        User.room_id == room.id,
        User.is_admin.is_(True),
    ).first()
    if not admin:
        raise HTTPException(status_code=403, detail="Only the room admin can remove users.")

    if user.is_admin:
        raise HTTPException(status_code=400, detail="The admin cannot be removed from the room.")

    room_code = user.room.room_code
    user_name = user.name
    db.delete(user)
    db.commit()

    updated_users = [
        item
        for item in manager.get_user_list(room_code)
        if item["user_id"] != user_id
    ]

    await manager.send_to_user(room_code, user_id, {
        "event": "kicked",
        "message": "You have been removed from the room by the admin.",
    })

    await manager.broadcast(room_code, {
        "event": "user_left",
        "user_id": user_id,
        "user_name": user_name,
        "users": updated_users,
    })

    return {"message": "User removed.", "user_id": user_id}
