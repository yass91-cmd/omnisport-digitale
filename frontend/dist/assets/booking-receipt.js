const key="omni-booking-receipt";

export function receiptForBooking(booking) {
  if(booking.reservation_status==="cancelled"||booking.status==="cancelled")return {heading:"Reservation cancelled",message:"Check My bookings for the current details."};
  if(booking.approval_status==="awaiting")return {heading:"Request received",message:"The complex is reviewing your request. We’ll notify you here when it is accepted."};
  return {heading:"Reservation saved",message:"Your time is reserved. Follow your reservation below."};
}
export function rememberBookingReceipt(booking) {
  try {sessionStorage.setItem(key,JSON.stringify({id:booking.id,approval_status:booking.approval_status,reservation_status:booking.reservation_status,status:booking.status}));} catch { /* Saving still succeeds when browser storage is unavailable. */ }
}
export function takeBookingReceipt() {
  try {const value=sessionStorage.getItem(key);sessionStorage.removeItem(key);if(!value)return null;const booking=JSON.parse(value);return {...receiptForBooking(booking),reservationId:booking.id};} catch{return null;}
}
