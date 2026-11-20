"""Server-authoritative price estimates in each complex's local time."""

from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from importlib.resources import files
from pathlib import PurePosixPath
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from .auth import ComplexAdmin
from .models import Complex, Facility, FacilityTariff
from .security import Database

router = APIRouter(prefix="/api/v1", tags=["price estimates"])
CENT = Decimal("0.01")
TimeQuery = Annotated[str, Query(pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")]
DurationQuery = Annotated[int, Query(ge=1, le=1440)]


class PriceBreakdown(BaseModel):
    base_amount: Decimal
    weekend_percent: Decimal
    evening_percent: Decimal
    weekend_applied: bool
    evening_applied: bool
    applied_percent: Decimal
    surcharge_amount: Decimal
    total_amount: Decimal


class PriceQuote(PriceBreakdown):
    facility_id: UUID
    facility_version: int
    currency: str
    timezone: str
    starts_at: datetime
    ends_at: datetime
    minutes: int
    availability_checked: bool = False


@lru_cache(maxsize=128)
def business_zone(timezone: str) -> ZoneInfo:
    path = PurePosixPath(timezone)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Invalid timezone")
    with files("tzdata.zoneinfo").joinpath(*path.parts).open("rb") as data:
        return ZoneInfo.from_file(data, key=timezone)


def local_start(day: date, clock: str, timezone: str) -> datetime:
    try:
        zone = business_zone(timezone)
    except (OSError, ValueError, ModuleNotFoundError):
        raise HTTPException(
            503, "The complex's local time is unavailable. Please try again later."
        ) from None
    naive = datetime.combine(day, datetime.strptime(clock, "%H:%M").time())
    candidates = {}
    try:
        for fold in [0, 1]:
            aware = naive.replace(tzinfo=zone, fold=fold)
            utc = aware.astimezone(UTC)
            if utc.astimezone(zone).replace(tzinfo=None) == naive:
                candidates[utc] = aware
    except (OverflowError, ValueError):
        raise HTTPException(422, "Choose another date and time.") from None
    if not candidates:
        raise HTTPException(
            422, "This local time does not exist because the clocks change. Choose another time."
        )
    if len(candidates) > 1:
        raise HTTPException(
            422, "This local time occurs twice because the clocks change. Choose another time."
        )
    return next(iter(candidates.values()))


def calculate_price(
    base: Decimal, start: datetime, duration: int, weekend: Decimal, evening: Decimal
) -> PriceBreakdown:
    if start.tzinfo is None or start.utcoffset() is None or start.second or start.microsecond:
        raise ValueError("An aware start time on a minute boundary is required")
    if (
        not 1 <= duration <= 1440
        or not Decimal("0") <= weekend <= Decimal("100")
        or not Decimal("0") <= evening <= Decimal("100")
    ):
        raise ValueError("Invalid pricing inputs")
    utc = start.astimezone(UTC)
    # Intervals are [start, end): touching 18:00 at the end or starting at
    # 21:00 does not overlap peak time. Walk actual minutes across clock changes.
    instants = [
        (utc + timedelta(minutes=index)).astimezone(start.tzinfo) for index in range(duration)
    ]
    on_weekend = any(instant.weekday() in {5, 6} for instant in instants)
    in_evening = any(
        18 * 60 <= instant.hour * 60 + instant.minute < 21 * 60 for instant in instants
    )
    percent = (weekend if on_weekend else Decimal("0")) + (evening if in_evening else Decimal("0"))
    total = (base * (Decimal("1") + percent / Decimal("100"))).quantize(
        CENT, rounding=ROUND_HALF_UP
    )
    return PriceBreakdown(
        base_amount=base.quantize(CENT),
        weekend_percent=weekend,
        evening_percent=evening,
        weekend_applied=on_weekend and weekend > 0,
        evening_applied=in_evening and evening > 0,
        applied_percent=percent,
        surcharge_amount=total - base,
        total_amount=total,
    )


def quote_for(
    session: Database, facility: Facility, day: date, clock: str, duration: int
) -> PriceQuote:
    amount = session.scalar(
        select(FacilityTariff.amount).where(
            FacilityTariff.facility_id == facility.id, FacilityTariff.minutes == duration
        )
    )
    if amount is None:
        raise HTTPException(422, "No base price is set for this duration.")
    start = local_start(day, clock, facility.complex.timezone)
    try:
        breakdown = calculate_price(
            amount, start, duration, facility.weekend_percent, facility.evening_percent
        )
        end = (start.astimezone(UTC) + timedelta(minutes=duration)).astimezone(start.tzinfo)
    except (OverflowError, ValueError):
        raise HTTPException(422, "Choose another date and time.") from None
    return PriceQuote(
        **breakdown.model_dump(),
        facility_id=facility.id,
        facility_version=facility.version,
        currency=facility.complex.currency,
        timezone=facility.complex.timezone,
        starts_at=start,
        ends_at=end,
        minutes=duration,
    )


@router.get("/complexes/{complex_id}/facilities/{facility_id}/quote", response_model=PriceQuote)
def public_quote(
    complex_id: UUID,
    facility_id: UUID,
    day: date,
    starts_at: TimeQuery,
    minutes: DurationQuery,
    session: Database,
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
    return quote_for(session, facility, day, starts_at, minutes)


@router.get(
    "/staff/complexes/{complex_id}/facilities/{facility_id}/quote", response_model=PriceQuote
)
def admin_quote(
    facility_id: UUID,
    day: date,
    starts_at: TimeQuery,
    minutes: DurationQuery,
    assignment: ComplexAdmin,
    session: Database,
):
    facility = session.scalar(
        select(Facility).where(
            Facility.id == facility_id, Facility.complex_id == assignment.complex_id
        )
    )
    if facility is None:
        raise HTTPException(404, "Facility not found in this complex.")
    return quote_for(session, facility, day, starts_at, minutes)
