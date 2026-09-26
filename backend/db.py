import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine():
    url = os.getenv("FACTISH_DATABASE_URL")
    if not url:
        data = Path(__file__).resolve().parent.parent / "data"
        data.mkdir(exist_ok=True)
        url = f"sqlite:///{(data / 'factish.sqlite3').as_posix()}"
    engine = create_engine(url, connect_args={"check_same_thread": False}, pool_pre_ping=True)

    @event.listens_for(engine, "connect")
    def configure(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    return engine


engine = make_engine()
SessionLocal = sessionmaker(engine, expire_on_commit=False)
