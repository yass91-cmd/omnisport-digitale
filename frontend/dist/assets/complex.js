import { element, readApi } from "./catalog-ui.js";

const params = new URLSearchParams(window.location.search);
const id = params.get("id");
const detail = document.querySelector("#complex-detail");
const error = document.querySelector("#detail-error");
const status = document.querySelector("#detail-status");
const retry = document.querySelector("#detail-retry");

async function loadComplex() {
  detail.hidden = true;
  error.hidden = true;
  status.textContent = "Getting the facilities ready…";
  try {
    if (!id) throw Object.assign(new Error("Missing complex"), { status: 404 });
    const complex = await readApi(`/api/v1/complexes/${encodeURIComponent(id)}`);
    document.title = `${complex.name} — OmniSport Digitale`;
    document.querySelector("#complex-name").textContent = complex.name;
    document.querySelector("#complex-location").textContent = `${complex.city} · ${complex.address}`;
    document.querySelector("#complex-description").textContent = complex.description;
    document.querySelector("#detail-demo").hidden = !complex.is_demo;
    document.querySelector("#detail-demo-notice").hidden = !complex.is_demo;
    document.querySelector("#facility-count").textContent = `${complex.facilities.length} ${complex.facilities.length === 1 ? "facility" : "facilities"}`;
    const grid = document.querySelector("#facility-grid");
    grid.replaceChildren();
    complex.facilities.forEach(facility => {
      const card = element("article", "facility-card");
      card.dataset.sport = facility.sport.slug;
      card.append(element("span", "sport-label", facility.sport.name));
      card.append(element("h3", "", facility.name));
      card.append(element("p", "facility-surface", facility.surface));
      card.append(element("p", "", facility.description));
      grid.append(card);
    });
    if (!complex.facilities.length) grid.append(element("p", "catalog-note", "Facilities will be listed here when they open."));
    status.textContent = "";
    detail.hidden = false;
  } catch (failure) {
    const missing = failure.status === 404 || failure.status === 422;
    document.querySelector("#detail-error-title").textContent = missing ? "This complex isn't listed." : "We couldn't load this complex.";
    document.querySelector("#detail-error-message").textContent = missing ? "Explore the directory to find another place to play." : "Please try again in a moment.";
    retry.hidden = missing;
    status.textContent = "";
    error.hidden = false;
  }
}

retry.addEventListener("click", loadComplex);
loadComplex();
