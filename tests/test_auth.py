from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select

from backend.app import security
from backend.app.accounts import change_access
from backend.app.config import Settings
from backend.app.database import get_session
from backend.app.main import create_app
from backend.app.models import Complex, LoginSession, StaffAssignment, User
from backend.app.seed import demo_id

PASSWORD = "a memorable test password 2026"
WRITE = {"X-Omni-Request": "1", "Origin": "http://testserver"}


def signup(client, **changes):
    data = {"name": "Test Player", "email": "player@example.com", "password": PASSWORD}
    data.update(changes)
    return client.post("/api/v1/auth/register", json=data, headers=WRITE)


def signin(client, **changes):
    data = {"email": "player@example.com", "password": PASSWORD}
    data.update(changes)
    return client.post("/api/v1/auth/login", json=data, headers=WRITE)


def csrf(data):
    return {**WRITE, "X-CSRF-Token": data["csrf_token"]}


def test_register_hashes_secrets_and_returns_only_safe_account_fields(client, session):
    response = signup(client, name="  Test Player  ", email="  PLAYER@EXAMPLE.COM  ")
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test Player"
    assert data["email"] == "player@example.com"
    assert data["client_role"] == "player" and data["staff_assignments"] == []
    user = session.get(User, UUID(data["id"]))
    assert user.password_hash.startswith("$argon2id$")
    assert security.password_matches(user.password_hash, PASSWORD)
    token = client.cookies.get("omni_session")
    login = session.get(LoginSession, security.token_hash(token))
    assert login is not None and login.token_hash != token
    assert PASSWORD not in response.text and user.password_hash not in response.text
    assert token not in response.text
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
    assert "domain=" not in cookie
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/api/v1/auth/me").json()["id"] == data["id"]


def test_duplicate_email_is_canonical_and_does_not_replace_account(client, session):
    signup(client)
    response = signup(client, email="PLAYER@example.com", name="Replacement")
    assert response.status_code == 409
    assert session.scalar(select(func.count()).select_from(User)) == 1
    assert session.scalar(select(User.name)) == "Test Player"


def test_public_registration_cannot_grant_roles_or_assignments(client, session):
    for fields in [
        {"client_role": "admin"},
        {"role": "admin"},
        {"active": True},
        {"staff_assignments": []},
    ]:
        assert signup(client, **fields).status_code == 422
    assert session.scalar(select(func.count()).select_from(User)) == 0


def test_invalid_registration_never_echoes_passwords(client, session):
    for fields in [
        {"password": "secret"},
        {"password": "x" * 129},
        {"name": "   "},
        {"email": "invalid"},
    ]:
        response = signup(client, **fields)
        assert response.status_code == 422
        password = fields.get("password", PASSWORD)
        assert password not in response.text
        assert all("input" not in item and "ctx" not in item for item in response.json()["detail"])
    assert session.scalar(select(func.count()).select_from(User)) == 0


def test_login_uses_generic_errors_and_disabled_accounts_cannot_sign_in(client, session):
    signup(client)
    wrong = signin(client, password="incorrect password")
    absent = signin(client, email="unknown@example.com")
    assert wrong.status_code == absent.status_code == 401
    assert wrong.json() == absent.json()
    assert signin(client, email="PLAYER@EXAMPLE.COM").status_code == 200
    user = session.scalar(select(User))
    user.active = False
    session.flush()
    assert signin(client).json() == wrong.json()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_login_rotates_session_and_old_tokens_are_rejected(client, session):
    first = signup(client).json()
    old_token = client.cookies.get("omni_session")
    second = signin(client).json()
    assert client.cookies.get("omni_session") != old_token
    assert first["csrf_token"] != second["csrf_token"]
    assert session.get(LoginSession, security.token_hash(old_token)) is None
    assert client.post("/api/v1/auth/logout", json={}, headers=csrf(first)).status_code == 403
    assert (
        client.get("/api/v1/auth/me", headers={"Cookie": f"omni_session={old_token}"}).status_code
        == 401
    )


def test_logout_revokes_server_session_and_stolen_cookie(client, session):
    data = signup(client).json()
    token = client.cookies.get("omni_session")
    assert client.post("/api/v1/auth/logout", json={}, headers=csrf(data)).status_code == 204
    assert session.get(LoginSession, security.token_hash(token)) is None
    assert client.get("/api/v1/auth/session").json() is None
    assert (
        client.get("/api/v1/auth/me", headers={"Cookie": f"omni_session={token}"}).status_code
        == 401
    )


@pytest.mark.parametrize("client_type", ["player", "coach"])
def test_registered_name_and_client_type_are_fixed(client, session, client_type):
    assert client.get("/api/v1/auth/me").status_code == 401
    data = signup(client, client_role=client_type).json()
    path = "/api/v1/auth/me"
    for attempt in range(3):
        assert (
            client.patch(path, json={"name": f"Changed {attempt}"}, headers=csrf(data)).status_code
            == 404
        )
    assert signin(client, name="Another name").status_code == 422
    change_access(session, "grant-staff", data["email"], complex_id=demo_id("atlas"), role="admin")
    assert (
        client.patch(
            path, json={"name": "Admin rename", "client_role": "coach"}, headers=csrf(data)
        ).status_code
        == 404
    )
    profile = client.get(path).json()
    assert profile["name"] == "Test Player" and profile["client_role"] == client_type
    assert session.get(User, UUID(data["id"])).name == "Test Player"


def test_logout_requires_valid_ascii_csrf(client):
    data = signup(client).json()
    for supplied in [None, b"\xc3\xa9", "bad"]:
        headers = WRITE if supplied is None else {**WRITE, "X-CSRF-Token": supplied}
        assert client.post("/api/v1/auth/logout", json={}, headers=headers).status_code == 403
    assert client.post("/api/v1/auth/logout", json={}, headers=csrf(data)).status_code == 204


def test_cross_site_and_simple_form_requests_are_rejected(client):
    payload = {"name": "Player", "email": "player@example.com", "password": PASSWORD}
    path = "/api/v1/auth/register"
    assert client.post(path, json=payload).status_code == 403
    assert (
        client.post(
            path, json=payload, headers={**WRITE, "Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert client.post(path, json=payload, headers={**WRITE, "Origin": "null"}).status_code == 403
    assert (
        client.post(
            path, json=payload, headers={**WRITE, "Sec-Fetch-Site": "cross-site"}
        ).status_code
        == 403
    )
    assert client.post(path, data=payload, headers={"X-Omni-Request": "1"}).status_code == 403
    data = signup(client).json()
    assert (
        client.post(
            "/api/v1/auth/logout", json={}, headers={**csrf(data), "Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert client.get("/api/v1/auth/me").status_code == 200


@pytest.mark.parametrize("expiry", ["idle", "absolute"])
def test_expired_sessions_are_rejected_and_revoked(client, session, expiry):
    signup(client)
    token = client.cookies.get("omni_session")
    login = session.get(LoginSession, security.token_hash(token))
    if expiry == "idle":
        login.last_seen_at = security.utcnow() - timedelta(minutes=31)
    else:
        login.expires_at = security.utcnow() - timedelta(seconds=1)
    session.flush()
    assert client.get("/api/v1/auth/me").status_code == 401
    assert session.get(LoginSession, security.token_hash(token)) is None


def test_login_attempt_limit_persists_across_requests_and_expires(client, monkeypatch):
    client.app.state.settings.login_email_limit = 2
    assert signin(client).status_code == 401
    assert signin(client).status_code == 401
    blocked = signin(client)
    assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) > 0
    later = security.utcnow() + timedelta(seconds=601)
    monkeypatch.setattr(security, "utcnow", lambda: later)
    assert signin(client).status_code == 401


def test_ip_limit_also_blocks_attempts_using_different_emails(client):
    client.app.state.settings.login_ip_limit = 2
    assert signin(client, email="one@example.com").status_code == 401
    assert signin(client, email="two@example.com").status_code == 401
    assert signin(client, email="three@example.com").status_code == 429


def test_staff_access_resolves_real_complex_and_admin_scope(client, session):
    signup(client)
    atlas, riverside = demo_id("atlas"), demo_id("riverside")
    path = f"/api/v1/staff/complexes/{atlas}"
    assert client.get(path).status_code == 403
    change_access(session, "grant-staff", "player@example.com", complex_id=atlas, role="employee")
    assert client.get(path).status_code == 200
    assert len(client.get(path).json()["facilities"]) == 3
    assert client.get(path + "/staff").status_code == 403
    assert client.get(f"/api/v1/staff/complexes/{riverside}?complex_id={atlas}").status_code == 403
    assert client.get(f"/api/v1/staff/complexes/{uuid4()}").status_code == 403
    change_access(session, "grant-staff", "player@example.com", complex_id=atlas, role="admin")
    assert client.get(path + "/staff").status_code == 200
    assert client.get(f"/api/v1/staff/complexes/{riverside}/staff").status_code == 403
    assert session.scalar(select(func.count()).select_from(StaffAssignment)) == 1
    me = client.get("/api/v1/auth/me").json()
    assert len(me["staff_assignments"]) == 1 and me["staff_assignments"][0]["role"] == "admin"


def test_revoking_assignment_or_disabling_complex_removes_access_immediately(client, session):
    signup(client)
    atlas = demo_id("atlas")
    path = f"/api/v1/staff/complexes/{atlas}"
    change_access(session, "grant-staff", "player@example.com", complex_id=atlas, role="admin")
    assert client.get(path).status_code == 200
    change_access(session, "revoke-staff", "player@example.com", complex_id=atlas)
    assert client.get(path).status_code == 403
    assert client.get("/api/v1/auth/me").json()["staff_assignments"] == []
    change_access(session, "grant-staff", "player@example.com", complex_id=atlas, role="admin")
    session.get(Complex, atlas).active = False
    session.flush()
    assert client.get(path).status_code == 403
    assert client.get("/api/v1/auth/me").json()["staff_assignments"] == []


def test_admin_staff_directory_never_includes_another_complexs_staff(client, session):
    signup(client, email="other@example.com", name="Other complex staff")
    signup(client, email="player@example.com", name="Atlas staff")
    change_access(
        session, "grant-staff", "other@example.com", complex_id=demo_id("riverside"), role="admin"
    )
    change_access(
        session, "grant-staff", "player@example.com", complex_id=demo_id("atlas"), role="admin"
    )
    response = client.get(f"/api/v1/staff/complexes/{demo_id('atlas')}/staff")
    assert response.status_code == 200
    assert [person["email"] for person in response.json()] == ["player@example.com"]


def test_coach_capability_does_not_grant_staff_access(client, session):
    signup(client)
    change_access(session, "set-client-role", "player@example.com", role="coach")
    assert client.get("/api/v1/auth/me").json()["client_role"] == "coach"
    assert client.get(f"/api/v1/staff/complexes/{demo_id('atlas')}").status_code == 403
    with pytest.raises(ValueError):
        change_access(session, "set-client-role", "missing@example.com", role="coach")


def test_session_is_backed_by_database_in_a_new_application_instance(client, database):
    data = signup(client).json()
    settings, engine, session = database
    other_app = create_app(settings, engine=engine)

    def same_database_session():
        yield session

    other_app.dependency_overrides[get_session] = same_database_session
    with TestClient(other_app) as other:
        response = other.get(
            "/api/v1/auth/me",
            headers={"Cookie": f"omni_session={client.cookies.get('omni_session')}"},
        )
        assert response.status_code == 200 and response.json()["id"] == data["id"]


def test_secure_cookie_configuration_uses_host_prefix(client):
    client.app.state.settings.cookie_secure = True
    response = signup(client)
    assert response.status_code == 201
    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith("__host-omni_session=") and "; secure" in cookie


def test_production_requires_https_and_secure_cookies():
    with pytest.raises(ValidationError):
        Settings(environment="production", _env_file=None)
    settings = Settings(
        environment="production",
        cookie_secure=True,
        auth_origins=["https://sports.example"],
        _env_file=None,
    )
    assert settings.session_cookie.startswith("__Host-")
