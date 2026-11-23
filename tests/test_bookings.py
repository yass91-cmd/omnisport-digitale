from datetime import datetime, timedelta
from uuid import UUID, uuid4
from zlib import crc32

import pytest
from sqlalchemy import func, select

from backend.app.models import (
    ClientNotification,
    Facility,
    LoginSession,
    Reservation,
    StaffAssignment,
    StaffNotification,
    StaffNotificationRead,
)
from backend.app.security import token_hash
from backend.app.seed import demo_id

WRITE = {"X-Omni-Request": "1", "Origin": "http://testserver"}
PASSWORD = "an isolated booking test passphrase"


def register(client, email, role="player"):
    response = client.post(
        "/api/v1/auth/register",
        headers=WRITE,
        json={
            "name": "Booking test",
            "email": email,
            "password": PASSWORD,
            "client_role": role,
            "phone": "+2126" + f"{crc32(email.encode()) % 100000000:08d}",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def headers(account):
    return {**WRITE, "X-CSRF-Token": account["csrf_token"]}


@pytest.fixture
def booking_setup(client, session, monkeypatch):
    now = datetime(2026, 11, 20, 7)
    monkeypatch.setattr("backend.app.bookings.utcnow", lambda: now)
    monkeypatch.setattr("backend.app.availability.utcnow", lambda: now)
    monkeypatch.setattr("backend.app.facilities.utcnow", lambda: now)
    monkeypatch.setattr("backend.app.notifications.utcnow", lambda: now)
    account = register(client, "owner@example.com")
    assignment = StaffAssignment(
        user_id=UUID(account["id"]), complex_id=demo_id("atlas"), role="admin"
    )
    session.add(assignment)
    session.commit()
    facility_body = {
        "name": "Booking test court",
        "sport_id": str(demo_id("tennis")),
        "surface": "Hard court",
        "description": "Disposable test",
        "active": True,
        "opening_hours": [
            {"weekday": day, "opens_at": "09:00", "closes_at": "22:00"} for day in range(7)
        ],
        "tariffs": [
            {"minutes": minutes, "amount": amount}
            for minutes, amount in [(60, "120.00"), (90, "170.00"), (120, "220.00")]
        ],
    }
    admin_base = f"/api/v1/staff/complexes/{demo_id('atlas')}/facilities"
    response = client.post(admin_base, headers=headers(account), json=facility_body)
    assert response.status_code == 201, response.text
    facility = response.json()
    public = f"/api/v1/complexes/{demo_id('atlas')}/facilities/{facility['id']}"
    return account, assignment, facility, facility_body, public, admin_base + "/" + facility["id"]


def payload(version=1, start="2026-11-23T17:30", minutes=60, request_id=None):
    return {
        "facility_version": version,
        "starts_local": start,
        "minutes": minutes,
        "request_id": str(request_id or uuid4()),
    }


def reserve(client, setup, body=None):
    return client.post(
        setup[4] + "/reservations", headers=headers(setup[0]), json=body or payload()
    )


def test_employee_arrival_is_audited_idempotent_and_keeps_price(client, session, booking_setup):
    setup = booking_setup
    booking = reserve(client, setup).json()
    setup[1].role = "employee"
    session.commit()
    path = f"/api/v1/staff/complexes/{demo_id('atlas')}/reservations/{booking['id']}/arrive"
    accepted = client.post(
        path.removesuffix("/arrive") + "/accept", headers=headers(setup[0]), json={"version": 1}
    )
    assert accepted.status_code == 200 and accepted.json()["status"] == "pending"
    approved = client.post(path, headers=headers(setup[0]), json={"version": 2})
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "confirmed" and approved.json()["version"] == 3
    assert approved.json()["total_amount"] == booking["total_amount"]
    assert approved.json()["can_mark_arrived"] is False
    assert (
        client.post(path, headers=headers(setup[0]), json={"version": 2}).json() == approved.json()
    )
    stored = session.get(Reservation, UUID(booking["id"]))
    assert stored.arrived_by == UUID(setup[0]["id"]) and stored.arrived_at is not None
    assert stored.approved_by == UUID(setup[0]["id"]) and stored.approved_at is not None
    assert reserve(client, setup, payload(4)).status_code == 409
    assert session.scalar(select(func.count()).select_from(StaffNotification)) == 0


def test_cancellation_releases_reserved_time_and_prevents_arrival(
    client, booking_setup, monkeypatch
):
    setup = booking_setup
    booking = reserve(client, setup).json()
    monkeypatch.setattr("backend.app.bookings.utcnow", lambda: datetime(2026, 11, 23, 13))
    base = f"/api/v1/staff/complexes/{demo_id('atlas')}/reservations/{booking['id']}"
    rejected = client.post(base + "/cancel", headers=headers(setup[0]), json={"version": 1})
    assert rejected.status_code == 200 and rejected.json()["status"] == "cancelled"
    assert (
        client.post(base + "/cancel", headers=headers(setup[0]), json={"version": 1}).status_code
        == 200
    )
    assert (
        client.post(base + "/arrive", headers=headers(setup[0]), json={"version": 1}).status_code
        == 409
    )
    availability = client.get(
        setup[4] + "/availability", params={"day": "2026-11-23", "minutes": 60}
    ).json()
    assert any(slot["starts_at"][11:16] == "17:30" for slot in availability["slots"])


def test_arrival_and_cancellation_require_assignment_csrf_and_current_version(
    client, booking_setup
):
    setup = booking_setup
    booking = reserve(client, setup).json()
    base = f"/api/v1/staff/complexes/{demo_id('atlas')}/reservations/{booking['id']}"
    assert client.post(base + "/arrive", headers=WRITE, json={"version": 1}).status_code == 403
    assert (
        client.post(base + "/arrive", headers=headers(setup[0]), json={"version": 2}).status_code
        == 409
    )
    wrong = base.replace(str(demo_id("atlas")), str(demo_id("riverside")))
    for action in ["arrive", "cancel"]:
        assert (
            client.post(
                wrong + "/" + action, headers=headers(setup[0]), json={"version": 1}
            ).status_code
            == 403
        )
    outsider = register(client, "unassigned@example.com")
    for action in ["arrive", "cancel"]:
        assert (
            client.post(
                base + "/" + action, headers=headers(outsider), json={"version": 1}
            ).status_code
            == 403
        )


def test_passage_of_time_never_records_attendance_without_staff(client, booking_setup, monkeypatch):
    setup = booking_setup
    booking = reserve(client, setup).json()
    base = f"/api/v1/staff/complexes/{demo_id('atlas')}/reservations/{booking['id']}"
    assert (
        client.post(base + "/accept", headers=headers(setup[0]), json={"version": 1}).status_code
        == 200
    )
    monkeypatch.setattr("backend.app.bookings.utcnow", lambda: datetime(2026, 11, 24, 9))
    base = f"/api/v1/staff/complexes/{demo_id('atlas')}/reservations/{booking['id']}"
    assert client.get("/api/v1/reservations").json()["items"][0]["status"] == "pending"
    arrived = client.post(base + "/arrive", headers=headers(setup[0]), json={"version": 2})
    assert arrived.status_code == 200 and arrived.json()["status"] == "confirmed"
    assert (
        client.post(base + "/cancel", headers=headers(setup[0]), json={"version": 3}).status_code
        == 409
    )


def test_status_filters_are_applied_before_pagination_and_day_filter(client, booking_setup):
    setup = booking_setup
    pending = reserve(client, setup).json()
    confirmed = client.post(
        setup[5] + "/reservations",
        headers=headers(setup[0]),
        json={
            **payload(2, "2026-11-23T19:00"),
            "client_name": "Guest",
            "client_phone": "0612345678",
        },
    ).json()
    confirmed = client.post(
        f"/api/v1/staff/complexes/{demo_id('atlas')}/reservations/{confirmed['id']}/arrive",
        headers=headers(setup[0]),
        json={"version": 1},
    ).json()
    cancelled = reserve(client, setup, payload(4, "2026-11-24T09:00")).json()
    client.post(
        f"/api/v1/reservations/{cancelled['id']}/cancel",
        headers=headers(setup[0]),
        json={"version": 1},
    )
    base = f"/api/v1/staff/complexes/{demo_id('atlas')}/reservations"
    for state, row in [("pending", pending), ("confirmed", confirmed), ("cancelled", cancelled)]:
        page = client.get(base, params={"status": state, "limit": 1}).json()
        assert page["total"] == 1 and page["items"][0]["id"] == row["id"]
    assert (
        client.get(base, params={"status": "cancelled", "day": "2026-11-23"}).json()["total"] == 0
    )
    assert client.get("/api/v1/reservations", params={"status": "pending"}).json()["total"] == 1
    assert client.get(base, params={"status": "unknown"}).status_code == 422


@pytest.mark.parametrize("role", ["player", "coach"])
def test_registration_selects_client_type_once_without_staff_privileges(client, session, role):
    account = register(client, "role@example.com", role)
    assert account["client_role"] == role and account["staff_assignments"] == []
    assert client.get("/api/v1/staff/me").status_code == 403
    assert client.get(f"/api/v1/staff/complexes/{demo_id('atlas')}").status_code == 403
    assert (
        client.post(
            "/api/v1/staff/auth/login",
            headers=WRITE,
            json={"email": "role@example.com", "password": PASSWORD},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/staff/auth/login",
            headers=WRITE,
            json={"email": "role@example.com", "password": "wrong"},
        ).status_code
        == 401
    )


def test_selected_available_time_is_pending_and_removed_from_shared_schedule(
    client, session, booking_setup
):
    setup = booking_setup
    response = reserve(client, setup)
    assert response.status_code == 201, response.text
    booking = response.json()
    assert booking["status"] == "pending" and booking["source"] == "online"
    assert booking["total_amount"] == "132.00" and booking["currency"] == "MAD"
    assert booking["client_id"] == setup[0]["id"] and booking["reference"].startswith("OM-")
    assert booking["starts_at"].startswith("2026-11-23T17:30") and booking["ends_at"].startswith(
        "2026-11-23T18:30"
    )
    assert booking["can_cancel"] is True
    available = client.get(
        setup[4] + "/availability", params={"day": "2026-11-23", "minutes": 60}
    ).json()
    starts = {row["starts_at"][11:16] for row in available["slots"]}
    assert not {"17:00", "17:30", "18:00"} & starts and {"16:30", "18:30"} <= starts
    assert client.get("/api/v1/reservations").json()["items"][0]["id"] == booking["id"]
    assert session.get(Facility, UUID(setup[2]["id"])).version == 2


def test_retries_replay_one_booking_and_reused_key_cannot_change_details(
    client, session, booking_setup
):
    body = payload()
    first = reserve(client, booking_setup, body)
    assert first.status_code == 201
    again = reserve(client, booking_setup, body)
    assert again.status_code == 200 and again.json()["id"] == first.json()["id"]
    assert (
        reserve(client, booking_setup, {**body, "starts_local": "2026-11-23T19:00"}).status_code
        == 409
    )
    assert session.scalar(select(func.count()).select_from(Reservation)) == 1
    assert session.get(Facility, UUID(booking_setup[2]["id"])).version == 2


def test_overlap_rejected_adjacent_start_allowed_and_history_prices_stay_saved(
    client, session, booking_setup
):
    setup = booking_setup
    booked = reserve(client, setup).json()
    assert reserve(client, setup, payload(2, "2026-11-23T18:00", 90)).status_code == 409
    assert reserve(client, setup, payload(2, "2026-11-23T18:30", 60)).status_code == 201
    changed = {**setup[3], "version": 3, "tariffs": [{"minutes": 60, "amount": "999.00"}]}
    assert client.put(setup[5], headers=headers(setup[0]), json=changed).status_code == 200
    history = client.get("/api/v1/reservations").json()["items"]
    assert next(row for row in history if row["id"] == booked["id"])["total_amount"] == "132.00"


def test_stale_unpriced_past_off_grid_and_closed_requests_leave_no_booking(
    client, session, booking_setup
):
    setup = booking_setup
    for body, status in [
        (payload(2), 409),
        (payload(start="2026-11-19T10:00"), 422),
        (payload(start="0001-01-02T10:00"), 422),
        (payload(start="2026-11-23T10:15"), 422),
        (payload(start="2026-11-23T21:30", minutes=90), 409),
    ]:
        assert reserve(client, setup, body).status_code == status
        assert session.scalar(select(func.count()).select_from(Reservation)) == 0
    closure = {
        "facility_version": 1,
        "starts_local": "2026-11-23T17:00",
        "ends_local": "2026-11-23T19:00",
        "reason": "Test closure",
    }
    assert (
        client.post(setup[5] + "/closures", headers=headers(setup[0]), json=closure).status_code
        == 201
    )
    assert reserve(client, setup, payload(2)).status_code == 409
    assert session.scalar(select(func.count()).select_from(Reservation)) == 0


def test_existing_bookings_protect_against_conflicting_closures_and_settings(
    client, session, booking_setup
):
    setup = booking_setup
    assert reserve(client, setup).status_code == 201
    closure = {
        "facility_version": 2,
        "starts_local": "2026-11-23T18:00",
        "ends_local": "2026-11-23T20:00",
        "reason": "Cannot erase a booking",
    }
    assert (
        client.post(setup[5] + "/closures", headers=headers(setup[0]), json=closure).status_code
        == 409
    )
    for changes in [
        {"active": False},
        {"sport_id": str(demo_id("football"))},
        {"opening_hours": []},
    ]:
        assert (
            client.put(
                setup[5], headers=headers(setup[0]), json={**setup[3], "version": 2, **changes}
            ).status_code
            == 409
        )
    assert session.get(Facility, UUID(setup[2]["id"])).version == 2


def test_cancellation_obeys_h2_owner_scope_and_retains_audit(
    client, session, booking_setup, monkeypatch
):
    setup = booking_setup
    booking = reserve(client, setup).json()
    accept = f"/api/v1/staff/complexes/{demo_id('atlas')}/reservations/{booking['id']}/accept"
    assert client.post(accept, headers=headers(setup[0]), json={"version": 1}).status_code == 200
    row = session.get(Reservation, UUID(booking["id"]))
    monkeypatch.setattr(
        "backend.app.bookings.utcnow",
        lambda: row.starts_at - timedelta(hours=2) + timedelta(microseconds=1),
    )
    path = f"/api/v1/reservations/{booking['id']}/cancel"
    assert client.post(path, headers=headers(setup[0]), json={"version": 2}).status_code == 409
    assert client.get("/api/v1/reservations").json()["items"][0]["can_cancel"] is False
    start = row.starts_at
    monkeypatch.setattr("backend.app.bookings.utcnow", lambda: start - timedelta(hours=2))
    assert client.post(path, headers=headers(setup[0]), json={"version": 2}).status_code == 200
    assert client.post(path, headers=headers(setup[0]), json={"version": 2}).status_code == 200
    row = session.get(Reservation, UUID(booking["id"]))
    assert (
        row.status == "cancelled" and row.version == 3 and row.cancelled_by == UUID(setup[0]["id"])
    )
    assert session.get(Facility, UUID(setup[2]["id"])).version == 4
    assert any(
        slot["starts_at"][11:16] == "17:30"
        for slot in client.get(setup[4] + "/availability", params={"day": "2026-11-23"}).json()[
            "slots"
        ]
    )


def test_staff_has_separate_entry_and_books_only_inside_assigned_complex(
    client, session, booking_setup
):
    setup = booking_setup
    setup[1].role = "employee"
    session.commit()
    assert client.get("/api/v1/staff/me").status_code == 200
    login = client.post(
        "/api/v1/staff/auth/login",
        headers=WRITE,
        json={"email": "owner@example.com", "password": PASSWORD},
    )
    assert login.status_code == 200
    staff = login.json()
    target = register(client, "client@example.com", "coach")
    login = client.post(
        "/api/v1/staff/auth/login",
        headers=WRITE,
        json={"email": "owner@example.com", "password": PASSWORD},
    )
    staff = login.json()
    body = {**payload(), "client_name": target["name"].upper(), "client_phone": target["phone"]}
    response = client.post(setup[5] + "/reservations", headers=headers(staff), json=body)
    assert response.status_code == 201, response.text
    booking = response.json()
    assert booking["source"] == "staff" and booking["client_id"] == target["id"]
    assert (
        client.get(f"/api/v1/staff/complexes/{demo_id('atlas')}/reservations").json()["total"] == 1
    )
    assert (
        client.get(f"/api/v1/staff/complexes/{demo_id('riverside')}/reservations").status_code
        == 403
    )
    wrong = setup[5].replace(str(demo_id("atlas")), str(demo_id("riverside")))
    assert (
        client.post(wrong + "/reservations", headers=headers(staff), json=body).status_code == 403
    )
    assert (
        client.post(
            f"/api/v1/reservations/{booking['id']}/cancel",
            headers=headers(staff),
            json={"version": 1},
        ).status_code
        == 404
    )
    assert client.get("/api/v1/reservations").json()["total"] == 0
    setup[1].active = False
    session.commit()
    assert client.get("/api/v1/staff/me").status_code == 403


def test_request_validation_and_csrf_cannot_inject_price_or_owner(client, session, booking_setup):
    setup = booking_setup
    for bad in [
        {"total_amount": "0.01"},
        {"client_id": str(uuid4())},
        {"minutes": 30},
        {"request_id": "bad"},
        {"facility_version": True},
    ]:
        assert reserve(client, setup, {**payload(), **bad}).status_code == 422
    assert (
        client.post(
            setup[4] + "/reservations",
            headers={**headers(setup[0]), "X-CSRF-Token": "bad"},
            json=payload(),
        ).status_code
        == 403
    )
    assert (
        client.post(
            setup[4] + "/reservations",
            headers={**headers(setup[0]), "Origin": "https://other.example"},
            json=payload(),
        ).status_code
        == 403
    )
    assert session.scalar(select(func.count()).select_from(Reservation)) == 0


def test_booking_requests_stay_in_history_without_creating_inbox_alerts(
    client, session, booking_setup
):
    body = payload()
    booking = reserve(client, booking_setup, body).json()
    assert reserve(client, booking_setup, body).status_code == 200
    assert reserve(client, booking_setup, payload(2, "2026-11-23T18:00")).status_code == 409
    assert session.scalar(select(func.count()).select_from(StaffNotification)) == 0
    summary = client.get("/api/v1/staff/notifications/summary").json()
    assert summary["total"] == 0
    page = client.get(f"/api/v1/staff/complexes/{demo_id('atlas')}/notifications").json()
    assert page["unread"] == 0 and page["items"] == []
    history = client.get(f"/api/v1/staff/complexes/{demo_id('atlas')}/reservations").json()
    assert history["items"][0]["id"] == booking["id"]
    assert history["items"][0]["can_accept"] is True


@pytest.mark.parametrize("kind", ["booking_requested", "booking_confirmed", "time_requested"])
def test_existing_request_records_are_preserved_but_excluded_from_inbox(
    client, session, booking_setup, kind
):
    setup = booking_setup
    booking = reserve(client, setup).json()
    notice = StaffNotification(
        complex_id=demo_id("atlas"),
        facility_id=UUID(setup[2]["id"]),
        client_id=UUID(setup[0]["id"]),
        kind=kind,
        reservation_id=None if kind == "time_requested" else UUID(booking["id"]),
        intent_key=uuid4().hex if kind == "time_requested" else None,
        requested_day=datetime(2026, 11, 21).date(),
        minutes=60,
        created_at=datetime(2026, 11, 20, 7),
    )
    session.add(notice)
    session.commit()
    inbox = f"/api/v1/staff/complexes/{demo_id('atlas')}/notifications"
    requests = f"/api/v1/staff/complexes/{demo_id('atlas')}/time-requests"
    assert client.get(inbox).json()["items"] == []
    summary = client.get("/api/v1/staff/notifications/summary").json()
    assert summary["total"] == 0
    assert (
        client.post(f"{inbox}/{notice.id}/read", headers=headers(setup[0]), json={}).status_code
        == 404
    )
    assert client.get(requests).status_code == 404
    assert "time_requests" not in summary["complexes"][0]
    assert (
        client.post(f"{requests}/{notice.id}/read", headers=headers(setup[0]), json={}).status_code
        == 404
    )
    assert session.scalar(select(func.count()).select_from(StaffNotification)) == 1
    assert session.scalar(select(func.count()).select_from(StaffNotificationRead)) == 0
    assert session.get(Reservation, UUID(booking["id"])) is not None


def test_notification_polling_does_not_extend_idle_session(
    client, session, booking_setup, monkeypatch
):
    login = session.get(LoginSession, token_hash(client.cookies.get("omni_session")))
    last_seen = login.last_seen_at
    monkeypatch.setattr("backend.app.security.utcnow", lambda: last_seen + timedelta(minutes=15))
    assert client.get("/api/v1/staff/notifications/summary").status_code == 200
    assert (
        client.get(f"/api/v1/staff/complexes/{demo_id('atlas')}/notifications").status_code == 200
    )
    session.refresh(login)
    assert login.last_seen_at == last_seen
    monkeypatch.setattr("backend.app.security.utcnow", lambda: last_seen + timedelta(minutes=31))
    assert client.get("/api/v1/staff/notifications/summary").status_code == 401


def test_failed_customer_update_rolls_back_acceptance_without_releasing_the_booking(
    client, session, booking_setup, monkeypatch
):
    from fastapi import HTTPException
    from sqlalchemy.orm import Session

    from backend.app.database import get_session
    from backend.app.notifications import notify_client

    booking = reserve(client, booking_setup).json()

    def failed_alert(*args):
        notify_client(*args)
        raise HTTPException(503, "Simulated alert failure")

    monkeypatch.setattr("backend.app.bookings.notify_client", failed_alert)
    path = f"/api/v1/staff/complexes/{demo_id('atlas')}/reservations/{booking['id']}/accept"
    # Share the fixture's connection: its seeded MySQL data is inside an outer transaction.
    # A separate request session owns a savepoint and rolls it back on close after failure.
    override = client.app.dependency_overrides[get_session]

    def request_session():
        with Session(bind=session.get_bind(), join_transaction_mode="create_savepoint") as scoped:
            yield scoped

    client.app.dependency_overrides[get_session] = request_session
    try:
        assert (
            client.post(path, headers=headers(booking_setup[0]), json={"version": 1}).status_code
            == 503
        )
    finally:
        client.app.dependency_overrides[get_session] = override
    assert session.scalar(select(func.count()).select_from(Reservation)) == 1
    assert session.scalar(select(func.count()).select_from(StaffNotification)) == 0
    assert session.scalar(select(func.count()).select_from(ClientNotification)) == 0
    session.expire_all()
    assert session.get(Facility, UUID(booking_setup[2]["id"])).version == 2
    saved = session.get(Reservation, UUID(booking["id"]))
    assert saved.approval_status == "awaiting" and saved.version == 1 and saved.arrived_at is None


def test_staff_can_reserve_for_walk_in_without_creating_account(client, session, booking_setup):
    from backend.app.models import User

    setup = booking_setup
    users = session.scalar(select(func.count()).select_from(User))
    body = {
        **payload(start="2026-11-23T11:00", minutes=120),
        "client_name": "  Walk-in   Customer  ",
        "client_phone": "06 99 00 11 22",
    }
    response = client.post(setup[5] + "/reservations", headers=headers(setup[0]), json=body)
    assert response.status_code == 201, response.text
    row = response.json()
    assert row["walk_in"] is True and row["client_id"] is None
    assert row["client_name"] == "Walk-in Customer" and row["client_phone"] == "+212699001122"
    assert row["total_amount"] == "220.00"
    assert session.scalar(select(func.count()).select_from(User)) == users
    assert client.get("/api/v1/reservations").json()["total"] == 0
    replay = client.post(setup[5] + "/reservations", headers=headers(setup[0]), json=body)
    assert replay.status_code == 200 and replay.json()["id"] == row["id"]
    assert session.scalar(select(func.count()).select_from(StaffNotification)) == 0
    history = client.get(f"/api/v1/staff/complexes/{demo_id('atlas')}/reservations").json()[
        "items"
    ][0]
    assert (
        history["client_name"] == row["client_name"]
        and history["client_phone"] == row["client_phone"]
    )
    path = f"/api/v1/staff/complexes/{demo_id('atlas')}/reservations/{row['id']}/cancel"
    assert client.post(path, headers=headers(setup[0]), json={"version": 1}).status_code == 200
    assert client.post(path, headers=headers(setup[0]), json={"version": 1}).status_code == 200


def test_timetable_merges_long_bookings_and_hides_customer_details_publicly(
    client, session, booking_setup
):
    setup = booking_setup
    first = reserve(client, setup, payload(start="2026-11-23T09:00", minutes=120)).json()
    second = reserve(client, setup, payload(2, "2026-11-23T12:00", 90)).json()
    public = client.get(
        setup[4] + "/availability", params={"day": "2026-11-23", "minutes": 120}
    ).json()
    timeline = public["timeline"]
    assert [(r["state"], r["starts_at"][11:16], r["ends_at"][11:16]) for r in timeline] == [
        ("reserved", "09:00", "11:00"),
        ("available", "11:00", "12:00"),
        ("reserved", "12:00", "13:30"),
        ("available", "13:30", "22:00"),
    ]
    assert all(
        not {"client_name", "client_phone", "reservation_id", "reference"} & row.keys()
        for row in timeline
    )
    assert not any(
        slot["starts_at"][11:16]
        in {"09:00", "09:30", "10:00", "10:30", "11:00", "11:30", "12:00", "12:30", "13:00"}
        for slot in public["slots"]
    )
    private = client.get(
        setup[5] + "/availability", params={"day": "2026-11-23", "minutes": 120}
    ).json()
    booked = [r for r in private["timeline"] if r["state"] == "reserved"]
    assert [r["minutes"] for r in booked] == [120, 90]
    assert [r["reservation_id"] for r in booked] == [first["id"], second["id"]]
    assert all(r["client_phone"] == setup[0]["phone"] for r in booked)


def test_registered_phone_linking_and_guest_cancellation_scope(client, session, booking_setup):
    setup = booking_setup
    guest = client.post(
        setup[5] + "/reservations",
        headers=headers(setup[0]),
        json={**payload(), "client_name": "Walk-in", "client_phone": "0611111122"},
    ).json()
    wrong = f"/api/v1/staff/complexes/{demo_id('riverside')}/reservations/{guest['id']}/cancel"
    assert client.post(wrong, headers=headers(setup[0]), json={"version": 1}).status_code == 403
    account_booking = reserve(client, setup, payload(2, "2026-11-23T19:00")).json()
    path = f"/api/v1/staff/complexes/{demo_id('atlas')}/reservations/{account_booking['id']}/cancel"
    assert (
        client.post(
            path.removesuffix("/cancel") + "/accept", headers=headers(setup[0]), json={"version": 1}
        ).status_code
        == 200
    )
    approved = client.post(
        path.removesuffix("/cancel") + "/arrive", headers=headers(setup[0]), json={"version": 2}
    )
    assert approved.status_code == 200
    assert client.post(path, headers=headers(setup[0]), json={"version": 3}).status_code == 409
    assert (
        client.post(
            setup[5] + "/reservations",
            headers=headers(setup[0]),
            json={
                **payload(5, "2026-11-23T20:00"),
                "client_name": "Missing phone",
                "client_phone": "wrong",
            },
        ).status_code
        == 422
    )


def test_guest_cancel_obeys_h2_and_revocation(client, session, booking_setup, monkeypatch):
    setup = booking_setup
    row = client.post(
        setup[5] + "/reservations",
        headers=headers(setup[0]),
        json={**payload(), "client_name": "Walk-in", "client_phone": "0612345678"},
    ).json()
    booking = session.get(Reservation, UUID(row["id"]))
    start = booking.starts_at
    path = f"/api/v1/staff/complexes/{demo_id('atlas')}/reservations/{row['id']}/cancel"
    monkeypatch.setattr(
        "backend.app.bookings.utcnow",
        lambda: start - timedelta(hours=2) + timedelta(microseconds=1),
    )
    assert client.post(path, headers=headers(setup[0]), json={"version": 1}).status_code == 409
    setup[1].active = False
    session.commit()
    assert client.post(path, headers=headers(setup[0]), json={"version": 1}).status_code == 403


def test_phone_is_normalized_on_registration_and_required_for_new_reservation(
    client, session, booking_setup
):
    setup = booking_setup
    from backend.app.models import User

    user = session.get(User, UUID(setup[0]["id"]))
    user.phone = None
    session.commit()
    assert reserve(client, setup).status_code == 422
    booked = reserve(client, setup, {**payload(), "phone": "06 12 34 56 78"})
    assert booked.status_code == 201 and booked.json()["client_phone"] == "+212612345678"
    assert client.get("/api/v1/auth/session").json()["phone"] == "+212612345678"


def test_timetable_keeps_overnight_booking_one_block_per_day_with_actual_bounds(
    client, session, booking_setup
):
    from backend.app.models import Complex

    setup = booking_setup
    complex_ = session.get(Complex, demo_id("atlas"))
    complex_.timezone = "Asia/Kolkata"
    session.commit()
    body = {
        **setup[3],
        "version": 1,
        "opening_hours": [
            {"weekday": 0, "opens_at": "22:00", "closes_at": "00:00"},
            {"weekday": 1, "opens_at": "00:00", "closes_at": "03:00"},
        ],
    }
    assert client.put(setup[5], headers=headers(setup[0]), json=body).status_code == 200
    booking = reserve(client, setup, payload(2, "2026-11-23T23:30", 120)).json()
    for day, begin, end in [("2026-11-23", "23:30", "00:00"), ("2026-11-24", "00:00", "01:30")]:
        data = client.get(setup[5] + "/availability", params={"day": day}).json()
        occupied = [row for row in data["timeline"] if row["state"] == "reserved"]
        assert len(occupied) == 1 and occupied[0]["reservation_id"] == booking["id"]
        assert occupied[0]["starts_at"][11:16] == begin and occupied[0]["ends_at"][11:16] == end
        assert occupied[0]["reservation_starts_at"].startswith("2026-11-23T23:30")
        assert occupied[0]["reservation_ends_at"].startswith("2026-11-24T01:30")
        assert occupied[0]["minutes"] == 120


def test_timetable_keeps_closed_breaks_and_blocks_without_exposing_private_reason(
    client, session, booking_setup
):
    setup = booking_setup
    body = {
        **setup[3],
        "version": 1,
        "opening_hours": [
            {"weekday": 0, "opens_at": "09:00", "closes_at": "12:00"},
            {"weekday": 0, "opens_at": "14:00", "closes_at": "22:00"},
        ],
    }
    assert client.put(setup[5], headers=headers(setup[0]), json=body).status_code == 200
    assert (
        client.post(
            setup[5] + "/closures",
            headers=headers(setup[0]),
            json={
                "facility_version": 2,
                "starts_local": "2026-11-23T15:00",
                "ends_local": "2026-11-23T16:00",
                "reason": "PRIVATE maintenance detail",
            },
        ).status_code
        == 201
    )
    result = client.get(setup[4] + "/availability", params={"day": "2026-11-23"})
    assert "PRIVATE" not in result.text
    assert [
        (row["state"], row["starts_at"][11:16], row["ends_at"][11:16])
        for row in result.json()["timeline"]
    ] == [
        ("available", "09:00", "12:00"),
        ("closed", "12:00", "14:00"),
        ("available", "14:00", "15:00"),
        ("blocked", "15:00", "16:00"),
        ("available", "16:00", "22:00"),
    ]


@pytest.mark.parametrize("role", ["player", "coach"])
def test_online_acceptance_notifies_only_the_customer_and_keeps_attendance_pending(
    client, session, booking_setup, role
):
    setup = booking_setup
    customer = register(client, f"{role}.acceptance@example.com", role)
    created = client.post(setup[4] + "/reservations", headers=headers(customer), json=payload())
    assert created.status_code == 201, created.text
    booking = created.json()
    assert booking["approval_status"] == "awaiting" and booking["status"] == "pending"
    assert booking["can_mark_arrived"] is False
    path = f"/api/v1/staff/complexes/{demo_id('atlas')}/reservations/{booking['id']}"
    assert (
        client.post(path + "/accept", headers=headers(customer), json={"version": 1}).status_code
        == 403
    )
    admin = client.post(
        "/api/v1/auth/login", headers=WRITE, json={"email": setup[0]["email"], "password": PASSWORD}
    ).json()
    assert (
        client.post(path + "/arrive", headers=headers(admin), json={"version": 1}).status_code
        == 409
    )
    accepted = client.post(path + "/accept", headers=headers(admin), json={"version": 1})
    assert accepted.status_code == 200, accepted.text
    assert (
        accepted.json()["approval_status"] == "accepted" and accepted.json()["status"] == "pending"
    )
    assert (
        accepted.json()["total_amount"] == booking["total_amount"]
        and accepted.json()["arrived_at"] is None
    )
    assert (
        client.post(path + "/accept", headers=headers(admin), json={"version": 1}).status_code
        == 200
    )
    assert session.scalar(select(func.count()).select_from(ClientNotification)) == 1
    assert client.get("/api/v1/notifications").json()["total"] == 0
    owner = client.post(
        "/api/v1/auth/login", headers=WRITE, json={"email": customer["email"], "password": PASSWORD}
    ).json()
    login = session.scalar(select(LoginSession).where(LoginSession.user_id == UUID(owner["id"])))
    seen = login.last_seen_at
    page = client.get("/api/v1/notifications?unread_only=true").json()
    assert page["unread"] == 1 and page["items"][0]["kind"] == "accepted"
    assert page["items"][0]["reference"] == booking["reference"]
    history = client.get("/api/v1/reservations").json()["items"][0]
    assert history["approval_status"] == "accepted" and history["status"] == "pending"
    session.refresh(login)
    assert login.last_seen_at == seen
    notice = page["items"][0]
    for _ in range(2):
        assert (
            client.post(
                f"/api/v1/notifications/{notice['id']}/read", headers=headers(owner), json={}
            ).status_code
            == 204
        )
    assert client.get("/api/v1/notifications?unread_only=true").json()["unread"] == 0


def test_customer_updates_are_private_and_cancelled_requests_cannot_be_accepted(
    client, session, booking_setup
):
    setup = booking_setup
    booking = reserve(client, setup).json()
    path = f"/api/v1/staff/complexes/{demo_id('atlas')}/reservations/{booking['id']}"
    cancelled = client.post(path + "/cancel", headers=headers(setup[0]), json={"version": 1})
    assert cancelled.status_code == 200
    assert (
        client.post(path + "/accept", headers=headers(setup[0]), json={"version": 1}).status_code
        == 409
    )
    notice = client.get("/api/v1/notifications").json()["items"][0]
    assert notice["kind"] == "cancelled"
    outsider = register(client, "private.updates@example.com")
    page = client.get("/api/v1/notifications")
    assert page.json()["total"] == 0 and booking["reference"] not in page.text
    assert (
        client.post(
            f"/api/v1/notifications/{notice['id']}/read", headers=headers(outsider), json={}
        ).status_code
        == 404
    )


def test_acceptance_requires_current_version_and_assignment(client, booking_setup):
    setup = booking_setup
    booking = reserve(client, setup).json()
    path = f"/api/v1/staff/complexes/{demo_id('atlas')}/reservations/{booking['id']}/accept"
    assert client.post(path, headers=WRITE, json={"version": 1}).status_code == 403
    assert client.post(path, headers=headers(setup[0]), json={"version": 2}).status_code == 409
    wrong = path.replace(str(demo_id("atlas")), str(demo_id("riverside")))
    assert client.post(wrong, headers=headers(setup[0]), json={"version": 1}).status_code == 403


def test_acceptance_migration_refuses_to_discard_waiting_requests(client, session, booking_setup):
    from alembic import command
    from alembic.config import Config

    from backend.app.config import ROOT

    booking = reserve(client, booking_setup).json()
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection"] = session.connection()
    with pytest.raises(RuntimeError, match="Acceptance history exists"):
        command.downgrade(config, "0010_booking_arrival")
    assert session.get(Reservation, UUID(booking["id"])).approval_status == "awaiting"


@pytest.mark.parametrize("endpoint,method", [("create", "POST"), ("list", "GET"), ("read", "POST")])
def test_removed_time_request_endpoints_cannot_write(
    client, session, booking_setup, endpoint, method
):
    from backend.app.models import User

    setup = booking_setup
    staff = f"/api/v1/staff/complexes/{demo_id('atlas')}/time-requests"
    path = (
        setup[4] + "/time-requests"
        if endpoint == "create"
        else staff
        if endpoint == "list"
        else staff + f"/{uuid4()}/read"
    )
    phone = session.get(User, UUID(setup[0]["id"])).phone
    result = client.request(
        method,
        path,
        headers=headers(setup[0]),
        json={"day": "2026-11-21", "minutes": 60, "phone": "+212699887766"},
    )
    assert result.status_code == 404
    assert session.scalar(select(func.count()).select_from(StaffNotification)) == 0
    assert session.scalar(select(func.count()).select_from(Reservation)) == 0
    assert session.get(Facility, UUID(setup[2]["id"])).version == 1
    assert session.get(User, UUID(setup[0]["id"])).phone == phone
    assert client.get("/time-requests.html").status_code == 404


def test_inbox_scope_and_revocation_are_immediate(client, session, booking_setup):
    path = f"/api/v1/staff/complexes/{demo_id('atlas')}/notifications"
    employee = register(client, "employee@example.com")
    assert client.get(path).status_code == 403
    assignment = StaffAssignment(
        user_id=UUID(employee["id"]), complex_id=demo_id("atlas"), role="employee"
    )
    session.add(assignment)
    session.commit()
    assert client.get(path).json()["unread"] == 0
    assert (
        client.get(f"/api/v1/staff/complexes/{demo_id('riverside')}/notifications").status_code
        == 403
    )
    assert (
        client.post(path + f"/{uuid4()}/read", headers=headers(employee), json={}).status_code
        == 404
    )
    assignment.active = False
    session.commit()
    assert client.get(path).status_code == 403
    assert client.get("/api/v1/staff/notifications/summary").status_code == 403
