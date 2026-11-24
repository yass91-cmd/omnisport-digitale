export function safeReturn(value, origin, staff = false) {
  if (!value) return null;
  try {
    const url = new URL(value,origin);
    const allowed = ["/availability.html","/bookings.html","/teams.html","/team-inbox.html"];
    if (staff) allowed.push("/workspace.html","/staff-bookings.html","/closures.html","/facility.html","/notifications.html");
    return url.origin === origin && !url.username && !url.password && allowed.includes(url.pathname) ? `${url.pathname}${url.search}` : null;
  } catch { return null; }
}

export function localDateTime(value) {
  const date = new Intl.DateTimeFormat("en-GB",{timeZone:"UTC",day:"numeric",month:"short",year:"numeric"}).format(new Date(`${value.slice(0,10)}T12:00:00Z`));
  return `${date} · ${value.slice(11,16)}`;
}

export const money = (value,currency) => `${Number(value).toLocaleString("en",{minimumFractionDigits:2,maximumFractionDigits:2})} ${currency}`;
