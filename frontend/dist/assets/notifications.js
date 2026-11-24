import { accountRequest } from "./auth-api.js";
import { element } from "./catalog-ui.js";
import { localDateTime } from "./account-navigation.js";
import { applySport, sportBadge } from "./sport-ui.js";

const select = value => document.querySelector(value), complexId = new URLSearchParams(location.search).get("complex_id");
const base = `/api/v1/staff/complexes/${encodeURIComponent(complexId)}/notifications`, limit = 20;
let account, offset = 0, busy = false, pending = false, signature = "", facilitySports=new Map();
select("#notification-back").href = `workspace.html?id=${encodeURIComponent(complexId)}`;

function card(notice) {
  const node = element("article",`settings-card notification-card${notice.read ? "" : " unread"}`);
  const header=element("div","booking-card-header"),sport=facilitySports.get(notice.facility_id);if(sport){applySport(node,sport);header.append(sportBadge(sport));}
  header.append(element("span",`status-badge ${notice.read?"cancelled":"confirmed"}`,notice.read?"Read":"New"));
  node.append(header,element("h2","","Complex update"));
  node.append(element("p","field-help",`Received ${localDateTime(notice.created_at)}`));
  const actions = element("div","notification-actions");
  if (!notice.read) {
    const button = element("button","secondary-button","Mark as read"), message = element("p","field-help");message.setAttribute("role","status");
    button.addEventListener("click",async () => {
      if (busy) return;busy = true;button.disabled = true;
      try {await accountRequest(`${base}/${encodeURIComponent(notice.id)}/read`,{method:"POST",csrfToken:account.csrf_token,body:{}});await load();}
      catch(error) {message.textContent = error.message;button.disabled = false;}
      finally {busy = false;}
    });
    actions.append(button,message);
  }
  node.append(actions);return node;
}

async function load(quiet = false) {
  if (pending) return;pending = true;
  if (!quiet) select("#notification-status").textContent = "Loading updates…";
  try {
    if (!complexId) throw new Error("Choose your assigned complex first.");
    if (!account) {account = await accountRequest("/api/v1/staff/me");const workspace=await accountRequest(`/api/v1/staff/complexes/${encodeURIComponent(complexId)}`);facilitySports=new Map(workspace.facilities.map(facility=>[facility.id,facility.sport]));}
    const page = await accountRequest(`${base}?offset=${offset}&limit=${limit}`);
    const changed = JSON.stringify(page);
    if (signature !== changed) {
      select("#notification-list").replaceChildren(...page.items.map(card));signature = changed;
    }
    select("#notification-context").textContent = `${page.complex_name} · ${page.unread} unread`;
    select("#notification-status").textContent = page.total ? "" : "No updates yet.";
    select("#notification-error").hidden = true;
    select("#notification-page").textContent = page.total ? `${offset+1}–${offset+page.items.length} of ${page.total}` : "";
    select("#notification-previous").hidden = offset === 0;select("#notification-next").hidden = offset+limit >= page.total;
  } catch(error) {
    select("#notification-error").hidden = false;select("#notification-error-message").textContent = error.message;
    select("#notification-status").textContent = "";
    if ([401,403].includes(error.status)) {account = null;select("#notification-list").replaceChildren();signature = "";clearInterval(timer);}
    select("#notification-login").hidden = error.status !== 401;
    select("#notification-login").href = `staff.html?return_to=${encodeURIComponent(location.pathname+location.search)}`;
  } finally {pending = false;}
}
select("#notification-refresh").addEventListener("click",() => load());
select("#notification-previous").addEventListener("click",() => {offset = Math.max(0,offset-limit);load();});
select("#notification-next").addEventListener("click",() => {offset += limit;load();});
let timer;
function startPolling() {clearInterval(timer);timer = setInterval(() => {if (!document.hidden && !busy) load(true);},30000);}
window.addEventListener("pagehide",() => clearInterval(timer),{once:true});
window.addEventListener("pageshow",event => {if (event.persisted) {startPolling();load();}});
startPolling();
load();
