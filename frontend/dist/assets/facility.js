import { accountRequest } from "./auth-api.js";
import { element } from "./catalog-ui.js";
import { pricingDescription } from "./pricing-rules.js";

const select = value => document.querySelector(value);
const query = new URLSearchParams(location.search);
const complexId = query.get("complex_id");
let facilityId = query.get("id"), version = null, account = null, sports = [], currency = "MAD", busy = false, sequence = 0;
const weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

function updatePricingDescription() {
  const weekend = select("#weekend-percent").value, evening = select("#evening-percent").value;
  select("#pricing-description").textContent = pricingDescription({weekend_percent:weekend,evening_percent:evening});
}

function showMessage(text, success = false) {
  const node = select("#facility-message"); node.textContent = text; node.hidden = !text;
  node.classList.toggle("is-success", success);
}

function labeledInput(row, label, control) {
  const wrapper = element("div", "settings-field"), id = `setting-${++sequence}`;
  control.id = id; const caption = element("label", "", label); caption.htmlFor = id;
  wrapper.append(caption, control); row.append(wrapper); return control;
}

function updateEmptyStates() {
  select("#hours-empty").hidden = !!select("#opening-rows").children.length;
  select("#tariffs-empty").hidden = !!select("#tariff-rows").children.length;
  const controls = [...document.querySelectorAll('[data-field="minutes"]')];
  const used = new Set(controls.map(node => Number(node.value)));
  controls.forEach(node => [...node.options].forEach(option => {
    option.disabled = option.value !== node.value && used.has(Number(option.value));
  }));
  select("#add-tariff").disabled = !allowedDurations().length || used.size >= allowedDurations().length;
  select("#add-opening").disabled = select("#opening-rows").children.length >= 56;
}

function removeButton(row, title) {
  const button = element("button", "remove-setting", "Remove"); button.type = "button";
  button.setAttribute("aria-label", title);
  button.addEventListener("click", () => { row.remove(); updateEmptyStates(); }); row.append(button);
}

function openingRow(data = null) {
  const row = element("div", "opening-row");
  const day = element("select"); day.dataset.field = "weekday";
  weekdays.forEach((name, index) => { const option = element("option", "", name); option.value = String(index); day.append(option); });
  const used = [...document.querySelectorAll('[data-field="weekday"]')].map(node => Number(node.value));
  day.value = String(data?.weekday ?? Math.max(0, weekdays.findIndex((_, index) => !used.includes(index))));
  labeledInput(row, "Day", day);
  for (const [field, label] of [["opens_at", "Opening time"], ["closes_at", "Closing time"]]) {
    const input = element("input"); input.type = "time"; input.step = "60"; input.required = true; input.dataset.field = field;
    input.value = data?.[field] === "24:00" ? "00:00" : data?.[field] || "";
    labeledInput(row, label, input);
  }
  removeButton(row, "Remove opening interval"); select("#opening-rows").append(row); updateEmptyStates();
}

function allowedDurations() { return sports.find(item => item.id === select("#facility-sport").value)?.allowed_durations || []; }

function tariffRow(data = null) {
  const allowed = allowedDurations();
  if (!allowed.length) { showMessage("No booking durations are configured for this sport."); return; }
  const row = element("div", "tariff-row"), duration = element("select"); duration.dataset.field = "minutes";
  duration.addEventListener("change", updateEmptyStates);
  allowed.forEach(value => { const option = element("option", "", `${value} min`); option.value = String(value); duration.append(option); });
  const used = [...document.querySelectorAll('[data-field="minutes"]')].map(node => Number(node.value));
  duration.value = String(data?.minutes ?? allowed.find(value => !used.includes(value)) ?? allowed[0]);
  labeledInput(row, "Duration", duration);
  const amount = element("input"); amount.type = "number"; amount.min = "0"; amount.max = "99999999.99"; amount.step = "0.01"; amount.required = true; amount.inputMode = "decimal"; amount.dataset.field = "amount"; amount.value = data?.amount ?? "";
  labeledInput(row, `Price (${currency})`, amount); removeButton(row, "Remove duration price");
  select("#tariff-rows").append(row); updateEmptyStates();
}

function populate(data) {
  version = data?.version ?? null;
  select("#facility-name").value = data?.name || "";
  select("#facility-sport").value = data?.sport.id || (sports.some(row => row.id === query.get("sport_id")) ? query.get("sport_id") : sports[0]?.id) || "";
  select("#facility-surface").value = data?.surface || "";
  select("#facility-description").value = data?.description || "";
  select("#facility-active").checked = data?.active ?? false;
  select("#weekend-percent").value = data?.weekend_percent ?? "10.00";
  select("#evening-percent").value = data?.evening_percent ?? "10.00";
  updatePricingDescription();
  select("#opening-rows").replaceChildren(); select("#tariff-rows").replaceChildren();
  (data?.opening_hours || []).forEach(openingRow); (data?.tariffs || []).forEach(tariffRow); updateEmptyStates();
  select("#editor-heading").textContent = data ? "EDIT YOUR FACILITY." : "ADD A FACILITY.";
  document.title = data ? `${data.name} settings — OmniSport Digitale` : "Add a facility — OmniSport Digitale";
  select("#save-facility").textContent = data ? "Save changes" : "Create facility";
}

async function initialize() {
  select("#facility-form").hidden = true; select("#editor-error").hidden = true; select("#reload-settings").hidden = true;
  select("#editor-status").textContent = "Loading facility settings…"; showMessage("");
  try {
    if (!complexId) throw new Error("Open a complex from your account page first.");
    const [workspace, sportList, signedIn] = await Promise.all([
      accountRequest(`/api/v1/staff/complexes/${encodeURIComponent(complexId)}`),
      accountRequest("/api/v1/sports"), accountRequest("/api/v1/auth/session"),
    ]);
    if (!signedIn) throw Object.assign(new Error("Please sign in to manage this facility."), {status:401});
    if (workspace.role !== "admin") throw Object.assign(new Error("Only this complex’s administrator can change facility settings."), {status:403});
    account = signedIn; sports = sportList; currency = workspace.currency;
    select("#editor-context").textContent = `${workspace.name} · ${workspace.city}`;
    select("#hours-timezone").textContent = `All times are local to ${workspace.timezone}.`;
    select("#prices-currency").textContent = `Prices are in ${currency}, the currency of this complex.`;
    const back = `workspace.html?id=${encodeURIComponent(complexId)}`;
    select("#back-workspace").href = back; select("#cancel-facility").href = back;
    select("#facility-sport").replaceChildren(...sports.map(sport => { const option = element("option", "", sport.name); option.value = sport.id; return option; }));
    const data = facilityId ? await accountRequest(`/api/v1/staff/complexes/${encodeURIComponent(complexId)}/facilities/${encodeURIComponent(facilityId)}`) : null;
    populate(data); select("#facility-form").hidden = false;
  } catch (error) {
    select("#editor-error").hidden = false;
    select("#editor-error-title").textContent = error.status === 401 ? "Sign in to manage your facility." : error.status === 403 ? "Administrator access is required." : "We couldn’t load this facility.";
    select("#editor-error-message").textContent = error.message;
    select("#editor-retry").hidden = [401,403,404,422].includes(error.status) || !complexId;
  } finally { select("#editor-status").textContent = ""; }
}

select("#facility-sport").addEventListener("change", () => {
  const allowed = allowedDurations();
  document.querySelectorAll('[data-field="minutes"]').forEach(node => {
    const previous = Number(node.value);
    node.replaceChildren(...allowed.map(value => { const option = element("option", "", `${value} min`); option.value = String(value); return option; }));
    if (allowed.includes(previous)) node.value = String(previous);
  });
  updateEmptyStates();
});
select("#add-opening").addEventListener("click", () => openingRow());
select("#add-tariff").addEventListener("click", () => tariffRow());
select("#weekend-percent").addEventListener("input",updatePricingDescription);
select("#evening-percent").addEventListener("input",updatePricingDescription);
select("#editor-retry").addEventListener("click", initialize);
select("#reload-settings").addEventListener("click", initialize);

select("#facility-form").addEventListener("submit", async event => {
  event.preventDefault(); if (busy) return;
  const body = {
    name:select("#facility-name").value, sport_id:select("#facility-sport").value,
    surface:select("#facility-surface").value, description:select("#facility-description").value,
    active:select("#facility-active").checked,
    weekend_percent:select("#weekend-percent").value,
    evening_percent:select("#evening-percent").value,
    opening_hours:[...select("#opening-rows").children].map(row => ({
      weekday:Number(row.querySelector('[data-field="weekday"]').value), opens_at:row.querySelector('[data-field="opens_at"]').value, closes_at:row.querySelector('[data-field="closes_at"]').value,
    })),
    tariffs:[...select("#tariff-rows").children].map(row => ({minutes:Number(row.querySelector('[data-field="minutes"]').value), amount:row.querySelector('[data-field="amount"]').value})),
    ...(facilityId ? {version} : {}),
  };
  busy = true; select("#facility-fields").disabled = true; select("#facility-form").setAttribute("aria-busy", "true"); showMessage(""); select("#reload-settings").hidden = true;
  try {
    const data = await accountRequest(`/api/v1/staff/complexes/${encodeURIComponent(complexId)}/facilities${facilityId ? `/${encodeURIComponent(facilityId)}` : ""}`, {method:facilityId ? "PUT" : "POST",body,csrfToken:account.csrf_token});
    facilityId = data.id; populate(data);
    const url = new URL(location.href); url.searchParams.set("id", facilityId); history.replaceState(null,"",url);
    showMessage(data.active ? "Facility saved and published in the directory." : "Facility saved. It remains unpublished.", true);
  } catch (error) {
    showMessage(error.message); select("#reload-settings").hidden = error.status !== 409;
  } finally { busy = false; select("#facility-fields").disabled = false; select("#facility-form").setAttribute("aria-busy", "false"); }
});
initialize();
