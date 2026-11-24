import test from "node:test";
import assert from "node:assert/strict";
import { receiptForBooking, rememberBookingReceipt, takeBookingReceipt } from "../dist/assets/booking-receipt.js";

test("acceptance messaging does not confuse pending attendance with a waiting request",()=>{
  assert.equal(receiptForBooking({status:"pending",approval_status:"accepted"}).heading,"Reservation saved");
  assert.equal(receiptForBooking({status:"pending",approval_status:"awaiting"}).heading,"Request received");
  assert.match(receiptForBooking({approval_status:"awaiting"}).message,/notify you here/);
  assert.equal(receiptForBooking({status:"cancelled",approval_status:"awaiting"}).heading,"Reservation cancelled");
});
test("request receipt follows the redirect once without storing customer contact details",()=>{
  const store=new Map();globalThis.sessionStorage={setItem:(key,value)=>store.set(key,value),getItem:key=>store.get(key),removeItem:key=>store.delete(key)};
  try {
    rememberBookingReceipt({id:"request-id",status:"pending",approval_status:"awaiting",client_phone:"private contact"});
    assert.ok(![...store.values()].join().includes("private contact"));
    assert.equal(takeBookingReceipt().reservationId,"request-id");assert.equal(takeBookingReceipt(),null);
    globalThis.sessionStorage={setItem(){throw Error("blocked");},getItem(){throw Error("blocked");}};
    assert.doesNotThrow(()=>rememberBookingReceipt({approval_status:"awaiting"}));assert.equal(takeBookingReceipt(),null);
  } finally {delete globalThis.sessionStorage;}
});
