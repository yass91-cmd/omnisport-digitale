"""Two coaches cannot simultaneously transfer a player from the same membership."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import delete, make_url, select
from sqlalchemy.orm import Session

from backend.app.config import ROOT, Settings
from backend.app.database import make_engine
from backend.app.models import (
    RosterIdentityLock,
    Sport,
    Team,
    TeamContactMember,
    TeamMembership,
    TeamRequest,
    User,
)
from backend.app.security import utcnow
from backend.app.teams import AddPlayerInput, DecisionInput, add_player, decide_request, roster_key


@pytest.mark.parametrize("mode", ["join", "contact"])
def test_concurrent_team_acceptance_has_one_winner(mode):
    url = os.environ.get("OMNI_TEST_DATABASE_URL")
    if not url:
        if os.environ.get("CI") == "true":
            pytest.fail("CI requires MySQL transfer concurrency proof")
        pytest.skip("Run Docker tests for MySQL concurrency proof")
    parsed = make_url(url)
    assert parsed.get_backend_name() == "mysql" and parsed.database.endswith("_test")
    engine = make_engine(Settings(database_url=url, _env_file=None))
    config = Config(str(ROOT / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    sport_id, player_id = uuid4(), uuid4()
    coaches, teams, requests = [uuid4(), uuid4()], [uuid4(), uuid4()], [uuid4(), uuid4()]
    try:
        with Session(engine) as session, session.begin():
            session.add(Sport(id=sport_id, slug=str(sport_id), name="Concurrent sport"))
            for uid, role in [(player_id, "player"), *[(uid, "coach") for uid in coaches]]:
                session.add(
                    User(
                        id=uid,
                        email=f"{uid}@example.com",
                        name="Concurrent test",
                        password_hash="unused",
                        client_role=role,
                        created_at=utcnow(),
                    )
                )
            session.flush()
            for index in range(2):
                session.add(
                    Team(
                        id=teams[index],
                        coach_id=coaches[index],
                        sport_id=sport_id,
                        name=f"Concurrent {index}",
                        created_at=utcnow(),
                    )
                )
            session.flush()
            for index in range(2):
                session.add(
                    TeamRequest(
                        id=requests[index],
                        team_id=teams[index],
                        player_id=player_id,
                        kind="join",
                        created_at=utcnow(),
                    )
                )
        barrier = Barrier(2)

        def accept(index):
            with Session(engine) as session:
                # Establish two old snapshots before either transition starts.
                session.get(TeamRequest, requests[index])
                barrier.wait(timeout=10)
                try:
                    identity = SimpleNamespace(
                        user=SimpleNamespace(id=coaches[index], client_role="coach")
                    )
                    if mode == "contact":
                        add_player(
                            teams[index],
                            AddPlayerInput(name=str(player_id), phone="0611223344"),
                            identity,
                            session,
                        )
                    else:
                        decide_request(
                            requests[index], DecisionInput(action="accept"), identity, session
                        )
                    return 200
                except HTTPException as error:
                    session.rollback()
                    return error.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(accept, range(2)))
        assert sorted(results) == [200, 409]
        with Session(engine) as session:
            members = session.scalars(
                select(TeamMembership).where(TeamMembership.player_id == player_id)
            ).all()
            if mode == "contact":
                members = session.scalars(
                    select(TeamContactMember).where(TeamContactMember.sport_id == sport_id)
                ).all()
            assert len(members) == 1 and members[0].active_slot == 1
    finally:
        with Session(engine) as session, session.begin():
            session.execute(delete(TeamRequest).where(TeamRequest.id.in_(requests)))
            session.execute(delete(TeamMembership).where(TeamMembership.player_id == player_id))
            session.execute(delete(TeamContactMember).where(TeamContactMember.sport_id == sport_id))
            session.execute(
                delete(RosterIdentityLock).where(
                    RosterIdentityLock.key == roster_key(str(player_id), "+212611223344")
                )
            )
            session.execute(delete(Team).where(Team.id.in_(teams)))
            session.execute(delete(User).where(User.id.in_([player_id, *coaches])))
            session.execute(delete(Sport).where(Sport.id == sport_id))
        engine.dispose()
