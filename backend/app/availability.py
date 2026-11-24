"""Available-time previews and administrator-managed dated closures."""

from datetime import UTC, date, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select

from .auth import ComplexAdmin, ComplexAssignment
from .facilities import owned_facility
from .models import Complex, Facility, FacilityClosure, Reservation
from .pricing import DurationQuery, PriceBreakdown, calculate_price, local_start
from .scheduling import LOCAL_DATETIME, bump_schedule, interval_is_open, local_instant, zone_for
from .security import CsrfIdentity, Database, same_origin_write, utcnow
from .timetable import daily_timetable

router = APIRouter(prefix="/api/v1", tags=["availability"])


class ScheduleVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    facility_version: Annotated[int, Field(strict=True, ge=1)]


class ClosureInput(ScheduleVersion):
    starts_local: Annotated[str, Field(pattern=LOCAL_DATETIME)]
    ends_local: Annotated[str, Field(pattern=LOCAL_DATETIME)]
    reason: Annotated[str, Field(min_length=1, max_length=500)]

    @field_validator("reason", mode="before")
    @classmethod
    def trim_reason(cls, value):
        return value.strip() if isinstance(value, str) else value


class AvailableSlot(PriceBreakdown):
    starts_at: datetime
    ends_at: datetime


def availability_for(session, facility, day, duration):
    zone = zone_for(facility)
    now = utcnow().replace(tzinfo=UTC)
    today = now.astimezone(zone).date()
    day = day or today
    prices = {row.minutes: row.amount for row in facility.tariffs}
    if duration is not None and duration not in prices:
        raise HTTPException(422, "No base price is set for this duration.")
    duration = duration if duration is not None else min(prices, default=None)
    result = {
        "facility_id": facility.id,
        "facility_name": facility.name,
        "complex_id": facility.complex_id,
        "complex_name": facility.complex.name,
        "sport": facility.sport.name,
        "timezone": zone.key,
        "currency": facility.complex.currency,
        "facility_version": facility.version,
        "published": facility.active,
        "day": day,
        "today": today,
        "minutes": duration,
        "priced_durations": sorted(prices),
        "slot_step_minutes": 30,
        "booking_enabled": bool(facility.active and prices and facility.opening_hours),
        "status": "unavailable",
        "opening_weekdays": sorted({row.weekday for row in facility.opening_hours}),
        "unavailable_reason": None,
        "slots": [],
    }
    if day < today:
        return {**result, "status": "past"}
    if not prices or not facility.opening_hours:
        return {**result, "status": "unconfigured"}
    candidates = []
    try:
        for minute in range(0, 1440, 30):
            try:
                start = local_start(day, f"{minute // 60:02}:{minute % 60:02}", zone.key)
            except HTTPException as error:
                if error.status_code == 422:
                    continue  # Missing/ambiguous local starts are never silently selected.
                raise
            utc = start.astimezone(UTC)
            end = utc + timedelta(minutes=duration)
            if utc > now and interval_is_open(start, duration, facility.opening_hours):
                candidates.append((start, utc.replace(tzinfo=None), end.replace(tzinfo=None)))
    except (OverflowError, ValueError):
        raise HTTPException(422, "Choose another date.") from None
    if not candidates:
        reason = (
            "closed" if day.weekday() not in result["opening_weekdays"] else "no_suitable_start"
        )
        return {**result, "unavailable_reason": reason}
    closures = session.scalars(
        select(FacilityClosure).where(
            FacilityClosure.facility_id == facility.id,
            FacilityClosure.active.is_(True),
            FacilityClosure.starts_at < max(end for _, _, end in candidates),
            FacilityClosure.ends_at > min(start for _, start, _ in candidates),
        )
    ).all()
    slots = []
    reservations = session.scalars(
        select(Reservation).where(
            Reservation.facility_id == facility.id,
            Reservation.status.in_(["pending", "confirmed"]),
            Reservation.starts_at < max(end for _, _, end in candidates),
            Reservation.ends_at > min(start for _, start, _ in candidates),
        )
    ).all()
    for local, start, end in candidates:
        if any(row.starts_at < end and row.ends_at > start for row in [*closures, *reservations]):
            continue
        price = calculate_price(
            prices[duration], local, duration, facility.weekend_percent, facility.evening_percent
        )
        slots.append(
            AvailableSlot(
                **price.model_dump(),
                starts_at=local,
                ends_at=end.replace(tzinfo=UTC).astimezone(zone),
            )
        )
    return {
        **result,
        "slots": slots,
        "status": "available" if slots else "unavailable",
        "unavailable_reason": None if slots else "occupied_or_closed",
    }


def schedule_search(session, facility, day, duration, find_next):
    result = availability_for(session, facility, day, duration)
    if not find_next or result["status"] in {"available", "unconfigured", "past"}:
        return result
    first = result["day"]
    for offset in range(1, 29):
        try:
            candidate = first + timedelta(days=offset)
        except OverflowError:
            break
        if candidate.weekday() not in result["opening_weekdays"]:
            continue
        following = availability_for(session, facility, candidate, duration)
        if following["status"] == "available":
            return {**following, "searched_from": first}
    return {**result, "searched_from": first, "search_exhausted": True}


@router.get("/complexes/{complex_id}/facilities/{facility_id}/availability")
def public_availability(
    complex_id: UUID,
    facility_id: UUID,
    session: Database,
    day: date | None = None,
    minutes: DurationQuery | None = None,
    find_next: bool = False,
):
    facility = session.scalar(
        select(Facility)
        .join(Complex)
        .where(
            Facility.id == facility_id,
            Facility.complex_id == complex_id,
            Facility.active.is_(True),
            Complex.active.is_(True),
        )
    )
    if facility is None:
        raise HTTPException(404, "Facility not found.")
    result = schedule_search(session, facility, day, minutes, find_next)
    return {**result, "timeline": daily_timetable(session, facility, result["day"], utcnow())}


@router.get("/staff/complexes/{complex_id}/facilities/{facility_id}/availability")
def admin_availability(
    facility_id: UUID,
    assignment: ComplexAssignment,
    session: Database,
    day: date | None = None,
    minutes: DurationQuery | None = None,
    find_next: bool = False,
):
    facility = owned_facility(session, assignment, facility_id)
    if not facility.active and assignment.role != "admin":
        raise HTTPException(403, "Only the administrator can preview unpublished facilities.")
    result = schedule_search(session, facility, day, minutes, find_next)
    return {
        **result,
        "timeline": daily_timetable(session, facility, result["day"], utcnow(), staff=True),
    }


def closure_read(row, zone):
    return {
        "id": row.id,
        "starts_at": row.starts_at.replace(tzinfo=UTC).astimezone(zone),
        "ends_at": row.ends_at.replace(tzinfo=UTC).astimezone(zone),
        "reason": row.reason,
    }


@router.get("/staff/complexes/{complex_id}/facilities/{facility_id}/closures")
def list_closures(
    facility_id: UUID,
    assignment: ComplexAdmin,
    session: Database,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    facility = owned_facility(session, assignment, facility_id)
    zone = zone_for(facility)
    conditions = (
        FacilityClosure.facility_id == facility.id,
        FacilityClosure.active.is_(True),
        FacilityClosure.ends_at > utcnow(),
    )
    total = session.scalar(select(func.count()).select_from(FacilityClosure).where(*conditions))
    rows = session.scalars(
        select(FacilityClosure)
        .where(*conditions)
        .order_by(FacilityClosure.starts_at, FacilityClosure.id)
        .offset(offset)
        .limit(limit)
    ).all()
    return {
        "facility_id": facility.id,
        "facility_name": facility.name,
        "complex_name": facility.complex.name,
        "timezone": zone.key,
        "facility_version": facility.version,
        "today": utcnow().replace(tzinfo=UTC).astimezone(zone).date(),
        "items": [closure_read(row, zone) for row in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.post(
    "/staff/complexes/{complex_id}/facilities/{facility_id}/closures",
    status_code=201,
    dependencies=[Depends(same_origin_write)],
)
def create_closure(
    facility_id: UUID,
    data: ClosureInput,
    assignment: ComplexAdmin,
    identity: CsrfIdentity,
    session: Database,
):
    facility = owned_facility(session, assignment, facility_id, lock=True)
    start = local_instant(data.starts_local, facility.complex.timezone)
    end = local_instant(data.ends_local, facility.complex.timezone)
    if start >= end or end <= utcnow():
        raise HTTPException(422, "The end must follow the start and be in the future.")
    overlap = session.scalar(
        select(FacilityClosure.id)
        .where(
            FacilityClosure.facility_id == facility.id,
            FacilityClosure.active.is_(True),
            FacilityClosure.starts_at < end,
            FacilityClosure.ends_at > start,
        )
        .limit(1)
        .with_for_update()  # Use MySQL's current read, even after an earlier auth snapshot.
    )
    if overlap:
        raise HTTPException(409, "This closure overlaps another active closure.")
    booked = session.scalar(
        select(Reservation.id)
        .where(
            Reservation.facility_id == facility.id,
            Reservation.status.in_(["pending", "confirmed"]),
            Reservation.starts_at < end,
            Reservation.ends_at > start,
        )
        .limit(1)
        .with_for_update()
    )
    if booked:
        raise HTTPException(
            409, "A pending or confirmed booking overlaps this closure. Resolve it first."
        )
    bump_schedule(session, facility, data.facility_version)
    row = FacilityClosure(
        facility_id=facility.id,
        starts_at=start,
        ends_at=end,
        reason=data.reason,
        created_by=identity.user.id,
        created_at=utcnow(),
    )
    session.add(row)
    session.commit()
    return {
        "closure": closure_read(row, zone_for(facility)),
        "facility_version": data.facility_version + 1,
    }


@router.post(
    "/staff/complexes/{complex_id}/facilities/{facility_id}/closures/{closure_id}/cancel",
    status_code=204,
    dependencies=[Depends(same_origin_write)],
)
def cancel_closure(
    facility_id: UUID,
    closure_id: UUID,
    data: ScheduleVersion,
    assignment: ComplexAdmin,
    identity: CsrfIdentity,
    session: Database,
):
    facility = owned_facility(session, assignment, facility_id, lock=True)
    row = session.scalar(
        select(FacilityClosure)
        .where(FacilityClosure.id == closure_id, FacilityClosure.facility_id == facility.id)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(404, "Closure not found in this facility.")
    if not row.active:
        raise HTTPException(409, "This closure was already cancelled. Reload the saved closures.")
    bump_schedule(session, facility, data.facility_version)
    row.active = False
    row.cancelled_by = identity.user.id
    row.cancelled_at = utcnow()
    session.commit()
