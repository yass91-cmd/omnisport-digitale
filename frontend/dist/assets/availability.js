import { accountRequest } from "./auth-api.js";
import { element } from "./catalog-ui.js";
import { money, localDateTime } from "./account-navigation.js";
import { weekdays } from "./opening-hours.js";
import { applySport, sportBadge } from "./sport-ui.js";
import { durationChoices } from "./booking-durations.js";
import { bookingHistoryPath } from "./booking-feedback.js";
import { rememberBookingReceipt } from "./booking-receipt.js";

const select=value=>document.querySelector(value), params=new URLSearchParams(location.search);
const complexId=params.get("complex_id"),facilityId=params.get("facility_id"),staff=params.get("staff")==="1";
const base=`/api/v1/${staff?"staff/":""}complexes/${encodeURIComponent(complexId)}/facilities/${encodeURIComponent(facilityId)}`;
let coachTeams=[];
let account=null,schedule=null,request=0,busy=false,period=null,intent=null,navigating=false;
document.body.classList.add(staff?"staff-ui":"sport-ui");
if(staff){select("#schedule-eyebrow").textContent="STAFF WORKSPACE";select("#schedule-heading").textContent="Book a time";}
const range=(start,end)=>start.slice(0,10)===end.slice(0,10)?`${start.slice(11,16)}–${end.slice(11,16)}`:`${localDateTime(start)} → ${localDateTime(end)}`;

function loginLink() {
  const back=new URL(location.href);
  const day=select("#slot-day").value||params.get("day"),minutes=select("#slot-duration").value||params.get("minutes");
  if(day)back.searchParams.set("day",day);
  if(minutes)back.searchParams.set("minutes",minutes);
  const selected=select("#reservation-start").value;
  if(selected)back.searchParams.set("start",selected);
  return `${staff?"staff":"account"}.html?return_to=${encodeURIComponent(back.pathname+back.search)}`;
}
function updateChoice() {
  const slot=schedule?.slots.find(item=>item.starts_at.slice(0,16)===select("#reservation-start").value);
  select("#confirm-reservation").disabled=busy||!slot;
  select("#reservation-summary").textContent=slot?`${range(slot.starts_at,slot.ends_at)} · ${schedule.minutes} min · ${money(slot.total_amount,schedule.currency)}`:"Choose a suitable start time.";
}
function choosePeriod(block,preferred=null) {
  period=block;
  const slots=schedule.slots.filter(slot=>!block||(Date.parse(slot.starts_at)>=Date.parse(block.starts_at)&&Date.parse(slot.ends_at)<=Date.parse(block.ends_at)));
  select("#reservation-start").replaceChildren(...slots.map(slot=>{const option=element("option","",range(slot.starts_at,slot.ends_at));option.value=slot.starts_at.slice(0,16);return option;}));
  if(preferred&&slots.some(slot=>slot.starts_at.slice(0,16)===preferred))select("#reservation-start").value=preferred;
  else if(!block){const placeholder=element("option","","Select a start time");placeholder.value="";select("#reservation-start").prepend(placeholder);select("#reservation-start").value="";}
  select("#reservation-form").hidden=!slots.length||!schedule.booking_enabled;
  updateChoice();
}
function drawTimetable() {
  const periods=schedule.timeline.flatMap(block=>{
    if(block.state!=="available")return [];
    const slots=schedule.slots.filter(slot=>Date.parse(slot.starts_at)>=Date.parse(block.starts_at)&&Date.parse(slot.ends_at)<=Date.parse(block.ends_at)).sort((a,b)=>Date.parse(a.starts_at)-Date.parse(b.starts_at));
    if(!slots.length)return [];
    return [{state:"available",starts_at:slots[0].starts_at,ends_at:slots.at(-1).ends_at}];
  });
  const list=select("#daily-timetable");list.replaceChildren();
  if(!periods.length)return;
  const row=element("li","timetable-block available combined-availability");
  const details=element("div","timetable-details");details.append(element("strong","","Available"));
  const times=element("div","available-ranges");times.setAttribute("role","list");times.setAttribute("aria-label","Available periods");
  periods.forEach(block=>{const time=element("strong","available-range",range(block.starts_at,block.ends_at));time.setAttribute("role","listitem");times.append(time);});
  row.append(details,times);
  if(schedule.booking_enabled){const button=element("button","secondary-button","Choose time");button.type="button";button.setAttribute("aria-label","Choose an available time");button.addEventListener("click",()=>{choosePeriod(null);select("#reservation-form").scrollIntoView({block:"center",behavior:"smooth"});select("#reservation-start").focus();});row.append(button);}
  list.append(row);
}
async function load(initial=false,findNext=false) {
  const current=++request,previousStart=select("#reservation-start").value;
  select("#schedule-error").hidden=true;select("#slot-fields").disabled=true;select("#reservation-form").hidden=true;
  select("#slot-status").textContent="Loading available times…";select("#daily-timetable").replaceChildren();
  try{
    if(!complexId||!facilityId)throw new Error("Choose a facility from a complex first.");
    const query=new URLSearchParams(),day=initial?params.get("day"):select("#slot-day").value,minutes=initial?params.get("minutes"):select("#slot-duration").value;
    if(day)query.set("day",day);if(minutes)query.set("minutes",minutes);if(findNext||(initial&&!day))query.set("find_next","true");
    const data=await accountRequest(`${base}/availability?${query}`);if(current!==request)return;schedule=data;
    const selectedTeam=select("#reservation-team").value;
    const matchingTeams=coachTeams.filter(team=>team.sport.toLowerCase()===data.sport.toLowerCase());
    select("#team-choice").hidden=staff||!matchingTeams.length;
    select("#reservation-team").replaceChildren(Object.assign(element("option","","Myself"),{value:""}),...matchingTeams.map(team=>Object.assign(element("option","",team.name),{value:team.id})));
    if(matchingTeams.some(team=>team.id===selectedTeam))select("#reservation-team").value=selectedTeam;
    document.title=`${data.facility_name} booking — OmniSport Digitale`;
    select("#schedule-context").textContent=`${data.facility_name} · ${data.complex_name} · ${data.sport}`;
    applySport(document.body,data.sport);select("#schedule-sport").replaceChildren(sportBadge(data.sport));
    select("#schedule-timezone").textContent=`Times are local to ${data.timezone}.`;
    select("#schedule-preview").hidden=data.published;
    select("#schedule-back").href=staff?`workspace.html?id=${encodeURIComponent(complexId)}`:`complex.html?id=${encodeURIComponent(complexId)}`;select("#schedule-back").textContent=staff?"Back to workspace":"Back to complex";
    select("#schedule-history").href=bookingHistoryPath(staff,complexId,"pending");select("#schedule-history").textContent=staff?"Booking history":"My bookings";
    select("#slot-day").value=data.day;select("#slot-day").min=data.today;
    select("#slot-duration").replaceChildren(...durationChoices(data.priced_durations).map(choice=>{const option=element("option","",choice.label);option.value=String(choice.minutes);option.disabled=!choice.enabled;return option;}));
    if(data.minutes)select("#slot-duration").value=String(data.minutes);
    const missing=durationChoices(data.priced_durations).filter(choice=>!choice.enabled).map(choice=>choice.minutes);
    select("#duration-note").textContent=missing.length?`${missing.join(" / ")} min: this facility has not set a price yet.`:"Prices are set by this facility.";
    const messages={unconfigured:"Opening hours and prices are not published yet.",past:"Choose today or a later date.",unavailable:"No suitable start is available for this duration. Try another date or duration."};
    let message=data.status==="available"?"Choose a free period below, or select a start time.":messages[data.status];
    if(data.unavailable_reason==="closed")message=`Closed on this day. Opening days: ${data.opening_weekdays.map(day=>weekdays[day]).join(", ")}.`;
    if(data.searched_from&&data.status==="available")message=`Showing the next available date: ${localDateTime(`${data.day}T12:00:00Z`).split(" · ")[0]}. ${message}`;
    if(data.search_exhausted)message+=" No start was found in the following 28 days.";
    select("#slot-status").textContent=message;
    select("#slot-search").hidden=data.status==="unconfigured";
    select("#slot-help").hidden=data.status!=="available";
    select("#next-available").hidden=data.status!=="unavailable"||data.search_exhausted;
    const admin=account?.staff_assignments?.some(item=>item.complex_id===complexId&&item.role==="admin");
    select("#configure-hours").hidden=!admin||(data.published&&data.status!=="unconfigured"&&data.unavailable_reason!=="closed"&&!missing.length);
    select("#configure-hours").textContent=data.status==="unconfigured"?"Set hours & prices":!data.published?"Review & publish facility":missing.length?"Set missing duration prices":"Edit opening days";
    select("#configure-hours").href=`facility.html?complex_id=${encodeURIComponent(complexId)}&id=${encodeURIComponent(facilityId)}`;
    select("#booking-policy").hidden=!data.booking_enabled||data.status!=="available";
    select("#booking-policy").textContent=staff?"Staff bookings are accepted immediately. Review online requests in booking history.":"Your chosen time is held while staff review your request. Acceptance updates appear in My bookings.";
    select("#reservation-contact").hidden=!account;select("#client-name").required=staff;select("#client-name").readOnly=!staff;
    if(!staff)select("#client-name").value=account?.name||"";
    if(!staff&&!select("#client-phone").value)select("#client-phone").value=account?.phone||"";
    select("#client-phone").required=!!account;select("#staff-contact-help").hidden=!staff;
    select("#confirm-reservation").textContent=account?(staff?"Reserve time":"Send booking request"):"Sign in to reserve";
    drawTimetable();choosePeriod(null,initial?params.get("start"):previousStart);
    select("#slots-panel").hidden=false;
  }catch(error){if(current!==request)return;select("#schedule-error").hidden=false;select("#schedule-error-message").textContent=error.message;select("#slot-status").textContent="";select("#schedule-retry").hidden=[401,403,404].includes(error.status);const link=select("#schedule-error a");link.href=loginLink();link.textContent=staff?"Staff sign in":"Sign in";}
  finally{if(current===request){select("#slot-fields").disabled=busy;select("#schedule-loading").textContent="";}}
}
select("#slot-search").addEventListener("submit",event=>{event.preventDefault();load();});
select("#slot-day").addEventListener("change",()=>load());select("#slot-duration").addEventListener("change",()=>{period=null;load();});
select("#reservation-start").addEventListener("change",updateChoice);
select("#next-available").addEventListener("click",()=>load(false,true));select("#schedule-retry").addEventListener("click",()=>load());
select("#reservation-form").addEventListener("submit",async event=>{
  event.preventDefault();if(busy)return;if(!account){location.assign(loginLink());return;}
  const slot=schedule.slots.find(item=>item.starts_at.slice(0,16)===select("#reservation-start").value);if(!slot)return;
  const details={facility_version:schedule.facility_version,starts_local:slot.starts_at.slice(0,16),minutes:schedule.minutes,...(staff?{client_name:select("#client-name").value,client_phone:select("#client-phone").value}:{phone:select("#client-phone").value})};
  if(!staff&&select("#reservation-team").value)details.team_id=select("#reservation-team").value;
  const key=JSON.stringify(details);if(intent?.key!==key)intent={key,id:crypto.randomUUID()};
  busy=true;select("#reservation-fields").disabled=true;select("#slot-fields").disabled=true;const message=select("#booking-message");message.hidden=false;message.textContent="Saving reservation…";
  select("#booking-history").textContent=staff?"View booking history":"My bookings";select("#booking-history").href=bookingHistoryPath(staff,complexId,"pending");
  try{
    const booking=await accountRequest(`${base}/reservations`,{method:"POST",csrfToken:account.csrf_token,body:{...details,request_id:intent.id}});
    if(!staff){account.phone=booking.client_phone;rememberBookingReceipt(booking);navigating=true;location.assign(bookingHistoryPath(false,complexId,booking.status));return;}
    message.textContent="Saved successfully. View your reservation in booking history.";
    select("#booking-history").hidden=true;
    intent=null;period=null;select("#reservation-start").value="";
    if(staff){select("#client-name").value="";select("#client-phone").value="";}
    await load();
    select("#daily-timetable").scrollIntoView({block:"start",behavior:"smooth"});
  }catch(error){if(error.status===401){location.assign(loginLink());return;}message.textContent=error.status?error.message:"We couldn’t verify saving. Check your booking history before retrying.";if(!error.status)select("#booking-history").hidden=false;if(error.status===409)await load();}
  finally{if(!navigating){busy=false;select("#reservation-fields").disabled=false;select("#slot-fields").disabled=false;updateChoice();}}
});
async function start(){coachTeams=[];try{account=await accountRequest(staff?"/api/v1/staff/me":"/api/v1/auth/session");if(!staff&&account?.client_role==="coach"){let offset=0;while(true){const page=await accountRequest(`/api/v1/teams?mine=true&offset=${offset}`);coachTeams.push(...page.items);if(!page.has_more)break;offset+=50;}}}catch{account=null;}await load(true);}
window.addEventListener("pageshow",event=>{
  if(!event.persisted)return;
  busy=false;intent=null;navigating=false;
  select("#reservation-fields").disabled=false;select("#slot-fields").disabled=false;
  select("#booking-message").hidden=true;select("#booking-history").hidden=true;
  start();
});
start();
