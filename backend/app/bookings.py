"""Atomic online/staff bookings with saved prices and actor-scoped retries."""

import secrets
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError

from .auth import ComplexAssignment
from .booking_state import history_status
from .contact import name_key, normalize_phone
from .models import Facility, FacilityClosure, FacilityTariff, OpeningHour, Reservation, User
from .notifications import notify_client
from .pricing import business_zone, calculate_price
from .scheduling import LOCAL_DATETIME, bump_schedule, interval_is_open, local_instant, zone_for
from .security import (
    CsrfIdentity,
    Database,
    PassiveIdentity,
    same_origin_write,
    utcnow,
)

router = APIRouter(prefix="/api/v1", tags=["reservations"])


class BookingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    facility_version: Annotated[int, Field(strict=True, ge=1)]
    starts_local: Annotated[str, Field(pattern=LOCAL_DATETIME)]
    minutes: Literal[60, 90, 120]
    phone: str | None = None
    _phone = field_validator("phone", mode="before")(normalize_phone)


class StaffBookingInput(BookingInput):
    client_name: Annotated[str, Field(min_length=1, max_length=100)]
    client_phone: str
    _client_phone = field_validator("client_phone", mode="before")(normalize_phone)

    @field_validator("client_name", mode="before")
    @classmethod
    def clean_name(cls, value):
        return " ".join(value.split()) if isinstance(value, str) else value


class CancelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Annotated[int, Field(strict=True, ge=1)]


class BookingRead(BaseModel):
    id: UUID
    reference: str
    facility_id: UUID
    facility_name: str
    complex_id: UUID
    complex_name: str
    client_id: UUID | None
    client_name: str
    client_phone: str | None
    client_email: str | None
    walk_in: bool
    source: Literal["online", "staff"]
    status: Literal["pending", "confirmed", "cancelled"]
    approval_status: Literal["awaiting", "accepted"]
    reservation_status: Literal["reserved", "cancelled"]
    arrived_at: datetime | None
    version: int
    starts_at: datetime
    ends_at: datetime
    minutes: int
    timezone: str
    currency: str
    base_amount: Decimal
    total_amount: Decimal
    applied_percent: Decimal
    weekend_applied: bool
    evening_applied: bool
    can_cancel: bool
    can_mark_arrived: bool
    can_accept: bool


def booking_read(row):
    try:
        zone = business_zone(row.timezone)
    except (ValueError, OSError, ModuleNotFoundError):
        raise HTTPException(503, "The booking's local time is unavailable.") from None
    return BookingRead(
        id=row.id,
        reference=row.reference,
        facility_id=row.facility_id,
        facility_name=row.facility.name,
        complex_id=row.facility.complex_id,
        complex_name=row.facility.complex.name,
        client_id=row.client_id,
        client_name=row.client_name,
        client_phone=row.client_phone,
        client_email=row.client.email if row.client else None,
        walk_in=row.client_id is None,
        source=row.source,
        status=history_status(row),
        approval_status=row.approval_status,
        reservation_status="cancelled" if row.status == "cancelled" else "reserved",
        arrived_at=row.arrived_at.replace(tzinfo=UTC).astimezone(zone) if row.arrived_at else None,
        version=row.version,
        starts_at=row.starts_at.replace(tzinfo=UTC).astimezone(zone),
        ends_at=row.ends_at.replace(tzinfo=UTC).astimezone(zone),
        minutes=row.minutes,
        timezone=row.timezone,
        currency=row.currency,
        base_amount=row.base_amount,
        total_amount=row.total_amount,
        applied_percent=row.applied_percent,
        weekend_applied=row.weekend_applied,
        evening_applied=row.evening_applied,
        can_cancel=row.status in {"pending", "confirmed"}
        and row.arrived_at is None
        and (row.approval_status == "awaiting" or row.starts_at - utcnow() >= timedelta(hours=2)),
        can_mark_arrived=row.status in {"pending", "confirmed"}
        and row.approval_status == "accepted"
        and row.arrived_at is None,
        can_accept=row.status in {"pending", "confirmed"}
        and row.approval_status == "awaiting"
        and row.starts_at > utcnow(),
    )


def claim(
    session,
    complex_id,
    facility_id,
    data,
    actor_id,
    client_id,
    source,
    response,
    *,
    client_name,
    client_phone,
):
    # Every schedule writer takes this same facility lock before checking current rows.
    facility = session.scalar(
        select(Facility)
        .where(
            Facility.id == facility_id,
            Facility.complex_id == complex_id,
        )
        .with_for_update()
    )
    if facility is None or not facility.active or not facility.complex.active:
        raise HTTPException(404, "This facility is not open for reservations.")
    start = local_instant(data.starts_local, facility.complex.timezone)
    if start.year < 1000:
        raise HTTPException(422, "Choose a future date.")
    try:
        end = start + timedelta(minutes=data.minutes)
    except OverflowError:
        raise HTTPException(422, "Choose another date.") from None
    # Claim the unique retry key inside the transaction. These placeholder prices
    # are never committed: all checks and final price calculation follow below.
    row = Reservation(
        id=uuid4(),
        reference="OM-" + secrets.token_hex(10).upper(),
        request_id=data.request_id,
        facility_id=facility.id,
        client_id=client_id,
        client_name=client_name,
        client_phone=client_phone,
        entered_by=actor_id,
        source=source,
        starts_at=start,
        ends_at=end,
        minutes=data.minutes,
        timezone=facility.complex.timezone,
        currency=facility.complex.currency,
        base_amount=Decimal("0.00"),
        total_amount=Decimal("0.00"),
        applied_percent=Decimal("0.00"),
        weekend_applied=False,
        evening_applied=False,
        quoted_version=data.facility_version,
        created_at=utcnow(),
        status="confirmed",
        approval_status="awaiting" if source == "online" else "accepted",
        version=1,
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        previous = session.scalar(
            select(Reservation).where(
                Reservation.entered_by == actor_id,
                Reservation.request_id == data.request_id,
            )
        )
        if previous is None:
            raise HTTPException(
                503, "The booking could not be confirmed. Please try again."
            ) from None
        if (
            previous.facility_id,
            previous.client_id,
            previous.starts_at,
            previous.minutes,
            previous.quoted_version,
            previous.source,
            previous.client_name,
            previous.client_phone,
        ) != (
            facility_id,
            client_id,
            start,
            data.minutes,
            data.facility_version,
            source,
            client_name,
            client_phone,
        ):
            raise HTTPException(
                409, "This booking request was already used for different details."
            ) from None
        response.status_code = 200
        return booking_read(previous)
    try:
        if start <= utcnow() or int(data.starts_local[-2:]) % 30:
            raise HTTPException(422, "Choose a future time starting on the hour or half-hour.")
        if facility.version != data.facility_version:
            raise HTTPException(
                409, "The schedule changed. Refresh available times before booking."
            )
        # Locking reads avoid an older authentication snapshot on MySQL.
        hours = session.scalars(
            select(OpeningHour).where(OpeningHour.facility_id == facility.id).with_for_update()
        ).all()
        tariff = session.scalar(
            select(FacilityTariff)
            .where(
                FacilityTariff.facility_id == facility.id,
                FacilityTariff.minutes == data.minutes,
            )
            .with_for_update()
        )
        local = start.replace(tzinfo=UTC).astimezone(zone_for(facility))
        if tariff is None or not interval_is_open(local, data.minutes, hours):
            raise HTTPException(
                409, "This time or duration is not available within the published hours and prices."
            )
        closed = session.scalar(
            select(FacilityClosure.id)
            .where(
                FacilityClosure.facility_id == facility.id,
                FacilityClosure.active.is_(True),
                FacilityClosure.starts_at < end,
                FacilityClosure.ends_at > start,
            )
            .limit(1)
            .with_for_update()
        )
        occupied = session.scalar(
            select(Reservation.id)
            .where(
                Reservation.facility_id == facility.id,
                Reservation.id != row.id,
                Reservation.status.in_(["pending", "confirmed"]),
                Reservation.starts_at < end,
                Reservation.ends_at > start,
            )
            .limit(1)
            .with_for_update()
        )
        if closed or occupied:
            raise HTTPException(
                409, "This time is no longer available. Please choose another time."
            )
        price = calculate_price(
            tariff.amount, local, data.minutes, facility.weekend_percent, facility.evening_percent
        )
        row.base_amount = price.base_amount
        row.total_amount = price.total_amount
        row.applied_percent = price.applied_percent
        row.weekend_applied = price.weekend_applied
        row.evening_applied = price.evening_applied
        bump_schedule(session, facility, data.facility_version)
        session.commit()
    except HTTPException:
        session.rollback()
        raise
    return booking_read(row)


@router.post(
    "/complexes/{complex_id}/facilities/{facility_id}/reservations",
    status_code=201,
    response_model=BookingRead,
    dependencies=[Depends(same_origin_write)],
)
def reserve_online(
    complex_id: UUID,
    facility_id: UUID,
    data: BookingInput,
    identity: CsrfIdentity,
    session: Database,
    response: Response,
):
    phone = data.phone or identity.user.phone
    if not phone:
        raise HTTPException(422, "Enter your phone number to confirm this reservation.")
    if data.phone:
        identity.user.phone = data.phone
    return claim(
        session,
        complex_id,
        facility_id,
        data,
        identity.user.id,
        identity.user.id,
        "online",
        response,
        client_name=identity.user.name,
        client_phone=phone,
    )


@router.post(
    "/staff/complexes/{complex_id}/facilities/{facility_id}/reservations",
    status_code=201,
    response_model=BookingRead,
    dependencies=[Depends(same_origin_write)],
)
def reserve_for_client(
    facility_id: UUID,
    data: StaffBookingInput,
    assignment: ComplexAssignment,
    identity: CsrfIdentity,
    session: Database,
    response: Response,
):
    clients = session.scalars(
        select(User).where(User.phone == data.client_phone, User.active.is_(True))
    ).all()
    matched = [client for client in clients if name_key(client.name) == name_key(data.client_name)]
    if len(matched) > 1:
        raise HTTPException(
            409,
            "More than one account matches these contact details. Ask the customer to book from their account.",
        )
    client = matched[0] if matched else None
    return claim(
        session,
        assignment.complex_id,
        facility_id,
        data,
        identity.user.id,
        client.id if client else None,
        "staff",
        response,
        client_name=client.name if client else data.client_name,
        client_phone=data.client_phone,
    )


def booking_page(session, conditions, offset, limit, day=None, timezone=None):
    if day is not None:
        # A broad UTC window plus exact local-date filtering handles midnight clock changes.
        try:
            begin = datetime.combine(day, datetime.min.time()) - timedelta(days=1)
            finish = begin + timedelta(days=3)
        except OverflowError:
            raise HTTPException(422, "Choose another date.") from None
        conditions += [Reservation.ends_at > begin, Reservation.starts_at < finish]
        rows = session.scalars(
            select(Reservation)
            .join(Facility)
            .where(*conditions)
            .order_by(Reservation.starts_at, Reservation.id)
        ).all()
        try:
            zone = business_zone(timezone)
        except (OSError, ValueError, ModuleNotFoundError):
            raise HTTPException(503, "The complex's local time is unavailable.") from None
        rows = [
            row
            for row in rows
            if any(
                (row.starts_at.replace(tzinfo=UTC) + timedelta(minutes=i)).astimezone(zone).date()
                == day
                for i in range(row.minutes)
            )
        ]
        return {
            "items": [booking_read(row) for row in rows[offset : offset + limit]],
            "total": len(rows),
            "offset": offset,
            "limit": limit,
        }
    total = session.scalar(
        select(func.count()).select_from(Reservation).join(Facility).where(*conditions)
    )
    rows = session.scalars(
        select(Reservation)
        .join(Facility)
        .where(*conditions)
        .order_by(Reservation.starts_at.desc(), Reservation.id)
        .offset(offset)
        .limit(limit)
    ).all()
    return {
        "items": [booking_read(row) for row in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


def history_condition(status):
    if status == "cancelled":
        return Reservation.status == "cancelled"
    return and_(
        Reservation.status.in_(["pending", "confirmed"]),
        Reservation.arrived_at.is_(None)
        if status == "pending"
        else Reservation.arrived_at.is_not(None),
    )


@router.get("/reservations")
def my_bookings(
    identity: PassiveIdentity,
    session: Database,
    status: Literal["pending", "confirmed", "cancelled"] | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    conditions = [Reservation.client_id == identity.user.id]
    if status is not None:
        conditions.append(history_condition(status))
    return booking_page(session, conditions, offset, limit)


@router.get("/staff/complexes/{complex_id}/reservations")
def staff_bookings(
    assignment: ComplexAssignment,
    session: Database,
    day: date | None = None,
    facility_id: UUID | None = None,
    status: Literal["pending", "confirmed", "cancelled"] | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    conditions = [Facility.complex_id == assignment.complex_id]
    if facility_id is not None:
        conditions.append(Reservation.facility_id == facility_id)
    if status is not None:
        conditions.append(history_condition(status))
    page = booking_page(session, conditions, offset, limit, day, assignment.complex.timezone)
    return {
        **page,
        "complex_name": assignment.complex.name,
        "timezone": assignment.complex.timezone,
    }


@router.post(
    "/reservations/{reservation_id}/cancel",
    response_model=BookingRead,
    dependencies=[Depends(same_origin_write)],
)
def cancel_booking(
    reservation_id: UUID, data: CancelInput, identity: CsrfIdentity, session: Database
):
    facility_id = session.scalar(
        select(Reservation.facility_id).where(
            Reservation.id == reservation_id,
            Reservation.client_id == identity.user.id,
        )
    )
    if facility_id is None:
        raise HTTPException(404, "Booking not found.")
    facility = session.scalar(select(Facility).where(Facility.id == facility_id).with_for_update())
    row = session.scalar(
        select(Reservation)
        .where(Reservation.id == reservation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row.status == "cancelled":
        return booking_read(row)
    if row.version != data.version:
        raise HTTPException(409, "This booking changed. Refresh My bookings.")
    if row.arrived_at is not None:
        raise HTTPException(409, "Arrival is already recorded. This booking cannot be cancelled.")
    if row.approval_status != "awaiting" and row.starts_at - utcnow() < timedelta(hours=2):
        raise HTTPException(409, "Cancellation is allowed only until 2 hours before the start.")
    row.status = "cancelled"
    row.cancelled_by = identity.user.id
    row.cancelled_at = utcnow()
    row.version += 1
    bump_schedule(session, facility, facility.version)
    session.commit()
    return booking_read(row)


@router.post(
    "/staff/complexes/{complex_id}/reservations/{reservation_id}/cancel",
    response_model=BookingRead,
    dependencies=[Depends(same_origin_write)],
)
def cancel_staff_booking(
    reservation_id: UUID,
    data: CancelInput,
    assignment: ComplexAssignment,
    identity: CsrfIdentity,
    session: Database,
):
    facility_id = session.scalar(
        select(Reservation.facility_id)
        .join(Facility)
        .where(
            Reservation.id == reservation_id,
            Facility.complex_id == assignment.complex_id,
        )
    )
    if facility_id is None:
        raise HTTPException(404, "Booking not found in this complex.")
    facility = session.scalar(select(Facility).where(Facility.id == facility_id).with_for_update())
    row = session.scalar(
        select(Reservation)
        .where(Reservation.id == reservation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row.status == "cancelled":
        return booking_read(row)
    if row.version != data.version:
        raise HTTPException(409, "This booking changed. Refresh the list.")
    if row.arrived_at is not None:
        raise HTTPException(409, "Arrival is already recorded. This booking cannot be cancelled.")
    if row.approval_status != "awaiting" and row.starts_at - utcnow() < timedelta(hours=2):
        raise HTTPException(409, "Cancellation is allowed only until 2 hours before the start.")
    row.status = "cancelled"
    row.cancelled_by = identity.user.id
    row.cancelled_at = utcnow()
    row.version += 1
    bump_schedule(session, facility, facility.version)
    notify_client(session, row, "cancelled")
    session.commit()
    return booking_read(row)


@router.post(
    "/staff/complexes/{complex_id}/reservations/{reservation_id}/arrive",
    response_model=BookingRead,
    dependencies=[Depends(same_origin_write)],
)
def mark_arrived(
    reservation_id: UUID,
    data: CancelInput,
    assignment: ComplexAssignment,
    identity: CsrfIdentity,
    session: Database,
):
    facility_id = session.scalar(
        select(Reservation.facility_id)
        .join(Facility)
        .where(
            Reservation.id == reservation_id,
            Facility.complex_id == assignment.complex_id,
        )
    )
    if facility_id is None:
        raise HTTPException(404, "Booking not found in this complex.")
    facility = session.scalar(select(Facility).where(Facility.id == facility_id).with_for_update())
    row = session.scalar(
        select(Reservation)
        .where(Reservation.id == reservation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row.status == "cancelled":
        raise HTTPException(409, "This reservation was cancelled. Arrival cannot be recorded.")
    if row.approval_status != "accepted":
        raise HTTPException(409, "Accept this request before recording arrival.")
    if row.arrived_at is not None:
        return booking_read(row)
    if row.version != data.version:
        raise HTTPException(409, "This booking changed. Refresh the booking history.")
    row.arrived_by = identity.user.id
    row.arrived_at = utcnow()
    row.version += 1
    bump_schedule(session, facility, facility.version)
    session.commit()
    return booking_read(row)


@router.post(
    "/staff/complexes/{complex_id}/reservations/{reservation_id}/accept",
    response_model=BookingRead,
    dependencies=[Depends(same_origin_write)],
)
def accept_booking(
    reservation_id: UUID,
    data: CancelInput,
    assignment: ComplexAssignment,
    identity: CsrfIdentity,
    session: Database,
):
    facility_id = session.scalar(
        select(Reservation.facility_id)
        .join(Facility)
        .where(Reservation.id == reservation_id, Facility.complex_id == assignment.complex_id)
    )
    if facility_id is None:
        raise HTTPException(404, "Booking not found in this complex.")
    facility = session.scalar(select(Facility).where(Facility.id == facility_id).with_for_update())
    row = session.scalar(
        select(Reservation)
        .where(Reservation.id == reservation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row.status == "cancelled":
        raise HTTPException(409, "This request was cancelled.")
    if row.approval_status == "accepted":
        return booking_read(row)
    if row.version != data.version:
        raise HTTPException(409, "This request changed. Refresh booking history.")
    if row.starts_at <= utcnow():
        raise HTTPException(409, "This time has started. Cancel the request instead.")
    row.approval_status = "accepted"
    row.status = "confirmed"
    row.approved_by = identity.user.id
    row.approved_at = utcnow()
    row.version += 1
    bump_schedule(session, facility, facility.version)
    notify_client(session, row, "accepted")
    session.commit()
    return booking_read(row)
