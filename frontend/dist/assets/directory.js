import { SPORTS } from "./media.js";
import { element, readApi, sportLabels } from "./catalog-ui.js";

const filters = [...document.querySelectorAll("[data-filter]")];
const citySelect = document.querySelector("#city-filter");
const grid = document.querySelector("#complex-grid");
const status = document.querySelector("#catalog-status");
const message = document.querySelector("#catalog-message");
const action = document.querySelector("#catalog-retry");
const params = new URLSearchParams(window.location.search);
let sport = Object.hasOwn(SPORTS, params.get("sport")) ? params.get("sport") : "all";
let city = params.get("city") || "";
let request = null;
let actionMode = "retry";

function reflectSelection() {
  filters.forEach(button => button.setAttribute("aria-pressed", String(button.dataset.filter === sport)));
  const url = new URL(window.location.href);
  if (sport === "all") url.searchParams.delete("sport");
  else url.searchParams.set("sport", sport);
  if (city) url.searchParams.set("city", city);
  else url.searchParams.delete("city");
  window.history.replaceState(null, "", url);
}

function card(complex) {
  const article = element("article", "complex-card");
  const art = element("div", "complex-card-art");
  const image = element("img");
  image.src = "assets/complex-art.svg";
  image.alt = "";
  image.loading = "lazy";
  art.append(image);
  if (complex.is_demo) art.append(element("span", "demo-badge", "Demo complex"));
  const body = element("div", "complex-card-body");
  body.append(element("p", "complex-card-city", complex.city));
  body.append(element("h2", "", complex.name));
  body.append(element("p", "complex-card-description", complex.description));
  body.append(sportLabels(complex.sports));
  const footer = element("div", "complex-card-footer");
  footer.append(element("span", "facility-count", `${complex.facility_count} ${complex.facility_count === 1 ? "facility" : "facilities"}`));
  const link = element("a", "primary-button", "View facilities");
  link.href = `complex.html?id=${encodeURIComponent(complex.id)}`;
  link.setAttribute("aria-label", `View facilities at ${complex.name}`);
  footer.append(link);
  body.append(footer);
  article.append(art, body);
  return article;
}

async function loadComplexes() {
  request?.abort();
  const controller = new AbortController();
  request = controller;
  grid.setAttribute("aria-busy", "true");
  grid.replaceChildren();
  message.hidden = true;
  document.querySelector("#demo-notice").hidden = true;
  status.textContent = "Finding your next place to play…";
  reflectSelection();
  const query = new URLSearchParams();
  if (sport !== "all") query.set("sport", sport);
  if (city) query.set("city", city);
  try {
    const data = await readApi(`/api/v1/complexes?${query}`, controller.signal);
    if (controller.signal.aborted) return;
    grid.replaceChildren(...data.items.map(card));
    status.textContent = `${data.total} ${data.total === 1 ? "complex" : "complexes"} found`;
    document.querySelector("#demo-notice").hidden = !data.items.length || !data.items.every(item => item.is_demo);
    if (!data.items.length) {
      actionMode = "clear";
      document.querySelector("#empty-title").textContent = "No matches this time.";
      document.querySelector("#directory-message").textContent = "Try another city or sport to find your place.";
      action.textContent = "Clear filters";
      message.hidden = false;
    }
  } catch (error) {
    if (controller.signal.aborted) return;
    status.textContent = "";
    actionMode = "retry";
    document.querySelector("#empty-title").textContent = "We couldn't load the complexes.";
    document.querySelector("#directory-message").textContent = "Please try again in a moment.";
    action.textContent = "Try again";
    message.hidden = false;
  } finally {
    if (request === controller) grid.setAttribute("aria-busy", "false");
  }
}

async function loadCities() {
  try {
    const cities = await readApi("/api/v1/cities");
    const allCities = element("option", "", "All cities");
    allCities.value = "";
    citySelect.replaceChildren(allCities);
    cities.forEach(name => {
      const option = element("option", "", name);
      option.value = name;
      citySelect.append(option);
    });
    if (city && !cities.includes(city)) {
      const option = element("option", "", city);
      option.value = city;
      citySelect.append(option);
    }
    citySelect.value = city;
  } catch {
    // The main results region provides the retry state.
  }
}

filters.forEach(button => button.addEventListener("click", () => {
  sport = button.dataset.filter;
  loadComplexes();
}));
citySelect.addEventListener("change", () => { city = citySelect.value; loadComplexes(); });
action.addEventListener("click", () => {
  if (actionMode === "clear") { sport = "all"; city = ""; citySelect.value = ""; }
  if (actionMode === "retry") loadCities();
  loadComplexes();
});
window.addEventListener("pagehide", () => request?.abort());
loadCities();
loadComplexes();
