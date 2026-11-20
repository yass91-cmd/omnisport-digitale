from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from backend.app.models import Facility, FacilityTariff, OpeningHour, SportDuration, StaffAssignment
from backend.app.seed import demo_id

BASE = f"/api/v1/staff/complexes/{demo_id('atlas')}/facilities"
WRITE = {"X-Omni-Request": "1", "Origin": "http://testserver"}


@pytest.fixture
def admin(client, session):
    response = client.post(
        "/api/v1/auth/register",
        headers=WRITE,
        json={
            "name": "Facility Admin",
            "email": "facility-admin@example.com",
            "password": "a memorable facility test password",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assignment = StaffAssignment(
        user_id=UUID(data["id"]), complex_id=demo_id("atlas"), role="admin"
    )
    session.add(assignment)
    session.commit()
    return client, {**WRITE, "X-CSRF-Token": data["csrf_token"]}, assignment


def payload(**changes):
    data = {
        "name": "New Test Court",
        "sport_id": str(demo_id("tennis")),
        "surface": "Hard court",
        "description": "A test facility",
        "active": True,
        "opening_hours": [
            {"weekday": 0, "opens_at": "09:00", "closes_at": "12:00"},
            {"weekday": 0, "opens_at": "13:00", "closes_at": "22:00"},
        ],
        "tariffs": [
            {"minutes": 60, "amount": "125.50"},
            {"minutes": 90, "amount": "175.00"},
            {"minutes": 120, "amount": "220.00"},
        ],
    }
    data.update(changes)
    return data


def create(admin, **changes):
    client, headers, _ = admin
    response = client.post(BASE, json=payload(**changes), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_admin_creates_complete_configuration_and_public_reads_same_data(admin, session):
    client, _, _ = admin
    data = create(admin)
    assert (
        data["version"] == 1
        and data["currency"] == "MAD"
        and data["timezone"] == "Africa/Casablanca"
    )
    assert data["sport"]["allowed_durations"] == [60, 90, 120]
    assert data["tariffs"][0]["amount"] == "125.50"
    assert len(data["opening_hours"]) == 2
    stored = session.get(Facility, UUID(data["id"]))
    assert stored.complex_id == demo_id("atlas")
    public = client.get(f"/api/v1/complexes/{demo_id('atlas')}").json()
    exposed = next(item for item in public["facilities"] if item["id"] == data["id"])
    assert (
        exposed["opening_hours"] == data["opening_hours"] and exposed["tariffs"] == data["tariffs"]
    )
    assert client.get(BASE + f"/{data['id']}").json() == data


def test_update_replaces_settings_atomically_and_increments_version(admin, session):
    client, headers, _ = admin
    data = create(admin)
    changes = payload(
        name="Renamed court",
        version=1,
        sport_id=str(demo_id("football")),
        opening_hours=[{"weekday": 6, "opens_at": "10:00", "closes_at": "00:00"}],
        tariffs=[{"minutes": 60, "amount": "0.00"}],
    )
    updated = client.put(BASE + f"/{data['id']}", json=changes, headers=headers)
    assert updated.status_code == 200, updated.text
    result = updated.json()
    assert result["version"] == 2 and result["sport"]["slug"] == "football"
    assert result["opening_hours"] == [{"weekday": 6, "opens_at": "10:00", "closes_at": "24:00"}]
    assert result["tariffs"] == [{"minutes": 60, "amount": "0.00"}]
    assert (
        session.scalar(
            select(func.count())
            .select_from(OpeningHour)
            .where(OpeningHour.facility_id == UUID(data["id"]))
        )
        == 1
    )
    assert session.scalar(
        select(FacilityTariff.sport_id).where(FacilityTariff.facility_id == UUID(data["id"]))
    ) == demo_id("football")


def test_stale_editor_cannot_overwrite_newer_settings(admin):
    client, headers, _ = admin
    data = create(admin)
    path = BASE + f"/{data['id']}"
    assert (
        client.put(path, json=payload(version=1, name="First editor"), headers=headers).status_code
        == 200
    )
    stale = client.put(
        path,
        json=payload(version=1, name="Stale editor", opening_hours=[], tariffs=[]),
        headers=headers,
    )
    assert stale.status_code == 409
    saved = client.get(path).json()
    assert saved["name"] == "First editor" and len(saved["tariffs"]) == 3 and saved["version"] == 2


def test_invalid_hours_are_rejected_without_writes(admin, session):
    client, headers, _ = admin
    for rows in [
        [{"weekday": 7, "opens_at": "09:00", "closes_at": "18:00"}],
        [{"weekday": 0, "opens_at": "22:00", "closes_at": "02:00"}],
        [{"weekday": 0, "opens_at": "09:00", "closes_at": "09:00"}],
        [{"weekday": 0, "opens_at": "24:00", "closes_at": "24:00"}],
        [{"weekday": 0, "opens_at": "09:00:30", "closes_at": "18:00"}],
        [
            {"weekday": 0, "opens_at": "09:00", "closes_at": "12:00"},
            {"weekday": 0, "opens_at": "11:30", "closes_at": "15:00"},
        ],
    ]:
        response = client.post(BASE, json=payload(opening_hours=rows), headers=headers)
        assert response.status_code == 422, response.text
    assert session.scalar(select(func.count()).select_from(Facility)) == 5


def test_adjacent_intervals_and_full_day_are_valid(admin):
    data = create(
        admin,
        opening_hours=[
            {"weekday": 0, "opens_at": "00:00", "closes_at": "24:00"},
            {"weekday": 1, "opens_at": "09:00", "closes_at": "12:00"},
            {"weekday": 1, "opens_at": "12:00", "closes_at": "18:00"},
        ],
    )
    assert len(data["opening_hours"]) == 3


def test_invalid_prices_and_unapproved_durations_are_rejected(admin, session):
    client, headers, _ = admin
    for rows in [
        [{"minutes": 60, "amount": "-0.01"}],
        [{"minutes": 60, "amount": "1.001"}],
        [{"minutes": 60, "amount": "100000000.00"}],
        [{"minutes": 60, "amount": "NaN"}],
        [{"minutes": 30, "amount": "50.00"}],
        [{"minutes": 45, "amount": "50.00"}],
        [{"minutes": 60, "amount": "10.00"}, {"minutes": 60, "amount": "20.00"}],
    ]:
        response = client.post(BASE, json=payload(tariffs=rows), headers=headers)
        assert response.status_code == 422, response.text
    assert session.scalar(select(func.count()).select_from(Facility)) == 5


def test_rejected_update_preserves_name_hours_prices_and_version(admin):
    client, headers, _ = admin
    data = create(admin)
    path = BASE + f"/{data['id']}"
    invalid = payload(
        version=1, name="Must not persist", tariffs=[{"minutes": 30, "amount": "10.00"}]
    )
    assert client.put(path, json=invalid, headers=headers).status_code == 422
    assert client.get(path).json() == data


def test_duplicate_name_conflicts_roll_back_settings_and_other_complex_can_reuse_name(
    admin, session
):
    client, headers, _ = admin
    data = create(admin)
    path = BASE + f"/{data['id']}"
    assert client.post(BASE, json=payload(), headers=headers).status_code == 409
    response = client.put(
        path,
        json=payload(version=1, name="Atlas Football Pitch", opening_hours=[], tariffs=[]),
        headers=headers,
    )
    assert response.status_code == 409, response.text
    assert client.get(path).json() == data
    session.add(
        StaffAssignment(user_id=admin[2].user_id, complex_id=demo_id("riverside"), role="admin")
    )
    session.commit()
    other = f"/api/v1/staff/complexes/{demo_id('riverside')}/facilities"
    assert client.post(other, json=payload(), headers=headers).status_code == 201


def test_admin_cannot_access_or_modify_other_complex_facilities(admin):
    client, headers, _ = admin
    riverside = f"/api/v1/staff/complexes/{demo_id('riverside')}/facilities"
    assert client.post(riverside, json=payload(), headers=headers).status_code == 403
    path = riverside + f"/{demo_id('riverside-tennis')}"
    assert client.get(path).status_code == 403
    assert client.put(path, json=payload(version=1), headers=headers).status_code == 403
    spoofed = BASE + f"/{demo_id('riverside-tennis')}"
    assert client.get(spoofed).status_code == 404
    assert client.put(spoofed, json=payload(version=1), headers=headers).status_code == 404


def test_employees_and_players_cannot_manage_facilities(admin, session):
    client, headers, assignment = admin
    path = BASE + f"/{demo_id('atlas-tennis')}"
    assignment.role = "employee"
    session.commit()
    assert client.get(f"/api/v1/staff/complexes/{demo_id('atlas')}").status_code == 200
    assert client.get(path).status_code == 403
    assert client.post(BASE, json=payload(), headers=headers).status_code == 403
    assert client.put(path, json=payload(version=1), headers=headers).status_code == 403
    assignment.active = False
    session.commit()
    assert client.post(BASE, json=payload(), headers=headers).status_code == 403


def test_mutations_require_session_origin_and_csrf(admin):
    client, headers, _ = admin
    assert client.post(BASE, json=payload(), headers=WRITE).status_code == 403
    assert (
        client.post(
            BASE, json=payload(), headers={**headers, "Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    client.cookies.clear()
    assert client.post(BASE, json=payload(), headers=headers).status_code == 401


def test_admin_cannot_transfer_ownership_or_change_global_rules(admin):
    client, headers, _ = admin
    for fields in [
        {"complex_id": str(demo_id("riverside"))},
        {"currency": "EUR"},
        {"allowed_durations": [30]},
    ]:
        assert client.post(BASE, json=payload(**fields), headers=headers).status_code == 422
    assert (
        client.post(BASE, json=payload(sport_id=str(uuid4())), headers=headers).status_code == 422
    )
    assert client.post(BASE, json=payload(name="   "), headers=headers).status_code == 422


def test_deactivation_hides_public_facility_and_reactivation_preserves_configuration(admin):
    client, headers, _ = admin
    data = create(admin)
    path = BASE + f"/{data['id']}"
    assert (
        client.put(path, json=payload(version=1, active=False), headers=headers).status_code == 200
    )
    public = client.get(f"/api/v1/complexes/{demo_id('atlas')}").json()
    assert all(item["id"] != data["id"] for item in public["facilities"])
    assert any(
        item["id"] == data["id"] and not item["active"]
        for item in client.get(f"/api/v1/staff/complexes/{demo_id('atlas')}").json()["facilities"]
    )
    assert (
        client.put(path, json=payload(version=2, active=True), headers=headers).status_code == 200
    )
    assert client.get(path).json()["tariffs"] == data["tariffs"]


def test_database_rejects_tariff_for_a_different_sport_even_without_api(admin, session):
    data = create(admin, tariffs=[])
    session.add(
        FacilityTariff(
            facility_id=UUID(data["id"]),
            sport_id=demo_id("football"),
            minutes=60,
            amount=Decimal("10.00"),
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_database_rejects_unapproved_duration_even_without_api(admin, session):
    data = create(admin)
    session.add(
        FacilityTariff(
            facility_id=UUID(data["id"]),
            sport_id=demo_id("tennis"),
            minutes=45,
            amount=Decimal("10.00"),
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_defaults_have_exactly_the_agreed_durations(admin, session):
    client, _, _ = admin
    for sport in client.get("/api/v1/sports").json():
        assert sport["allowed_durations"] == [60, 90, 120]
    assert session.scalar(select(func.count()).select_from(SportDuration)) == 9
