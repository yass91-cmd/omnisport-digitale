from uuid import UUID

from sqlalchemy import func, select
from test_bookings import booking_setup as booking_setup
from test_bookings import headers, payload, reserve

from backend.app.models import ClientNotification, FacilityClosure, MaintenanceChange, Reservation


def closure_body(version, booking, action="reschedule", start="2026-11-24T10:00"):
    return {
        "facility_version": version,
        "starts_local": "2026-11-23T17:00",
        "ends_local": "2026-11-23T20:00",
        "reason": "Court maintenance",
        "resolutions": [
            {
                "reservation_id": booking["id"],
                "version": booking["version"],
                "action": action,
                "starts_local": start if action == "reschedule" else None,
            }
        ],
    }


def test_maintenance_moves_preserves_price_and_audits(client, session, booking_setup):
    booking = reserve(client, booking_setup).json()
    endpoint = booking_setup[5] + "/closures"
    body = closure_body(2, booking)
    preview = client.post(endpoint + "/preview", headers=headers(booking_setup[0]), json=body)
    assert preview.status_code == 200, preview.text
    assert preview.json()["items"][0]["id"] == booking["id"]
    saved = client.post(endpoint, headers=headers(booking_setup[0]), json=body)
    assert saved.status_code == 201, saved.text
    stored = session.get(Reservation, UUID(booking["id"]))
    assert str(stored.total_amount) == booking["total_amount"]
    assert stored.starts_at.day == 24 and stored.version == 2
    assert session.scalar(select(func.count()).select_from(MaintenanceChange)) == 1
    notice = session.scalar(select(ClientNotification))
    assert notice.kind == "rescheduled"
    history = client.get(endpoint + "/history").json()["items"]
    assert history[0]["reference"] == booking["reference"]
    assert "2026-11-23" in history[0]["old_start"]
    assert client.post(endpoint, headers=headers(booking_setup[0]), json=body).status_code == 409


def test_invalid_replacement_does_not_save_closure_or_changes(client, session, booking_setup):
    booking = reserve(client, booking_setup).json()
    response = client.post(
        booking_setup[5] + "/closures",
        headers=headers(booking_setup[0]),
        json=closure_body(2, booking, start="2026-11-23T18:00"),
    )
    assert response.status_code == 409
    session.expire_all()
    assert session.get(Reservation, UUID(booking["id"])).version == 1
    assert session.scalar(select(func.count()).select_from(FacilityClosure)) == 0
    assert session.scalar(select(func.count()).select_from(MaintenanceChange)) == 0


def test_maintenance_cancel_and_employee_denial(client, session, booking_setup):
    booking = reserve(client, booking_setup).json()
    endpoint = booking_setup[5] + "/closures"
    body = closure_body(2, booking, action="cancel")
    booking_setup[1].role = "employee"
    session.commit()
    assert client.post(endpoint, headers=headers(booking_setup[0]), json=body).status_code == 403
    assert (
        client.post(endpoint + "/preview", headers=headers(booking_setup[0]), json=body).status_code
        == 403
    )
    booking_setup[1].role = "admin"
    session.commit()
    saved = client.post(endpoint, headers=headers(booking_setup[0]), json=body)
    assert saved.status_code == 201, saved.text
    assert session.get(Reservation, UUID(booking["id"])).status == "cancelled"
    assert session.scalar(select(ClientNotification)).kind == "cancelled"


def test_stale_review_and_missing_decisions_rejected(client, booking_setup):
    booking = reserve(client, booking_setup).json()
    endpoint = booking_setup[5] + "/closures"
    body = closure_body(1, booking)
    assert client.post(endpoint, headers=headers(booking_setup[0]), json=body).status_code == 409
    body["facility_version"] = 2
    body["resolutions"] = []
    assert client.post(endpoint, headers=headers(booking_setup[0]), json=body).status_code == 409


def test_replacements_cannot_overlap_each_other(client, session, booking_setup):
    first = reserve(client, booking_setup).json()
    second = reserve(client, booking_setup, payload(2, start="2026-11-23T19:00")).json()
    body = closure_body(3, first)
    body["resolutions"] += closure_body(3, second)["resolutions"]
    response = client.post(
        booking_setup[5] + "/closures", headers=headers(booking_setup[0]), json=body
    )
    assert response.status_code == 409
    assert session.scalar(select(func.count()).select_from(MaintenanceChange)) == 0
    assert session.scalar(select(func.count()).select_from(FacilityClosure)) == 0
