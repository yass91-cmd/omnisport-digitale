import { accountRequest } from "./auth-api.js";
import { element } from "./catalog-ui.js";

const select = selector => document.querySelector(selector);
let account = null;
let submitting = false;

function message(target, text, success = false) {
  const node = select(target);
  node.textContent = text;
  node.hidden = !text;
  node.classList.toggle("is-success", success);
}

function setMode(mode) {
  const register = mode === "register";
  select("#login-form").hidden = register;
  select("#register-form").hidden = !register;
  select("#auth-heading").textContent = register ? "Make yourself at home." : "Welcome back.";
  select("#auth-lead").textContent = register ? "Create your player account to get started." : "Sign in and find your next place to play.";
  document.querySelectorAll("[data-auth-mode]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.authMode === mode)));
  message("#auth-message", "");
}

function showProfile(data) {
  account = data;
  select("#auth-view").hidden = true;
  select("#profile-view").hidden = false;
  select("#client-role").textContent = data.client_role === "coach" ? "Coach" : "Player";
  select("#profile-heading").textContent = `Good to see you, ${data.name}.`;
  select("#profile-email").textContent = data.email;
  select("#profile-name").value = data.name;
  select("#staff-links").replaceChildren(...data.staff_assignments.map(assignment => {
    const link = element("a", "staff-link");
    link.href = `workspace.html?id=${encodeURIComponent(assignment.complex_id)}`;
    link.append(element("strong", "", assignment.complex_name));
    link.append(element("span", "", `${assignment.city} · ${assignment.role === "admin" ? "Administrator" : "Employee"}`));
    return link;
  }));
  select("#staff-section").hidden = !data.staff_assignments.length;
}

function showLogin() {
  account = null;
  select("#profile-view").hidden = true;
  select("#profile-form").reset();
  select("#profile-email").textContent = "";
  select("#profile-heading").textContent = "";
  select("#staff-links").replaceChildren();
  select("#auth-view").hidden = false;
}

async function initialize() {
  select("#auth-view").hidden = true;
  select("#profile-view").hidden = true;
  select("#account-status").textContent = "Getting your account ready…";
  select("#account-error").hidden = true;
  try {
    const data = await accountRequest("/api/v1/auth/session");
    if (data) showProfile(data);
    else { showLogin(); setMode(new URLSearchParams(location.search).get("mode") === "register" ? "register" : "login"); }
  } catch {
    select("#account-error").hidden = false;
    select("#auth-view").hidden = true;
    select("#profile-view").hidden = true;
  } finally { select("#account-status").textContent = ""; }
}

document.querySelectorAll("[data-auth-mode]").forEach(button => button.addEventListener("click", () => setMode(button.dataset.authMode)));
document.querySelectorAll("[data-password-toggle]").forEach(button => button.addEventListener("click", () => {
  const input = document.getElementById(button.dataset.passwordToggle);
  const show = input.type === "password";
  input.type = show ? "text" : "password";
  button.textContent = show ? "Hide" : "Show";
  button.setAttribute("aria-pressed", String(show));
  button.setAttribute("aria-label", `${show ? "Hide" : "Show"} ${input.id === "login-password" ? "sign-in" : "new"} password`);
}));

for (const mode of ["login", "register"]) {
  const form = select(`#${mode}-form`);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (submitting) return;
    const fields = new FormData(form);
    if (mode === "register" && fields.get("password") !== fields.get("confirmation")) {
      message("#auth-message", "The passwords don’t match. Please check them.");
      select("#confirm-password").focus();
      return;
    }
    const body = { email: fields.get("email"), password: fields.get("password") };
    if (mode === "register") body.name = fields.get("name");
    submitting = true;
    document.querySelectorAll("[data-auth-mode]").forEach(button => { button.disabled = true; });
    form.querySelector("fieldset").disabled = true;
    form.setAttribute("aria-busy", "true");
    message("#auth-message", "");
    try {
      const data = await accountRequest(`/api/v1/auth/${mode}`, { method: "POST", body });
      select("#login-form").reset(); select("#register-form").reset();
      showProfile(data);
      select("#profile-heading").setAttribute("tabindex", "-1"); select("#profile-heading").focus();
    } catch (error) { message("#auth-message", error.message); }
    finally {
      submitting = false;
      document.querySelectorAll("[data-auth-mode]").forEach(button => { button.disabled = false; });
      form.querySelector("fieldset").disabled = false; form.setAttribute("aria-busy", "false");
    }
  });
}

select("#profile-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (submitting) return;
  submitting = true;
  const fieldset = select("#profile-form fieldset");
  const body = { name: select("#profile-name").value };
  fieldset.disabled = true;
  try {
    showProfile(await accountRequest("/api/v1/auth/me", { method: "PATCH", body, csrfToken: account.csrf_token }));
    message("#profile-message", "Your name has been saved.", true);
  } catch (error) {
    if (error.status === 401) showLogin();
    message(error.status === 401 ? "#auth-message" : "#profile-message", error.message);
  } finally { fieldset.disabled = false; submitting = false; }
});

select("#sign-out").addEventListener("click", async () => {
  if (submitting) return;
  submitting = true;
  select("#sign-out").disabled = true;
  try {
    await accountRequest("/api/v1/auth/logout", { method: "POST", body: {}, csrfToken: account.csrf_token });
    showLogin(); setMode("login"); message("#auth-message", "You’ve signed out.", true);
  } catch (error) {
    if (error.status === 401) { showLogin(); setMode("login"); }
    message(error.status === 401 ? "#auth-message" : "#profile-message", error.message);
  } finally { select("#sign-out").disabled = false; submitting = false; }
});
select("#account-retry").addEventListener("click", initialize);
window.addEventListener("pageshow", event => { if (event.persisted) initialize(); });
initialize();
