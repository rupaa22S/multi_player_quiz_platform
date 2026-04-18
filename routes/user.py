from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import Room, User, Answer, Question
from websocket_manager import manager

router = APIRouter()


class JoinRoomRequest(BaseModel):
    name: str
    email: str | None = None
    auth_email: str | None = None
    room_code: str


@router.post("/join-room")
async def join_room(payload: JoinRoomRequest, db: Session = Depends(get_db)):
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Name is required.")

    normalized_email = (payload.email or payload.auth_email or "").strip().lower()
    if not normalized_email:
        raise HTTPException(status_code=400, detail="Email is required.")

    room_code = payload.room_code.strip().upper()
    normalized_name = payload.name.strip()

    room = db.query(Room).filter(Room.room_code == room_code).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    if room.status == "closed":
        raise HTTPException(status_code=400, detail="Room is closed and no longer accepting participants.")

    existing_user = (
        db.query(User)
        .filter(
            User.room_id == room.id,
            func.lower(User.email) == normalized_email,
            User.is_admin.is_(False),
        )
        .first()
    )

    if existing_user:
        existing_user.name = normalized_name
        existing_user.email = normalized_email
        db.commit()
        return {
            "user_id": existing_user.id,
            "user_name": existing_user.name,
            "user_email": existing_user.email,
            "room_code": room.room_code,
            "room_status": room.status,
            "room_id": room.id,
            "score": existing_user.score,
            "rejoined": True,
        }

    if room.status != "waiting":
        raise HTTPException(status_code=400, detail="This room is already in progress. Rejoin using your existing name if you were already in the room.")

    user = User(
        name=normalized_name,
        email=normalized_email,
        room_id=room.id,
        is_admin=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return {
        "user_id": user.id,
        "user_name": user.name,
        "user_email": user.email,
        "room_code": room.room_code,
        "room_status": room.status,
        "room_id": room.id,
        "score": user.score,
        "rejoined": False,
    }


@router.get("/room-info/{room_code}")
async def room_info(room_code: str, db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.room_code == room_code.strip().upper()).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    users = []
    for u in room.users:
        answer_count = db.query(Answer).filter(Answer.user_id == u.id).count()
        users.append({
            "id": u.id,
            "name": u.name,
            "score": u.score,
            "email": u.email,
            "is_admin": u.is_admin,
            "submission_status": "submitted" if answer_count else "taking",
        })

    return {
        "room_code": room.room_code,
        "admin_name": room.admin_name,
        "status": room.status,
        "quiz_topic": room.quiz_topic,
        "difficulty": room.difficulty,
        "question_type": room.question_type,
        "num_questions": room.num_questions,
        "users": users,
    }


@router.get("/admin/user-results/{room_code}/{user_id}")
async def admin_user_results(room_code: str, user_id: int, admin_id: int, db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.room_code == room_code.strip().upper()).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    admin = db.query(User).filter(
        User.id == admin_id,
        User.room_id == room.id,
        User.is_admin.is_(True),
    ).first()
    if not admin:
        raise HTTPException(status_code=403, detail="Only the room admin can view submissions.")

    user = db.query(User).filter(
        User.id == user_id,
        User.room_id == room.id,
        User.is_admin.is_(False),
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    question_results = []
    for question in room.questions:
        answer = (
            db.query(Answer)
            .filter(Answer.user_id == user.id, Answer.question_id == question.id)
            .first()
        )
        question_results.append({
            "question_number": len(question_results) + 1,
            "question_text": question.question_text,
            "type": question.type,
            "options": question.options,
            "correct_answer": question.correct_answer,
            "user_answer": answer.answer if answer else "",
            "is_correct": answer.is_correct if answer else False,
        })

    return {
        "user_id": user.id,
        "user_name": user.name,
        "score": user.score,
        "question_results": question_results,
    }
