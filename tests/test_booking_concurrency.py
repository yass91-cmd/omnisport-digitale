"""Independent MySQL connections prove shared occupancy, snapshots and retry safety."""

import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import timedelta
from decimal import Decimal
from threading import Barrier, Event
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import delete, make_url, select
from sqlalchemy.orm import Session

from backend.app.config import ROOT, Settings
from backend.app.database import make_engine
from backend.app.main import create_app
from backend.app.models import (
    ClientNotification,
    Complex,
    Facility,
    FacilityClosure,
    FacilityTariff,
    LoginSession,
    OpeningHour,
    Reservation,
    Sport,
    SportDuration,
    StaffAssignment,
    StaffNotification,
    User,
)
from backend.app.security import Database, csrf_token, current_identity, token_hash, utcnow


@pytest.mark.parametrize(
    "second,ordered,version",
    [
        ("online", False, 1),
        ("online", True, 1),
        ("online", True, 2),
        ("staff", True, 2),
        ("closure", False, 1),
        ("closure", True, 2),
        ("retry", False, 1),
        ("walk-in", False, 1),
        ("walk-in", True, 2),
        ("decision", False, 1),
        ("decision", True, 1),
        ("acceptance", False, 1),
        ("acceptance", True, 1),
    ],
    ids=[
        "simultaneous",
        "old-snapshot",
        "predicted-version",
        "staff-online",
        "closure-online",
        "closure-old-snapshot",
        "same-request",
        "walk-in-online",
        "walk-in-predicted-version",
        "arrival-cancellation-race",
        "arrival-stale-cancellation",
        "accept-cancel-race",
        "accept-stale-cancel",
    ],
)
def test_mysql_claim_has_one_winner_across_all_schedule_writers(second, ordered, version):
    url = os.environ.get("OMNI_TEST_DATABASE_URL")
    if not url:
        if os.environ.get("CI") == "true":
            pytest.fail("MySQL booking concurrency proof is required in CI")
        pytest.skip("Run Docker tests for independent-connection booking proof")
    parsed = make_url(url)
    assert parsed.get_backend_name() == "mysql" and (parsed.database or "").endswith("_test")
    settings = Settings(database_url=url, auth_origins=["http://testserver"], _env_file=None)
    engine = make_engine(settings)
    config = Config(str(ROOT / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    complex_id, facility_id, sport_id = [uuid4() for _ in range(3)]
    users = [uuid4(), uuid4()]
    if second == "retry":
        users[1] = users[0]
    phones = {uid: "+21260000" + f"{i:04d}" for i, uid in enumerate(dict.fromkeys(users))}
    tokens = [secrets.token_urlsafe(32), secrets.token_urlsafe(32)]
    now = utcnow()
    day = (now + timedelta(days=14)).date().isoformat()
    request_ids = [str(uuid4()), str(uuid4())]
    if second == "retry":
        request_ids[1] = request_ids[0]
    try:
        with Session(engine) as session, session.begin():
            session.add_all(
                [
                    Complex(
                        id=complex_id,
                        name="Booking race",
                        city="Test",
                        address="Test",
                        timezone="UTC",
                        description="Disposable",
                        is_demo=True,
                    ),
                    Sport(id=sport_id, slug=f"race-{sport_id.hex}", name="Race sport"),
                    *[
                        User(
                            id=uid,
                            name="Race client",
                            phone=phones[uid],
                            email=f"{uid.hex}@example.com",
                            password_hash="unused isolated test hash",
                            created_at=now,
                        )
                        for uid in set(users)
                    ],
                ]
            )
            session.flush()
            session.add(
                Facility(
                    id=facility_id,
                    complex_id=complex_id,
                    sport_id=sport_id,
                    name="Race court",
                    surface="Hard",
                    description="Disposable",
                )
            )
            session.flush()
            session.add(SportDuration(sport_id=sport_id, minutes=60))
            session.flush()
            session.add_all(
                [
                    *[
                        OpeningHour(
                            facility_id=facility_id,
                            weekday=day_index,
                            start_minute=540,
                            end_minute=1320,
                        )
                        for day_index in range(7)
                    ],
                    FacilityTariff(
                        facility_id=facility_id,
                        sport_id=sport_id,
                        minutes=60,
                        amount=Decimal("120.00"),
                    ),
                    *[
                        StaffAssignment(user_id=uid, complex_id=complex_id, role="admin")
                        for uid in set(users)
                    ],
                    *[
                        LoginSession(
                            token_hash=token_hash(token),
                            user_id=users[i],
                            created_at=now,
                            last_seen_at=now,
                            expires_at=now + timedelta(hours=1),
                        )
                        for i, token in enumerate(tokens)
                    ],
                ]
            )
        if second in {"decision", "acceptance"}:
            with TestClient(create_app(settings, engine=engine)) as initial:
                initial.cookies.set("omni_session", tokens[0])
                saved = initial.post(
                    f"/api/v1/complexes/{complex_id}/facilities/{facility_id}/reservations",
                    headers={
                        "X-Omni-Request": "1",
                        "Origin": "http://testserver",
                        "X-CSRF-Token": csrf_token(tokens[0]),
                    },
                    json={
                        "facility_version": 1,
                        "starts_local": f"{day}T10:00",
                        "minutes": 60,
                        "request_id": str(uuid4()),
                    },
                )
                assert saved.status_code == 201, saved.text
                pending_id = saved.json()["id"]
                if second == "decision":
                    accepted = initial.post(
                        f"/api/v1/staff/complexes/{complex_id}/reservations/{pending_id}/accept",
                        headers={
                            "X-Omni-Request": "1",
                            "Origin": "http://testserver",
                            "X-CSRF-Token": csrf_token(tokens[0]),
                        },
                        json={"version": 1},
                    )
                    assert accepted.status_code == 200, accepted.text
        barrier, first_done = Barrier(2), Event()

        def synchronized_identity(request: Request, session: Database):
            identity = current_identity(request, session)
            session.scalar(select(User.id).where(User.id == identity.user.id))
            # Authentication establishes both REPEATABLE READ snapshots before a winner commits.
            barrier.wait(timeout=15)
            if ordered and request.headers.get("X-Test-Writer") == "1":
                assert first_done.wait(timeout=15)
            return identity

        with ExitStack() as stack:
            clients = []
            for _ in tokens:
                app = create_app(settings, engine=engine)
                app.dependency_overrides[current_identity] = synchronized_identity
                clients.append(stack.enter_context(TestClient(app)))

            def create(index):
                client = clients[index]
                client.cookies.set("omni_session", tokens[index])
                is_closure = index == 1 and second == "closure"
                staff = index == 1 and second in {"staff", "closure", "walk-in"}
                path = f"/api/v1/{'staff/' if staff else ''}complexes/{complex_id}/facilities/{facility_id}"
                body = {
                    "facility_version": 1 if index == 0 else version,
                    "starts_local": f"{day}T10:00",
                }
                if is_closure:
                    body.update(ends_local=f"{day}T12:00", reason="Race closure")
                else:
                    body.update(minutes=60, request_id=request_ids[index])
                    if staff:
                        body["client_name"] = (
                            "Walk-in test" if second == "walk-in" else "Race client"
                        )
                        body["client_phone"] = (
                            "+212611112222" if second == "walk-in" else phones[users[0]]
                        )
                try:
                    if second in {"decision", "acceptance"}:
                        return client.post(
                            f"/api/v1/staff/complexes/{complex_id}/reservations/{pending_id}/{('arrive' if second == 'decision' else 'accept') if index == 0 else 'cancel'}",
                            headers={
                                "X-Omni-Request": "1",
                                "Origin": "http://testserver",
                                "X-CSRF-Token": csrf_token(tokens[index]),
                                "X-Test-Writer": str(index),
                            },
                            json={"version": 2 if second == "decision" else 1},
                        )
                    return client.post(
                        path + ("/closures" if is_closure else "/reservations"),
                        headers={
                            "X-Omni-Request": "1",
                            "Origin": "http://testserver",
                            "X-CSRF-Token": csrf_token(tokens[index]),
                            "X-Test-Writer": str(index),
                        },
                        json=body,
                    )
                finally:
                    if index == 0:
                        first_done.set()

            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(create, range(2)))
            codes = sorted(r.status_code for r in responses)
            assert codes in (
                [[200, 409]]
                if second in {"decision", "acceptance"}
                else [[200, 201]]
                if second == "retry"
                else [[201, 409]]
            ), [r.text for r in responses]
            if second == "retry":
                assert responses[0].json()["id"] == responses[1].json()["id"]
        with Session(engine) as session:
            bookings = session.scalars(
                select(Reservation).where(Reservation.facility_id == facility_id)
            ).all()
            closures = session.scalars(
                select(FacilityClosure).where(FacilityClosure.facility_id == facility_id)
            ).all()
            assert len(bookings) + len(closures) == 1
            notices = session.scalars(
                select(StaffNotification).where(StaffNotification.facility_id == facility_id)
            ).all()
            assert len(notices) == 0
            assert session.get(Facility, facility_id).version == (
                4 if second == "decision" else 3 if second == "acceptance" else 2
            )
            if second == "decision":
                assert bookings[0].status in {"confirmed", "cancelled"}
                assert bookings[0].version == 3
                assert (bookings[0].arrived_by is not None) == (bookings[0].status == "confirmed")
    finally:
        with Session(engine) as session, session.begin():
            session.execute(
                delete(ClientNotification).where(
                    ClientNotification.reservation_id.in_(
                        select(Reservation.id).where(Reservation.facility_id == facility_id)
                    )
                )
            )
            for model in [
                StaffNotification,
                Reservation,
                FacilityClosure,
                FacilityTariff,
                OpeningHour,
            ]:
                session.execute(delete(model).where(model.facility_id == facility_id))
            session.execute(delete(Facility).where(Facility.id == facility_id))
            for model in [StaffAssignment, LoginSession]:
                session.execute(delete(model).where(model.user_id.in_(users)))
            session.execute(delete(User).where(User.id.in_(users)))
            session.execute(delete(SportDuration).where(SportDuration.sport_id == sport_id))
            session.execute(delete(Sport).where(Sport.id == sport_id))
            session.execute(delete(Complex).where(Complex.id == complex_id))
        engine.dispose()
