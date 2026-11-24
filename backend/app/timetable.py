"""Daily, non-overlapping timetable blocks with staff-only customer details."""

from datetime import UTC, datetime, time, timedelta

from fastapi import HTTPException
from sqlalchemy import select

from .booking_state import history_status
from .models import FacilityClosure, Reservation
from .scheduling import zone_for


def day_bounds(day, zone):
    def edge(value):
        wall = datetime.combine(value, time())
        choices = [wall.replace(tzinfo=zone, fold=fold).astimezone(UTC) for fold in (0, 1)]
        return min(instant for instant in choices if instant.astimezone(zone).date() >= value)

    try:
        return edge(day), edge(day + timedelta(days=1))
    except (OverflowError, ValueError):
        raise HTTPException(422, "Choose another date.") from None


def daily_timetable(session, facility, day, now, *, staff=False):
    zone = zone_for(facility)
    begin, end = day_bounds(day, zone)
    begin_naive, end_naive = begin.replace(tzinfo=None), end.replace(tzinfo=None)
    bookings = session.scalars(
        select(Reservation)
        .where(
            Reservation.facility_id == facility.id,
            Reservation.status.in_(["pending", "confirmed"]),
            Reservation.starts_at < end_naive,
            Reservation.ends_at > begin_naive,
        )
        .order_by(Reservation.starts_at)
    ).all()
    closures = session.scalars(
        select(FacilityClosure).where(
            FacilityClosure.facility_id == facility.id,
            FacilityClosure.active.is_(True),
            FacilityClosure.starts_at < end_naive,
            FacilityClosure.ends_at > begin_naive,
        )
    ).all()
    hours = [
        (row.start_minute, row.end_minute)
        for row in facility.opening_hours
        if row.weekday == day.weekday()
    ]
    points = []
    instant = begin
    while instant < end:
        naive = instant.replace(tzinfo=None)
        local = instant.astimezone(zone)
        minute = local.hour * 60 + local.minute
        opened = any(start <= minute < finish for start, finish in hours)
        booking = next((row for row in bookings if row.starts_at <= naive < row.ends_at), None)
        closure = next((row for row in closures if row.starts_at <= naive < row.ends_at), None)
        state = (
            "reserved"
            if booking
            else "blocked"
            if closure and opened
            else "past"
            if opened and naive <= now
            else "available"
            if opened
            else "closed"
        )
        key = (state, booking.id if booking else closure.id if closure and opened else None)
        points.append((instant, key, booking, opened or booking is not None))
        instant += timedelta(minutes=1)
    relevant = [index for index, point in enumerate(points) if point[3]]
    if not relevant:
        return []
    rows = []
    for instant, key, booking, _ in points[min(relevant) : max(relevant) + 1]:
        if rows and rows[-1]["key"] == key:
            rows[-1]["end"] = instant + timedelta(minutes=1)
            continue
        rows.append(
            {
                "key": key,
                "start": instant,
                "end": instant + timedelta(minutes=1),
                "booking": booking,
            }
        )
    result = []
    for row in rows:
        booking = row["booking"]
        item = {
            "state": row["key"][0],
            "starts_at": row["start"].astimezone(zone),
            "ends_at": row["end"].astimezone(zone),
        }
        if staff and booking:
            item.update(
                reservation_id=booking.id,
                booking_status=history_status(booking),
                client_name=booking.client_name,
                client_phone=booking.client_phone,
                minutes=booking.minutes,
                reservation_starts_at=booking.starts_at.replace(tzinfo=UTC).astimezone(zone),
                reservation_ends_at=booking.ends_at.replace(tzinfo=UTC).astimezone(zone),
                reference=booking.reference,
                walk_in=booking.client_id is None,
            )
        result.append(item)
    return result
