from uuid import UUID

from sqlalchemy import func, select

from backend.app.models import TeamMembership, TeamRequest
from backend.app.seed import demo_id

WRITE = {"X-Omni-Request": "1", "Origin": "http://testserver"}
PASSWORD = "a disposable teams test passphrase"


def register(client, name, role="player"):
    response = client.post(
        "/api/v1/auth/register",
        headers=WRITE,
        json={
            "name": name,
            "email": f"{name}@example.com",
            "password": PASSWORD,
            "client_role": role,
            "phone": "+212612345678",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def login(client, name):
    response = client.post(
        "/api/v1/auth/login",
        headers=WRITE,
        json={"email": f"{name}@example.com", "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()


def post(client, account, path, body=None):
    return client.post(
        "/api/v1/teams" + path,
        headers={**WRITE, "X-CSRF-Token": account["csrf_token"]},
        json=body or {},
    )


def create(client, account, name="Atlas", sport="football"):
    response = post(client, account, "", {"name": name, "sport_id": str(demo_id(sport))})
    assert response.status_code == 201, response.text
    return response.json()


def decide(client, account, request, action="accept"):
    return post(client, account, f"/requests/{request['id']}/decide", {"action": action})


def test_team_ownership_search_csrf_and_private_roster(client):
    assert client.get("/api/v1/teams").status_code == 401
    coach = register(client, "coach", "coach")
    team = create(client, coach)
    assert (
        post(client, coach, "", {"name": " ", "sport_id": str(demo_id("football"))}).status_code
        == 422
    )
    assert (
        post(client, coach, "", {"name": "Atlas", "sport_id": str(demo_id("football"))}).status_code
        == 409
    )
    other = register(client, "other", "coach")
    assert (
        client.patch(
            f"/api/v1/teams/{team['id']}",
            json={"open_to_requests": False},
            headers={**WRITE, "X-CSRF-Token": other["csrf_token"]},
        ).status_code
        == 404
    )
    player = register(client, "player")
    assert (
        post(client, player, "", {"name": "Fake", "sport_id": str(demo_id("football"))}).status_code
        == 403
    )
    assert (
        client.post(f"/api/v1/teams/{team['id']}/join", headers=WRITE, json={}).status_code == 403
    )
    assert client.get("/api/v1/teams/activity").json() == {
        "requests": [],
        "members": [],
        "has_more": False,
    }
    coach = login(client, "coach")
    assert (
        client.patch(
            f"/api/v1/teams/{team['id']}",
            json={"open_to_requests": False},
            headers={**WRITE, "X-CSRF-Token": coach["csrf_token"]},
        ).status_code
        == 200
    )
    player = login(client, "player")
    assert client.get("/api/v1/teams").json()["items"][0]["id"] == team["id"]
    assert post(client, player, f"/{team['id']}/join").status_code == 201


def test_join_acceptance_transfer_keeps_other_sports_and_history(client, session):
    coach = register(client, "coach", "coach")
    first = create(client, coach)
    second = create(client, coach, "Lions")
    tennis = create(client, coach, "Tennis", "tennis")
    player = register(client, "player")
    for team in [first, tennis, second]:
        player = login(client, "player")
        response = post(client, player, f"/{team['id']}/join")
        assert response.status_code == 201, response.text
        request = response.json()
        assert decide(client, player, request).status_code == 403
        assert post(client, player, f"/{team['id']}/join").status_code == 409
        coach = login(client, "coach")
        assert decide(client, coach, request).status_code == 200
        assert decide(client, coach, request).status_code == 200
    active = session.scalars(select(TeamMembership).where(TeamMembership.active_slot == 1)).all()
    assert {str(row.team_id) for row in active} == {second["id"], tennis["id"]}
    assert session.scalar(select(func.count()).select_from(TeamMembership)) == 3
    old = session.scalar(select(TeamMembership).where(TeamMembership.team_id == UUID(first["id"])))
    assert old.ended_at is not None and old.active_slot is None


def test_invitation_consent_decline_withdraw_and_leave(client, session):
    coach = register(client, "coach", "coach")
    team = create(client, coach)
    register(client, "player")
    coach = login(client, "coach")
    invite = post(client, coach, f"/{team['id']}/invite", {"email": "player@example.com"}).json()
    assert decide(client, coach, invite).status_code == 403
    player = login(client, "player")
    assert decide(client, player, invite, "decline").status_code == 200
    assert session.scalar(select(func.count()).select_from(TeamMembership)) == 0
    request = post(client, player, f"/{team['id']}/join").json()
    assert decide(client, player, request, "withdraw").status_code == 200
    coach = login(client, "coach")
    invite = post(client, coach, f"/{team['id']}/invite", {"email": "player@example.com"}).json()
    stranger = register(client, "stranger")
    assert decide(client, stranger, invite).status_code == 404
    assert client.get("/api/v1/teams/activity").json()["requests"] == []
    player = login(client, "player")
    assert decide(client, player, invite).status_code == 200
    member = client.get("/api/v1/teams/activity").json()["members"][0]
    assert post(client, player, f"/memberships/{member['id']}/leave").status_code == 200
    assert client.get("/api/v1/teams/activity").json()["members"] == []


def test_stale_join_cannot_silently_replace_newer_membership(client, session):
    coach = register(client, "coach", "coach")
    teams = [create(client, coach, name) for name in ["Atlas", "Lions"]]
    player = register(client, "player")
    requests = [post(client, player, f"/{team['id']}/join").json() for team in teams]
    coach = login(client, "coach")
    assert decide(client, coach, requests[0]).status_code == 200
    assert decide(client, coach, requests[1]).status_code == 409
    assert session.scalar(select(func.count()).select_from(TeamMembership)) == 1


def test_transfer_failure_rolls_back_old_membership(client, session, monkeypatch):
    from sqlalchemy.orm import Session

    from backend.app.database import get_session

    coach = register(client, "coach", "coach")
    teams = [create(client, coach, name) for name in ["Atlas", "Lions"]]
    player = register(client, "player")
    request = post(client, player, f"/{teams[0]['id']}/join").json()
    coach = login(client, "coach")
    assert decide(client, coach, request).status_code == 200
    player = login(client, "player")
    request = post(client, player, f"/{teams[1]['id']}/join").json()
    coach = login(client, "coach")
    override = client.app.dependency_overrides[get_session]

    def request_session():
        with Session(bind=session.get_bind(), join_transaction_mode="create_savepoint") as scoped:
            yield scoped

    original = Session.add

    def fail_new_membership(self, instance, **kwargs):
        if isinstance(instance, TeamMembership):
            from sqlalchemy.exc import SQLAlchemyError

            raise SQLAlchemyError("Simulated transfer failure")
        return original(self, instance, **kwargs)

    client.app.dependency_overrides[get_session] = request_session
    monkeypatch.setattr(Session, "add", fail_new_membership)
    try:
        assert decide(client, coach, request).status_code == 503
    finally:
        client.app.dependency_overrides[get_session] = override
    session.expire_all()
    assert session.scalar(
        select(TeamMembership).where(TeamMembership.active_slot == 1)
    ).team_id == UUID(teams[0]["id"])
    assert session.get(TeamRequest, UUID(request["id"])).status == "pending"


def test_coach_adds_player_without_email_or_login_and_removes_privately(client, session):
    from backend.app.models import TeamContactMember, User

    coach = register(client, "coach", "coach")
    team = create(client, coach)
    count = session.scalar(select(func.count()).select_from(User))
    body = {"name": "  Omar   Benali  ", "phone": "06 11 22 33 44"}
    response = post(client, coach, f"/{team['id']}/players", body)
    assert response.status_code == 201, response.text
    member = response.json()
    assert member["player_name"] == "Omar Benali"
    assert member["phone"] == "+212611223344" and member["email"] is None
    assert session.scalar(select(func.count()).select_from(User)) == count
    assert client.get("/api/v1/teams/activity").json()["members"][0]["id"] == member["id"]
    body["name"] = "omar benali"
    body["phone"] = "+212611223344"
    assert post(client, coach, f"/{team['id']}/players", body).status_code == 409
    other = register(client, "other", "coach")
    assert post(client, other, f"/{team['id']}/players", body).status_code == 404
    assert post(client, other, f"/players/{member['id']}/remove").status_code == 404
    assert client.get("/api/v1/teams/activity").json()["members"] == []
    player = register(client, "player")
    assert post(client, player, f"/{team['id']}/players", body).status_code == 403
    coach = login(client, "coach")
    assert post(client, coach, f"/players/{member['id']}/remove").status_code == 200
    assert session.get(TeamContactMember, UUID(member["id"])).ended_at is not None
    assert client.get("/api/v1/teams/activity").json()["members"] == []
    assert post(client, coach, f"/{team['id']}/players", body).status_code == 201


def test_player_contact_validation_optional_email_and_sport_conflict(client, session):
    coach = register(client, "coach", "coach")
    first = create(client, coach)
    other = create(client, coach, "Lions")
    tennis = create(client, coach, "Rackets", "tennis")
    body = {"name": "Omar Benali", "phone": "0611223344", "email": " omar@example.com "}
    for invalid in [{"name": " "}, {"phone": ""}, {"phone": "wrong"}, {"email": "wrong"}]:
        assert (
            post(client, coach, f"/{first['id']}/players", {**body, **invalid}).status_code == 422
        )
    assert (
        client.post(f"/api/v1/teams/{first['id']}/players", headers=WRITE, json=body).status_code
        == 403
    )
    response = post(client, coach, f"/{first['id']}/players", body)
    assert response.status_code == 201, response.text
    assert response.json()["email"] == "omar@example.com"
    assert post(client, coach, f"/{other['id']}/players", body).status_code == 409
    body["email"] = ""
    response = post(client, coach, f"/{tennis['id']}/players", body)
    assert response.status_code == 201 and response.json()["email"] is None


def test_existing_player_join_reconciles_same_team_contact_after_coach_accepts(client, session):
    from backend.app.models import TeamContactMember

    coach = register(client, "coach", "coach")
    team = create(client, coach)
    body = {"name": "player", "phone": "+212612345678"}
    contact = post(client, coach, f"/{team['id']}/players", body)
    assert contact.status_code == 201
    player = register(client, "player")
    request = post(client, player, f"/{team['id']}/join").json()
    coach = login(client, "coach")
    assert decide(client, coach, request).status_code == 200
    assert session.get(TeamContactMember, UUID(contact.json()["id"])).ended_at is not None
    members = client.get("/api/v1/teams/activity").json()["members"]
    assert len(members) == 1 and members[0]["player_name"] == "player"
    assert post(client, coach, f"/{team['id']}/players", body).status_code == 409
