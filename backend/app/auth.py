"""Opaque HttpOnly sessions; password derivation uses Python's scrypt."""

import hashlib
import hmac
import json
import re
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


def provision_accounts(db, store, document: bytes) -> list[str]:
    """Create the admin/developer accounts named in an issued package; never overwrite an existing account.

    An existing active account of the same role keeps its password. Anything else changes nothing.
    """
    try:
        provision = json.loads(document)
    except ValueError:
        provision = None
    accounts = provision.get("accounts") if isinstance(provision, dict) else None
    if not (isinstance(provision, dict) and provision.get("format") == "kdog-provision-1"
            and isinstance(provision.get("customer"), str) and re.fullmatch(r"[A-Za-z0-9-]{1,32}", provision["customer"])
            and isinstance(accounts, list) and 1 <= len(accounts) <= 2
            and all(isinstance(account, dict) and set(account) == {"username", "role", "password_hash"}
                    and isinstance(account["username"], str) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", account["username"])
                    and account["role"] in ("admin", "developer")
                    and isinstance(account["password_hash"], str)
                    and re.fullmatch(r"scrypt\$[0-9a-f]{32}\$[0-9a-f]{128}", account["password_hash"])
                    for account in accounts)
            and sorted(account["role"] for account in accounts) in (["admin"], ["admin", "developer"])
            and len({account["username"] for account in accounts}) == len(accounts)):
        raise ValueError("발행 계정 정보가 올바르지 않습니다.")
    messages, new = [], []
    for account in accounts:
        row = db.execute("SELECT role, active FROM users WHERE username=?", (account["username"],)).fetchone()
        if row is None:
            new.append(account)
            messages.append(f"{account['username']} ({account['role']}): 새 계정을 만들었습니다.")
        elif row["role"] == account["role"] and row["active"]:
            messages.append(f"{account['username']} ({account['role']}): 기존 계정과 기존 비밀번호가 유지됩니다.")
        else:
            raise ValueError(f"{account['username']}: 역할이 다르거나 비활성인 기존 계정이 있어 아무것도 바꾸지 않았습니다.")
    for account in new:
        db.execute("INSERT INTO users(username,password_hash,role) VALUES (?,?,?)",
                   (account["username"], account["password_hash"], account["role"]))
        store.audit(db, account["username"], account["username"], "user.provisioned",
                    {"role": account["role"], "customer": provision["customer"]})
    return messages


def user_view(row) -> UserView:
    return UserView(username=row["username"], role=row["role"], active=bool(row["active"]))


def authenticate(db, token: str | None):
    row = db.execute("SELECT * FROM users WHERE session_hash=? AND active=1 AND session_expires>?",
                     (token_hash(token or ""), time.time())).fetchone()
    if row is None:
        raise HTTPException(401, "로그인이 필요합니다.")
    return row
