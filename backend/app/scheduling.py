"""Shared local-time coverage and version rules for schedule writers."""

from datetime import UTC, date, timedelta
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select, update

from .models import Facility, Reservation
from .pricing import business_zone, local_start

LOCAL_DATETIME = r"^\d{4}-\d{2}-\d{2}T(?:[01][0-9]|2[0-3]):[0-5][0-9]$"


def zone_for(facility):
    try:
        return business_zone(facility.complex.timezone)
    except (OSError, ValueError, ModuleNotFoundError):
        raise HTTPException(503, "The complex's local time is unavailable.") from None


def local_instant(value, timezone):
    try:
        day = date.fromisoformat(value[:10])
    except ValueError:
        raise HTTPException(422, "Choose a valid date.") from None
    return local_start(day, value[11:], timezone).astimezone(UTC).replace(tzinfo=None)


def interval_is_open(start, duration, hours):
    by_day = {}
    for row in hours:
        by_day.setdefault(row.weekday, []).append((row.start_minute, row.end_minute))
    utc = start.astimezone(UTC)
    for offset in range(duration):
        instant = (utc + timedelta(minutes=offset)).astimezone(start.tzinfo)
        minute = instant.hour * 60 + instant.minute
        if not any(begin <= minute < end for begin, end in by_day.get(instant.weekday(), [])):
            return False
    return True


def bump_schedule(session, facility, expected):
    if facility.version != expected:
        raise HTTPException(409, "The schedule changed. Reload and try again.")
    result = session.execute(
        update(Facility)
        .where(
            Facility.id == facility.id,
            Facility.version == expected,
        )
        .values(version=expected + 1)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        session.rollback()
        raise HTTPException(409, "The schedule changed. Reload and try again.")


def protect_confirmed_bookings(session, facility, data, now):
    rows = session.scalars(
        select(Reservation)
        .where(
            Reservation.facility_id == facility.id,
            Reservation.status.in_(["pending", "confirmed"]),
            Reservation.ends_at > now,
        )
        .with_for_update()
    ).all()
    if not rows:
        return
    if not data.active or data.sport_id != facility.sport_id:
        raise HTTPException(
            409,
            "Pending or confirmed bookings exist. Keep this facility published with its booked sport until they are resolved.",
        )
    hours = []
    for row in data.opening_hours:
        start = int(row.opens_at[:2]) * 60 + int(row.opens_at[3:])
        end = int(row.closes_at[:2]) * 60 + int(row.closes_at[3:])
        hours.append(
            SimpleNamespace(weekday=row.weekday, start_minute=start, end_minute=end or 1440)
        )
    zone = zone_for(facility)
    if any(
        not interval_is_open(row.starts_at.replace(tzinfo=UTC).astimezone(zone), row.minutes, hours)
        for row in rows
    ):
        raise HTTPException(
            409, "The new hours would exclude a pending or confirmed booking. Resolve it first."
        )
