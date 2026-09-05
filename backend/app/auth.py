"""Opaque HttpOnly sessions; password derivation uses Python's scrypt."""

import hashlib
import hmac
import secrets
import time

from fastapi import HTTPException

from app.input_models import UserCreate, UserView


def password_hash(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return f"scrypt${salt}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    return hmac.compare_digest(password_hash(password, stored.split("$")[1]), stored)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_user(db, user: UserCreate):
    if len(user.password) < 12:
        raise HTTPException(422, "비밀번호는 12자 이상이어야 합니다.")
    db.execute("INSERT INTO users(username,password_hash,role) VALUES (?,?,?)",
               (user.username, password_hash(user.password), user.role))


def user_view(row) -> UserView:
    return UserView(username=row["username"], role=row["role"], active=bool(row["active"]))


def authenticate(db, token: str | None):
    row = db.execute("SELECT * FROM users WHERE session_hash=? AND active=1 AND session_expires>?",
                     (token_hash(token or ""), time.time())).fetchone()
    if row is None:
        raise HTTPException(401, "로그인이 필요합니다.")
    return row
