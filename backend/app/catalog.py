from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, selectinload

from .database import get_session
from .models import Complex, Facility, Sport
from .schemas import (
    ComplexDetail,
    ComplexPage,
    ComplexSummary,
    FacilityRead,
    OpeningRead,
    SportRead,
    TariffRead,
)

router = APIRouter(prefix="/api/v1", tags=["catalogue"])
Database = Annotated[Session, Depends(get_session)]


def public_facilities(complex_: Complex) -> list[Facility]:
    return sorted(
        (facility for facility in complex_.facilities if facility.active), key=lambda f: f.name
    )


def clock_time(value: int) -> str:
    return f"{value // 60:02}:{value % 60:02}"


def facility_read(facility: Facility) -> FacilityRead:
    return FacilityRead(
        id=facility.id,
        name=facility.name,
        surface=facility.surface,
        description=facility.description,
        sport=SportRead.model_validate(facility.sport),
        weekend_percent=facility.weekend_percent,
        evening_percent=facility.evening_percent,
        opening_hours=[
            OpeningRead(
                weekday=row.weekday,
                opens_at=clock_time(row.start_minute),
                closes_at=clock_time(row.end_minute),
            )
            for row in sorted(
                facility.opening_hours, key=lambda row: (row.weekday, row.start_minute)
            )
        ],
        tariffs=[
            TariffRead(minutes=row.minutes, amount=row.amount)
            for row in sorted(facility.tariffs, key=lambda row: row.minutes)
        ],
    )


def summary(complex_: Complex) -> ComplexSummary:
    facilities = public_facilities(complex_)
    sports = {facility.sport.slug: facility.sport for facility in facilities}
    return ComplexSummary(
        id=complex_.id,
        name=complex_.name,
        city=complex_.city,
        address=complex_.address,
        timezone=complex_.timezone,
        description=complex_.description,
        is_demo=complex_.is_demo,
        currency=complex_.currency,
        sports=[SportRead.model_validate(sports[key]) for key in sorted(sports)],
        facility_count=len(facilities),
    )


@router.get("/sports", response_model=list[SportRead])
def list_sports(session: Database):
    return session.scalars(
        select(Sport).options(selectinload(Sport.durations)).order_by(Sport.name)
    ).all()


@router.get("/cities", response_model=list[str])
def list_cities(session: Database):
    return session.scalars(
        select(Complex.city).where(Complex.active.is_(True)).distinct().order_by(Complex.city)
    ).all()


@router.get("/complexes", response_model=ComplexPage)
def list_complexes(
    session: Database,
    sport: Annotated[str | None, Query(max_length=40, pattern=r"^[a-z0-9-]+$")] = None,
    city: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    conditions = [Complex.active.is_(True)]
    if city and city.strip():
        conditions.append(func.lower(Complex.city) == city.strip().lower())
    if sport:
        conditions.append(
            Complex.facilities.any(
                and_(Facility.active.is_(True), Facility.sport.has(Sport.slug == sport))
            )
        )
    total = session.scalar(select(func.count()).select_from(Complex).where(*conditions))
    items = session.scalars(
        select(Complex)
        .where(*conditions)
        .options(
            selectinload(Complex.facilities)
            .selectinload(Facility.sport)
            .selectinload(Sport.durations)
        )
        .order_by(Complex.name, Complex.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return ComplexPage(items=[summary(item) for item in items], total=total or 0)


@router.get("/complexes/{complex_id}", response_model=ComplexDetail)
def get_complex(complex_id: UUID, session: Database):
    complex_ = session.scalar(
        select(Complex)
        .where(Complex.id == complex_id, Complex.active.is_(True))
        .options(
            selectinload(Complex.facilities)
            .selectinload(Facility.sport)
            .selectinload(Sport.durations),
            selectinload(Complex.facilities).selectinload(Facility.opening_hours),
            selectinload(Complex.facilities).selectinload(Facility.tariffs),
        )
    )
    if complex_ is None:
        raise HTTPException(status_code=404, detail="Complex not found")
    return ComplexDetail(
        **summary(complex_).model_dump(),
        facilities=[facility_read(facility) for facility in public_facilities(complex_)],
    )
