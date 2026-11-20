from decimal import Decimal
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.config import ROOT, Settings
from backend.app.database import make_engine
from backend.app.models import Complex, Facility, FacilityTariff, OpeningHour, StaffAssignment, User
from backend.app.security import utcnow
from backend.app.seed import demo_id, seed_demo


def test_account_upgrade_and_rollback_preserve_existing_catalogue(tmp_path):
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'upgrade.sqlite').as_posix()}",
        _env_file=None,
    )
    engine = make_engine(settings)
    config = Config(str(ROOT / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
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


def test_pricing_migration_preserves_existing_facilities_hours_tariffs_and_staff(tmp_path):
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'price_upgrade.sqlite').as_posix()}",
        _env_file=None,
    )
    engine = make_engine(settings)
    config = Config(str(ROOT / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    user_id = uuid4()
    with Session(engine) as session, session.begin():
        seed_demo(session)
        session.add(
            User(
                id=user_id,
                email="migration@example.com",
                name="Existing admin",
                password_hash="unused test hash",
                created_at=utcnow(),
            )
        )
        session.flush()
        session.add_all(
            [
                OpeningHour(
                    facility_id=demo_id("atlas-tennis"),
                    weekday=0,
                    start_minute=540,
                    end_minute=1260,
                ),
                FacilityTariff(
                    facility_id=demo_id("atlas-tennis"),
                    sport_id=demo_id("tennis"),
                    minutes=60,
                    amount=Decimal("120.00"),
                ),
                StaffAssignment(user_id=user_id, complex_id=demo_id("atlas"), role="admin"),
            ]
        )
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0003_facility_settings")
        command.upgrade(config, "head")
    with Session(engine) as session:
        facility = session.get(Facility, demo_id("atlas-tennis"))
        assert len(facility.opening_hours) == 1
        assert facility.tariffs[0].amount == Decimal("120.00")
        assert facility.weekend_percent == facility.evening_percent == Decimal("10.00")
        assert (
            session.scalar(select(StaffAssignment.role).where(StaffAssignment.user_id == user_id))
            == "admin"
        )
        assert session.scalar(select(func.count()).select_from(Facility)) == 5
    engine.dispose()
