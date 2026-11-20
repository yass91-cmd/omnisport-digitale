import argparse
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .database import make_engine
from .models import Complex, Facility, Sport, SportDuration


def demo_id(name: str):
    return uuid5(NAMESPACE_URL, f"https://example.invalid/omnisport-demo/{name}")


def seed_demo(session: Session) -> None:
    sports = {}
    for slug, name in [
        ("football", "Football"),
        ("basketball", "Basketball"),
        ("tennis", "Tennis"),
    ]:
        sport = session.scalar(select(Sport).where(Sport.slug == slug))
        if sport is None:
            sport = Sport(id=demo_id(slug), slug=slug, name=name)
            session.add(sport)
        sports[slug] = sport.id
    for slug, name, city, description in [
        (
            "atlas",
            "Atlas Demo Complex",
            "Casablanca",
            "An illustrative multi-sport location with outdoor pitches and courts.",
        ),
        (
            "riverside",
            "Riverside Demo Complex",
            "Rabat",
            "An illustrative place for football games and tennis rallies.",
        ),
    ]:
        if session.get(Complex, demo_id(slug)) is None:
            session.add(
                Complex(
                    id=demo_id(slug),
                    name=name,
                    city=city,
                    address=f"Demo location in {city}",
                    timezone="Africa/Casablanca",
                    description=description,
                    is_demo=True,
                    active=True,
                )
            )
    session.flush()
    for sport_id in sports.values():
        for value in [60, 90, 120]:
            if session.get(SportDuration, (sport_id, value)) is None:
                session.add(SportDuration(sport_id=sport_id, minutes=value))
    session.flush()
    for complex_slug, sport, name, surface, description in [
        (
            "atlas",
            "football",
            "Atlas Football Pitch",
            "Synthetic grass",
            "An outdoor football pitch for your team's next game.",
        ),
        (
            "atlas",
            "basketball",
            "Atlas Basketball Court",
            "Hard court",
            "An outdoor court for practice and team games.",
        ),
        (
            "atlas",
            "tennis",
            "Atlas Tennis Court",
            "Hard court",
            "A dedicated tennis court for your next rally.",
        ),
        (
            "riverside",
            "football",
            "Riverside Football Pitch",
            "Synthetic grass",
            "An outdoor football pitch for training and team games.",
        ),
        (
            "riverside",
            "tennis",
            "Riverside Tennis Court",
            "Clay",
            "A clay court for tennis practice and friendly games.",
        ),
    ]:
        facility_id = demo_id(f"{complex_slug}-{sport}")
        if session.get(Facility, facility_id) is None:
            session.add(
                Facility(
                    id=facility_id,
                    complex_id=demo_id(complex_slug),
                    sport_id=sports[sport],
                    name=name,
                    surface=surface,
                    description=description,
                    active=True,
                )
            )
    session.flush()


def main():
    parser = argparse.ArgumentParser(
        description="Insert clearly labeled, fictional demonstration catalogue data."
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        required=True,
        help="Explicitly opt into adding demo records.",
    )
    parser.parse_args()
    engine = make_engine(Settings())
    try:
        with Session(engine) as session, session.begin():
            seed_demo(session)
        print(
            "Base demo catalogue ensured (2 complexes, 3 sports, 5 facilities). Existing records were preserved."
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
