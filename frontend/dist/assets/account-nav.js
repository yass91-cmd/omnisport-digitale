import { accountRequest } from "./auth-api.js";

const links = [...document.querySelectorAll("[data-account-link]")];
if (links.length) {
  accountRequest("/api/v1/auth/session").then(account => {
    links.forEach(link => {
      const label = link.querySelector("[data-account-label]") || link;
      label.textContent = account ? "My account" : "Sign in";
    });
  }).catch(() => {});
}
