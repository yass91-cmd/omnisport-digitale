import { accountRequest } from "./auth-api.js";
import { element } from "./catalog-ui.js";

const select = value => document.querySelector(value);
const query = new URLSearchParams(location.search), complexId = query.get("complex_id"), facilityId = query.get("facility_id");
const endpoint = `/api/v1/staff/complexes/${encodeURIComponent(complexId)}/facilities/${encodeURIComponent(facilityId)}/closures`;
let account, version, loaded = 0, busy = false;

function message(text, success = false) {
  const node = select("#closures-message"); node.textContent = text; node.hidden = !text; node.classList.toggle("is-success",success);
}
function setBusy(value) {
  busy = value; select("#closure-fields").disabled = value; select("#closures-more").disabled = value; select("#closures-reload").disabled = value;
  select("#closure-form").setAttribute("aria-busy",String(value));
  select("#closure-list").querySelectorAll("button").forEach(button => {button.disabled = value;});
}
async function refresh(append = false) {
  const data = await accountRequest(`${endpoint}?offset=${append ? loaded : 0}&limit=50`);
  if (append && version !== data.facility_version) throw Object.assign(new Error("The schedule changed. Reload the saved closures."),{status:409});
  version = data.facility_version;
  document.title = `${data.facility_name} closures — OmniSport Digitale`;
  select("#closures-context").textContent = `${data.facility_name} · ${data.complex_name}`;
  select("#closures-timezone").textContent = `All times are local to ${data.timezone}. Closures can span several dates.`;
  select("#closures-back").href = `facility.html?complex_id=${encodeURIComponent(complexId)}&id=${encodeURIComponent(facilityId)}`;
  select("#closures-preview").href = `availability.html?complex_id=${encodeURIComponent(complexId)}&facility_id=${encodeURIComponent(facilityId)}&staff=1`;
  if (!select("#closure-start").value) {
    const tomorrow = new Date(`${data.today}T12:00:00Z`); tomorrow.setUTCDate(tomorrow.getUTCDate()+1);
    const day = tomorrow.toISOString().slice(0,10); select("#closure-start").value = `${day}T09:00`; select("#closure-end").value = `${day}T10:00`;
  }
  const dateFormat = new Intl.DateTimeFormat("en-GB",{timeZone:"UTC",day:"numeric",month:"short",year:"numeric"});
  const format = value => `${dateFormat.format(new Date(`${value.slice(0,10)}T12:00:00Z`))} ${value.slice(11,16)}`;
  const rows = data.items.map(closure => {
    const row = element("article","closure-row"), period = `${format(closure.starts_at)} – ${format(closure.ends_at)}`;
    row.append(element("h3","",period),element("p","",closure.reason));
    const cancel = element("button","remove-setting","Cancel closure"); cancel.type = "button"; cancel.setAttribute("aria-label",`Cancel closure ${period}`);
    cancel.addEventListener("click",() => cancelClosure(closure.id)); row.append(cancel); return row;
  });
  if (!append) {select("#closure-list").replaceChildren(); loaded = 0;}
  select("#closure-list").append(...rows); loaded += rows.length;
  if (!data.total) select("#closure-list").append(element("p","field-help","No upcoming closures. The weekly opening hours apply."));
  select("#closures-count").textContent = data.total ? `${loaded} of ${data.total} ${data.total === 1 ? "closure" : "closures"}` : "";
  select("#closures-more").hidden = loaded >= data.total;
  select("#closures-reload").hidden = true;
}
function showFailure(error) {message(error.message); select("#closures-reload").hidden = false;}
async function cancelClosure(id) {
  if (busy) return; setBusy(true); message("");
  try {
    await accountRequest(`${endpoint}/${encodeURIComponent(id)}/cancel`,{method:"POST",csrfToken:account.csrf_token,body:{facility_version:version}});
    await refresh(); message("Closure cancelled. Available times have been updated.",true);
  } catch (error) {showFailure(error);} finally {setBusy(false);}
}
select("#closure-form").addEventListener("submit",async event => {
  event.preventDefault(); if (busy) return; setBusy(true); message("");
  try {
    await accountRequest(endpoint,{method:"POST",csrfToken:account.csrf_token,body:{facility_version:version,starts_local:select("#closure-start").value,ends_local:select("#closure-end").value,reason:select("#closure-reason").value}});
    await refresh(); select("#closure-reason").value = ""; message("Closure added. Overlapping times are now unavailable.",true);
  } catch (error) {showFailure(error);} finally {setBusy(false);}
});
async function reload(append = false) {
  if (busy) return; setBusy(true); message("");
  try {await refresh(append);} catch (error) {showFailure(error);} finally {setBusy(false);}
}
select("#closures-more").addEventListener("click",() => reload(true));
select("#closures-reload").addEventListener("click",() => reload());
async function initialize() {
  try {
    if (!complexId || !facilityId) throw new Error("Open an existing facility from your workspace first.");
    account = await accountRequest("/api/v1/auth/session");
    if (!account) throw new Error("Please sign in to manage this facility’s closures.");
    await refresh(); select("#closures-view").hidden = false;
  } catch (error) {select("#closures-error").hidden = false; select("#closures-error-message").textContent = error.message;}
  finally {select("#closures-loading").textContent = "";}
}
initialize();
