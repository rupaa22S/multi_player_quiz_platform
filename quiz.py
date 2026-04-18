# routes/quiz.py - Quiz questions, answer submission, and results endpoints

import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import Room, User, Question, Answer
from ai_service import evaluate_blank_answer
from websocket_manager import manager

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class SubmitAnswerRequest(BaseModel):
    user_id: int
    question_id: int
    answer: str


class BulkSubmitRequest(BaseModel):
    user_id: int
    room_code: str
    answers: list[dict]   # [{question_id, answer}, ...]


class ManualScoreRequest(BaseModel):
    answer_id: int
    is_correct: bool
    admin_id: int


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/questions/{room_code}")
async def get_questions(room_code: str, db: Session = Depends(get_db)):
    """
    Return all questions for a room.
    NOTE: correct_answer is NOT included to prevent cheating.
    Only called after quiz starts.
    """
    room = db.query(Room).filter(Room.room_code == room_code.upper()).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    questions = []
    for q in room.questions:
        questions.append({
            "id": q.id,
            "question_text": q.question_text,
            "type": q.type,
            "options": q.options,
        })

    return {"questions": questions, "room_code": room_code}


@router.post("/submit-answers")
async def submit_answers(request: BulkSubmitRequest, db: Session = Depends(get_db)):
    """
    Accept all answers from a user in one request (submitted at end of quiz).
    - Evaluates MCQ answers automatically
    - Uses AI evaluation for fill-in-the-blank answers
    - Updates user score
    - Notifies admin via WebSocket
    """
    user = db.query(User).filter(User.id == request.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    room = db.query(Room).filter(Room.room_code == request.room_code.upper()).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    if room.status != "started":
        raise HTTPException(status_code=400, detail="Quiz is not active.")

    total_score = 0
    answer_results = []

    for ans_data in request.answers:
        q_id = ans_data.get("question_id")
        user_answer = str(ans_data.get("answer", "")).strip()

        question = db.query(Question).filter(Question.id == q_id, Question.room_id == room.id).first()
        if not question:
            continue

        # Skip if already answered
        existing = db.query(Answer).filter(
            Answer.user_id == request.user_id,
            Answer.question_id == q_id
        ).first()
        if existing:
            continue

        # Evaluate correctness
        if question.type == "mcq":
            is_correct = user_answer.strip().lower() == question.correct_answer.strip().lower()
        else:
            # AI-powered evaluation for fill-in-the-blank
            is_correct = await evaluate_blank_answer(
                question.question_text,
                question.correct_answer,
                user_answer
            )

        if is_correct:
            total_score += 1

        answer = Answer(
            user_id=request.user_id,
            question_id=q_id,
            answer=user_answer,
            is_correct=is_correct,
        )
        db.add(answer)
        answer_results.append({
            "question_id": q_id,
            "is_correct": is_correct,
        })

    # Update user's total score
    user.score += total_score
    db.commit()

    logger.info(f"User {user.name} submitted answers — score: {user.score}")

    # Notify admin that a user has submitted
    await manager.send_to_admin(request.room_code, {
        "event": "user_submitted",
        "user_id": user.id,
        "user_name": user.name,
        "score": user.score,
    })

    return {
        "message": "Answers submitted!",
        "score": user.score,
        "correct": total_score,
        "total": len(request.answers),
        "results": answer_results,
    }


@router.post("/submit-answer")
async def submit_single_answer(request: SubmitAnswerRequest, db: Session = Depends(get_db)):
    """Submit a single answer (used for incremental submission if needed)."""
    user = db.query(User).filter(User.id == request.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    question = db.query(Question).filter(Question.id == request.question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found.")

    existing = db.query(Answer).filter(
        Answer.user_id == request.user_id,
        Answer.question_id == request.question_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Already answered this question.")

    if question.type == "mcq":
        is_correct = request.answer.strip().lower() == question.correct_answer.strip().lower()
    else:
        is_correct = await evaluate_blank_answer(
            question.question_text, question.correct_answer, request.answer
        )

    answer = Answer(
        user_id=request.user_id,
        question_id=request.question_id,
        answer=request.answer,
        is_correct=is_correct,
    )
    db.add(answer)
    if is_correct:
        user.score += 1
    db.commit()

    return {"is_correct": is_correct, "score": user.score}


@router.get("/results/{room_code}/{user_id}")
async def get_user_results(room_code: str, user_id: int, db: Session = Depends(get_db)):
    """Fetch a specific user's quiz results including per-question breakdown."""
    room = db.query(Room).filter(Room.room_code == room_code.upper()).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    user = db.query(User).filter(User.id == user_id, User.room_id == room.id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found in this room.")

    # Build per-question results
    question_results = []
    for q in room.questions:
        answer = db.query(Answer).filter(
            Answer.user_id == user_id,
            Answer.question_id == q.id
        ).first()
        question_results.append({
            "question_text": q.question_text,
            "type": q.type,
            "options": q.options,
            "correct_answer": q.correct_answer,
            "user_answer": answer.answer if answer else "Not answered",
            "is_correct": answer.is_correct if answer else False,
        })

    # Leaderboard
    participants = db.query(User).filter(
        User.room_id == room.id,
        User.is_admin == False
    ).order_by(User.score.desc()).all()

    leaderboard = [
        {"rank": i + 1, "name": u.name, "score": u.score, "is_you": u.id == user_id}
        for i, u in enumerate(participants)
    ]

    return {
        "user_name": user.name,
        "score": user.score,
        "total_questions": len(room.questions),
        "quiz_topic": room.quiz_topic,
        "question_results": question_results,
        "leaderboard": leaderboard,
    }


@router.get("/leaderboard/{room_code}")
async def get_leaderboard(room_code: str, db: Session = Depends(get_db)):
    """Admin view — full leaderboard for a room."""
    room = db.query(Room).filter(Room.room_code == room_code.upper()).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found.")

    participants = db.query(User).filter(
        User.room_id == room.id,
        User.is_admin == False
    ).order_by(User.score.desc()).all()

    return {
        "room_code": room_code,
        "leaderboard": [
            {"rank": i + 1, "name": u.name, "score": u.score}
            for i, u in enumerate(participants)
        ]
    }


@router.post("/manual-score")
async def manual_score(request: ManualScoreRequest, db: Session = Depends(get_db)):
    """Admin manually marks a fill-in-the-blank answer as correct/incorrect."""
    admin = db.query(User).filter(User.id == request.admin_id, User.is_admin == True).first()
    if not admin:
        raise HTTPException(status_code=403, detail="Admin access required.")

    answer = db.query(Answer).filter(Answer.id == request.answer_id).first()
    if not answer:
        raise HTTPException(status_code=404, detail="Answer not found.")

    # Adjust score based on change
    user = db.query(User).filter(User.id == answer.user_id).first()
    if request.is_correct and not answer.is_correct:
        user.score += 1
    elif not request.is_correct and answer.is_correct:
        user.score = max(0, user.score - 1)

    answer.is_correct = request.is_correct
    db.commit()

    return {"message": "Score updated.", "new_score": user.score}
