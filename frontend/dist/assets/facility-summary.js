import { element } from "./catalog-ui.js";
import { pricingDescription } from "./pricing-rules.js";

const days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

export function facilitySummary(facility, currency, timezone) {
  const details = element("details", "facility-summary");
  details.append(element("summary", "", "Opening hours & prices"));
  details.append(element("p", "field-help", `Local times · ${timezone}`));
  if (!facility.opening_hours.length) details.append(element("p", "", "No opening hours published yet."));
  else {
    const list = element("ul", "hours-list");
    facility.opening_hours.forEach(row => list.append(element("li", "", `${days[row.weekday]} · ${row.opens_at}–${row.closes_at}`)));
    details.append(list);
  }
  if (!facility.tariffs.length) details.append(element("p", "", "No prices published yet."));
  else {
    details.append(element("h4","","Base prices"));
    const list = element("ul", "price-list");
    facility.tariffs.forEach(row => {
      const amount = Number(row.amount).toLocaleString("en", {minimumFractionDigits:2,maximumFractionDigits:2});
      list.append(element("li", "", `${row.minutes} min · ${amount} ${currency}`));
    });
    details.append(list);
    details.append(element("p","pricing-description",pricingDescription(facility)));
  }
  return details;
}
