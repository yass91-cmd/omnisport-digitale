"""Reservation occupancy is separate from a customer's recorded attendance."""


def history_status(booking):
    if booking.status == "cancelled":
        return "cancelled"
    return "confirmed" if booking.arrived_at is not None else "pending"
