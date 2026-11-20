import os

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import make_url
from sqlalchemy.orm import Session

from backend.app.config import ROOT, Settings
from backend.app.database import get_session, make_engine
from backend.app.main import create_app
from backend.app.seed import seed_demo


@pytest.fixture(params=["sqlite", "mysql"])
def database(request, tmp_path):
    if request.param == "mysql":
        url = os.environ.get("OMNI_TEST_DATABASE_URL")
        if not url:
            if os.environ.get("CI") == "true":
                pytest.fail("CI requires OMNI_TEST_DATABASE_URL; MySQL tests must not be skipped")
            pytest.skip(
                "Set OMNI_TEST_DATABASE_URL or run the Docker test service for MySQL checks"
            )
        parsed = make_url(url)
        if parsed.get_backend_name() != "mysql" or not (parsed.database or "").endswith("_test"):
            raise RuntimeError(
                "MySQL tests require an isolated database whose name ends with _test"
            )
    else:
        url = f"sqlite+pysqlite:///{(tmp_path / 'catalogue_test.sqlite').as_posix()}"
    settings = Settings(database_url=url, auth_origins=["http://testserver"], _env_file=None)
    engine = make_engine(settings)
    config = Config(str(ROOT / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    with engine.connect() as connection:
        transaction = connection.begin()
        session = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield settings, engine, session
        finally:
            session.close()
            if transaction.is_active:
                transaction.rollback()
    engine.dispose()


@pytest.fixture
def session(database):
    return database[2]


@pytest.fixture
def client(database):
    settings, engine, session = database
    with session.begin():
        seed_demo(session)
    app = create_app(settings, engine=engine)

    def test_session():
        yield session

    app.dependency_overrides[get_session] = test_session
    with TestClient(app) as client:
        yield client
