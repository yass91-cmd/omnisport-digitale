"""Prove closure writers serialize through the same physical facility row."""

import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import timedelta
from threading import Barrier, Event
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import delete, make_url, select
from sqlalchemy.orm import Session

from backend.app.auth import complex_assignment
from backend.app.config import ROOT, Settings
from backend.app.database import make_engine
from backend.app.main import create_app
from backend.app.models import (
    Complex,
    Facility,
    FacilityClosure,
    LoginSession,
    Sport,
    StaffAssignment,
    User,
)
from backend.app.security import (
    CurrentIdentity,
    Database,
    csrf_token,
    passwords,
    token_hash,
    utcnow,
)


@pytest.mark.parametrize(
    "second_version,wait_for_first",
    [(1, False), (1, True), (2, True)],
    ids=["simultaneous", "older-snapshot", "predicted-version"],
)
def test_simultaneous_mysql_closures_have_one_winner_and_do_not_overlap(
    second_version, wait_for_first
):
    url = os.environ.get("OMNI_TEST_DATABASE_URL")
    if not url:
        if os.environ.get("CI") == "true":
            pytest.fail("MySQL closure concurrency proof is required in CI")
        pytest.skip("Run the Docker test service for independent-connection closure proof")
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
    day = (now + timedelta(days=14)).date().isoformat()
    try:
        with Session(engine) as session, session.begin():
            session.add_all(
                [
                    Complex(
                        id=complex_id,
                        name="Closure race complex",
                        city="Test",
                        address="Test",
                        timezone="UTC",
                        description="Disposable concurrency test",
                        is_demo=True,
                    ),
                    Sport(id=sport_id, slug=f"race-{sport_id.hex}", name="Closure race sport"),
                    User(
                        id=user_id,
                        name="Closure race admin",
                        email=f"{user_id.hex}@example.com",
                        password_hash=passwords.hash(secrets.token_urlsafe(24)),
                        created_at=now,
                    ),
                ]
            )
            session.flush()
            session.add_all(
                [
                    Facility(
                        id=facility_id,
                        complex_id=complex_id,
                        sport_id=sport_id,
                        name="Race court",
                        surface="Hard",
                        description="Isolated",
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
        first_done = Event()

        def synchronized_assignment(
            complex_id: UUID, identity: CurrentIdentity, session: Database, request: Request
        ):
            assignment = complex_assignment(complex_id, identity, session)
            # Both MySQL read snapshots exist before the first closure commits.
            barrier.wait(timeout=10)
            if wait_for_first and request.headers.get("X-Test-Writer") == "1":
                assert first_done.wait(timeout=10)
            return assignment

        with ExitStack() as stack:
            clients = []
            for _ in tokens:
                app = create_app(settings, engine=engine)
                app.dependency_overrides[complex_assignment] = synchronized_assignment
                clients.append(stack.enter_context(TestClient(app)))
            path = f"/api/v1/staff/complexes/{complex_id}/facilities/{facility_id}/closures"

            def create(index):
                client = clients[index]
                client.cookies.set("omni_session", tokens[index])
                response = client.post(
                    path,
                    headers={
                        "X-Omni-Request": "1",
                        "Origin": "http://testserver",
                        "X-CSRF-Token": csrf_token(tokens[index]),
                        "X-Test-Writer": str(index),
                    },
                    json={
                        "facility_version": 1 if index == 0 else second_version,
                        "starts_local": f"{day}T10:00",
                        "ends_local": f"{day}T12:00",
                        "reason": f"Writer {index}",
                    },
                )
                if index == 0:
                    first_done.set()
                return response

            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(create, range(2)))
            assert sorted(response.status_code for response in responses) == [201, 409], [
                response.text for response in responses
            ]
            winner = next(
                index for index, response in enumerate(responses) if response.status_code == 201
            )
            if wait_for_first:
                assert winner == 0
        with Session(engine) as session:
            rows = session.scalars(
                select(FacilityClosure).where(FacilityClosure.facility_id == facility_id)
            ).all()
            assert len(rows) == 1 and rows[0].reason == f"Writer {winner}" and rows[0].active
            assert session.get(Facility, facility_id).version == 2
    finally:
        with Session(engine) as session, session.begin():
            session.execute(
                delete(FacilityClosure).where(FacilityClosure.facility_id == facility_id)
            )
            session.execute(delete(Facility).where(Facility.id == facility_id))
            session.execute(delete(StaffAssignment).where(StaffAssignment.user_id == user_id))
            session.execute(delete(LoginSession).where(LoginSession.user_id == user_id))
            session.execute(delete(User).where(User.id == user_id))
            session.execute(delete(Sport).where(Sport.id == sport_id))
            session.execute(delete(Complex).where(Complex.id == complex_id))
        engine.dispose()
