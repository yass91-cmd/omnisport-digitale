from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from backend.app.config import ROOT, Settings
from backend.app.database import make_engine
from backend.app.main import create_app


def test_health_reports_migrated_schema(client):
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").json() == {"status": "ready"}


def test_landing_and_required_media_are_served(client):
    landing = client.get("/")
    assert landing.status_code == 200
    assert 'id="intro-dialog"' in landing.text
    assert client.get("/complexes.html").status_code == 200
    assert client.get("/complex.html").status_code == 200
    assert client.get("/assets/intro.js").status_code == 200
    assert (
        client.get("/media/landing-intro.mp4", headers={"Range": "bytes=0-99"}).status_code == 206
    )


def test_private_documents_and_source_are_not_public(client):
    for path in [
        "/README.md",
        "/media/README.md",
        "/OmniSport_Digitale.pdf",
        "/.env",
        "/backend/app/config.py",
    ]:
        assert client.get(path).status_code == 404


def test_readiness_handles_missing_and_stale_schema(tmp_path):
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'health.sqlite').as_posix()}", _env_file=None
    )
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        failure = client.get("/health/ready")
        assert failure.status_code == 503
        assert "SELECT" not in failure.text
        config = Config(str(ROOT / "alembic.ini"))
        with app.state.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            connection.exec_driver_sql("UPDATE alembic_version SET version_num='old_schema'")
        assert client.get("/health/ready").status_code == 503


def test_new_database_has_an_empty_catalogue(tmp_path):
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'empty.sqlite').as_posix()}", _env_file=None
    )
    engine = make_engine(settings)
    config = Config(str(ROOT / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    with TestClient(create_app(settings, engine=engine)) as client:
        assert client.get("/api/v1/complexes").json() == {"items": [], "total": 0}
