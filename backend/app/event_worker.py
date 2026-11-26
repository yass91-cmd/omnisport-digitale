"""Publish the booking outbox and create staff notices from Kafka events."""

import json
import logging
import time
from datetime import UTC
from uuid import UUID

from kafka import KafkaConsumer, KafkaProducer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, sessionmaker

from .config import Settings
from .database import make_engine
from .models import Facility, OutboxEvent, Reservation, StaffNotification
from .pricing import business_zone
from .security import utcnow

logger = logging.getLogger(__name__)
EVENT_TYPE = "BookingRequested"
EVENT_SCHEMA_VERSION = 1
CONSUMER_GROUP = "omnisport-booking-notifications-v1"


class InvalidBookingEvent(ValueError):
    """An event cannot be handled and should be moved to the dead-letter topic."""


def publish_one(session_factory, producer):
    """Publish one row, then mark it only after Kafka acknowledges it."""
    with session_factory() as session:
        event = session.scalar(
            select(OutboxEvent)
            .where(OutboxEvent.published_at.is_(None))
            .order_by(OutboxEvent.created_at, OutboxEvent.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if event is None:
            return False
        producer.send(
            event.topic,
            key=event.message_key.encode("utf-8"),
            value=event.payload.encode("utf-8"),
        ).get(timeout=20)
        event.published_at = utcnow()
        session.commit()
        logger.info("Published %s event %s", event.event_type, event.id)
        return True


def booking_reservation_id(payload):
    try:
        if payload["event_type"] != EVENT_TYPE:
            raise InvalidBookingEvent("Unsupported event type")
        if payload["schema_version"] != EVENT_SCHEMA_VERSION:
            raise InvalidBookingEvent("Unsupported event schema version")
        if str(UUID(payload["event_id"])) != payload["event_id"]:
            raise InvalidBookingEvent("Invalid event identifier")
        if str(UUID(payload["aggregate_id"])) != payload["aggregate_id"]:
            raise InvalidBookingEvent("Invalid aggregate identifier")
        if payload["data"]["reservation_id"] != payload["aggregate_id"]:
            raise InvalidBookingEvent("Reservation and aggregate identifiers differ")
        return UUID(payload["data"]["reservation_id"])
    except InvalidBookingEvent:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise InvalidBookingEvent("Malformed booking event") from error


def create_staff_notice(session_factory, raw_value):
    try:
        payload = json.loads(raw_value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InvalidBookingEvent("Booking event is not valid UTF-8 JSON") from error
    reservation_id = booking_reservation_id(payload)

    with session_factory() as session:
        reservation = session.scalar(
            select(Reservation)
            .options(joinedload(Reservation.facility).joinedload(Facility.complex))
            .where(Reservation.id == reservation_id)
        )
        if reservation is None or reservation.source != "online":
            raise InvalidBookingEvent("Online reservation does not exist")
        existing = session.scalar(
            select(StaffNotification.id).where(StaffNotification.reservation_id == reservation.id)
        )
        if existing is not None:
            return False

        local_start = reservation.starts_at.replace(tzinfo=UTC).astimezone(
            business_zone(reservation.timezone)
        )
        session.add(
            StaffNotification(
                complex_id=reservation.facility.complex_id,
                facility_id=reservation.facility_id,
                client_id=reservation.client_id,
                reservation_id=reservation.id,
                kind="booking_requested",
                requested_day=local_start.date(),
                preferred_time=local_start.strftime("%H:%M"),
                minutes=reservation.minutes,
                created_at=utcnow(),
            )
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            if (
                session.scalar(
                    select(StaffNotification.id).where(
                        StaffNotification.reservation_id == reservation.id
                    )
                )
                is None
            ):
                raise
            return False
        logger.info("Created staff booking notice for %s", reservation.reference)
        return True


def dead_letter(producer, topic, record, error):
    headers = [
        ("source-topic", record.topic.encode("utf-8")),
        ("source-partition", str(record.partition).encode("ascii")),
        ("source-offset", str(record.offset).encode("ascii")),
        ("failure", str(error)[:500].encode("utf-8", errors="replace")),
    ]
    producer.send(topic, key=record.key, value=record.value, headers=headers).get(timeout=20)
    logger.error(
        "Moved invalid event from %s partition %s offset %s to %s",
        record.topic,
        record.partition,
        record.offset,
        topic,
    )


def run():
    settings = Settings()
    engine = make_engine(settings)
    session_factory = sessionmaker(engine, expire_on_commit=False)
    backoff_seconds = 1
    try:
        while True:
            producer = None
            consumer = None
            try:
                producer = KafkaProducer(
                    bootstrap_servers=settings.kafka_bootstrap_servers.split(","),
                    client_id="omnisport-booking-outbox",
                    enable_idempotence=True,
                    acks="all",
                    request_timeout_ms=10_000,
                    delivery_timeout_ms=30_000,
                )
                consumer = KafkaConsumer(
                    settings.kafka_booking_topic,
                    bootstrap_servers=settings.kafka_bootstrap_servers.split(","),
                    client_id="omnisport-staff-notifications",
                    group_id=CONSUMER_GROUP,
                    enable_auto_commit=False,
                    auto_offset_reset="earliest",
                    max_poll_records=1,
                )
                logger.info("Kafka booking event worker is ready")
                backoff_seconds = 1
                while True:
                    publish_one(session_factory, producer)
                    batches = consumer.poll(timeout_ms=1000, max_records=1)
                    for records in batches.values():
                        for record in records:
                            try:
                                create_staff_notice(session_factory, record.value)
                            except InvalidBookingEvent as error:
                                dead_letter(
                                    producer, settings.kafka_dead_letter_topic, record, error
                                )
                            consumer.commit()
            except KeyboardInterrupt:
                logger.info("Kafka booking event worker stopping")
                return
            except Exception:
                logger.exception("Kafka booking event worker lost connectivity; retrying")
                if consumer is not None:
                    consumer.close(autocommit=False)
                if producer is not None:
                    producer.close(timeout=5)
                time.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, 30)
    finally:
        engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
