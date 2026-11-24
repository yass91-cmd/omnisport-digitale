"""Complete facility settings are validated and replaced in one transaction."""

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from .auth import ComplexAdmin
from .models import Facility, FacilityTariff, OpeningHour, Sport, SportDuration
from .scheduling import protect_confirmed_bookings
from .security import CsrfIdentity, Database, same_origin_write, utcnow

router = APIRouter(
    prefix="/api/v1/staff/complexes/{complex_id}/facilities",
    tags=["facility management"],
    dependencies=[Depends(same_origin_write)],
)
TIME = r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$"


def minutes(value: str, *, closing=False) -> int:
    total = int(value[:2]) * 60 + int(value[3:])
    return 1440 if closing and total == 0 else total


class OpeningInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    weekday: Annotated[int, Field(strict=True, ge=0, le=6)]
    opens_at: Annotated[str, Field(pattern=TIME)]
    closes_at: Annotated[str, Field(pattern=r"^(?:(?:[01][0-9]|2[0-3]):[0-5][0-9]|24:00)$")]

    @model_validator(mode="after")
    def valid_interval(self):
        if minutes(self.opens_at) >= minutes(self.closes_at, closing=True):
            raise ValueError(
                "Closing time must follow opening time; split overnight hours into two days."
            )
        return self


class TariffInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    minutes: Annotated[int, Field(strict=True, ge=1, le=1440)]
    amount: Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2, allow_inf_nan=False)]


class FacilityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, Field(min_length=1, max_length=120)]
    sport_id: UUID
    surface: Annotated[str, Field(min_length=1, max_length=100)]
    description: Annotated[str, Field(max_length=2000)] = ""
    active: StrictBool = True
    weekend_percent: Annotated[
        Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2, allow_inf_nan=False)
    ] = Decimal("10.00")
    evening_percent: Annotated[
        Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2, allow_inf_nan=False)
    ] = Decimal("10.00")
    opening_hours: Annotated[list[OpeningInput], Field(max_length=56)] = []
    tariffs: Annotated[list[TariffInput], Field(max_length=20)] = []

    @field_validator("name", "surface", "description", mode="before")
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def coherent_configuration(self):
        intervals = sorted(self.opening_hours, key=lambda row: (row.weekday, minutes(row.opens_at)))
        for previous, current in zip(intervals, intervals[1:]):
            if previous.weekday == current.weekday and minutes(current.opens_at) < minutes(
                previous.closes_at, closing=True
            ):
                raise ValueError("Opening intervals on the same day must not overlap.")
        if len({row.minutes for row in self.tariffs}) != len(self.tariffs):
            raise ValueError("Set only one price for each duration.")
        return self


class FacilityUpdate(FacilityInput):
    version: Annotated[int, Field(strict=True, ge=1)]


def configuration(facility: Facility, assignment: ComplexAdmin):
    from .catalog import facility_read

    return {
        **facility_read(facility).model_dump(mode="json"),
        "active": facility.active,
        "version": facility.version,
        "complex_id": facility.complex_id,
        "complex_name": assignment.complex.name,
        "timezone": assignment.complex.timezone,
        "currency": assignment.complex.currency,
    }


def owned_facility(session: Database, assignment: ComplexAdmin, facility_id: UUID, *, lock=False):
    statement = select(Facility).where(
        Facility.id == facility_id, Facility.complex_id == assignment.complex_id
    )
    if lock:
        statement = statement.with_for_update()
    facility = session.scalar(statement)
    if facility is None:
        raise HTTPException(404, "Facility not found in this complex.")
    return facility


def validate_sport(session: Database, data: FacilityInput):
    if session.get(Sport, data.sport_id) is None:
        raise HTTPException(422, "Choose an existing sport.")
    allowed = set(
        session.scalars(
            select(SportDuration.minutes).where(SportDuration.sport_id == data.sport_id)
        )
    )
    if any(row.minutes not in allowed for row in data.tariffs):
        raise HTTPException(422, "A priced duration is not allowed for the selected sport.")


def save_children(session: Database, facility: Facility, data: FacilityInput):
    session.add_all(
        [
            OpeningHour(
                facility_id=facility.id,
                weekday=row.weekday,
                start_minute=minutes(row.opens_at),
                end_minute=minutes(row.closes_at, closing=True),
            )
            for row in data.opening_hours
        ]
    )
    session.add_all(
        [
            FacilityTariff(
                facility_id=facility.id,
                sport_id=data.sport_id,
                minutes=row.minutes,
                amount=row.amount,
            )
            for row in data.tariffs
        ]
    )


def commit_settings(session: Database):
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            409, "The facility name is already used, or a setting changed. Reload and try again."
        ) from None


@router.get("/{facility_id}")
def get_settings(facility_id: UUID, assignment: ComplexAdmin, session: Database):
    return configuration(owned_facility(session, assignment, facility_id), assignment)


@router.post("", status_code=201)
def create_facility(
    data: FacilityInput, assignment: ComplexAdmin, identity: CsrfIdentity, session: Database
):
    validate_sport(session, data)
    facility = Facility(
        complex_id=assignment.complex_id, **data.model_dump(exclude={"opening_hours", "tariffs"})
    )
    session.add(facility)
    try:
        session.flush()
        save_children(session, facility, data)
        commit_settings(session)
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            409, "A facility with this name already exists in this complex."
        ) from None
    session.expire_all()
    return configuration(session.get(Facility, facility.id), assignment)


@router.put("/{facility_id}")
def update_facility(
    facility_id: UUID,
    data: FacilityUpdate,
    assignment: ComplexAdmin,
    identity: CsrfIdentity,
    session: Database,
):
    facility = owned_facility(session, assignment, facility_id, lock=True)
    if facility.version != data.version:
        raise HTTPException(409, "This facility changed since you opened it. Reload before saving.")
    validate_sport(session, data)
    try:
        protect_confirmed_bookings(session, facility, data, utcnow())
        session.execute(delete(FacilityTariff).where(FacilityTariff.facility_id == facility.id))
        session.execute(delete(OpeningHour).where(OpeningHour.facility_id == facility.id))
        values = data.model_dump(exclude={"opening_hours", "tariffs", "version"})
        result = session.execute(
            update(Facility)
            .where(Facility.id == facility.id, Facility.version == data.version)
            .values(**values, version=data.version + 1)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            session.rollback()
            raise HTTPException(409, "This facility changed. Reload before saving.")
        save_children(session, facility, data)
        commit_settings(session)
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            409, "The facility name is already used, or a setting changed. Reload and try again."
        ) from None
    session.expire_all()
    return configuration(session.get(Facility, facility_id), assignment)
