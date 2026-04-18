import base64
import hashlib
import hmac
import secrets
from datetime import datetime
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import Account

router = APIRouter(prefix="/auth", tags=["auth"])

PBKDF2_ITERATIONS = 120_000


class SignInRequest(BaseModel):
    email: str
    password: str


async def _read_signin_payload(request: Request) -> SignInRequest:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        data = await request.json()
    else:
        body = (await request.body()).decode("utf-8")
        parsed = parse_qs(body)
        data = {key: values[0] for key, values in parsed.items() if values}
    return SignInRequest(**data)


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt_b64, digest_b64 = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64.encode())
        expected = base64.b64decode(digest_b64.encode())
        computed = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            int(iterations),
        )
        return hmac.compare_digest(expected, computed)
    except Exception:
        return False


@router.post("/signin")
async def signin(request: Request, db: Session = Depends(get_db)):
    payload = await _read_signin_payload(request)
    email = payload.email.strip().lower()
    password = payload.password

    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password are required.")

    account = db.query(Account).filter(Account.email == email).first()
    if account:
        if not _verify_password(password, account.password_hash):
            raise HTTPException(status_code=401, detail="Incorrect password.")
        created = False
    else:
        account = Account(
            email=email,
            password_hash=_hash_password(password),
            created_at=datetime.utcnow().isoformat(timespec="seconds"),
        )
        db.add(account)
        db.commit()
        created = True

    return {
        "message": "Signed in successfully.",
        "email": email,
        "created": created,
    }


@router.post("/signout")
async def signout():
    return JSONResponse({"message": "Signed out successfully."})
