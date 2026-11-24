export const BOOKING_DURATIONS=[60,90,120];

export function durationChoices(priced) {
  return BOOKING_DURATIONS.map(minutes=>({minutes,enabled:priced.includes(minutes),label:`${minutes} min${priced.includes(minutes)?"":" · price not set"}`}));
}
