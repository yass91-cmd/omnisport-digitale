import test from "node:test";
import assert from "node:assert/strict";
import { safeReturn, localDateTime } from "../dist/assets/account-navigation.js";

const origin = "http://127.0.0.1:8000";
test("client sign-in retains the selected booking page and date",() => {
  assert.equal(safeReturn("/availability.html?day=2026-11-23&minutes=90",origin),"/availability.html?day=2026-11-23&minutes=90");
  assert.equal(safeReturn("bookings.html",origin),"/bookings.html");
});
test("return links cannot leave this site or target an API",() => {
  for (const value of ["https://evil.example/availability.html","//evil.example/bookings.html","http://user:secret@127.0.0.1:8000/bookings.html","/api/v1/auth/logout","/unknown.html","",null,"http://["]) assert.equal(safeReturn(value,origin,true),null,value);
});
test("staff return pages require the staff entrance",() => {
  assert.equal(safeReturn("/workspace.html?id=atlas",origin),null);
  assert.equal(safeReturn("/workspace.html?id=atlas",origin,true),"/workspace.html?id=atlas");
  assert.equal(safeReturn("/staff-bookings.html?complex_id=atlas",origin,true),"/staff-bookings.html?complex_id=atlas");
  assert.equal(safeReturn("/notifications.html?complex_id=atlas",origin),null);
  assert.equal(safeReturn("/notifications.html?complex_id=atlas",origin,true),"/notifications.html?complex_id=atlas");
  assert.equal(safeReturn("/time-requests.html?complex_id=atlas",origin),null);
  assert.equal(safeReturn("/time-requests.html?complex_id=atlas",origin,true),null);
});
test("local booking labels retain the server local date across clock offsets",() => {
  assert.equal(localDateTime("2026-11-23T00:30:00+01:00"),"23 Nov 2026 · 00:30");
  assert.equal(localDateTime("2026-11-23T00:30:00Z"),"23 Nov 2026 · 00:30");
});
