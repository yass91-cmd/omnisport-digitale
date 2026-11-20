"""Use independent MySQL connections to prove simultaneous edits cannot mix settings."""

import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import delete, make_url
from sqlalchemy.orm import Session

from backend.app.config import ROOT, Settings
from backend.app.database import make_engine
from backend.app.main import create_app
from backend.app.models import (
    Complex,
    Facility,
    FacilityTariff,
    LoginSession,
    OpeningHour,
    Sport,
    SportDuration,
    StaffAssignment,
    User,
)
from backend.app.security import csrf_token, passwords, token_hash, utcnow


def test_concurrent_mysql_edits_allow_one_winner_and_keep_its_complete_configuration():
    url = os.environ.get("OMNI_TEST_DATABASE_URL")
    if not url:
        if os.environ.get("CI") == "true":
            pytest.fail("MySQL concurrency proof is required in CI")
        pytest.skip(
            "Run the Docker test service for independent-connection MySQL concurrency proof"
        )
    parsed = make_url(url)
    assert parsed.get_backend_name() == "mysql" and (parsed.database or "").endswith("_test")
    settings = Settings(database_url=url, auth_origins=["http://testserver"], _env_file=None)
    engine = make_engine(settings)
    config = Config(str(ROOT / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    user_id, complex_id, sport_id, facility_id = [uuid4() for _ in range(4)]
    tokens = [secrets.token_urlsafe(32), secrets.token_urlsafe(32)]
    now = utcnow()
    try:
        with Session(engine) as session, session.begin():
            session.add_all(
                [
                    Complex(
                        id=complex_id,
                        name="Concurrent test complex",
                        city="Test",
                        address="Test",
                        timezone="Africa/Casablanca",
                        description="Disposable isolated test data",
                        is_demo=True,
                    ),
                    Sport(id=sport_id, slug=f"test-{sport_id.hex}", name="Concurrent test sport"),
                    User(
                        id=user_id,
                        name="Concurrent test admin",
                        email=f"{user_id.hex}@example.com",
                        password_hash=passwords.hash(secrets.token_urlsafe(24)),
                        created_at=now,
                    ),
                ]
            )
            session.flush()
            session.add_all(
                [
                    SportDuration(sport_id=sport_id, minutes=60),
                    Facility(
                        id=facility_id,
                        complex_id=complex_id,
                        sport_id=sport_id,
                        name="Original",
                        surface="Hard court",
                        description="Concurrent test",
                    ),
                    StaffAssignment(user_id=user_id, complex_id=complex_id, role="admin"),
                    *[
                        LoginSession(
                            token_hash=token_hash(token),
                            user_id=user_id,
                            created_at=now,
                            last_seen_at=now,
                            expires_at=now + timedelta(hours=1),
                        )
                        for token in tokens
                    ],
                ]
            )
        barrier = Barrier(2)
        with ExitStack() as stack:
            clients = [
                stack.enter_context(TestClient(create_app(settings, engine=engine))) for _ in tokens
            ]
            bodies = [
                {
                    "version": 1,
                    "name": name,
                    "sport_id": str(sport_id),
                    "surface": "Hard court",
                    "active": True,
                    "description": "Concurrent test",
                    "opening_hours": [{"weekday": 0, "opens_at": opens, "closes_at": closes}],
                    "tariffs": [{"minutes": 60, "amount": amount}],
                }
                for name, opens, closes, amount in [
                    ("First editor", "09:00", "12:00", "100.00"),
                    ("Second editor", "13:00", "18:00", "200.00"),
                ]
            ]

            def edit(index):
                client = clients[index]
                client.cookies.set("omni_session", tokens[index])
                barrier.wait(timeout=10)
                return client.put(
                    f"/api/v1/staff/complexes/{complex_id}/facilities/{facility_id}",
                    json=bodies[index],
                    headers={
                        "X-Omni-Request": "1",
                        "Origin": "http://testserver",
                        "X-CSRF-Token": csrf_token(tokens[index]),
                    },
                )

            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(edit, index) for index in range(2)]
                responses = [future.result(timeout=30) for future in futures]
            assert sorted(response.status_code for response in responses) == [200, 409], [
                response.text for response in responses
            ]
            winner = next(
                index for index, response in enumerate(responses) if response.status_code == 200
            )
            saved = (
                clients[winner]
                .get(f"/api/v1/staff/complexes/{complex_id}/facilities/{facility_id}")
                .json()
            )
            assert saved["version"] == 2
            assert saved["name"] == bodies[winner]["name"]
            assert saved["opening_hours"] == bodies[winner]["opening_hours"]
            assert saved["tariffs"] == bodies[winner]["tariffs"]
    finally:
        with Session(engine) as session, session.begin():
            session.execute(delete(FacilityTariff).where(FacilityTariff.facility_id == facility_id))
            session.execute(delete(OpeningHour).where(OpeningHour.facility_id == facility_id))
            session.execute(delete(Facility).where(Facility.id == facility_id))
            session.execute(delete(StaffAssignment).where(StaffAssignment.user_id == user_id))
            session.execute(delete(LoginSession).where(LoginSession.user_id == user_id))
            session.execute(delete(User).where(User.id == user_id))
            session.execute(delete(SportDuration).where(SportDuration.sport_id == sport_id))
            session.execute(delete(Sport).where(Sport.id == sport_id))
            session.execute(delete(Complex).where(Complex.id == complex_id))
        engine.dispose()
