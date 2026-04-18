# routes/user.py - User join and profile endpoints

import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import Room, User
from websocket_manager import manager

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class JoinRoomRequest(BaseModel):
    name: str
    room_code: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/join-room")
async def join_room(request: JoinRoomRequest, db: Session = Depends(get_db)):
    """
    Allow a user to join an existing room.
    - Validates room exists and is still open (waiting)
    - Creates a User record
    - Returns user_id, room info, and current participant list
    """
    room = db.query(Room).filter(Room.room_code == request.room_code.upper()).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found. Check the room code and try again.")

    if room.status == "closed":
        raise HTTPException(status_code=400, detail="This room is closed. The quiz has ended.")

    if room.status == "started":
        # Allow rejoining to check results
        existing = db.query(User).filter(
            User.room_id == room.id,
            User.name == request.name,
            User.is_admin == False
        ).first()
        if existing:
            return {
                "user_id": existing.id,
                "room_code": room.room_code,
                "room_status": room.status,
                "score": existing.score,
                "message": "Quiz already started. Showing your results.",
                "rejoin": True,
            }
        raise HTTPException(status_code=400, detail="Quiz has already started. Cannot join now.")

    # Check for duplicate name in same room
    duplicate = db.query(User).filter(
        User.room_id == room.id,
        User.name == request.name
    ).first()
    if duplicate:
        raise HTTPException(status_code=400, detail="A user with this name already exists in the room.")

    # Create new participant
    user = User(
        name=request.name,
        room_id=room.id,
        is_admin=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    logger.info(f"User '{request.name}' joined room {room.room_code}")

    # Notify admin via WebSocket that someone joined
    await manager.broadcast(room.room_code, {
        "event": "user_joined",
        "user_id": user.id,
        "user_name": user.name,
        "users": manager.get_user_list(room.room_code),
    })

    return {
        "user_id": user.id,
        "room_code": room.room_code,
        "room_status": room.status,
        "quiz_topic": room.quiz_topic,
        "difficulty": room.difficulty,
        "num_questions": room.num_questions,
        "message": f"Joined room {room.room_code} successfully!",
        "rejoin": False,
    }


@router.get("/room-info/{room_code}")
async def get_room_info(room_code: str, db: Session = Depends(get_db)):
    """Get basic info about a room — used by admin dashboard on page load."""
    room = db.query(Room).filter(Room.room_code == room_code.upper()).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    participants = db.query(User).filter(
        User.room_id == room.id,
        User.is_admin == False
    ).all()

    return {
        "room_code": room.room_code,
        "admin_name": room.admin_name,
        "quiz_topic": room.quiz_topic,
        "difficulty": room.difficulty,
        "num_questions": room.num_questions,
        "question_type": room.question_type,
        "status": room.status,
        "participants": [{"id": u.id, "name": u.name, "score": u.score} for u in participants],
    }
