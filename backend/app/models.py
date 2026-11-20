from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
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
