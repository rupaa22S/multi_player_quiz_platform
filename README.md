# QuizBlast – Real-Time Multiplayer Quiz App

A full-stack real-time multiplayer quiz application powered by AI question generation,
WebSockets, FastAPI, and SQLite.

---

## Project Structure

```
quiz-app/
├── main.py              ← FastAPI app, WebSocket endpoint, page routes
├── database.py          ← SQLAlchemy engine + session setup
├── models.py            ← ORM models: Room, User, Question, Answer
├── ai_service.py        ← AI question generation (Gemini / OpenAI)
├── websocket_manager.py ← WebSocket connection manager (per-room)
├── routes/
│   ├── room.py          ← POST /create-room, /start-quiz, /end-quiz, DELETE /remove-user
│   ├── user.py          ← POST /join-room, GET /room-info
│   └── quiz.py          ← GET /questions, POST /submit-answers, GET /results, /leaderboard
├── static/
│   ├── style.css        ← Retro arcade UI design system
│   └── script.js        ← Shared JS utilities (toast, debounce)
├── templates/
│   ├── index.html       ← Home: create / join room
│   ├── admin.html       ← Admin dashboard
│   ├── quiz.html        ← Participant quiz page
│   └── result.html      ← Results + leaderboard
└── requirements.txt
```

---

## Prerequisites

- Python 3.10+
- pip

---

## Setup Instructions

### 1. Clone / copy the project

```bash
cd quiz-app
```

### 2. Create a virtual environment (recommended)

```bash
python -m venv venv

# macOS / Linux:
source venv/bin/activate

# Windows:
venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure your AI API key (optional but recommended)

You can place environment variables in a `.env` file in the project root, or export them in your shell.

Example `.env`:

```env
GEMINI_API_KEY=your-gemini-api-key-here
OPENAI_API_KEY=your-openai-api-key-here
GEMINI_MODEL=gemini-2.5-flash 
OPENAI_MODEL=gpt-4o-mini
```

**For Google Gemini (recommended — free tier available):**

```bash
# macOS / Linux:
export GEMINI_API_KEY="your-gemini-api-key-here"

# Windows (Command Prompt):
set GEMINI_API_KEY=your-gemini-api-key-here

# Windows (PowerShell):
$env:GEMINI_API_KEY="your-gemini-api-key-here"
```

Get a free Gemini API key at: https://aistudio.google.com/app/apikey

**For OpenAI:**

```bash
export OPENAI_API_KEY="your-openai-api-key-here"
```

> **No API key?** Question generation will fail until you set `GEMINI_API_KEY`
> or `OPENAI_API_KEY`.

---

## Running the Server

```bash
python main.py
```

Or with uvicorn directly:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

The server starts at: **http://0.0.0.0:8000**

---

## Accessing from Multiple Devices (LAN / WiFi)

1. Find your computer's local IP address:
   - **macOS/Linux:** `ifconfig | grep inet` or `ip addr`
   - **Windows:** `ipconfig` → look for IPv4 Address

2. Share this URL with participants on the **same WiFi network**:
   ```
   http://<your-ip-address>:8000
   ```
   Example: `http://192.168.1.42:8000`

3. Everyone — admin and participants — opens this URL in their browser.

---

## How to Play

### Admin (Quiz Host)

1. Go to `http://<server-ip>:8000`
2. Fill in your name, topic, difficulty, number of questions, and type
3. Click **"Create Room & Generate Questions"** — AI generates questions instantly
4. Share the **6-character room code** shown on the admin dashboard
5. Wait for participants to join (you'll see them appear live)
6. Click **"Start Quiz"** when ready — questions are sent to all players
7. Watch submissions come in on the progress bar
8. Click **"End Quiz"** to reveal the leaderboard to everyone

### Participants

1. Go to `http://<server-ip>:8000`
2. Enter your name and the room code shared by the admin
3. Wait on the lobby screen until admin starts the quiz
4. Answer all questions and click **"Submit All Answers"**
5. After admin ends the quiz, you're redirected to your results + leaderboard

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/create-room` | Create room + generate AI questions |
| POST | `/join-room` | Join an existing room |
| GET | `/room-info/{room_code}` | Get room status and participant list |
| POST | `/start-quiz` | Admin starts the quiz |
| POST | `/end-quiz` | Admin ends the quiz + broadcasts results |
| GET | `/questions/{room_code}` | Get all questions (no correct answers) |
| POST | `/submit-answers` | Submit all user answers at once |
| GET | `/results/{room_code}/{user_id}` | Get user's results + leaderboard |
| GET | `/leaderboard/{room_code}` | Get full leaderboard |
| DELETE | `/remove-user/{user_id}` | Admin kicks a user |
| WS | `/ws/{room_code}` | WebSocket connection for real-time events |

Interactive API docs (Swagger): **http://localhost:8000/docs**

---

## WebSocket Events

| Event | Direction | Description |
|-------|-----------|-------------|
| `user_joined` | Server → All | New participant joined |
| `user_left` | Server → All | Participant disconnected |
| `quiz_started` | Server → All | Quiz begins + questions payload |
| `quiz_ended` | Server → All | Quiz over + leaderboard payload |
| `user_submitted` | Server → Admin | A user submitted their answers |
| `kicked` | Server → User | This user was removed by admin |
| `ping` / `pong` | Client ↔ Server | Keepalive |

---

## Troubleshooting

**"Failed to generate questions"**
- Check that your API key environment variable is set correctly
- Verify internet access from the server machine
- The app will not generate placeholder questions anymore; it will return an error instead

**"Connection refused" on other devices**
- Make sure firewall allows port 8000
- Ensure all devices are on the same WiFi network
- Use the server machine's local IP, not `localhost`

**WebSocket disconnects**
- Check that your router doesn't block WebSocket upgrades
- Try with `--reload` disabled in production

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI + Uvicorn |
| Database | SQLite + SQLAlchemy ORM |
| Real-time | WebSockets (native FastAPI) |
| AI | Google Gemini 2.5 Flash / OpenAI GPT-4o-mini |
| Frontend | HTML + CSS + Vanilla JavaScript |
| Templating | Jinja2 |
