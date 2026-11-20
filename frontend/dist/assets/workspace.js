import { accountRequest } from "./auth-api.js";
import { element } from "./catalog-ui.js";

const select = value => document.querySelector(value);
const id = new URLSearchParams(location.search).get("id");

async function loadWorkspace() {
  select("#workspace-view").hidden = true; select("#workspace-error").hidden = true;
  select("#workspace-status").textContent = "Getting your complex ready…";
  try {
    if (!id) throw new Error("Choose a complex from your account page.");
    const data = await accountRequest(`/api/v1/staff/complexes/${encodeURIComponent(id)}`);
    select("#workspace-name").textContent = data.name;
    select("#workspace-city").textContent = data.city;
    select("#workspace-role").textContent = data.role === "admin" ? "Administrator" : "Employee";
    select("#workspace-facilities").replaceChildren(...data.facilities.map(facility => {
      const card = element("article", "facility-card");
      card.append(element("span", "role-badge", facility.active ? "Active" : "Inactive"), element("h3", "", facility.name));
      return card;
    }));
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
