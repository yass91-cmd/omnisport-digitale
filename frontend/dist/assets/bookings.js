import { accountRequest } from "./auth-api.js";
import { element } from "./catalog-ui.js";
import { localDateTime, money } from "./account-navigation.js";
import { applySport, sportBadge } from "./sport-ui.js";
import { takeBookingReceipt } from "./booking-receipt.js";

const select = value => document.querySelector(value), staff = document.body.dataset.staff === "true";
const params = new URLSearchParams(location.search), complexId = params.get("complex_id"), limit = 20;
const labels = {pending:"Pending", confirmed:"Confirmed", cancelled:"Cancelled"};
let status = Object.hasOwn(labels, params.get("status")) ? params.get("status") : "pending";
let offset = 0, account, busy = false, request = 0, facilitySports = new Map();
const submittedReceipt=staff?null:takeBookingReceipt();
let notificationSignature="", pageSignature="", timer, polling=false;
if (staff) select("#bookings-workspace").href = `workspace.html?id=${encodeURIComponent(complexId)}`;

function feedback(text) {
  select("#bookings-feedback").textContent = text;
  select("#bookings-feedback").hidden = !text;
}
feedback("");

function render(booking) {
  const row = element("article", "settings-card booking-card booking-row");
  const sport = facilitySports.get(booking.facility_id), main = element("div", "booking-main");
  if (staff && sport) { applySport(row, sport); main.append(sportBadge(sport)); }
  main.append(element("h2", "", booking.facility_name));
  if(booking.team_name)main.append(element("p","field-help",`Team: ${booking.team_name}`));
  if (!staff) main.append(element("p", "field-help", booking.complex_name));
  const finish = booking.starts_at.slice(0,10) === booking.ends_at.slice(0,10) ? booking.ends_at.slice(11,16) : localDateTime(booking.ends_at);
  main.append(element("p", "booking-time", `${localDateTime(booking.starts_at)}–${finish} · ${booking.minutes} min`));
  row.append(main);
  if (staff) {
    const contact = element("div", "booking-contact");
    contact.append(element("strong", "", booking.client_name), element("span", "", booking.client_phone || "Phone not provided"), element("small", "", booking.walk_in ? "Walk-in customer" : booking.source === "staff" ? "Entered by staff" : "Booked online"));
    row.append(contact);
  }
  const price = element("div", "booking-price");
  price.append(element("strong", "booking-total", money(booking.total_amount, booking.currency)), element("p", "field-help booking-reference", `Reference: ${booking.reference}`));
  const actions = element("div", "booking-row-actions");
  actions.append(element("span", `status-badge ${booking.status}`, labels[booking.status]));
  if (booking.status === "pending") actions.append(element("small", "field-help", booking.approval_status==="awaiting"?"Awaiting staff acceptance":"Accepted · Not arrived yet"));
  const message = element("p", "field-help booking-action-message"); message.setAttribute("role", "status");
  function action(label, verb, primary = false) {
    const button = element("button", primary ? "primary-button" : "secondary-button cancel-booking", label);
    button.type = "button";
    button.addEventListener("click", async () => {
      if (busy) return;
      busy = true; actions.querySelectorAll("button").forEach(item => { item.disabled = true; });
      try {
        await accountRequest(`${staff ? `/api/v1/staff/complexes/${encodeURIComponent(complexId)}` : "/api/v1"}/reservations/${encodeURIComponent(booking.id)}/${verb}`, {method:"POST", csrfToken:account.csrf_token, body:{version:booking.version}});
        await load(); feedback(verb === "accept"?"Request accepted. The customer has been notified.":verb === "arrive" ? "Arrival recorded. Booking moved to Confirmed." : "Reservation cancelled.");
      } catch (error) { message.textContent = error.message; actions.querySelectorAll("button").forEach(item => { item.disabled = false; }); }
      finally { busy = false; }
    });
    actions.append(button);
  }
  if (staff && booking.can_accept) action("Accept request", "accept", true);
  if (staff && booking.can_mark_arrived) action("Mark arrived", "arrive", true);
  if (booking.can_cancel) action("Cancel booking", "cancel");
  else if (booking.status === "pending") actions.append(element("small", "field-help", "Cancellation deadline passed"));
  if (booking.status === "confirmed" && booking.arrived_at) actions.append(element("small", "field-help", `Arrived ${localDateTime(booking.arrived_at)}`));
  actions.append(message); row.append(price, actions);
  return row;
}

async function loadUpdates() {
  try {
    const page=await accountRequest("/api/v1/notifications?unread_only=true");
    const signature=JSON.stringify(page);
    if(notificationSignature!==signature){
      notificationSignature=signature;
      select("#client-updates-list").replaceChildren(...page.items.map(notice=>{
        const row=element("article","client-update"),copy=element("div","");
        copy.append(element("strong","",notice.kind==="rescheduled"?"Your reservation was moved for maintenance":notice.kind==="accepted"?"Your booking request was accepted":"Your reservation was cancelled"),element("p","field-help",`${notice.facility_name} · ${localDateTime(notice.starts_at)}–${notice.ends_at.slice(11,16)}`));
        const button=element("button","secondary-button","Mark as read");button.type="button";
        button.addEventListener("click",async()=>{if(busy)return;busy=true;button.disabled=true;try{await accountRequest(`/api/v1/notifications/${encodeURIComponent(notice.id)}/read`,{method:"POST",csrfToken:account.csrf_token,body:{}});await loadUpdates();}catch(error){select("#client-updates-status").textContent=error.message;button.disabled=false;}finally{busy=false;}});
        row.append(copy,button);return row;
      }));
      if(submittedReceipt&&page.items.some(notice=>notice.reservation_id===submittedReceipt.reservationId))select("#booking-receipt").hidden=true;
    }
    select("#client-updates").hidden=!page.total;select("#client-updates-heading").textContent=`Your updates · ${page.unread}`;select("#client-updates-status").textContent="";
  }catch(error){if(error.status===401)throw error;select("#client-updates").hidden=false;select("#client-updates-status").textContent="Updates could not load. Use Refresh to try again.";}
}

function stopPolling(){clearInterval(timer);timer=null;}
function startPolling(){if(staff||timer)return;timer=setInterval(()=>{if(document.hidden||busy||polling)return;polling=true;load(true).finally(()=>{polling=false;});},30000);}

async function load(quiet=false) {
  const current = ++request;
  select("#bookings-error").hidden = true;
  if(!quiet){select("#bookings-status").textContent="Loading bookings…";select("#bookings-list").replaceChildren();select("#bookings-previous").hidden=true;select("#bookings-next").hidden=true;select("#bookings-page").textContent="";}
  select("#booking-status-filters").querySelectorAll("button").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.status === status)));
  try {
    const identity = quiet?account:await accountRequest(staff ? "/api/v1/staff/me" : "/api/v1/auth/session");
    if (current !== request) return; account = identity;
    if (staff && !complexId) throw new Error("Choose a complex from Staff access first.");
    if (staff) {
      const workspace = await accountRequest(`/api/v1/staff/complexes/${encodeURIComponent(complexId)}`);
      if (current !== request) return;
      facilitySports = new Map(workspace.facilities.map(facility => [facility.id, facility.sport]));
    }
    const query = new URLSearchParams({offset, limit, status});
    if (staff && select("#booking-day").value) query.set("day", select("#booking-day").value);
    const page = await accountRequest(`${staff ? `/api/v1/staff/complexes/${encodeURIComponent(complexId)}` : "/api/v1"}/reservations?${query}`);
    if (current !== request) return;
    if (staff) select("#booking-context").textContent = `${page.complex_name} · ${page.timezone}`;
    const signature=JSON.stringify(page);if(!quiet||signature!==pageSignature)select("#bookings-list").replaceChildren(...page.items.map(render));pageSignature=signature;
    select("#bookings-status").textContent = page.total ? "" : `No ${status} bookings.`;
    select("#bookings-page").textContent = page.total ? `${offset+1}–${offset+page.items.length} of ${page.total}` : "";
    select("#bookings-previous").hidden = offset === 0; select("#bookings-next").hidden = offset+limit >= page.total;
    if(!staff){
      if(submittedReceipt&&select("#booking-receipt").dataset.shown!=="true"){
        select("#booking-receipt").hidden=false;select("#booking-receipt").dataset.shown="true";
        select("#receipt-heading").textContent=submittedReceipt.heading;select("#receipt-message").textContent=submittedReceipt.message;
      }
      await loadUpdates();startPolling();
    }
  } catch (error) {
    if (current !== request) return;
    select("#bookings-error").hidden = false; select("#bookings-error-message").textContent = error.message;
    select("#bookings-status").textContent = ""; select("#bookings-login").hidden = error.status !== 401;
    select("#bookings-login").href = `${staff ? "staff" : "account"}.html?return_to=${encodeURIComponent(location.pathname+location.search)}`;
    select("#bookings-retry").hidden = [401,403].includes(error.status);
    if([401,403].includes(error.status)){stopPolling();select("#bookings-list").replaceChildren();if(!staff){select("#client-updates").hidden=true;select("#booking-receipt").hidden=true;}}
  }
}
select("#booking-status-filters").addEventListener("click", event => {
  const button = event.target.closest("button[data-status]");
  if (!button || busy || status === button.dataset.status) return;
  status = button.dataset.status; offset = 0; feedback("");
  const url = new URL(location.href); url.searchParams.set("status", status); history.replaceState(null, "", url); load();
});
select("#bookings-retry").addEventListener("click", ()=>load());
select("#bookings-refresh")?.addEventListener("click",()=>load());
select("#bookings-previous").addEventListener("click", () => {if (!busy) {offset = Math.max(0,offset-limit); load();}});
select("#bookings-next").addEventListener("click", () => {if (!busy) {offset += limit; load();}});
select("#bookings-filter")?.addEventListener("submit", event => {event.preventDefault(); if (!busy) {offset = 0; load();}});
window.addEventListener("pageshow", event => {if (event.persisted) load();});
window.addEventListener("pagehide",stopPolling);
load();
