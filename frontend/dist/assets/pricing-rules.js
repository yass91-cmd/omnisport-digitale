const percent = value => Number(value).toLocaleString("en", {maximumFractionDigits:2});

export function pricingDescription(data) {
  const weekend = Number(data.weekend_percent), evening = Number(data.evening_percent);
  const parts = [];
  if (weekend > 0) parts.push(`Saturday & Sunday: +${percent(weekend)}%.`);
  if (evening > 0) parts.push(`6–9 pm: +${percent(evening)}% for any overlap.`);
  if (weekend > 0 && evening > 0) parts.push(`Both together: +${percent(weekend + evening)}% total.`);
  return parts.join(" ") || "Base prices apply at all times.";
}
