from uuid import UUID, uuid4

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint, Uuid, false, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Complex(Base):
    __tablename__ = "complexes"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(150))
    city: Mapped[str] = mapped_column(String(100), index=True)
    address: Mapped[str] = mapped_column(String(255))
    timezone: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    facilities: Mapped[list["Facility"]] = relationship(back_populates="complex")


class Sport(Base):
    __tablename__ = "sports"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    facilities: Mapped[list["Facility"]] = relationship(back_populates="sport")


class Facility(Base):
    __tablename__ = "facilities"
    __table_args__ = (UniqueConstraint("complex_id", "name", name="uq_facilities_complex_name"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    complex_id: Mapped[UUID] = mapped_column(ForeignKey("complexes.id"), index=True)
    sport_id: Mapped[UUID] = mapped_column(ForeignKey("sports.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    surface: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    complex: Mapped[Complex] = relationship(back_populates="facilities")
    sport: Mapped[Sport] = relationship(back_populates="facilities")
