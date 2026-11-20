import { SPORTS } from "./media.js";

const filters = [...document.querySelectorAll("[data-filter]")];
const message = document.querySelector("#directory-message");

function selectSport(value) {
  const sport = Object.hasOwn(SPORTS, value) ? value : "all";
  filters.forEach(button => button.setAttribute("aria-pressed", String(button.dataset.filter === sport)));
  message.textContent = sport === "all"
    ? "No complexes are listed yet. Check back soon for your next place to play."
    : `No ${SPORTS[sport].name.toLowerCase()} complexes are listed yet. Check back soon for your next place to play.`;
  const url = new URL(window.location.href);
  if (sport === "all") url.searchParams.delete("sport");
  else url.searchParams.set("sport", sport);
  window.history.replaceState(null, "", url);
}

filters.forEach(button => button.addEventListener("click", () => selectSport(button.dataset.filter)));
selectSport(new URLSearchParams(window.location.search).get("sport"));
