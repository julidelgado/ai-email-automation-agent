from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Configure test settings before importing application modules.
os.environ["APP_ENVIRONMENT"] = "test"
os.environ["APP_DATABASE_URL"] = "sqlite:///./test.db"
os.environ["APP_SCHEDULER_ENABLED"] = "false"
os.environ["APP_AI_PROVIDER"] = "rule_based"
os.environ["APP_IMAP_HOST"] = ""
os.environ["APP_IMAP_USERNAME"] = ""
os.environ["APP_IMAP_PASSWORD"] = ""
os.environ["APP_SMTP_HOST"] = ""
os.environ["APP_SMTP_USERNAME"] = ""
os.environ["APP_SMTP_PASSWORD"] = ""
os.environ["APP_ACTION_INVOICE_ACCOUNTING_EMAIL"] = ""
os.environ["APP_SECURITY_BASIC_AUTH_ENABLED"] = "false"
os.environ["APP_SECURITY_BASIC_AUTH_USERNAME"] = ""
os.environ["APP_SECURITY_BASIC_AUTH_PASSWORD"] = ""

from app.config import get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_engine, get_session_factory, reset_db_state  # noqa: E402
from app.main import create_app  # noqa: E402
import app.db.models  # noqa: E402,F401


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_database():
    get_settings.cache_clear()
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    reset_db_state()
    test_db = Path("test.db")
    if test_db.exists():
        test_db.unlink()


@pytest.fixture(autouse=True)
def isolate_test_data():
    db = get_session_factory()()
    try:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(table.delete())
        db.commit()
        yield
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(table.delete())
        db.commit()
    finally:
        db.close()


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db_session():
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()
