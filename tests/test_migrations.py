from decimal import Decimal
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, func, select
from sqlalchemy.orm import Session

from backend.app.config import ROOT, Settings
from backend.app.database import make_engine
from backend.app.models import Complex, Facility, FacilityTariff, OpeningHour, StaffAssignment, User
from backend.app.security import utcnow
from backend.app.seed import demo_id, seed_demo


def test_contact_upgrade_preserves_legacy_booking_notifications_and_read_receipts(tmp_path):
    from datetime import datetime

    settings = Settings(
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'contacts.sqlite').as_posix()}",
        _env_file=None,
    )
    engine = make_engine(settings)
    config = Config(str(ROOT / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0007_staff_notifications")
    with Session(engine) as session, session.begin():
        seed_demo(session)
    uid, booking_id, notice_id = uuid4(), uuid4(), uuid4()
    now = datetime(2026, 11, 20, 7)
    with engine.begin() as connection:
        meta = MetaData()
        users = Table("users", meta, autoload_with=connection)
        bookings = Table("reservations", meta, autoload_with=connection)
        notices = Table("staff_notifications", meta, autoload_with=connection)
        reads = Table("staff_notification_reads", meta, autoload_with=connection)
        connection.execute(
            users.insert().values(
                id=uid.hex,
                name="Legacy Customer",
                email="legacy@example.com",
                password_hash="unused",
                client_role="player",
                active=True,
                created_at=now,
            )
        )
        connection.execute(
            bookings.insert().values(
                id=booking_id.hex,
                request_id=uuid4().hex,
                reference="OM-LEGACY-TEST",
                facility_id=demo_id("atlas-tennis").hex,
                client_id=uid.hex,
                entered_by=uid.hex,
                source="online",
                starts_at=datetime(2026, 11, 23, 9),
                ends_at=datetime(2026, 11, 23, 11),
                minutes=120,
                timezone="Africa/Casablanca",
                currency="MAD",
                base_amount=220,
                total_amount=220,
                applied_percent=0,
                weekend_applied=False,
                evening_applied=False,
                quoted_version=1,
                version=1,
                status="confirmed",
                created_at=now,
            )
        )
        connection.execute(
            notices.insert().values(
                id=notice_id.hex,
                complex_id=demo_id("atlas").hex,
                facility_id=demo_id("atlas-tennis").hex,
                client_id=uid.hex,
                reservation_id=booking_id.hex,
                kind="booking_confirmed",
                requested_day=datetime(2026, 11, 23).date(),
                minutes=120,
                created_at=now,
            )
        )
        connection.execute(
            reads.insert().values(notification_id=notice_id.hex, user_id=uid.hex, read_at=now)
        )
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    from backend.app.models import Reservation, StaffNotification, StaffNotificationRead

    with Session(engine) as session:
        row = session.get(Reservation, booking_id)
        assert row.client_name == "Legacy Customer" and row.client_phone is None
        assert row.total_amount == Decimal("220.00") and row.status == "confirmed"
        assert row.arrived_at is None and row.arrived_by is None
        assert row.approved_at is None and row.approved_by is None
        assert row.approval_status == "accepted"
        assert session.get(StaffNotification, notice_id).reservation_id == booking_id
        assert session.get(StaffNotificationRead, (notice_id, uid)).read_at == now
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0007_staff_notifications")
        command.upgrade(config, "head")
        assert not connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    with Session(engine) as session:
        assert session.get(Reservation, booking_id).client_name == "Legacy Customer"
        assert session.get(StaffNotificationRead, (notice_id, uid)) is not None
    with Session(engine) as session, session.begin():
        row = session.get(Reservation, booking_id)
        row.arrived_at = now
        row.arrived_by = uid
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        with pytest.raises(RuntimeError, match="Arrival history exists"):
            command.downgrade(config, "0009_booking_approval")
        command.upgrade(config, "head")
    with Session(engine) as session:
        assert session.get(Reservation, booking_id).arrived_at == now
        assert session.get(StaffNotificationRead, (notice_id, uid)) is not None
    engine.dispose()


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
