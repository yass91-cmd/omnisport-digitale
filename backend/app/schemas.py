from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    slug: str
    name: str
    allowed_durations: list[int]


class OpeningRead(BaseModel):
    weekday: int
    opens_at: str
    closes_at: str


class TariffRead(BaseModel):
    minutes: int
    amount: Decimal


class FacilityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    surface: str
    description: str
    sport: SportRead
    opening_hours: list[OpeningRead]
    tariffs: list[TariffRead]
    weekend_percent: Decimal
    evening_percent: Decimal


class ComplexSummary(BaseModel):
    id: UUID
    name: str
    city: str
    address: str
    timezone: str
    description: str
    is_demo: bool
    currency: str
    sports: list[SportRead]
    facility_count: int


class ComplexDetail(ComplexSummary):
    facilities: list[FacilityRead]


class ComplexPage(BaseModel):
    items: list[ComplexSummary]
    total: int
