from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.config import ROOT, Settings
from backend.app.database import make_engine
from backend.app.models import Complex, Facility
from backend.app.seed import seed_demo


def test_account_upgrade_and_rollback_preserve_existing_catalogue(tmp_path):
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'upgrade.sqlite').as_posix()}",
        _env_file=None,
    )
    engine = make_engine(settings)
    config = Config(str(ROOT / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0001_catalog")
    with Session(engine) as session, session.begin():
        seed_demo(session)
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        command.downgrade(config, "0001_catalog")
        command.upgrade(config, "head")
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Complex)) == 2
        assert session.scalar(select(func.count()).select_from(Facility)) == 5
    engine.dispose()
