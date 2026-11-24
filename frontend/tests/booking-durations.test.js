import test from "node:test";
import assert from "node:assert/strict";
import { durationChoices } from "../dist/assets/booking-durations.js";

test("120 minutes stays visible but cannot be booked until that facility prices it",()=>{
  const basketball=durationChoices([60,90]),football=durationChoices([60,90,120]);
  assert.deepEqual(basketball.map(choice=>choice.minutes),[60,90,120]);
  assert.equal(basketball.find(choice=>choice.minutes===120).enabled,false);
  assert.match(basketball.find(choice=>choice.minutes===120).label,/price not set/);
  assert.equal(football.find(choice=>choice.minutes===120).enabled,true);
  assert.equal(football.find(choice=>choice.minutes===120).label,"120 min");
});

test("a facility without prices gets no bookable default duration",()=>{
  assert.ok(durationChoices([]).every(choice=>!choice.enabled));
  assert.deepEqual(durationChoices([120]).filter(choice=>choice.enabled).map(choice=>choice.minutes),[120]);
});
