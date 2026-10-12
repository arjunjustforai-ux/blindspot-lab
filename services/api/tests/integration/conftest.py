"""Integration fixtures: a migrated test database, the API client and the ingested demo pack.

The demo pack (PDF, PPTX, narrated MP4) is ingested once per session through the real worker
pipeline (OCR, Whisper, embeddings, knowledge build, question generation). This takes a few
minutes on CPU the first time models are downloaded.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.config import REPO_ROOT, get_settings

API_ROOT = Path(__file__).resolve().parents[2]


def _reset_database(url: str) -> None:
    eng = create_engine(url)
    with eng.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        tables = conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")).scalars().all()
        for t in tables:
            conn.execute(text(f'DROP TABLE IF EXISTS "{t}" CASCADE'))
    eng.dispose()


@pytest.fixture(scope="session")
def database() -> str:
    url = get_settings().database_url
    assert "test" in url, f"refusing to reset a non-test database: {url}"
    try:
        eng = create_engine(url)
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
        eng.dispose()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"test database unavailable: {e}")
    _reset_database(url)
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config(str(API_ROOT / "alembic.ini")), "head")
    return url


@pytest.fixture(scope="session")
def client(database):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture(scope="session")
def demo_course_id(database) -> uuid.UUID:
    from app.cli import seed_demo

    for name in ("Marketing_Analytics_Primer.pdf", "Unit_Economics_for_Marketers.pptx", "Lecture_03_Price_Cuts.mp4"):
        if not (REPO_ROOT / "demo" / "course-materials" / name).exists():
            pytest.skip("demo course pack not built (run demo/scripts/build_course_pack.py)")
    return seed_demo(process=True)


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def demo_learner(client, demo_course_id) -> dict[str, str]:
    r = client.post("/api/auth/demo")
    assert r.status_code == 201, r.text
    return auth(r.json()["access_token"])


def register(client, name: str = "Tester") -> dict[str, str]:
    r = client.post("/api/auth/register", json={"email": f"{uuid.uuid4().hex[:10]}@example.com",
                                                "password": "correct-horse-battery", "display_name": name})
    assert r.status_code == 201, r.text
    return auth(r.json()["access_token"])
