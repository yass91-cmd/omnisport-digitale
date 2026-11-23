import { accountRequest } from "./auth-api.js";
import { safeReturn } from "./account-navigation.js";
import { watchNotificationCounts } from "./notification-badge.js";
import { showAssignedComplexes } from "./assigned-complexes.js";
const select = value => document.querySelector(value);
const returnTo = safeReturn(new URLSearchParams(location.search).get("return_to"),location.origin,true);
let account, busy = false;
let stopNotifications = () => {};

function showMessage(id,text) {const node = select(id);node.textContent = text;node.hidden = !text;}
function showPortal(data) {
  account = data;
  if (returnTo) {location.replace(returnTo);return;}
  select("#staff-login-view").hidden = true; select("#staff-portal-view").hidden = false;
  select("#staff-welcome").textContent = `Welcome, ${data.name}.`;
  showAssignedComplexes(select("#assigned-complexes"), data.staff_assignments);
  stopNotifications();stopNotifications = watchNotificationCounts(data => {
    document.querySelectorAll("[data-notifications-complex]").forEach(badge => {
      const complex = data.complexes.find(item => item.complex_id === badge.dataset.notificationsComplex);
      const count = complex?.unread || 0;
      badge.hidden = !count;badge.textContent = `${count} ${count === 1 ? "update" : "updates"}`;
    });
  });
}
async function initialize() {
  select("#staff-login-view").hidden = true; select("#staff-portal-view").hidden = true;
  try {showPortal(await accountRequest("/api/v1/staff/me"));}
  catch (error) {select("#staff-login-view").hidden = false;showMessage("#staff-login-message",error.status === 401 ? "" : error.message);}
  finally {select("#staff-loading").textContent = "";}
}
select("#staff-login-form").addEventListener("submit",async event => {
  event.preventDefault();if (busy) return;busy = true;
  const fields = new FormData(event.currentTarget), fieldset = select("#staff-login-form fieldset"); fieldset.disabled = true;showMessage("#staff-login-message","");
  try {
    const data = await accountRequest("/api/v1/staff/auth/login",{method:"POST",body:{email:fields.get("email"),password:fields.get("password")}});
    select("#staff-login-form").reset();showPortal(data);
  } catch (error) {showMessage("#staff-login-message",error.message);}
  finally {busy = false;fieldset.disabled = false;}
});
select("#staff-password-toggle").addEventListener("click",() => {
  const input = select("#staff-password"), show = input.type === "password";input.type = show ? "text" : "password";
  const button = select("#staff-password-toggle");button.textContent = show ? "Hide" : "Show";button.setAttribute("aria-pressed",String(show));button.setAttribute("aria-label",`${show ? "Hide" : "Show"} staff password`);
});
select("#staff-sign-out").addEventListener("click",async () => {
  if (busy) return;busy = true;select("#staff-sign-out").disabled = true;
  try {await accountRequest("/api/v1/auth/logout",{method:"POST",body:{},csrfToken:account.csrf_token});stopNotifications();account = null;select("#assigned-complexes").replaceChildren();select("#staff-welcome").textContent="";select("#staff-portal-view").hidden = true;select("#staff-login-view").hidden = false;}
  catch (error) {showMessage("#staff-portal-message",error.message);}
  finally {busy = false;select("#staff-sign-out").disabled = false;}
});
window.addEventListener("pageshow",event => {if (event.persisted) initialize();});
initialize();
