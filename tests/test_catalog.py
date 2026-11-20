from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from backend.app.models import Complex, Facility, Sport
from backend.app.seed import demo_id, seed_demo


def test_list_filter_and_pagination(client):
    all_complexes = client.get("/api/v1/complexes").json()
    assert all_complexes["total"] == 2
    assert all(item["is_demo"] for item in all_complexes["items"])
    assert {item["city"] for item in all_complexes["items"]} == {"Casablanca", "Rabat"}
    assert client.get("/api/v1/complexes?sport=basketball").json()["total"] == 1
    assert client.get("/api/v1/complexes?sport=football").json()["total"] == 2
    assert client.get("/api/v1/complexes?city=rabat&sport=basketball").json()["total"] == 0
    assert client.get("/api/v1/complexes?city=rabat&sport=tennis").json()["total"] == 1
    first = client.get("/api/v1/complexes?limit=1").json()
    second = client.get("/api/v1/complexes?limit=1&offset=1").json()
    assert first["total"] == second["total"] == 2
    assert len(first["items"]) == len(second["items"]) == 1
    assert first["items"][0]["id"] != second["items"][0]["id"]


def test_city_and_sport_catalogue(client):
    assert client.get("/api/v1/cities").json() == ["Casablanca", "Rabat"]
    assert {item["slug"] for item in client.get("/api/v1/sports").json()} == {
        "football",
        "basketball",
        "tennis",
    }


def test_detail_uses_facilities_owned_by_the_complex(client):
    atlas = client.get(f"/api/v1/complexes/{demo_id('atlas')}").json()
    riverside = client.get(f"/api/v1/complexes/{demo_id('riverside')}").json()
    assert atlas["facility_count"] == len(atlas["facilities"]) == 3
    assert riverside["facility_count"] == len(riverside["facilities"]) == 2
    assert all(f["name"].startswith("Atlas") for f in atlas["facilities"])
    assert all(f["name"].startswith("Riverside") for f in riverside["facilities"])


def test_inactive_complex_is_hidden(client, session):
    session.get(Complex, demo_id("atlas")).active = False
    session.flush()
    assert client.get("/api/v1/complexes").json()["total"] == 1
    assert client.get(f"/api/v1/complexes/{demo_id('atlas')}").status_code == 404
    assert client.get("/api/v1/cities").json() == ["Rabat"]


def test_inactive_facility_is_hidden_and_not_used_for_sport_filter(client, session):
    session.get(Facility, demo_id("atlas-basketball")).active = False
    session.flush()
    assert client.get("/api/v1/complexes?sport=basketball").json()["total"] == 0
    detail = client.get(f"/api/v1/complexes/{demo_id('atlas')}").json()
    assert detail["facility_count"] == 2
    assert all(f["sport"]["slug"] != "basketball" for f in detail["facilities"])


def test_invalid_input_and_missing_records(client):
    assert client.get(f"/api/v1/complexes/{uuid4()}").status_code == 404
    assert client.get("/api/v1/complexes/not-a-uuid").status_code == 422
    assert client.get("/api/v1/complexes?limit=0").status_code == 422
    assert client.get("/api/v1/complexes?offset=-1").status_code == 422
    attack = "Casablanca' OR 1=1 --"
    assert client.get("/api/v1/complexes", params={"city": attack}).json()["total"] == 0


def test_demo_seed_is_repeatable_without_overwriting_edits(client, session):
    session.get(Complex, demo_id("atlas")).name = "An edited demo name"
    seed_demo(session)
    seed_demo(session)
    assert session.scalar(select(func.count()).select_from(Complex)) == 2
    assert session.scalar(select(func.count()).select_from(Sport)) == 3
    assert session.scalar(select(func.count()).select_from(Facility)) == 5
    assert session.get(Complex, demo_id("atlas")).name == "An edited demo name"


def test_seed_reuses_existing_sport(session):
    sport_id = uuid4()
    session.add(Sport(id=sport_id, slug="football", name="Football"))
    session.flush()
    seed_demo(session)
    assert session.get(Facility, demo_id("atlas-football")).sport_id == sport_id
    assert session.scalar(select(func.count()).select_from(Sport)) == 3


def test_facility_requires_a_real_complex(client, session):
    session.add(
        Facility(
            id=uuid4(),
            complex_id=uuid4(),
            sport_id=demo_id("football"),
            name="Orphan",
            surface="Hard court",
            description="Invalid test record",
            active=True,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_facility_name_is_unique_within_each_complex(client, session):
    session.add(
        Facility(
            id=uuid4(),
            complex_id=demo_id("riverside"),
            sport_id=demo_id("football"),
            name="Atlas Football Pitch",
            surface="Synthetic grass",
            description="Valid distinct owner",
            active=True,
        )
    )
    session.flush()
    session.add(
        Facility(
            id=uuid4(),
            complex_id=demo_id("atlas"),
            sport_id=demo_id("football"),
            name="Atlas Football Pitch",
            surface="Synthetic grass",
            description="Duplicate test record",
            active=True,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()
