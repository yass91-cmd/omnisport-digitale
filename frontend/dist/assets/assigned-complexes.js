import { accountRequest } from "./auth-api.js";
import { element } from "./catalog-ui.js";

export function showAssignedComplexes(container, assignments) {
  container.replaceChildren(...assignments.map(assignment => {
    const card = element("article", "assigned-complex-card");
    const link = element("a", "staff-link");
    link.href = `workspace.html?id=${encodeURIComponent(assignment.complex_id)}`;
    const badge = element("span", "notification-count");
    badge.dataset.notificationsComplex = assignment.complex_id;
    badge.hidden = true;
    link.append(element("strong", "", assignment.complex_name), element("span", "", `${assignment.city} · ${assignment.role === "admin" ? "Administrator" : "Employee"}`), badge);
    card.append(link);
    if (assignment.role === "admin") {
      const section = element("section", "assigned-people"), list = element("ul", "assigned-people-list");
      const message = element("p", "field-help", "Loading assigned staff…");
      message.setAttribute("role", "status");
      section.append(element("h3", "", "Assigned staff"), list, message); card.append(section);
      accountRequest(`/api/v1/staff/complexes/${encodeURIComponent(assignment.complex_id)}/staff`).then(people => {
        list.replaceChildren(...people.map(person => {
          const row = element("li", "assigned-person");
          row.append(element("strong", "", person.name), element("span", "", person.role === "admin" ? "Administrator" : "Employee"), element("small", "", person.email));
          return row;
        }));
        message.textContent = people.length ? "" : "No staff assigned yet.";
      }).catch(() => { message.textContent = "Couldn’t load assigned staff. Refresh to try again."; });
    }
    return card;
  }));
}
