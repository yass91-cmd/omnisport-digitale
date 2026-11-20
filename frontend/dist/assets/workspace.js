import { accountRequest } from "./auth-api.js";
import { element } from "./catalog-ui.js";

const select = value => document.querySelector(value);
const id = new URLSearchParams(location.search).get("id");

function renderFacilities(data) {
  const groups = new Map();
  data.facilities.forEach(facility => {
    const key = facility.sport_id;
    if (!groups.has(key)) groups.set(key,{name:facility.sport,id:key,facilities:[]});
    groups.get(key).facilities.push(facility);
  });
  const sections = [...groups.values()].sort((left,right) => left.name.localeCompare(right.name)).map((group,index) => {
    const section = element("section","workspace-sport"), heading = element("h3","workspace-sport-title",group.name);
    heading.id = `workspace-sport-${index}`; section.setAttribute("aria-labelledby",heading.id);
    section.append(heading,element("p","field-help",`${group.facilities.length} ${group.facilities.length === 1 ? "facility" : "facilities"}`));
    if (data.role === "admin") {
      const add = element("a","text-link sport-add",`Add ${group.name} facility`);
      add.href = `facility.html?complex_id=${encodeURIComponent(id)}&sport_id=${encodeURIComponent(group.id)}`; section.append(add);
    }
    const grid = element("div","facility-grid");
    group.facilities.forEach(facility => {
      const card = element("article","facility-card");
      card.append(element("span","role-badge",facility.active ? "Active" : "Inactive"),element("h4","",facility.name),element("p","facility-surface",facility.surface));
      if (data.role === "admin") {
        const edit = element("a","text-link","Edit settings");
        edit.href = `facility.html?complex_id=${encodeURIComponent(id)}&id=${encodeURIComponent(facility.id)}`;
        edit.setAttribute("aria-label",`Edit settings for ${facility.name}`); card.append(edit);
      }
      grid.append(card);
    });
    section.append(grid); return section;
  });
  select("#workspace-facilities").replaceChildren(...sections);
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
    select("#workspace-note").textContent = data.role === "admin" ? "Manage your facilities, opening hours and prices." : "View your complex’s facilities. Settings are managed by its administrator.";
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
