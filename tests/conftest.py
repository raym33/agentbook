import os
from pathlib import Path

import pytest
import pytest_asyncio
import httpx


os.environ.setdefault("DATABASE_URL", "sqlite:///./data/test.db")
os.environ.setdefault("LLM_BASE_URL", "http://127.0.0.1:1234")
os.environ.setdefault("LLM_MODEL", "local-model")
os.environ.setdefault("ENABLE_AGENT_RUNNER", "false")

from app.main import app
from app.db import init_db


@pytest.fixture(autouse=True, scope="session")
def _ensure_data_dir():
    Path("./data").mkdir(parents=True, exist_ok=True)
    test_db = Path("./data/test.db")
    if test_db.exists():
        test_db.unlink()


@pytest_asyncio.fixture
async def async_client():
    init_db()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
