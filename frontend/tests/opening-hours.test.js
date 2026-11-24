import test from "node:test";
import assert from "node:assert/strict";
import { groupOpeningHours, expandOpeningHours, weeklyPlan, weeklyHours } from "../dist/assets/opening-hours.js";

test("days sharing the same hours reopen as one checklist",() => {
  assert.deepEqual(groupOpeningHours([
    {weekday:2,opens_at:"09:00",closes_at:"21:00"},
    {weekday:0,opens_at:"09:00",closes_at:"21:00"},
    {weekday:5,opens_at:"10:00",closes_at:"18:00"},
  ]),[
    {weekdays:[0,2],opens_at:"09:00",closes_at:"21:00"},
    {weekdays:[5],opens_at:"10:00",closes_at:"18:00"},
  ]);
});
test("one interval expands only to its checked days",() => {
  assert.deepEqual(expandOpeningHours([{weekdays:[4,0,2],opens_at:"09:00",closes_at:"21:00"}]),[
    {weekday:0,opens_at:"09:00",closes_at:"21:00"},
    {weekday:2,opens_at:"09:00",closes_at:"21:00"},
    {weekday:4,opens_at:"09:00",closes_at:"21:00"},
  ]);
});
test("a changed day and a lunch break retain their own intervals",() => {
  const hours = [
    {weekdays:[0,1,2,3,4],opens_at:"09:00",closes_at:"12:00"},
    {weekdays:[0,1,2,3,4],opens_at:"13:00",closes_at:"21:00"},
    {weekdays:[5],opens_at:"10:00",closes_at:"18:00"},
  ];
  const expanded = expandOpeningHours(hours);
  assert.equal(expanded.length,11);
  assert.deepEqual(groupOpeningHours(expanded),hours);
  assert.ok(expanded.every(row => row.weekday !== 6));
});
test("midnight closing survives grouping and saving",() => {
  assert.deepEqual(expandOpeningHours(groupOpeningHours([{weekday:4,opens_at:"18:00",closes_at:"24:00"}])),[{weekday:4,opens_at:"18:00",closes_at:"00:00"}]);
});
test("an interval without days cannot be silently lost; removing all intervals closes all days",() => {
  assert.throws(()=>expandOpeningHours([{weekdays:[],opens_at:"09:00",closes_at:"21:00"}]),/Choose at least one day/);
  assert.deepEqual(expandOpeningHours([]),[]);
});
test("invalid days and too many daily intervals are rejected",() => {
  assert.throws(()=>expandOpeningHours([{weekdays:[7],opens_at:"09:00",closes_at:"21:00"}]),/valid weekday/);
  assert.throws(()=>expandOpeningHours(Array.from({length:9},()=>({weekdays:[0,1,2,3,4,5,6],opens_at:"09:00",closes_at:"21:00"}))),/56/);
});

test("weekly rows preserve usual hours, exceptions, breaks and closed days",()=>{
  const hours=[{weekday:0,opens_at:"09:00",closes_at:"23:00"},{weekday:1,opens_at:"09:00",closes_at:"23:00"},{weekday:5,opens_at:"10:00",closes_at:"12:00"},{weekday:5,opens_at:"13:00",closes_at:"21:00"}];
  const plan=weeklyPlan(hours);
  assert.deepEqual(plan.usual,{opens_at:"09:00",closes_at:"23:00"});
  assert.equal(plan.days[0].custom,false);assert.equal(plan.days[5].custom,true);assert.equal(plan.days[6].open,false);
  assert.deepEqual(weeklyHours(plan),hours);
  plan.days[6].open=true;
  assert.deepEqual(weeklyHours(plan).at(-1),{weekday:6,opens_at:"09:00",closes_at:"23:00"});
});
test("weekly usual-hour changes do not overwrite day exceptions",()=>{
  const plan=weeklyPlan([{weekday:0,opens_at:"09:00",closes_at:"23:00"},{weekday:1,opens_at:"09:00",closes_at:"23:00"},{weekday:5,opens_at:"10:00",closes_at:"18:00"}]);
  plan.usual.closes_at="22:00";
  assert.deepEqual(weeklyHours(plan),[{weekday:0,opens_at:"09:00",closes_at:"22:00"},{weekday:1,opens_at:"09:00",closes_at:"22:00"},{weekday:5,opens_at:"10:00",closes_at:"18:00"}]);
});
