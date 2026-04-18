from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import Room, User, Question, Answer
from ai_service import evaluate_blank_answer
from websocket_manager import manager

router = APIRouter()


class SubmitAnswersRequest(BaseModel):
    room_code: str
    user_id: int
    answers: list[dict]


def build_question_results(db: Session, room: Room, user: User) -> list[dict]:
    """Build a per-question breakdown for a user's submitted answers."""
    question_results = []
    for question in room.questions:
        answer = (
            db.query(Answer)
            .filter(Answer.user_id == user.id, Answer.question_id == question.id)
            .first()
        )
        question_results.append({
            "question_id": question.id,
            "question_text": question.question_text,
            "type": question.type,
            "options": question.options,
            "correct_answer": question.correct_answer,
            "user_answer": answer.answer if answer else "",
            "is_correct": answer.is_correct if answer else False,
        })
    return question_results


@router.get("/questions/{room_code}")
async def get_questions(room_code: str, db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.room_code == room_code.strip().upper()).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    if room.status != "started":
        raise HTTPException(status_code=400, detail="Quiz has not started yet.")

    questions = [
        {
            "id": q.id,
            "question_text": q.question_text,
            "type": q.type,
            "options": q.options,
        }
        for q in room.questions
    ]
    return {"questions": questions}


@router.post("/submit-answer")
async def submit_answer(payload: SubmitAnswersRequest, db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.room_code == payload.room_code.strip().upper()).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    if room.status != "started":
        raise HTTPException(status_code=400, detail="Quiz is not active.")

    user = db.query(User).filter(User.id == payload.user_id, User.room_id == room.id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    for answer_item in payload.answers:
        question_id = answer_item.get("question_id")
        answer_text = str(answer_item.get("answer", "")).strip()

        question = db.query(Question).filter(Question.id == question_id, Question.room_id == room.id).first()
        if not question:
            continue

        existing_answer = (
            db.query(Answer)
            .filter(Answer.user_id == user.id, Answer.question_id == question.id)
            .first()
        )

        is_correct = False
        if question.type == "mcq":
            is_correct = answer_text.lower() == question.correct_answer.strip().lower()
        else:
            if answer_text:
                is_correct = await evaluate_blank_answer(question.question_text, question.correct_answer, answer_text)

        if existing_answer:
            existing_answer.answer = answer_text
            existing_answer.is_correct = is_correct
        else:
            existing_answer = Answer(
                user_id=user.id,
                question_id=question.id,
                answer=answer_text,
                is_correct=is_correct,
            )
            db.add(existing_answer)

    db.commit()

    user.score = sum(1 for item in user.answers if item.is_correct)
    db.commit()

    await manager.send_to_admin(room.room_code, {
        "event": "user_submitted",
        "user_id": user.id,
        "user_name": user.name,
        "score": user.score,
        "submission_status": "submitted",
    })

    return {
        "message": "Answers submitted successfully. Your results will be shown after the quiz ends.",
        "submitted": len(payload.answers),
    }


@router.get("/results/{room_code}/{user_id}")
async def get_results(room_code: str, user_id: int, db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.room_code == room_code.strip().upper()).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    if room.status != "closed":
        raise HTTPException(status_code=409, detail="Results are only available after the quiz ends.")

    user = db.query(User).filter(User.id == user_id, User.room_id == room.id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    leaderboard = [
        {"user_id": u.id, "name": u.name, "score": u.score, "is_you": u.id == user.id}
        for u in sorted(room.users, key=lambda x: x.score, reverse=True)
        if not u.is_admin
    ]

    return {
        "user_id": user.id,
        "user_name": user.name,
        "user_email": user.email,
        "score": user.score,
        "total_questions": len(room.questions),
        "quiz_topic": room.quiz_topic,
        "room_code": room.room_code,
        "question_results": build_question_results(db, room, user),
        "leaderboard": leaderboard,
    }


@router.get("/leaderboard/{room_code}")
async def get_leaderboard(room_code: str, db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.room_code == room_code.strip().upper()).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    leaderboard = [
        {"user_id": u.id, "name": u.name, "score": u.score}
        for u in sorted(room.users, key=lambda x: x.score, reverse=True)
        if not u.is_admin
    ]

    return {"leaderboard": leaderboard}


@router.get("/history")
async def get_history(email: str, db: Session = Depends(get_db)):
    normalized_email = email.strip().lower()
    if not normalized_email:
        raise HTTPException(status_code=400, detail="Email is required.")

    records = (
        db.query(User)
        .join(Room, Room.id == User.room_id)
        .filter(User.email == normalized_email, User.is_admin.is_(False))
        .order_by(Room.id.desc(), User.id.desc())
        .all()
    )

    history = []
    for user in records:
        room = user.room
        answered_count = db.query(Answer).filter(Answer.user_id == user.id).count()
        history.append({
            "room_code": room.room_code,
            "quiz_topic": room.quiz_topic,
            "difficulty": room.difficulty,
            "status": room.status,
            "score": user.score,
            "total_questions": room.num_questions,
            "answered": answered_count,
            "created_at": room.created_at,
            "display_name": user.name,
        })

    return {"email": normalized_email, "history": history}
