import io
import mimetypes
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from backend import app as web
from backend import import_content
from backend.db import Base
from backend.models import Fact, Fake, Round, Run, User


HEADERS = {"X-Factish-Request": "1"}


@pytest.fixture
def setup_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'test.sqlite3').as_posix()}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(web, "SessionLocal", sessions)
    monkeypatch.setattr(import_content, "SessionLocal", sessions)
    monkeypatch.setattr(web, "AVATAR_DIR", tmp_path)
    assert import_content.import_files() == (900, 900)
    yield sessions
    engine.dispose()


def post(client, path, body=None):
    return client.post(path, json=body, headers=HEADERS)


def test_csv_import_and_random_independent_content(setup_db):
    with setup_db() as db:
        assert db.scalar(select(func.count()).select_from(Fact)) == 900
        assert db.scalar(select(func.count()).select_from(Fake)) == 900
        assert all(0 <= item.difficulty <= 100 for item in db.scalars(select(Fact)))
        assert all(0 <= item.difficulty <= 100 for item in db.scalars(select(Fake)))
    with TestClient(web.app) as client:
        assert client.get("/api/bootstrap").json()["questionCount"] == 900
        card = post(client, "/api/game/next").json()
        with setup_db() as db:
            round_ = db.get(Round, card["roundId"])
            expected = {round_.fact.statement, round_.fake.statement}
            assert set(card["options"]) == expected
            assert "correctSide" not in card
            assert "explanation" not in card


def test_content_files_add_up_and_reimport_keeps_rows(setup_db):
    old, new, *_ = import_content.CONTENT_FILES
    with setup_db() as db:
        ids = set(db.scalars(select(Fact.id)))
        assert db.scalar(select(func.count()).select_from(Fact).where(Fact.source == old.name)) == 50
    assert import_content.import_files([new]) == (200, 200)
    with setup_db() as db:
        assert db.scalar(select(func.count()).select_from(Fact).where(Fact.active.is_(True))) == 200
    assert import_content.import_files() == (900, 900)
    with setup_db() as db:
        assert set(db.scalars(select(Fact.id).where(Fact.active.is_(True)))) == ids


def test_statement_repeated_across_files_is_rejected(tmp_path):
    header = "id,сфера,утверждение,тип,сложность_из_100,пояснение_после_ответа\n"
    for name, rows in (("a.csv", "1,Наука,Одно,факт,10,Да\n2,Наука,Другое,фейк,10,Нет\n"), ("b.csv", "1,Наука,Одно,фейк,10,Нет\n")):
        (tmp_path / name).write_text(header + rows, encoding="utf-8")
    with pytest.raises(ValueError, match="repeats one from a.csv"):
        import_content.load([tmp_path / "a.csv", tmp_path / "b.csv"])


def test_guest_result_transfers_once_and_enters_leaderboard(setup_db):
    with TestClient(web.app) as guest, TestClient(web.app) as stranger:
        assert guest.get("/api/bootstrap").json()["profile"]["displayName"] == "Гость"
        stranger.get("/api/bootstrap")
        first = post(guest, "/api/game/next").json()
        with setup_db() as db:
            side = db.get(Round, first["roundId"]).correct_side
        correct = post(guest, "/api/game/answer", {"roundId": first["roundId"], "choice": side})
        assert correct.status_code == 200
        assert correct.json()["streak"] == 1
        second = post(guest, "/api/game/next").json()
        with setup_db() as db:
            side = db.get(Round, second["roundId"]).correct_side
        wrong_side = "B" if side == "A" else "A"
        wrong = post(guest, "/api/game/answer", {"roundId": second["roundId"], "choice": wrong_side})
        assert wrong.json()["gameOver"] is True
        assert wrong.json()["stats"]["best"] == 1
        assert stranger.get("/api/leaderboard?period=all&metric=streak").json()["rows"] == []
        registered = post(guest, "/api/auth/register", {"login": "Player_1", "password": "correct horse battery"})
        assert registered.status_code == 200, registered.text
        assert registered.json()["profile"]["stats"]["best"] == 1
        assert registered.json()["profile"]["login"] == "player_1"
        with setup_db() as db:
            user = db.scalar(select(User).where(User.login == "player_1"))
            assert user.password_hash != "correct horse battery"
            assert db.scalar(select(func.count()).select_from(Run).where(Run.user_id == user.id)) == 1
        assert stranger.get("/api/leaderboard?period=all&metric=streak").json()["rows"][0]["best"] == 1
        assert post(guest, "/api/auth/register", {"login": "PLAYER_1", "password": "another password"}).status_code == 409
        assert post(guest, "/api/auth/logout").status_code == 200
        assert post(guest, "/api/auth/login", {"login": "PLAYER_1", "password": "correct horse battery"}).json()["profile"]["stats"]["best"] == 1
        with setup_db() as db:
            assert db.scalar(select(func.count()).select_from(Run).where(Run.user_id == user.id)) == 1
        assert post(stranger, "/api/game/answer", {"roundId": first["roundId"], "choice": "A"}).status_code == 404


def test_deadline_and_duplicate_answer(setup_db):
    with TestClient(web.app) as client:
        client.get("/api/bootstrap")
        card = post(client, "/api/game/next").json()
        with setup_db.begin() as db:
            round_ = db.get(Round, card["roundId"])
            round_.issued_at -= timedelta(seconds=16)
            correct_side = round_.correct_side
        result = post(client, "/api/game/answer", {"roundId": card["roundId"], "choice": correct_side})
        assert result.status_code == 200
        assert result.json()["timedOut"] is True
        assert result.json()["stats"]["completedRuns"] == 1
        assert result.json()["stats"]["best"] == 0
        assert post(client, "/api/game/answer", {"roundId": card["roundId"], "choice": correct_side}).status_code == 409
        assert post(client, "/api/game/next").json()["roundId"] != card["roundId"]


def test_avatar_upload_and_request_guard(setup_db):
    with TestClient(web.app) as client:
        client.get("/api/bootstrap")
        assert client.post("/api/game/next").status_code == 403
        post(client, "/api/auth/register", {"login": "avatar_user", "password": "secure password"})
        image = Image.new("RGB", (64, 64), "green")
        data = io.BytesIO()
        image.save(data, "PNG")
        response = client.post("/api/profile/avatar/upload", headers=HEADERS, files={"image": ("avatar.png", data.getvalue(), "image/png")})
        assert response.status_code == 200, response.text
        assert response.json()["profile"]["avatar"].startswith("/avatars/")
        invalid = client.post("/api/profile/avatar/upload", headers=HEADERS, files={"image": ("bad.txt", b"bad", "text/plain")})
        assert invalid.status_code == 422


def test_javascript_module_has_browser_compatible_mime_type():
    assert mimetypes.guess_type("factish.js")[0] == "text/javascript"


def test_guest_cookie_can_be_scoped_to_deployment_path(setup_db, monkeypatch):
    monkeypatch.setenv("FACTISH_COOKIE_PATH", "/factish")
    with TestClient(web.app) as client:
        response = client.get("/api/bootstrap")
        assert response.status_code == 200
        assert "path=/factish" in response.headers["set-cookie"].lower()


def test_card_carries_server_clock_for_skew_free_timer(setup_db):
    with TestClient(web.app) as client:
        client.get("/api/bootstrap")
        card = post(client, "/api/game/next").json()
    parse = lambda value: datetime.fromisoformat(value.replace("Z", "+00:00"))
    left = (parse(card["deadline"]) - parse(card["serverNow"])).total_seconds()
    assert 14 <= left <= 15


def test_new_avatar_presets_are_selectable(setup_db):
    with TestClient(web.app) as client:
        assert {"panda", "unicorn", "robot"} <= set(client.get("/api/bootstrap").json()["presets"])
        post(client, "/api/auth/register", {"login": "preset_user", "password": "secure password"})
        response = client.patch("/api/profile/avatar", headers=HEADERS, json={"preset": "unicorn"})
        assert response.status_code == 200
        assert response.json()["profile"]["avatar"] == "preset:unicorn"
        assert client.patch("/api/profile/avatar", headers=HEADERS, json={"preset": "nope"}).status_code == 422
