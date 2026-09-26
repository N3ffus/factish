from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(24))
    password_hash: Mapped[str] = mapped_column(String(255))
    avatar: Mapped[str] = mapped_column(String(255), default="preset:cat")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Fact(Base):
    __tablename__ = "facts"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(120), default="")
    source_id: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(80))
    statement: Mapped[str] = mapped_column(Text, unique=True)
    explanation: Mapped[str] = mapped_column(Text)
    difficulty: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class Fake(Base):
    __tablename__ = "fakes"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(120), default="")
    source_id: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(80))
    statement: Mapped[str] = mapped_column(Text, unique=True)
    explanation: Mapped[str] = mapped_column(Text)
    difficulty: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    guest_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    finished: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rounds: Mapped[list["Round"]] = relationship(back_populates="run")
    __table_args__ = (
        CheckConstraint("(user_id IS NOT NULL) != (guest_id IS NOT NULL)", name="run_one_owner"),
        Index("ix_runs_user_finished", "user_id", "finished", "finished_at"),
    )


class Round(Base):
    __tablename__ = "rounds"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    fact_id: Mapped[int] = mapped_column(ForeignKey("facts.id"))
    fake_id: Mapped[int] = mapped_column(ForeignKey("fakes.id"))
    correct_side: Mapped[str] = mapped_column(String(1))
    issued_at: Mapped[datetime] = mapped_column(DateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    selected_side: Mapped[str | None] = mapped_column(String(1), nullable=True)
    correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    run: Mapped[Run] = relationship(back_populates="rounds")
    fact: Mapped[Fact] = relationship()
    fake: Mapped[Fake] = relationship()


class AuthAttempt(Base):
    __tablename__ = "auth_attempts"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    window_at: Mapped[datetime] = mapped_column(DateTime)
