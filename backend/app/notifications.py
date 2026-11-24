"""General staff Inbox and private customer booking updates."""

from datetime import UTC
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError

from .auth import ComplexAssignment, complex_assignment
from .booking_state import history_status
from .models import (
    ClientNotification,
    Complex,
    StaffAssignment,
    StaffNotification,
    StaffNotificationRead,
)
from .pricing import business_zone
from .security import CsrfIdentity, Database, PassiveIdentity, same_origin_write, utcnow

router = APIRouter(prefix="/api/v1", tags=["staff notifications"])
LEGACY_REQUEST_KINDS = ("booking_requested", "booking_confirmed", "time_requested")


def passive_assignment(complex_id: UUID, identity: PassiveIdentity, session: Database):
    return complex_assignment(complex_id, identity, session)


NotificationAssignment = Annotated[StaffAssignment, Depends(passive_assignment)]


def notify_client(session, reservation, kind):
    if reservation.client_id is not None:
        session.add(
            ClientNotification(
                client_id=reservation.client_id,
                reservation_id=reservation.id,
                kind=kind,
                created_at=utcnow(),
            )
        )


def seen_by(user_id):
    return exists(
        select(StaffNotificationRead.notification_id).where(
            StaffNotificationRead.notification_id == StaffNotification.id,
            StaffNotificationRead.user_id == user_id,
        )
    )


@router.get("/staff/notifications/summary")
def notification_summary(identity: PassiveIdentity, session: Database):
    assigned = session.scalars(
        select(StaffAssignment.complex_id)
        .join(Complex)
        .where(
            StaffAssignment.user_id == identity.user.id,
            StaffAssignment.active.is_(True),
            Complex.active.is_(True),
        )
    ).all()
    if not assigned:
        raise HTTPException(403, "Staff access has not been assigned to this account.")
    counts = dict(
        session.execute(
            select(StaffNotification.complex_id, func.count())
            .where(
                StaffNotification.complex_id.in_(assigned),
                StaffNotification.kind.not_in(LEGACY_REQUEST_KINDS),
                ~seen_by(identity.user.id),
            )
            .group_by(StaffNotification.complex_id)
        ).all()
    )
    return {
        "total": sum(counts.values()),
        "complexes": [
            {
                "complex_id": complex_id,
                "unread": counts.get(complex_id, 0),
            }
            for complex_id in assigned
        ],
    }


@router.get("/staff/complexes/{complex_id}/notifications")
def list_notifications(
    assignment: NotificationAssignment,
    identity: PassiveIdentity,
    session: Database,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return staff_notice_page(session, assignment, identity, offset, limit)


def staff_notice_page(session, assignment, identity, offset, limit):
    where = (StaffNotification.complex_id == assignment.complex_id) & (
        StaffNotification.kind.not_in(LEGACY_REQUEST_KINDS)
    )
    total = session.scalar(select(func.count()).select_from(StaffNotification).where(where))
    unread = session.scalar(
        select(func.count()).select_from(StaffNotification).where(where, ~seen_by(identity.user.id))
    )
    rows = session.execute(
        select(StaffNotification, seen_by(identity.user.id))
        .where(where)
        .order_by(StaffNotification.created_at.desc(), StaffNotification.id)
        .offset(offset)
        .limit(limit)
    ).all()
    try:
        zone = business_zone(assignment.complex.timezone)
    except (ValueError, OSError, ModuleNotFoundError):
        raise HTTPException(503, "The complex's local time is unavailable.") from None
    items = []
    for notice, read in rows:
        booking = notice.reservation
        items.append(
            {
                "id": notice.id,
                "kind": notice.kind,
                "read": read,
                "facility_id": notice.facility_id,
                "facility_name": notice.facility.name,
                "client_name": booking.client_name if booking else notice.client.name,
                "client_phone": booking.client_phone if booking else notice.client.phone,
                "client_email": notice.client.email if notice.client else None,
                "day": notice.requested_day,
                "minutes": notice.minutes,
                "preferred_time": notice.preferred_time,
                "created_at": notice.created_at.replace(tzinfo=UTC).astimezone(zone),
                "reference": booking.reference if booking else None,
                "booking_status": history_status(booking) if booking else None,
                "approval_status": booking.approval_status if booking else None,
                "starts_at": booking.starts_at.replace(tzinfo=UTC).astimezone(zone)
                if booking
                else None,
                "ends_at": booking.ends_at.replace(tzinfo=UTC).astimezone(zone)
                if booking
                else None,
                "total_amount": str(booking.total_amount) if booking else None,
                "currency": booking.currency if booking else assignment.complex.currency,
            }
        )
    return {
        "items": items,
        "total": total,
        "unread": unread,
        "offset": offset,
        "limit": limit,
        "complex_name": assignment.complex.name,
        "timezone": assignment.complex.timezone,
    }


@router.get("/notifications")
def client_notifications(
    identity: PassiveIdentity,
    session: Database,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    unread_only: bool = False,
):
    where = ClientNotification.client_id == identity.user.id
    if unread_only:
        where = where & ClientNotification.read_at.is_(None)
    total = session.scalar(select(func.count()).select_from(ClientNotification).where(where))
    unread = session.scalar(
        select(func.count())
        .select_from(ClientNotification)
        .where(where, ClientNotification.read_at.is_(None))
    )
    rows = session.scalars(
        select(ClientNotification)
        .where(where)
        .order_by(ClientNotification.created_at.desc(), ClientNotification.id)
        .offset(offset)
        .limit(limit)
    ).all()
    items = []
    for notice in rows:
        booking = notice.reservation
        try:
            zone = business_zone(booking.timezone)
        except (ValueError, OSError, ModuleNotFoundError):
            raise HTTPException(503, "Booking local time is unavailable.") from None
        items.append(
            {
                "id": notice.id,
                "reservation_id": booking.id,
                "kind": notice.kind,
                "read": notice.read_at is not None,
                "reference": booking.reference,
                "facility_name": booking.facility.name,
                "complex_name": booking.facility.complex.name,
                "starts_at": booking.starts_at.replace(tzinfo=UTC).astimezone(zone),
                "ends_at": booking.ends_at.replace(tzinfo=UTC).astimezone(zone),
                "created_at": notice.created_at.replace(tzinfo=UTC).astimezone(zone),
                "approval_status": booking.approval_status,
                "status": history_status(booking),
            }
        )
    return {"items": items, "total": total, "unread": unread, "offset": offset, "limit": limit}


@router.post(
    "/notifications/{notification_id}/read",
    status_code=204,
    dependencies=[Depends(same_origin_write)],
)
def read_client_notification(notification_id: UUID, identity: CsrfIdentity, session: Database):
    notice = session.scalar(
        select(ClientNotification)
        .where(
            ClientNotification.id == notification_id,
            ClientNotification.client_id == identity.user.id,
        )
        .with_for_update()
    )
    if notice is None:
        raise HTTPException(404, "Update not found.")
    if notice.read_at is None:
        notice.read_at = utcnow()
        session.commit()
    return Response(status_code=204)


@router.post(
    "/staff/complexes/{complex_id}/notifications/{notification_id}/read",
    status_code=204,
    dependencies=[Depends(same_origin_write)],
)
def mark_read(
    notification_id: UUID, assignment: ComplexAssignment, identity: CsrfIdentity, session: Database
):
    return read_staff_notice(notification_id, assignment, identity, session)


def read_staff_notice(notification_id, assignment, identity, session):
    notice = session.scalar(
        select(StaffNotification.id).where(
            StaffNotification.id == notification_id,
            StaffNotification.complex_id == assignment.complex_id,
            StaffNotification.kind.not_in(LEGACY_REQUEST_KINDS),
        )
    )
    if notice is None:
        raise HTTPException(404, "Notification not found in this complex.")
    key = (notification_id, identity.user.id)
    if session.get(StaffNotificationRead, key) is None:
        session.add(
            StaffNotificationRead(
                notification_id=notification_id, user_id=identity.user.id, read_at=utcnow()
            )
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            if session.get(StaffNotificationRead, key) is None:
                raise HTTPException(503, "The read status could not be saved.") from None
    return Response(status_code=204)
