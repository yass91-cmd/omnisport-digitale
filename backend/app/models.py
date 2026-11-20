from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    false,
    true,
)
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
    currency: Mapped[str] = mapped_column(String(3), default="MAD", server_default="MAD")
    facilities: Mapped[list["Facility"]] = relationship(back_populates="complex")


class Sport(Base):
    __tablename__ = "sports"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    facilities: Mapped[list["Facility"]] = relationship(back_populates="sport")
    durations: Mapped[list["SportDuration"]] = relationship()

    @property
    def allowed_durations(self) -> list[int]:
        return sorted(rule.minutes for rule in self.durations)


class Facility(Base):
    __tablename__ = "facilities"
    __table_args__ = (
        UniqueConstraint("complex_id", "name", name="uq_facilities_complex_name"),
        UniqueConstraint("id", "sport_id", name="uq_facilities_id_sport"),
        CheckConstraint("version >= 1", name="ck_facilities_version"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    complex_id: Mapped[UUID] = mapped_column(ForeignKey("complexes.id"), index=True)
    sport_id: Mapped[UUID] = mapped_column(ForeignKey("sports.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    surface: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    weekend_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        CheckConstraint(
            "weekend_percent >= 0 AND weekend_percent <= 100", name="ck_facilities_weekend_percent"
        ),
        default=Decimal("10.00"),
        server_default="10.00",
    )
    evening_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        CheckConstraint(
            "evening_percent >= 0 AND evening_percent <= 100", name="ck_facilities_evening_percent"
        ),
        default=Decimal("10.00"),
        server_default="10.00",
    )
    complex: Mapped[Complex] = relationship(back_populates="facilities")
    sport: Mapped[Sport] = relationship(back_populates="facilities")
    opening_hours: Mapped[list["OpeningHour"]] = relationship(viewonly=True)
    tariffs: Mapped[list["FacilityTariff"]] = relationship(viewonly=True)


class SportDuration(Base):
    __tablename__ = "sport_durations"
    __table_args__ = (
        CheckConstraint("minutes > 0 AND minutes <= 1440", name="ck_sport_durations_minutes"),
    )

    sport_id: Mapped[UUID] = mapped_column(ForeignKey("sports.id"), primary_key=True)
    minutes: Mapped[int] = mapped_column(Integer, primary_key=True)


class OpeningHour(Base):
    __tablename__ = "opening_hours"
    __table_args__ = (
        UniqueConstraint("facility_id", "weekday", "start_minute", name="uq_opening_hours_start"),
        CheckConstraint("weekday >= 0 AND weekday <= 6", name="ck_opening_hours_weekday"),
        CheckConstraint(
            "start_minute >= 0 AND start_minute < end_minute AND end_minute <= 1440",
            name="ck_opening_hours_interval",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    facility_id: Mapped[UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    weekday: Mapped[int] = mapped_column(Integer)
    start_minute: Mapped[int] = mapped_column(Integer)
    end_minute: Mapped[int] = mapped_column(Integer)


class FacilityTariff(Base):
    __tablename__ = "facility_tariffs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["facility_id", "sport_id"],
            ["facilities.id", "facilities.sport_id"],
            name="fk_facility_tariffs_owner_sport",
        ),
        ForeignKeyConstraint(
            ["sport_id", "minutes"],
            ["sport_durations.sport_id", "sport_durations.minutes"],
            name="fk_facility_tariffs_allowed_duration",
        ),
        CheckConstraint("amount >= 0", name="ck_facility_tariffs_amount"),
    )

    facility_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    sport_id: Mapped[UUID] = mapped_column(Uuid)
    minutes: Mapped[int] = mapped_column(Integer, primary_key=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("client_role IN ('player', 'coach')", name="ck_users_client_role"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(255))
    client_role: Mapped[str] = mapped_column(String(16), default="player", server_default="player")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime)


class StaffAssignment(Base):
    __tablename__ = "staff_assignments"
    __table_args__ = (
        UniqueConstraint("user_id", "complex_id", name="uq_staff_assignments_user_complex"),
        CheckConstraint("role IN ('employee', 'admin')", name="ck_staff_assignments_role"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    complex_id: Mapped[UUID] = mapped_column(ForeignKey("complexes.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    complex: Mapped[Complex] = relationship()


class LoginSession(Base):
    __tablename__ = "login_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    user: Mapped[User] = relationship()


class AuthAttemptBucket(Base):
    __tablename__ = "auth_attempt_buckets"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
