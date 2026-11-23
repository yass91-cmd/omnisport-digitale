from datetime import date, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError

from backend.app.availability import interval_is_open
from backend.app.models import Facility, FacilityClosure, StaffAssignment
from backend.app.pricing import local_start
from backend.app.seed import demo_id

BASE = f"/api/v1/staff/complexes/{demo_id('atlas')}/facilities"


@pytest.fixture
def schedule(client, session, monkeypatch):
    monkeypatch.setattr("backend.app.availability.utcnow", lambda: datetime(2026, 11, 20, 7))
    write = {"X-Omni-Request": "1", "Origin": "http://testserver"}
    response = client.post(
        "/api/v1/auth/register",
        headers=write,
        json={
            "name": "Schedule Admin",
            "email": "schedule@example.com",
            "password": "a long isolated schedule test password",
        },
    )
    assert response.status_code == 201
    account = response.json()
    assignment = StaffAssignment(
        user_id=UUID(account["id"]), complex_id=demo_id("atlas"), role="admin"
    )
    session.add(assignment)
    session.commit()
    headers = {**write, "X-CSRF-Token": account["csrf_token"]}
    body = {
        "name": "Schedule test court",
        "sport_id": str(demo_id("tennis")),
        "surface": "Hard court",
        "description": "Isolated test",
        "active": True,
        "opening_hours": [
            {"weekday": day, "opens_at": "09:00", "closes_at": "22:00"} for day in range(7)
        ],
        "tariffs": [
            {"minutes": minutes, "amount": amount}
            for minutes, amount in [(60, "120.00"), (90, "170.00"), (120, "220.00")]
        ],
    }
    response = client.post(BASE, json=body, headers=headers)
    assert response.status_code == 201, response.text
    data = response.json()
    admin_path = BASE + "/" + data["id"]
    public_path = f"/api/v1/complexes/{demo_id('atlas')}/facilities/{data['id']}"
    return SimpleNamespace(
        client=client,
        session=session,
        headers=headers,
        body=body,
        data=data,
        admin=admin_path,
        public=public_path,
        assignment=assignment,
    )


def slots(schedule, day="2026-11-20", minutes=60):
    response = schedule.client.get(
        schedule.public + "/availability", params={"day": day, "minutes": minutes}
    )
    assert response.status_code == 200, response.text
    return response.json()


def times(response):
    return {row["starts_at"][11:16]: row for row in response["slots"]}


def close(schedule, version=1, start="2026-11-20T10:00", end="2026-11-20T11:00", **changes):
    return schedule.client.post(
        schedule.admin + "/closures",
        headers=schedule.headers,
        json={
            "facility_version": version,
            "starts_local": start,
            "ends_local": end,
            "reason": "PRIVATE administrator-only reason",
            **changes,
        },
    )


def test_available_times_use_whole_duration_saved_prices_and_peak_rules(schedule):
    result = slots(schedule)
    assert result["status"] == "available" and result["booking_enabled"] is True
    assert result["slot_step_minutes"] == 30 and result["priced_durations"] == [60, 90, 120]
    assert result["timezone"] == "Africa/Casablanca" and result["currency"] == "MAD"
    rows = times(result)
    assert len(rows) == 25 and "09:00" in rows and "21:00" in rows and "21:30" not in rows
    assert rows["17:00"]["total_amount"] == "120.00"
    assert rows["17:30"]["total_amount"] == "132.00"
    assert rows["21:00"]["total_amount"] == "120.00"
    weekend = times(slots(schedule, "2026-11-21", 90))
    assert weekend["18:00"]["total_amount"] == "204.00"
    assert weekend["18:00"]["applied_percent"] == "20.00"
    assert weekend["18:00"]["ends_at"][11:16] == "19:30"
    assert "20:30" in weekend and "21:00" not in weekend


def test_closed_weekday_is_explained_and_next_search_preserves_duration(schedule):
    body = {
        **schedule.body,
        "version": 1,
        "opening_hours": [
            {"weekday": day, "opens_at": "09:00", "closes_at": "22:00"} for day in range(5)
        ],
    }
    assert (
        schedule.client.put(schedule.admin, headers=schedule.headers, json=body).status_code == 200
    )
    result = slots(schedule, "2026-11-21", 90)
    assert result["status"] == "unavailable" and result["unavailable_reason"] == "closed"
    assert result["day"] == "2026-11-21" and result["opening_weekdays"] == list(range(5))
    following = schedule.client.get(
        schedule.public + "/availability",
        params={"day": "2026-11-21", "minutes": 90, "find_next": True},
    ).json()
    assert following["day"] == "2026-11-23" and following["searched_from"] == "2026-11-21"
    assert following["status"] == "available" and following["minutes"] == 90
    assert following["slots"][0]["total_amount"] == "170.00"


def test_next_search_skips_a_fully_blocked_day_and_is_bounded(schedule):
    assert close(schedule, start="2026-11-20T09:00", end="2026-11-21T00:00").status_code == 201
    result = schedule.client.get(
        schedule.public + "/availability", params={"day": "2026-11-20", "find_next": True}
    ).json()
    assert result["day"] == "2026-11-21" and result["status"] == "available"
    assert "PRIVATE" not in str(result)
    assert (
        close(schedule, version=2, start="2026-11-21T00:00", end="2026-12-20T00:00").status_code
        == 201
    )
    result = schedule.client.get(
        schedule.public + "/availability", params={"day": "2026-11-20", "find_next": True}
    ).json()
    assert result["status"] == "unavailable" and result["search_exhausted"] is True
    assert result["day"] == "2026-11-20"


def test_next_search_keeps_past_and_unconfigured_states_honest(schedule):
    assert (
        schedule.client.get(
            schedule.public + "/availability", params={"day": "2026-11-19", "find_next": True}
        ).json()["status"]
        == "past"
    )
    assert (
        schedule.client.put(
            schedule.admin,
            headers=schedule.headers,
            json={**schedule.body, "version": 1, "opening_hours": []},
        ).status_code
        == 200
    )
    result = schedule.client.get(
        schedule.public + "/availability", params={"find_next": True}
    ).json()
    assert result["status"] == "unconfigured" and not result.get("searched_from")


def test_closure_removes_every_overlapping_start_but_keeps_adjacent_intervals(schedule):
    response = close(schedule)
    assert response.status_code == 201, response.text
    assert response.json()["facility_version"] == 2
    rows = times(slots(schedule))
    assert {"09:00", "11:00"} <= rows.keys()
    assert not {"09:30", "10:00", "10:30"} & rows.keys()
    assert "PRIVATE" not in schedule.client.get(schedule.public + "/availability").text
    listing = schedule.client.get(schedule.admin + "/closures").json()
    assert listing["total"] == 1 and listing["facility_version"] == 2
    assert listing["items"][0]["reason"].startswith("PRIVATE")


def test_overlaps_and_stale_creates_roll_back_and_adjacent_closures_are_valid(schedule):
    assert close(schedule).status_code == 201
    assert (
        close(schedule, version=2, start="2026-11-20T10:30", end="2026-11-20T12:00").status_code
        == 409
    )
    assert (
        close(schedule, version=1, start="2026-11-20T13:00", end="2026-11-20T14:00").status_code
        == 409
    )
    assert schedule.session.scalar(select(func.count()).select_from(FacilityClosure)) == 1
    assert (
        close(schedule, version=2, start="2026-11-20T11:00", end="2026-11-20T12:00").status_code
        == 201
    )
    assert schedule.client.get(schedule.admin).json()["version"] == 3
    assert len(times(slots(schedule))) == 20


def test_cancel_restores_slots_and_retains_closure_audit_and_version_checks(schedule):
    row = close(schedule).json()["closure"]
    path = schedule.admin + f"/closures/{row['id']}/cancel"
    assert (
        schedule.client.post(
            path, headers=schedule.headers, json={"facility_version": 1}
        ).status_code
        == 409
    )
    assert (
        schedule.client.post(
            path, headers=schedule.headers, json={"facility_version": 2}
        ).status_code
        == 204
    )
    assert {"09:30", "10:00", "10:30"} <= times(slots(schedule)).keys()
    stored = schedule.session.get(FacilityClosure, UUID(row["id"]))
    assert not stored.active and stored.cancelled_by == schedule.assignment.user_id
    assert stored.created_by == stored.cancelled_by and stored.cancelled_at is not None
    assert stored.reason.startswith("PRIVATE")
    assert schedule.client.get(schedule.admin + "/closures").json()["total"] == 0
    assert (
        schedule.client.post(
            path, headers=schedule.headers, json={"facility_version": 3}
        ).status_code
        == 409
    )


def test_cross_midnight_opening_and_closure_are_evaluated_in_complex_local_time(schedule):
    facility = schedule.session.get(Facility, UUID(schedule.data["id"]))
    facility.complex.timezone = "Asia/Kolkata"
    schedule.session.commit()
    body = {
        **schedule.body,
        "version": 1,
        "opening_hours": [
            {"weekday": 4, "opens_at": "22:00", "closes_at": "00:00"},
            {"weekday": 5, "opens_at": "00:00", "closes_at": "04:00"},
        ],
    }
    assert (
        schedule.client.put(schedule.admin, headers=schedule.headers, json=body).status_code == 200
    )
    assert "23:30" in times(slots(schedule, minutes=120))
    response = close(schedule, version=2, start="2026-11-21T00:30", end="2026-11-21T01:00")
    assert response.status_code == 201, response.text
    row = schedule.session.get(FacilityClosure, UUID(response.json()["closure"]["id"]))
    assert row.starts_at == datetime(2026, 11, 20, 19, 0)  # 00:30 local at UTC+05:30.
    rows = times(slots(schedule, minutes=120))
    assert "22:30" in rows and "23:00" not in rows and "23:30" not in rows


def test_only_future_starts_are_offered_and_past_or_closed_days_have_no_slots(
    schedule, monkeypatch
):
    monkeypatch.setattr("backend.app.availability.utcnow", lambda: datetime(2026, 11, 20, 9))
    rows = times(slots(schedule))
    assert "09:00" not in rows and "09:30" in rows
    assert slots(schedule, "2026-11-19")["status"] == "past"
    body = {
        **schedule.body,
        "version": 1,
        "opening_hours": [{"weekday": 0, "opens_at": "09:00", "closes_at": "22:00"}],
    }
    assert (
        schedule.client.put(schedule.admin, headers=schedule.headers, json=body).status_code == 200
    )
    assert slots(schedule)["status"] == "unavailable"
    body.update(version=2, opening_hours=[])
    assert (
        schedule.client.put(schedule.admin, headers=schedule.headers, json=body).status_code == 200
    )
    assert slots(schedule)["status"] == "unconfigured"


def test_unpublished_preview_and_private_closures_require_the_owning_administrator(schedule):
    body = {**schedule.body, "version": 1, "active": False}
    assert (
        schedule.client.put(schedule.admin, headers=schedule.headers, json=body).status_code == 200
    )
    assert schedule.client.get(schedule.public + "/availability").status_code == 404
    assert schedule.client.get(schedule.admin + "/availability").status_code == 200
    wrong = schedule.admin.replace(str(demo_id("atlas")), str(demo_id("riverside")))
    assert schedule.client.get(wrong + "/closures").status_code == 403
    assert schedule.client.get(wrong + "/availability").status_code == 403
    assert (
        schedule.client.get(BASE + f"/{demo_id('riverside-tennis')}/availability").status_code
        == 404
    )
    schedule.assignment.role = "employee"
    schedule.session.commit()
    assert schedule.client.get(schedule.admin + "/closures").status_code == 403
    assert schedule.client.get(schedule.admin + "/availability").status_code == 403
    assert close(schedule).status_code == 403
    schedule.assignment.active = False
    schedule.session.commit()
    assert schedule.client.get(schedule.admin + "/closures").status_code == 403


def test_bad_dates_missing_prices_bad_times_and_csrf_are_rejected(schedule):
    path = schedule.public + "/availability"
    for query in [{"day": "not-a-date"}, {"minutes": 30}, {"minutes": 1441}]:
        assert schedule.client.get(path, params=query).status_code == 422
    for changes in [
        {"reason": "   "},
        {"reason": "x" * 501},
        {"starts_local": "2026-02-30T10:00"},
        {"ends_local": "2026-11-20T09:00"},
        {"ends_local": "2026-11-20T10:00"},
        {"ends_local": "2025-11-20T11:00"},
        {"starts_local": "2026-11-20T24:00"},
        {"facility_version": True},
    ]:
        assert close(schedule, **changes).status_code == 422
    original = schedule.headers
    schedule.headers = {**original, "X-CSRF-Token": "wrong"}
    assert close(schedule).status_code == 403
    schedule.headers = {**original, "Origin": "https://other.example"}
    assert close(schedule).status_code == 403
    schedule.headers = original
    assert schedule.session.scalar(select(func.count()).select_from(FacilityClosure)) == 0
    assert schedule.client.get(schedule.admin).json()["version"] == 1
    facility = schedule.session.get(Facility, UUID(schedule.data["id"]))
    facility.complex.timezone = "missing/timezone"
    schedule.session.commit()
    assert schedule.client.get(path).status_code == 503
    assert schedule.client.get(schedule.admin + "/closures").status_code == 503


def test_closure_pagination_is_stable_and_cannot_cancel_another_facilitys_closure(schedule):
    identifiers = []
    for index in range(5):
        response = close(
            schedule,
            version=index + 1,
            start=f"2026-11-{21 + index}T10:00",
            end=f"2026-11-{21 + index}T11:00",
        )
        assert response.status_code == 201
        identifiers.append(response.json()["closure"]["id"])
    response = schedule.client.get(
        schedule.admin + "/closures", params={"limit": 2, "offset": 2}
    ).json()
    assert response["total"] == 5 and [row["id"] for row in response["items"]] == identifiers[2:4]
    wrong = BASE + f"/{demo_id('atlas-tennis')}/closures/{identifiers[0]}/cancel"
    assert (
        schedule.client.post(
            wrong, headers=schedule.headers, json={"facility_version": 1}
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "hours,clock,duration,expected",
    [
        ([(4, 22 * 60, 1440), (5, 0, 120)], "23:30", 120, True),
        ([(4, 22 * 60, 1440)], "23:30", 120, False),
        ([(4, 9 * 60, 10 * 60), (4, 10 * 60, 11 * 60)], "09:30", 60, True),
        ([(4, 9 * 60, 10 * 60), (4, 10 * 60 + 1, 11 * 60)], "09:30", 60, False),
    ],
)
def test_every_elapsed_minute_is_open_including_adjacent_and_overnight_intervals(
    hours, clock, duration, expected
):
    rows = [
        SimpleNamespace(weekday=day, start_minute=start, end_minute=end)
        for day, start, end in hours
    ]
    assert (
        interval_is_open(
            local_start(date(2026, 11, 20), clock, "Africa/Casablanca"), duration, rows
        )
        is expected
    )


@pytest.mark.parametrize("invalid", ["interval", "cancellation"])
def test_database_checks_reject_inconsistent_closures_even_without_api_validation(
    schedule, invalid
):
    start = datetime(2026, 11, 21, 10)
    row = FacilityClosure(
        facility_id=UUID(schedule.data["id"]),
        starts_at=start,
        ends_at=start if invalid == "interval" else datetime(2026, 11, 21, 11),
        reason="Database check test",
        created_by=schedule.assignment.user_id,
        created_at=datetime(2026, 11, 20, 7),
        active=invalid != "cancellation",
    )
    schedule.session.add(row)
    with pytest.raises((IntegrityError, OperationalError)) as rejected:
        schedule.session.flush()
    if isinstance(rejected.value, OperationalError):
        assert rejected.value.orig.args[0] == 3819
    assert f"ck_facility_closures_{invalid}" in str(rejected.value.orig)
    schedule.session.rollback()


def test_clock_change_uses_real_elapsed_minutes_and_omits_ambiguous_starts(schedule, monkeypatch):
    facility = schedule.session.get(Facility, UUID(schedule.data["id"]))
    facility.complex.timezone = "Europe/Paris"
    schedule.session.commit()
    monkeypatch.setattr("backend.app.availability.utcnow", lambda: datetime(2024, 3, 30, 7))
    body = {
        **schedule.body,
        "version": 1,
        "opening_hours": [{"weekday": 6, "opens_at": "01:00", "closes_at": "05:00"}],
    }
    assert (
        schedule.client.put(schedule.admin, headers=schedule.headers, json=body).status_code == 200
    )
    rows = times(slots(schedule, "2024-03-31", 120))
    assert "02:00" not in rows and "02:30" not in rows
    assert rows["01:30"]["ends_at"] == "2024-03-31T04:30:00+02:00"
    monkeypatch.setattr("backend.app.availability.utcnow", lambda: datetime(2024, 10, 26, 7))
    rows = times(slots(schedule, "2024-10-27", 60))
    assert "02:00" not in rows and "02:30" not in rows
    assert "01:30" in rows and "03:00" in rows
    assert (
        close(schedule, version=2, start="2024-10-27T02:30", end="2024-10-27T04:30").status_code
        == 422
    )
