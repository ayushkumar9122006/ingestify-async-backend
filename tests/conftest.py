import os
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure test storage directories exist
os.environ["UPLOAD_DIR"] = "/tmp/ingestify_test/uploads"
os.environ["ARTIFACT_DIR"] = "/tmp/ingestify_test/artifacts"
os.environ["THUMBNAIL_DIR"] = "/tmp/ingestify_test/thumbnails"
os.environ["STORAGE_BASE_DIR"] = "/tmp/ingestify_test"

from app.main import app
from app.core.database import Base, get_db
from app.core.rate_limiter import get_redis_client

# In-memory SQLite engine for tests
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

test_engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    """Create all database tables before test suite runs."""
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def db_session():
    """Provides a fresh database session for each test, rolling back after."""
    connection = test_engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


class MockRedisPipeline:
    def __init__(self, store):
        self.store = store
        self.commands = []

    def incr(self, key):
        self.commands.append(("incr", key))
        return self

    def ttl(self, key):
        self.commands.append(("ttl", key))
        return self

    def execute(self):
        results = []
        for cmd, key in self.commands:
            if cmd == "incr":
                val = self.store.get(key, 0) + 1
                self.store[key] = val
                results.append(val)
            elif cmd == "ttl":
                results.append(60)
        self.commands = []
        return results


class MockRedis:
    def __init__(self):
        self.store = {}

    def pipeline(self):
        return MockRedisPipeline(self.store)

    def expire(self, key, seconds):
        return True

    def flushall(self):
        self.store.clear()


@pytest.fixture
def mock_redis():
    """Fixture providing an isolated in-memory Redis mock for rate limit tests."""
    fake_redis = MockRedis()
    with patch("app.core.rate_limiter.get_redis_client", return_value=fake_redis):
        yield fake_redis


@pytest.fixture
def mock_celery():
    """Mocks Celery send_task and task revocation."""
    mock_task = MagicMock()
    mock_task.id = "mock-celery-task-9999"

    with patch("app.workers.celery_app.celery_app.send_task", return_value=mock_task) as mock_send, \
         patch("app.workers.celery_app.celery_app.control.revoke", return_value=True) as mock_revoke, \
         patch("app.workers.celery_app.celery_app.AsyncResult") as mock_async_res:

        res_instance = MagicMock()
        res_instance.state = "PENDING"
        mock_async_res.return_value = res_instance

        yield {
            "send_task": mock_send,
            "revoke": mock_revoke,
            "async_result": mock_async_res,
            "task": mock_task,
        }


@pytest.fixture
def client(db_session, mock_celery, mock_redis):
    """FastAPI TestClient with overridden dependencies and mocked broker."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
