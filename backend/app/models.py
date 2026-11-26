from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
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


class StaffNotification(Base):
    __tablename__ = "staff_notifications"
    __table_args__ = (
        UniqueConstraint("reservation_id", name="uq_staff_notifications_reservation"),
        UniqueConstraint("intent_key", name="uq_staff_notifications_intent"),
        CheckConstraint("minutes IN (60, 90, 120)", name="ck_staff_notifications_duration"),
        CheckConstraint(
            "(kind IN ('booking_confirmed', 'booking_requested') AND reservation_id IS NOT NULL AND intent_key IS NULL) OR "
            "(kind = 'time_requested' AND reservation_id IS NULL AND intent_key IS NOT NULL AND client_id IS NOT NULL)",
            name="ck_staff_notifications_kind",
        ),
        Index("ix_staff_notifications_complex", "complex_id", "created_at", "id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    complex_id: Mapped[UUID] = mapped_column(ForeignKey("complexes.id"))
    facility_id: Mapped[UUID] = mapped_column(ForeignKey("facilities.id"))
    client_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    reservation_id: Mapped[UUID | None] = mapped_column(ForeignKey("reservations.id"))
    intent_key: Mapped[str | None] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(24))
    requested_day: Mapped[date] = mapped_column(Date)
    preferred_time: Mapped[str | None] = mapped_column(String(5))
    minutes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    facility: Mapped["Facility"] = relationship()
    client: Mapped["User | None"] = relationship()
    reservation: Mapped["Reservation | None"] = relationship()


class StaffNotificationRead(Base):
    __tablename__ = "staff_notification_reads"
    notification_id: Mapped[UUID] = mapped_column(
        ForeignKey("staff_notifications.id"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    read_at: Mapped[datetime] = mapped_column(DateTime)


class ClientNotification(Base):
    __tablename__ = "client_notifications"
    __table_args__ = (
        UniqueConstraint("reservation_id", "kind", name="uq_client_notifications_event"),
        CheckConstraint(
            "kind IN ('accepted', 'cancelled', 'rescheduled')", name="ck_client_notifications_kind"
        ),
        Index("ix_client_notifications_owner", "client_id", "created_at", "id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    client_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    reservation_id: Mapped[UUID] = mapped_column(ForeignKey("reservations.id"))
    kind: Mapped[str] = mapped_column(String(12))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    read_at: Mapped[datetime | None] = mapped_column(DateTime)
    reservation: Mapped["Reservation"] = relationship()


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        CheckConstraint("schema_version >= 1", name="ck_outbox_events_schema_version"),
        Index("ix_outbox_events_pending", "published_at", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    event_type: Mapped[str] = mapped_column(String(80))
    schema_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    aggregate_id: Mapped[UUID] = mapped_column(Uuid)
    topic: Mapped[str] = mapped_column(String(249))
    message_key: Mapped[str] = mapped_column(String(100))
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)


class MaintenanceChange(Base):
    __tablename__ = "maintenance_changes"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    closure_id: Mapped[UUID] = mapped_column(ForeignKey("facility_closures.id"))
    reservation_id: Mapped[UUID] = mapped_column(ForeignKey("reservations.id"), index=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(12))
    old_start: Mapped[datetime] = mapped_column(DateTime)
    old_end: Mapped[datetime] = mapped_column(DateTime)
    new_start: Mapped[datetime | None] = mapped_column(DateTime)
    new_end: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime)


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


class FacilityClosure(Base):
    __tablename__ = "facility_closures"
    __table_args__ = (
        CheckConstraint("starts_at < ends_at", name="ck_facility_closures_interval"),
        CheckConstraint(
            "(active = 1 AND cancelled_at IS NULL AND cancelled_by IS NULL) OR "
            "(active = 0 AND cancelled_at IS NOT NULL AND cancelled_by IS NOT NULL)",
            name="ck_facility_closures_cancellation",
        ),
        Index("ix_facility_closures_schedule", "facility_id", "active", "ends_at", "starts_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    facility_id: Mapped[UUID] = mapped_column(ForeignKey("facilities.id"))
    starts_at: Mapped[datetime] = mapped_column(DateTime)
    ends_at: Mapped[datetime] = mapped_column(DateTime)
    reason: Mapped[str] = mapped_column(String(500))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    cancelled_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)


class Reservation(Base):
    __tablename__ = "reservations"
    __table_args__ = (
        UniqueConstraint("reference", name="uq_reservations_reference"),
        UniqueConstraint("entered_by", "request_id", name="uq_reservations_request"),
        CheckConstraint("starts_at < ends_at", name="ck_reservations_interval"),
        CheckConstraint("minutes IN (60, 90, 120)", name="ck_reservations_duration"),
        CheckConstraint("version >= 1 AND quoted_version >= 1", name="ck_reservations_versions"),
        CheckConstraint(
            "base_amount >= 0 AND total_amount >= base_amount", name="ck_reservations_price"
        ),
        CheckConstraint(
            "applied_percent >= 0 AND applied_percent <= 200", name="ck_reservations_percent"
        ),
        CheckConstraint(
            "status IN ('pending', 'confirmed', 'cancelled')", name="ck_reservations_status"
        ),
        CheckConstraint(
            "source = 'staff' OR (source = 'online' AND client_id IS NOT NULL AND client_id = entered_by)",
            name="ck_reservations_source",
        ),
        CheckConstraint(
            "(status IN ('pending', 'confirmed') AND cancelled_at IS NULL AND cancelled_by IS NULL) OR "
            "(status = 'cancelled' AND cancelled_at IS NOT NULL AND cancelled_by IS NOT NULL)",
            name="ck_reservations_cancellation",
        ),
        CheckConstraint(
            "(approved_at IS NULL AND approved_by IS NULL) OR "
            "(approved_at IS NOT NULL AND approved_by IS NOT NULL AND source = 'online' AND status IN ('confirmed', 'cancelled'))",
            name="ck_reservations_approval",
        ),
        CheckConstraint(
            "(arrived_at IS NULL AND arrived_by IS NULL) OR "
            "(arrived_at IS NOT NULL AND arrived_by IS NOT NULL)",
            name="ck_reservations_arrival",
        ),
        CheckConstraint(
            "approval_status IN ('awaiting', 'accepted')", name="ck_reservations_acceptance"
        ),
        CheckConstraint(
            "approval_status = 'accepted' OR (source = 'online' AND client_id IS NOT NULL AND arrived_at IS NULL)",
            name="ck_reservations_awaiting",
        ),
        Index("ix_reservations_schedule", "facility_id", "status", "ends_at", "starts_at"),
        Index("ix_reservations_client", "client_id", "starts_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    reference: Mapped[str] = mapped_column(String(24))
    request_id: Mapped[UUID] = mapped_column(Uuid)
    facility_id: Mapped[UUID] = mapped_column(ForeignKey("facilities.id"))
    client_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    client_name: Mapped[str] = mapped_column(String(100))
    client_phone: Mapped[str | None] = mapped_column(String(20))
    entered_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    source: Mapped[str] = mapped_column(String(12))
    starts_at: Mapped[datetime] = mapped_column(DateTime)
    ends_at: Mapped[datetime] = mapped_column(DateTime)
    minutes: Mapped[int] = mapped_column(Integer)
    timezone: Mapped[str] = mapped_column(String(80))
    currency: Mapped[str] = mapped_column(String(3))
    base_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    applied_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    weekend_applied: Mapped[bool] = mapped_column(Boolean)
    evening_applied: Mapped[bool] = mapped_column(Boolean)
    quoted_version: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    status: Mapped[str] = mapped_column(String(12), default="confirmed", server_default="confirmed")
    created_at: Mapped[datetime] = mapped_column(DateTime)
    cancelled_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)
    facility: Mapped[Facility] = relationship()
    approved_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    arrived_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime)
    approval_status: Mapped[str] = mapped_column(
        String(12), default="accepted", server_default="accepted"
    )
    client: Mapped["User | None"] = relationship(foreign_keys=[client_id])
    team_booking: Mapped["TeamBooking | None"] = relationship()


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("client_role IN ('player', 'coach')", name="ck_users_client_role"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(20), index=True)
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


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (
        UniqueConstraint("coach_id", "sport_id", "name", name="uq_teams_coach_sport_name"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    coach_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    sport_id: Mapped[UUID] = mapped_column(ForeignKey("sports.id"))
    name: Mapped[str] = mapped_column(String(100))
    open_to_requests: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    sport: Mapped[Sport] = relationship()
    coach: Mapped[User] = relationship()


class TeamMembership(Base):
    __tablename__ = "team_memberships"
    __table_args__ = (
        UniqueConstraint("player_id", "sport_id", "active_slot", name="uq_membership_active_sport"),
        CheckConstraint(
            "(active_slot IS NOT NULL AND active_slot = 1 AND ended_at IS NULL) OR (active_slot IS NULL AND ended_at IS NOT NULL)",
            name="ck_membership_state",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    team_id: Mapped[UUID] = mapped_column(ForeignKey("teams.id"), index=True)
    player_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    sport_id: Mapped[UUID] = mapped_column(ForeignKey("sports.id"))
    active_slot: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    team: Mapped[Team] = relationship()
    player: Mapped[User] = relationship()


class RosterIdentityLock(Base):
    __tablename__ = "roster_identity_locks"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)


class TeamContactMember(Base):
    __tablename__ = "team_contact_members"
    __table_args__ = (
        UniqueConstraint("identity_key", "sport_id", "active_slot", name="uq_contact_member_sport"),
        CheckConstraint(
            "(active_slot IS NOT NULL AND active_slot = 1 AND ended_at IS NULL) OR (active_slot IS NULL AND ended_at IS NOT NULL)",
            name="ck_contact_member_state",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    team_id: Mapped[UUID] = mapped_column(ForeignKey("teams.id"), index=True)
    sport_id: Mapped[UUID] = mapped_column(ForeignKey("sports.id"))
    identity_key: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(254))
    active_slot: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    team: Mapped[Team] = relationship()


class TeamBooking(Base):
    __tablename__ = "team_bookings"
    reservation_id: Mapped[UUID] = mapped_column(ForeignKey("reservations.id"), primary_key=True)
    team_id: Mapped[UUID] = mapped_column(ForeignKey("teams.id"), index=True)
    team_name: Mapped[str] = mapped_column(String(100))


class TeamRequest(Base):
    __tablename__ = "team_requests"
    __table_args__ = (
        UniqueConstraint("team_id", "player_id", "pending_slot", name="uq_team_request_pending"),
        CheckConstraint("kind IN ('join', 'invite')", name="ck_team_request_kind"),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'declined', 'withdrawn')",
            name="ck_team_request_status",
        ),
        CheckConstraint(
            "(status = 'pending' AND pending_slot IS NOT NULL AND pending_slot = 1 AND decided_at IS NULL) OR (status <> 'pending' AND pending_slot IS NULL AND decided_at IS NOT NULL)",
            name="ck_team_request_state",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    team_id: Mapped[UUID] = mapped_column(ForeignKey("teams.id"), index=True)
    player_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(12), default="pending")
    pending_slot: Mapped[int | None] = mapped_column(Integer, default=1)
    previous_membership_id: Mapped[UUID | None] = mapped_column(ForeignKey("team_memberships.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    team: Mapped[Team] = relationship()
    player: Mapped[User] = relationship()


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
