export function bookingHistoryPath(staff, complexId, status) {
  const query = new URLSearchParams();
  if (staff) query.set("complex_id", complexId);
  if (["pending", "confirmed", "cancelled"].includes(status)) query.set("status", status);
  return `${staff ? "staff-bookings" : "bookings"}.html${query.size ? `?${query}` : ""}`;
}
