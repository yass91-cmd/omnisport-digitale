import test from "node:test";
import assert from "node:assert/strict";
import { bookingHistoryPath } from "../dist/assets/booking-feedback.js";

test("history links preserve the chosen role, complex and status", () => {
  assert.equal(bookingHistoryPath(true,"complex with space","confirmed"),"staff-bookings.html?complex_id=complex+with+space&status=confirmed");
  assert.equal(bookingHistoryPath(false,null,"pending"),"bookings.html?status=pending");
  assert.equal(bookingHistoryPath(false,null,"invalid"),"bookings.html");
});
