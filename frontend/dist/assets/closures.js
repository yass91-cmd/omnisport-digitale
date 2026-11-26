import { accountRequest } from "./auth-api.js";
import { element } from "./catalog-ui.js";

const select = value => document.querySelector(value);
const query = new URLSearchParams(location.search), complexId = query.get("complex_id"), facilityId = query.get("facility_id");
const endpoint = `/api/v1/staff/complexes/${encodeURIComponent(complexId)}/facilities/${encodeURIComponent(facilityId)}/closures`;
let account, version, loaded = 0, busy = false;
let reviewed = null, resolutions = [];

function message(text, success = false) {
  const node = select("#closures-message"); node.textContent = text; node.hidden = !text; node.classList.toggle("is-success",success);
}
function setBusy(value) {
  busy = value; select("#closure-fields").disabled = value; select("#closures-more").disabled = value; select("#closures-reload").disabled = value;
  select("#closure-form").setAttribute("aria-busy",String(value));
  select("#closure-review").querySelectorAll("button,input,select").forEach(control=>{control.disabled=value;});
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
  const history = await accountRequest(`${endpoint}/history`);
  select("#maintenance-history").replaceChildren(...history.items.map(item=>{
    const row=element("article","closure-row");
    row.append(element("h3","",`${item.reference} · ${item.action==="cancel"?"Cancelled":"Rescheduled"}`),element("p","",`${format(item.old_start)} – ${format(item.old_end)}${item.new_start?` → ${format(item.new_start)} – ${format(item.new_end)}`:""}`));
    return row;
  }));
  if(!history.items.length)select("#maintenance-history").textContent="No maintenance changes yet.";
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
  reviewed=null;select("#closure-review").hidden=true;
  try {
    const body={facility_version:version,starts_local:select("#closure-start").value,ends_local:select("#closure-end").value,reason:select("#closure-reason").value};
    const result=await accountRequest(`${endpoint}/preview`,{method:"POST",csrfToken:account.csrf_token,body});
    reviewed={...body,facility_version:result.facility_version};resolutions=[];
    select("#closure-affected").replaceChildren(...result.items.map(booking=>{
      const row=element("article","closure-row"),choice=element("select",""),time=element("input","");
      row.append(element("h4","",`${booking.client_name} · ${booking.reference}`),element("p","",`${booking.starts_at.slice(0,16).replace("T"," ")} – ${booking.ends_at.slice(11,16)} · ${booking.total_amount} ${booking.currency}`));
      if(booking.walk_in)row.append(element("p","",`Call customer: ${booking.client_phone||"Phone unavailable"}`));
      choice.setAttribute("aria-label",`Action for ${booking.reference}`);
      for(const [value,label] of [["","Choose an action"],["reschedule","Move to another time"],["cancel","Cancel booking"]]){const option=element("option","",label);option.value=value;choice.append(option);}
      time.type="datetime-local";time.step="60";time.hidden=true;time.setAttribute("aria-label",`New start for ${booking.reference}`);
      choice.addEventListener("change",()=>{time.hidden=choice.value!=="reschedule";});
      resolutions.push({booking,choice,time});row.append(choice,time);return row;
    }));
    if(!result.items.length)select("#closure-affected").textContent="No bookings are affected.";
    select("#closure-review").hidden=false;
  } catch (error) {showFailure(error);} finally {setBusy(false);}
});
select("#closure-form").addEventListener("input",()=>{reviewed=null;select("#closure-review").hidden=true;});
select("#closure-confirm").addEventListener("click",async()=>{
  if(busy||!reviewed)return;
  if(resolutions.some(item=>!item.choice.value||(item.choice.value==="reschedule"&&!item.time.value))){message("Choose an action and replacement time for every affected booking.");return;}
  setBusy(true);message("");
  try{
    await accountRequest(endpoint,{method:"POST",csrfToken:account.csrf_token,body:{...reviewed,resolutions:resolutions.map(({booking,choice,time})=>({reservation_id:booking.id,version:booking.version,action:choice.value,starts_local:choice.value==="reschedule"?time.value:null}))}});
    reviewed=null;select("#closure-review").hidden=true;await refresh();select("#closure-reason").value="";
    message("Closure saved. Bookings updated and account holders notified. Call any walk-in customers shown during review.",true);
  }catch(error){reviewed=null;select("#closure-review").hidden=true;showFailure(error);}finally{setBusy(false);}
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
