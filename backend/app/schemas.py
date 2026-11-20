from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    slug: str
    name: str


class FacilityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    surface: str
    description: str
    sport: SportRead


class ComplexSummary(BaseModel):
    id: UUID
    name: str
    city: str
    address: str
    timezone: str
    description: str
    is_demo: bool
    sports: list[SportRead]
    facility_count: int


class ComplexDetail(ComplexSummary):
    facilities: list[FacilityRead]


class ComplexPage(BaseModel):
    items: list[ComplexSummary]
    total: int
