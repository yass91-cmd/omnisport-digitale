from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError, OperationalError

from backend.app.models import Facility, StaffAssignment
from backend.app.pricing import calculate_price, local_start
from backend.app.seed import demo_id


@pytest.mark.parametrize(
    "day,clock,duration,weekend,evening,total",
    [
        ("2026-11-20", "10:00", 60, False, False, "100.00"),
        ("2026-11-20", "17:00", 60, False, False, "100.00"),
        ("2026-11-20", "17:01", 60, False, True, "110.00"),
        ("2026-11-20", "17:30", 60, False, True, "110.00"),
        ("2026-11-20", "18:00", 60, False, True, "110.00"),
        ("2026-11-20", "20:59", 60, False, True, "110.00"),
        ("2026-11-20", "21:00", 60, False, False, "100.00"),
        ("2026-11-20", "16:00", 120, False, False, "100.00"),
        ("2026-11-20", "16:01", 120, False, True, "110.00"),
        ("2026-11-21", "10:00", 60, True, False, "110.00"),
        ("2026-11-22", "10:00", 90, True, False, "110.00"),
        ("2026-11-21", "18:00", 120, True, True, "120.00"),
        ("2026-11-22", "17:30", 60, True, True, "120.00"),
        ("2026-11-22", "20:30", 120, True, True, "120.00"),
        ("2026-11-20", "23:00", 60, False, False, "100.00"),
        ("2026-11-20", "23:30", 60, True, False, "110.00"),
        ("2026-11-22", "23:30", 120, True, False, "110.00"),
        ("2026-11-23", "00:00", 60, False, False, "100.00"),
    ],
)
def test_additive_whole_booking_increases_and_exact_boundaries(
    day, clock, duration, weekend, evening, total
):
    start = local_start(date.fromisoformat(day), clock, "Africa/Casablanca")
    quote = calculate_price(Decimal("100.00"), start, duration, Decimal("10"), Decimal("10"))
    assert quote.weekend_applied is weekend
    assert quote.evening_applied is evening
    assert quote.total_amount == Decimal(total)


@pytest.mark.parametrize(
    "base,clock,expected",
    [("0.05", "18:00", "0.06"), ("10.05", "18:00", "12.06"), ("0.00", "18:00", "0.00")],
)
def test_rounds_total_once_to_mad_cents_and_preserves_free_prices(base, clock, expected):
    quote = calculate_price(
        Decimal(base),
        local_start(date(2026, 11, 21), clock, "Africa/Casablanca"),
        60,
        Decimal("10"),
        Decimal("10"),
    )
    assert quote.total_amount == Decimal(expected)
    assert quote.base_amount + quote.surcharge_amount == quote.total_amount


def test_zero_percent_disables_rule_and_custom_percentages_still_add():
    start = local_start(date(2026, 11, 21), "18:00", "Africa/Casablanca")
    quote = calculate_price(Decimal("100.00"), start, 60, Decimal("0"), Decimal("15"))
    assert not quote.weekend_applied and quote.evening_applied
    assert quote.total_amount == Decimal("115.00")
    quote = calculate_price(Decimal("100.00"), start, 60, Decimal("7.50"), Decimal("12.50"))
    assert quote.applied_percent == Decimal("20.00")
    assert quote.total_amount == Decimal("120.00")


def test_half_cent_uses_half_up_rounding():
    quote = calculate_price(
        Decimal("10.15"),
        local_start(date(2026, 11, 20), "18:00", "Africa/Casablanca"),
        60,
        Decimal("10"),
        Decimal("10"),
    )
    assert quote.total_amount == Decimal("11.17")


@pytest.mark.parametrize("day", [date(2024, 3, 31), date(2024, 10, 27)])
def test_clock_change_missing_or_ambiguous_local_start_is_rejected(day):
    with pytest.raises(HTTPException) as failure:
        local_start(day, "02:30", "Europe/Paris")
    assert failure.value.status_code == 422


@pytest.fixture
def priced(client, session):
    write = {"X-Omni-Request": "1", "Origin": "http://testserver"}
    response = client.post(
        "/api/v1/auth/register",
        headers=write,
        json={
            "name": "Pricing admin",
            "email": "pricing@example.com",
            "password": "a long pricing test password",
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
        "name": "Priced Tennis Court",
        "sport_id": str(demo_id("tennis")),
        "surface": "Hard court",
        "description": "Pricing test",
        "active": True,
        "opening_hours": [{"weekday": 0, "opens_at": "09:00", "closes_at": "22:00"}],
        "tariffs": [
            {"minutes": 60, "amount": "125.50"},
            {"minutes": 90, "amount": "175.00"},
            {"minutes": 120, "amount": "220.00"},
        ],
        "weekend_percent": "10.00",
        "evening_percent": "10.00",
    }
    base = f"/api/v1/staff/complexes/{demo_id('atlas')}/facilities"
    response = client.post(base, json=body, headers=headers)
    assert response.status_code == 201, response.text
    return client, session, headers, assignment, body, response.json(), base


def public_path(data):
    return f"/api/v1/complexes/{demo_id('atlas')}/facilities/{data['id']}/quote"


def test_quote_uses_saved_base_duration_rates_currency_and_local_time(priced):
    client, _, _, _, _, data, _ = priced
    path = public_path(data)
    response = client.get(
        path,
        params={
            "day": "2026-11-21",
            "starts_at": "17:30",
            "minutes": 60,
            "base_amount": "0.01",
            "weekend_percent": 0,
            "currency": "EUR",
        },
    )
    assert response.status_code == 200, response.text
    quote = response.json()
    assert quote["base_amount"] == "125.50" and quote["total_amount"] == "150.60"
    assert quote["applied_percent"] == "20.00" and quote["currency"] == "MAD"
    assert quote["availability_checked"] is False and quote["facility_version"] == 1
    assert quote["starts_at"].startswith("2026-11-21T17:30")
    assert quote["ends_at"].startswith("2026-11-21T18:30")
    assert response.headers["Cache-Control"] == "no-store"
    quote = client.get(
        path, params={"day": "2026-11-21", "starts_at": "18:00", "minutes": 90}
    ).json()
    assert quote["base_amount"] == "175.00" and quote["total_amount"] == "210.00"
    quote = client.get(
        path, params={"day": "2026-11-20", "starts_at": "21:00", "minutes": 60}
    ).json()
    assert not quote["evening_applied"] and quote["total_amount"] == "125.50"


def test_private_facility_quote_is_admin_only_and_never_public(priced):
    client, session, headers, assignment, body, data, base = priced
    path = base + f"/{data['id']}"
    body.update(version=1, active=False)
    assert client.put(path, json=body, headers=headers).status_code == 200
    params = {"day": "2026-11-21", "starts_at": "18:00", "minutes": 60}
    assert client.get(public_path(data), params=params).status_code == 404
    assert client.get(path + "/quote", params=params).status_code == 200
    spoofed = f"/api/v1/staff/complexes/{demo_id('riverside')}/facilities/{data['id']}/quote"
    assert client.get(spoofed, params=params).status_code == 403
    assignment.role = "employee"
    session.commit()
    assert client.get(path + "/quote", params=params).status_code == 403


def test_rate_edits_are_versioned_and_bad_percentages_do_not_persist(priced):
    client, session, headers, _, body, data, base = priced
    path = base + f"/{data['id']}"
    for invalid in ["-0.01", "100.01", "NaN", "10.001"]:
        invalid_body = {**body, "version": 1, "weekend_percent": invalid}
        assert client.put(path, json=invalid_body, headers=headers).status_code == 422
    assert client.get(path).json()["version"] == 1
    body.update(version=1, weekend_percent="0.00", evening_percent="0.00")
    response = client.put(path, json=body, headers=headers)
    assert response.status_code == 200 and response.json()["version"] == 2
    quote = client.get(
        public_path(data), params={"day": "2026-11-21", "starts_at": "18:00", "minutes": 60}
    ).json()
    assert (
        quote["total_amount"] == "125.50"
        and not quote["weekend_applied"]
        and not quote["evening_applied"]
    )
    facility = session.get(Facility, UUID(data["id"]))
    facility.weekend_percent = Decimal("-1")
    with pytest.raises((IntegrityError, OperationalError)) as rejected:
        session.flush()
    if isinstance(rejected.value, OperationalError):
        # MySQL reports CHECK violations as error 3819 via OperationalError.
        assert rejected.value.orig.args[0] == 3819
    assert "ck_facilities_weekend_percent" in str(rejected.value.orig)
    session.rollback()
    assert session.get(Facility, UUID(data["id"])).weekend_percent == Decimal("0.00")


def test_quote_rejects_unpriced_duration_bad_clock_and_unavailable_timezone(priced):
    client, session, _, _, _, data, _ = priced
    path = public_path(data)
    assert (
        client.get(
            path, params={"day": "2026-11-21", "starts_at": "18:00", "minutes": 30}
        ).status_code
        == 422
    )
    assert (
        client.get(
            path, params={"day": "2026-11-21", "starts_at": "24:00", "minutes": 60}
        ).status_code
        == 422
    )
    assert (
        client.get(
            path, params={"day": "2026-11-21", "starts_at": "18:00:01", "minutes": 60}
        ).status_code
        == 422
    )
    session.get(Facility, UUID(data["id"])).complex.timezone = "missing/timezone"
    session.commit()
    assert (
        client.get(
            path, params={"day": "2026-11-21", "starts_at": "18:00", "minutes": 60}
        ).status_code
        == 503
    )


def test_complex_has_multiple_sports_with_many_independently_priced_facilities(priced):
    client, _, headers, _, body, _, base = priced
    rows = []
    for name, amount in [("Second Tennis Stadium", "10.00"), ("Third Tennis Stadium", "20.00")]:
        response = client.post(
            base,
            json={**body, "name": name, "tariffs": [{"minutes": 60, "amount": amount}]},
            headers=headers,
        )
        assert response.status_code == 201, response.text
        rows.append(response.json())
    workspace = client.get(f"/api/v1/staff/complexes/{demo_id('atlas')}").json()
    assert {row["sport"] for row in workspace["facilities"]} == {"Football", "Basketball", "Tennis"}
    assert (
        len([row for row in workspace["facilities"] if row["sport_id"] == str(demo_id("tennis"))])
        == 4
    )
    public = client.get(f"/api/v1/complexes/{demo_id('atlas')}").json()
    assert len(public["sports"]) == 3 and public["facility_count"] == 6
    for row, amount in zip(rows, ["10.00", "20.00"]):
        quote = client.get(
            public_path(row), params={"day": "2026-11-20", "starts_at": "10:00", "minutes": 60}
        ).json()
        assert quote["base_amount"] == quote["total_amount"] == amount


def test_quote_duration_is_real_elapsed_time_across_clock_change(priced):
    client, session, _, _, _, data, _ = priced
    session.get(Facility, UUID(data["id"])).complex.timezone = "Europe/Paris"
    session.commit()
    response = client.get(
        public_path(data), params={"day": "2024-03-31", "starts_at": "01:30", "minutes": 120}
    )
    assert response.status_code == 200, response.text
    quote = response.json()
    assert quote["starts_at"].startswith("2024-03-31T01:30:00+01:00")
    assert quote["ends_at"].startswith("2024-03-31T04:30:00+02:00")
    assert quote["total_amount"] == "242.00"
