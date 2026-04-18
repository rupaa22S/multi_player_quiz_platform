# main.py - FastAPI application entry point

import json
import logging
from contextlib import asynccontextmanager

from env_utils import load_env_file

load_env_file()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import inspect, text

from database import engine, get_db, Base
import models  # noqa: F401 — ensures all models are registered before create_all

from routes.room import router as room_router
from routes.auth import router as auth_router
from routes.user import router as user_router
from routes.quiz import router as quiz_router
from websocket_manager import manager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def ensure_sqlite_columns():
    """Add lightweight schema upgrades for older SQLite databases."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    if "rooms" in tables:
        room_columns = {column["name"] for column in inspector.get_columns("rooms")}
        if "created_at" not in room_columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE rooms ADD COLUMN created_at VARCHAR(50)"))

    if "users" in tables:
        user_columns = {column["name"] for column in inspector.get_columns("users")}
        if "email" not in user_columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR(255)"))


# ── Lifespan: create DB tables on startup ─────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    ensure_sqlite_columns()
    logger.info("Database ready.")
    yield
    logger.info("Shutting down.")


# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title="QuizBlast – Real-Time Multiplayer Quiz",
    version="1.0.0",
    lifespan=lifespan,
)

# Serve static files (CSS, JS)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Jinja2 templates
templates = Jinja2Templates(directory="templates")

# Register route modules
app.include_router(room_router)
app.include_router(auth_router)
app.include_router(user_router)
app.include_router(quiz_router)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Serve the home page (create / join room)."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/signin", response_class=HTMLResponse)
async def signin_page(request: Request):
    """Serve the sign-in page."""
    return templates.TemplateResponse("signin.html", {"request": request})


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    """Serve the admin dashboard."""
    return templates.TemplateResponse("admin.html", {"request": request})


@app.get("/quiz", response_class=HTMLResponse)
async def quiz_page(request: Request):
    """Serve the quiz page for participants."""
    return templates.TemplateResponse("quiz.html", {"request": request})


@app.get("/result", response_class=HTMLResponse)
async def result_page(request: Request):
    """Serve the results / leaderboard page."""
    return templates.TemplateResponse("result.html", {"request": request})


# ── WebSocket endpoint ────────────────────────────────────────────────────────

@app.websocket("/ws/{room_code}")
async def websocket_endpoint(
    websocket: WebSocket,
    room_code: str,
    user_id: int,
    user_name: str,
    is_admin: bool = False,
    db: Session = Depends(get_db),
):
    """
    WebSocket handler for real-time events.

    Query parameters (passed in URL):
      ?user_id=1&user_name=Alice&is_admin=false

    Events sent FROM server:
      - user_joined       → admin sees new participant
      - user_left         → admin sees someone left
      - quiz_started      → all users receive questions
      - quiz_ended        → all users receive leaderboard
      - kicked            → target user is removed
      - user_submitted    → admin notified of submission

    Events received FROM client:
      - ping              → server echoes pong (keepalive)
    """
    await manager.connect(websocket, room_code, user_id, user_name, is_admin)

    # Announce join to room (admin gets live user list)
    if not is_admin:
        await manager.broadcast(room_code, {
            "event": "user_joined",
            "user_id": user_id,
            "user_name": user_name,
            "users": manager.get_user_list(room_code),
        }, exclude_ws=websocket)

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                continue

            event = msg.get("event")

            if event == "ping":
                await websocket.send_text(json.dumps({"event": "pong"}))

            # Additional client-side events can be handled here

    except WebSocketDisconnect:
        manager.disconnect(websocket, room_code)
        logger.info(f"[WS] {user_name} disconnected from room {room_code}")

        if not is_admin:
            await manager.broadcast(room_code, {
                "event": "user_left",
                "user_id": user_id,
                "user_name": user_name,
                "users": manager.get_user_list(room_code),
            })


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    # Bind to all interfaces so LAN users can connect
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
