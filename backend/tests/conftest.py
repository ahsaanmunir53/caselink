import pytest
from fastapi.testclient import TestClient

from app.ai import model_status
from app.config import Settings
from app.main import create_app


@pytest.fixture(autouse=True)
def _fresh_model_status():
    model_status.reset()
    yield
    model_status.reset()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(_env_file=None, app_env="test", llm_provider="none", groq_api_key=None, google_api_key=None,
                    sqlite_path=str(tmp_path / "test.db"), rate_limit_per_minute=10_000, demo_mode=True,
                    cron_secret="cron-secret-for-tests")


@pytest.fixture
def client(settings):
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def login(client, email="ayesha.analyst@caselink.demo") -> dict:
    token = client.post("/api/auth/demo", json={"email": email}).json()["token"]
    return {"Authorization": f"Bearer {token}"}
