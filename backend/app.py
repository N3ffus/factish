import hashlib
import io
import mimetypes
import os
import random
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import AuthAttempt, Fact, Fake, Round, Run, User
from .security import GUEST_AGE, REFRESH_AGE, actor, clear_user_cookies, passwords, read_token, set_cookie, set_user_cookies, token


ROUND_SECONDS = 15
# Windows can register .js as text/plain; ES modules are rejected with that MIME type.
mimetypes.add_type("text/javascript", ".js", strict=True)
PRESETS = ("cat", "fox", "owl", "frog", "bear", "star", "panda", "koala", "tiger", "penguin", "rabbit", "hedgehog",
           "octopus", "unicorn", "dragon", "robot", "alien", "rocket")
AVATAR_DIR = Path(__file__).resolve().parent.parent / "data" / "avatars"
AVATAR_DIR.mkdir(parents=True, exist_ok=True)
app = FastAPI(title="Factish API")
app.mount("/avatars", StaticFiles(directory=AVATAR_DIR), name="avatars")


@app.middleware("http")
async def browser_guard(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path.startswith("/api/"):
        origin = request.headers.get("origin")
        allowed = {str(request.base_url).rstrip("/"), "http://localhost:5173", "http://127.0.0.1:5173", os.getenv("FACTISH_FRONTEND_ORIGIN", "http://localhost:5173")}
        if request.headers.get("x-factish-request") != "1" or (origin and origin not in allowed):
            return Response(status_code=403)
    return await call_next(request)


def db_session():
    with SessionLocal() as db:
        yield db


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(value: datetime):
    return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def owner_filter(user_id: int | None, guest_id: str | None):
    return Run.user_id == user_id if user_id is not None else Run.guest_id == guest_id


def current_actor(request: Request, db: Session):
    user_id, guest_id = actor(request)
    if user_id is not None and db.get(User, user_id) is None:
        raise HTTPException(401, "Account not found")
    return user_id, guest_id


def statistics(db: Session, user_id: int | None, guest_id: str | None):
    owned = owner_filter(user_id, guest_id)
    best, completed, completed_correct = db.execute(
        select(func.coalesce(func.max(Run.score), 0),
               func.coalesce(func.sum(case((Run.finished.is_(True), 1), else_=0)), 0),
               func.coalesce(func.sum(case((Run.finished.is_(True), Run.score), else_=0)), 0))
        .where(owned)
    ).one()
    correct, total = db.execute(
        select(func.coalesce(func.sum(case((Round.correct.is_(True), 1), else_=0)), 0),
               func.coalesce(func.count(Round.selected_side), 0))
        .join(Run, Round.run_id == Run.id).where(owned)
    ).one()
    return {"best": best, "correct": correct, "total": total, "completedRuns": completed,
            "average": round(completed_correct / completed, 1) if completed else None}


def profile(db: Session, user_id: int | None, guest_id: str | None):
    user = db.get(User, user_id) if user_id else None
    return {"authenticated": user is not None, "userId": user.id if user else None, "login": user.login if user else None,
            "displayName": user.display_name if user else "Гость",
            "avatar": user.avatar if user else "preset:cat", "stats": statistics(db, user_id, guest_id)}


@app.get("/api/bootstrap")
def bootstrap(request: Request, response: Response, db: Session = Depends(db_session)):
    content_count = min(db.scalar(select(func.count()).select_from(Fact).where(Fact.active.is_(True))) or 0,
                        db.scalar(select(func.count()).select_from(Fake).where(Fake.active.is_(True))) or 0)
    user_id = read_token(request.cookies.get("factish_access"), "access")
    if user_id:
        user = db.get(User, int(user_id))
        if user:
            return {"profile": profile(db, user.id, None), "questionCount": content_count, "presets": PRESETS}
    guest = read_token(request.cookies.get("factish_guest"), "guest")
    if not guest:
        guest = str(uuid.uuid4())
        set_cookie(response, "factish_guest", token("guest", guest, GUEST_AGE), GUEST_AGE)
    return {"profile": profile(db, None, guest), "questionCount": content_count, "presets": PRESETS}


class Credentials(BaseModel):
    login: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)


def valid_login(login: str):
    normalized = login.strip().lower()
    if not re.fullmatch(r"[a-z0-9_]{3,32}", normalized):
        raise HTTPException(422, "Логин: 3–32 латинских буквы, цифры или _")
    return normalized


def transfer_guest(db: Session, request: Request, user_id: int):
    guest = read_token(request.cookies.get("factish_guest"), "guest")
    if guest:
        db.execute(update(Run).where(Run.guest_id == guest).values(guest_id=None, user_id=user_id))


def finish_auth(db: Session, request: Request, response: Response, user: User):
    transfer_guest(db, request, user.id)
    db.commit()
    set_user_cookies(response, user.id)
    response.delete_cookie("factish_guest", path=os.getenv("FACTISH_COOKIE_PATH", "/"))
    return {"profile": profile(db, user.id, None)}


@app.post("/api/auth/register")
def register(data: Credentials, request: Request, response: Response, db: Session = Depends(db_session)):
    login = valid_login(data.login)
    if not 8 <= len(data.password) <= 128:
        raise HTTPException(422, "Пароль должен содержать от 8 до 128 символов")
    if db.scalar(select(User.id).where(User.login == login)):
        raise HTTPException(409, "Этот логин уже занят")
    user = User(login=login, display_name=login, password_hash=passwords.hash(data.password))
    db.add(user)
    try:
        db.flush()
        return finish_auth(db, request, response, user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Этот логин уже занят") from None


def check_rate(db: Session, request: Request, login: str):
    ip = request.client.host if request.client else "unknown"
    key = hashlib.sha256(f"{ip}:{login}".encode()).hexdigest()
    now = utcnow()
    attempt = db.get(AuthAttempt, key)
    if not attempt or now - attempt.window_at > timedelta(minutes=10):
        if attempt:
            attempt.count, attempt.window_at = 0, now
        else:
            attempt = AuthAttempt(key=key, count=0, window_at=now)
            db.add(attempt)
    if attempt.count >= 8:
        raise HTTPException(429, "Слишком много попыток. Повторите позже")
    attempt.count += 1
    db.commit()


@app.post("/api/auth/login")
def login(data: Credentials, request: Request, response: Response, db: Session = Depends(db_session)):
    normalized = data.login.strip().lower()
    check_rate(db, request, normalized)
    user = db.scalar(select(User).where(User.login == normalized))
    if not user or not passwords.verify(data.password, user.password_hash):
        raise HTTPException(401, "Неверный логин или пароль")
    key = hashlib.sha256(f"{request.client.host if request.client else 'unknown'}:{normalized}".encode()).hexdigest()
    db.execute(update(AuthAttempt).where(AuthAttempt.key == key).values(count=0))
    return finish_auth(db, request, response, user)


@app.post("/api/auth/refresh")
def refresh(request: Request, response: Response, db: Session = Depends(db_session)):
    subject = read_token(request.cookies.get("factish_refresh"), "refresh")
    if not subject or not subject.isdigit() or not db.get(User, int(subject)):
        raise HTTPException(401, "Session expired")
    set_user_cookies(response, int(subject))
    return {"ok": True}


@app.post("/api/auth/logout")
def logout(response: Response):
    clear_user_cookies(response)
    return {"ok": True}


class DisplayName(BaseModel):
    displayName: str = Field(min_length=1, max_length=24)


@app.patch("/api/profile/name")
def change_name(data: DisplayName, request: Request, db: Session = Depends(db_session)):
    user_id, _ = current_actor(request, db)
    if not user_id:
        raise HTTPException(401, "Sign in first")
    name = data.displayName.strip()
    if not name or any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise HTTPException(422, "Введите имя игрока")
    db.get(User, user_id).display_name = name
    db.commit()
    return {"profile": profile(db, user_id, None)}


class AvatarChoice(BaseModel):
    preset: str


@app.patch("/api/profile/avatar")
def choose_avatar(data: AvatarChoice, request: Request, db: Session = Depends(db_session)):
    user_id, _ = current_actor(request, db)
    if not user_id:
        raise HTTPException(401, "Sign in first")
    if data.preset not in PRESETS:
        raise HTTPException(422, "Unknown avatar")
    db.get(User, user_id).avatar = f"preset:{data.preset}"
    db.commit()
    return {"profile": profile(db, user_id, None)}


@app.post("/api/profile/avatar/upload")
async def upload_avatar(request: Request, image: UploadFile = File(...), db: Session = Depends(db_session)):
    user_id, _ = current_actor(request, db)
    if not user_id:
        raise HTTPException(401, "Sign in first")
    if image.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(422, "Нужен PNG, JPEG или WebP")
    raw = await image.read(2_000_001)
    if len(raw) > 2_000_000:
        raise HTTPException(413, "Файл больше 2 МБ")
    try:
        photo = Image.open(io.BytesIO(raw))
        if photo.width > 4096 or photo.height > 4096:
            raise HTTPException(422, "Слишком большое изображение")
        photo.load()
        photo = photo.convert("RGB")
        photo.thumbnail((256, 256))
        filename = f"{uuid.uuid4().hex}.webp"
        photo.save(AVATAR_DIR / filename, "WEBP", quality=80, method=4)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise HTTPException(422, "Не удалось прочитать изображение") from None
    db.get(User, user_id).avatar = f"/avatars/{filename}"
    db.commit()
    return {"profile": profile(db, user_id, None)}


def card_payload(round_: Round):
    options = [round_.fact.statement, round_.fake.statement] if round_.correct_side == "A" else [round_.fake.statement, round_.fact.statement]
    return {"roundId": round_.id, "options": options, "deadline": iso(round_.issued_at + timedelta(seconds=ROUND_SECONDS)),
            "serverNow": iso(utcnow()), "streak": round_.run.score}


@app.post("/api/game/next")
def next_round(request: Request, db: Session = Depends(db_session)):
    # Serialise round creation per SQLite writer so concurrent clicks cannot open two rounds.
    db.execute(text("BEGIN IMMEDIATE"))
    user_id, guest_id = current_actor(request, db)
    if not db.scalar(select(Fact.id).where(Fact.active.is_(True)).limit(1)) or not db.scalar(select(Fake.id).where(Fake.active.is_(True)).limit(1)):
        raise HTTPException(409, "Вопросы пока не загружены")
    run = db.scalar(select(Run).where(owner_filter(user_id, guest_id), Run.finished.is_(False)).order_by(Run.id.desc()))
    if not run:
        run = Run(user_id=user_id, guest_id=guest_id)
        db.add(run)
        db.flush()
    previous = db.scalar(select(Round).where(Round.run_id == run.id).order_by(Round.id.desc()))
    if previous and previous.resolved_at is None:
        return card_payload(previous)
    fact_filter = [Fact.active.is_(True)]
    fake_filter = [Fake.active.is_(True)]
    if previous:
        fact_filter.append(Fact.id != previous.fact_id)
        fake_filter.append(Fake.id != previous.fake_id)
    fact_id = db.scalar(select(Fact.id).where(*fact_filter).order_by(func.random()).limit(1))
    fake_id = db.scalar(select(Fake.id).where(*fake_filter).order_by(func.random()).limit(1))
    if fact_id is None:
        fact_id = db.scalar(select(Fact.id).where(Fact.active.is_(True)).limit(1))
    if fake_id is None:
        fake_id = db.scalar(select(Fake.id).where(Fake.active.is_(True)).limit(1))
    round_ = Round(run_id=run.id, fact_id=fact_id, fake_id=fake_id, correct_side=random.choice(("A", "B")), issued_at=utcnow())
    db.add(round_)
    db.commit()
    db.refresh(round_)
    return card_payload(round_)


class Answer(BaseModel):
    roundId: int
    choice: str | None = None


@app.post("/api/game/answer")
def answer(data: Answer, request: Request, db: Session = Depends(db_session)):
    user_id, guest_id = current_actor(request, db)
    round_ = db.get(Round, data.roundId)
    if not round_ or not (round_.run.user_id == user_id if user_id is not None else round_.run.guest_id == guest_id):
        raise HTTPException(404, "Раунд не найден")
    if data.choice not in {"A", "B", None}:
        raise HTTPException(422, "Неверный вариант")
    now = utcnow()
    expired = now > round_.issued_at + timedelta(seconds=ROUND_SECONDS)
    choice = None if expired else data.choice
    if round_.resolved_at is not None:
        raise HTTPException(409, "Ответ уже засчитан")
    correct = choice == round_.correct_side
    changed = db.execute(update(Round).where(Round.id == round_.id, Round.resolved_at.is_(None)).values(resolved_at=now, selected_side=choice, correct=correct))
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Ответ уже засчитан")
    if correct:
        db.execute(update(Run).where(Run.id == round_.run_id).values(score=Run.score + 1))
    else:
        db.execute(update(Run).where(Run.id == round_.run_id).values(finished=True, finished_at=now))
    db.commit()
    db.refresh(round_.run)
    return {"correct": correct, "timedOut": choice is None, "correctSide": round_.correct_side,
            "explanation": f"Факт: {round_.fact.explanation} Фейк: {round_.fake.explanation}", "streak": round_.run.score,
            "gameOver": not correct, "stats": statistics(db, user_id, guest_id)}


@app.get("/api/leaderboard")
def leaderboard(period: str = "all", metric: str = "streak", db: Session = Depends(db_session)):
    if period not in {"today", "all"} or metric not in {"streak", "average"}:
        raise HTTPException(422, "Unknown leaderboard filter")
    stmt = select(Run.user_id, func.max(Run.score).label("best"),
                  func.sum(case((Run.finished.is_(True), Run.score), else_=0)).label("sum_score"),
                  func.sum(case((Run.finished.is_(True), 1), else_=0)).label("run_count"))\
        .where(Run.user_id.is_not(None)).group_by(Run.user_id)
    if period == "today":
        local_midnight = datetime.now(ZoneInfo("Europe/Moscow")).replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff = local_midnight.astimezone(timezone.utc).replace(tzinfo=None)
        stmt = stmt.where(Run.started_at >= cutoff)
    scores = db.execute(stmt).all()
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_([row.user_id for row in scores])))} if scores else {}
    rows = [{"userId": row.user_id, "name": users[row.user_id].display_name, "avatar": users[row.user_id].avatar,
             "best": row.best, "average": round(row.sum_score / row.run_count, 1) if row.run_count else None}
            for row in scores]
    if metric == "streak":
        rows.sort(key=lambda item: (-item["best"], -(item["average"] or -1), item["userId"]))
    else:
        rows = [item for item in rows if item["average"] is not None]
        rows.sort(key=lambda item: (-item["average"], -item["best"], item["userId"]))
    return {"rows": rows[:50]}


FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        target = (FRONTEND_DIST / path).resolve()
        if not target.is_relative_to(FRONTEND_DIST.resolve()) or not target.is_file():
            target = FRONTEND_DIST / "index.html"
        headers = {"Cache-Control": "no-cache"} if target.suffix == ".html" else None
        return FileResponse(target, headers=headers)
