import { accountRequest } from "./auth-api.js";
import { element } from "./catalog-ui.js";
import { watchNotificationCounts } from "./notification-badge.js";
import { applySport, sportBadge, sportCourt } from "./sport-ui.js";

const select = value => document.querySelector(value);
const id = new URLSearchParams(location.search).get("id");
let stopNotifications = () => {};

function renderFacilities(data) {
  const groups = new Map();
  data.facilities.forEach(facility => {
    const key = facility.sport_id;
    if (!groups.has(key)) groups.set(key,{name:facility.sport,id:key,facilities:[]});
    groups.get(key).facilities.push(facility);
  });
  const orderedGroups=[...groups.values()].sort((left,right)=>left.name.localeCompare(right.name));
  const sections = orderedGroups.map((group,index) => {
    const section = element("section","workspace-sport"), heading = element("h3","workspace-sport-title",group.name);
    heading.id = `workspace-sport-${index}`; section.setAttribute("aria-labelledby",heading.id);
    applySport(section,group.name);
    const header=element("div","sport-section-header"),title=element("div","sport-section-title");
    heading.replaceChildren(sportBadge(group.name));title.append(heading,element("span","field-help",`${group.facilities.length} ${group.facilities.length === 1 ? "facility" : "facilities"}`));header.append(sportCourt(group.name),title);section.append(header);
    if (data.role === "admin") {
      const add = element("a","text-link sport-add",`Add ${group.name} facility`);
      add.href = `facility.html?complex_id=${encodeURIComponent(id)}&sport_id=${encodeURIComponent(group.id)}`; header.append(add);
    }
    const grid = element("div","facility-grid");
    group.facilities.forEach(facility => {
      const card = element("article","facility-card");
      const state=element("span",`status-badge ${facility.active?"published":"unpublished"}`,facility.active?"Published":"Unpublished");
      card.append(state,element("h4","",facility.name),element("p","facility-surface",facility.surface));
      const actions=element("div","facility-actions");
      if (facility.active || data.role === "admin") {
        const book = element("a","primary-button",facility.active?"Open schedule":"Preview schedule");
        book.href = `availability.html?complex_id=${encodeURIComponent(id)}&facility_id=${encodeURIComponent(facility.id)}&staff=1`;
        book.setAttribute("aria-label",`${facility.active?"Open":"Preview"} schedule for ${facility.name}`);actions.append(book);
      }
      if (data.role === "admin") {
        const edit = element("a","secondary-button","Settings");
        edit.href = `facility.html?complex_id=${encodeURIComponent(id)}&id=${encodeURIComponent(facility.id)}`;
        edit.setAttribute("aria-label",`Edit settings for ${facility.name}`); actions.append(edit);
        const closures = element("a","text-link","Closures");
        closures.href = `closures.html?complex_id=${encodeURIComponent(id)}&facility_id=${encodeURIComponent(facility.id)}`;
        closures.setAttribute("aria-label",`Manage closures for ${facility.name}`); actions.append(closures);
      }
      card.append(actions);
      grid.append(card);
    });
    section.append(grid); return section;
  });
  select("#workspace-facilities").replaceChildren(...sections);
  const filters=select("#workspace-sport-filters");filters.replaceChildren();
  if(sections.length>1){
    ["All sports",...orderedGroups].forEach((group,index)=>{
      const button=element("button","sport-filter",index?group.name:"All sports");button.type="button";
      if(index)applySport(button,group.name);button.setAttribute("aria-pressed",String(!index));
      button.addEventListener("click",()=>{sections.forEach(section=>{section.hidden=!!index&&section.dataset.sport!==button.dataset.sport;});filters.querySelectorAll("button").forEach(item=>item.setAttribute("aria-pressed",String(item===button)));});filters.append(button);
    });
  }
  if (!sections.length) select("#workspace-facilities").append(element("p","catalog-note","No facilities have been added yet. Add courts or pitches for the sports your complex offers."));
}

async function loadWorkspace() {
  select("#workspace-view").hidden = true; select("#workspace-error").hidden = true;
  select("#workspace-status").textContent = "Getting your complex ready…";
  try {
    if (!id) throw new Error("Choose a complex from your account page.");
    const data = await accountRequest(`/api/v1/staff/complexes/${encodeURIComponent(id)}`);
    select("#workspace-name").textContent = data.name;
    select("#workspace-city").textContent = data.city;
    select("#workspace-note").textContent = data.role === "admin" ? "Choose a sport, then open a facility’s schedule or settings." : "Choose a facility to enter a booking. Settings are managed by your administrator.";
    select("#complex-bookings").href = `staff-bookings.html?complex_id=${encodeURIComponent(id)}`;
    select("#complex-notifications").href = `notifications.html?complex_id=${encodeURIComponent(id)}`;
    stopNotifications();stopNotifications = watchNotificationCounts(data => {
      const complex = data.complexes.find(item => item.complex_id === id);
      const count = complex?.unread || 0;
      select("#notifications-count").hidden = !count;select("#notifications-count").textContent = String(count);
    });
    select("#add-facility").hidden = data.role !== "admin";
    select("#add-facility").href = `facility.html?complex_id=${encodeURIComponent(id)}`;
    select("#workspace-role").textContent = data.role === "admin" ? "Administrator" : "Employee";
    renderFacilities(data);
    select("#workspace-view").hidden = false;
    select("#workspace-staff").hidden = data.role !== "admin";
    select("#workspace-staff-list").replaceChildren();
    select("#staff-load-message").textContent = "";
    if (data.role === "admin") {
      try {
        const staff = await accountRequest(`/api/v1/staff/complexes/${encodeURIComponent(id)}/staff`);
        select("#workspace-staff-list").replaceChildren(...staff.map(person => {
          const row = element("div", "staff-link");
          row.append(element("strong", "", person.name), element("span", "", `${person.email} · ${person.role === "admin" ? "Administrator" : "Employee"}`));
          return row;
        }));
      } catch { select("#staff-load-message").textContent = "We couldn’t load the staff list. Try refreshing the page."; }
    }
  } catch (error) {
    select("#workspace-error").hidden = false;
    select("#workspace-error-title").textContent = error.status === 403 ? "This complex isn’t assigned to you." : error.status === 401 ? "Sign in to open your workspace." : "We couldn’t load this workspace.";
    select("#workspace-error-message").textContent = error.message;
    select("#workspace-retry").hidden = [401,403,422].includes(error.status) || !id;
  } finally { select("#workspace-status").textContent = ""; }
}
select("#workspace-retry").addEventListener("click", loadWorkspace);
window.addEventListener("pageshow", event => { if (event.persisted) loadWorkspace(); });
loadWorkspace();
