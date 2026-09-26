import os
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException, Request
from pwdlib import PasswordHash


SECRET = os.getenv("FACTISH_SECRET_KEY", "development-only-change-this-key-before-deploying")
if os.getenv("FACTISH_SECURE_COOKIES") == "1" and SECRET == "development-only-change-this-key-before-deploying":
    raise RuntimeError("FACTISH_SECRET_KEY must be set before serving over HTTPS")
ALGORITHM = "HS256"
passwords = PasswordHash.recommended()
ACCESS_AGE = 15 * 60
REFRESH_AGE = 30 * 24 * 60 * 60
GUEST_AGE = 180 * 24 * 60 * 60


def token(kind: str, subject: str, age: int):
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": subject, "kind": kind, "iat": now, "exp": now + timedelta(seconds=age), "jti": str(uuid.uuid4())},
        SECRET,
        algorithm=ALGORITHM,
    )


def read_token(value: str | None, kind: str):
    if not value:
        return None
    try:
        payload = jwt.decode(value, SECRET, algorithms=[ALGORITHM], options={"require": ["sub", "exp", "kind"]})
        return payload["sub"] if payload["kind"] == kind else None
    except (jwt.PyJWTError, KeyError):
        return None


def set_cookie(response, name: str, value: str, age: int):
    response.set_cookie(name, value, max_age=age, httponly=True, secure=os.getenv("FACTISH_SECURE_COOKIES") == "1", samesite="lax", path=os.getenv("FACTISH_COOKIE_PATH", "/"))


def set_user_cookies(response, user_id: int):
    set_cookie(response, "factish_access", token("access", str(user_id), ACCESS_AGE), ACCESS_AGE)
    set_cookie(response, "factish_refresh", token("refresh", str(user_id), REFRESH_AGE), REFRESH_AGE)


def clear_user_cookies(response):
    path = os.getenv("FACTISH_COOKIE_PATH", "/")
    response.delete_cookie("factish_access", path=path)
    response.delete_cookie("factish_refresh", path=path)


def actor(request: Request):
    subject = read_token(request.cookies.get("factish_access"), "access")
    if subject:
        try:
            return int(subject), None
        except ValueError:
            raise HTTPException(401, "Invalid access token") from None
    guest = read_token(request.cookies.get("factish_guest"), "guest")
    if guest:
        return None, guest
    raise HTTPException(401, "Session expired")
