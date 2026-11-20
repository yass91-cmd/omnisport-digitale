export async function accountRequest(path, { method = "GET", body, csrfToken } = {}) {
  const headers = {};
  if (method !== "GET") {
    headers["Content-Type"] = "application/json";
    headers["X-Omni-Request"] = "1";
    if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
  }
  const response = await fetch(path, {
    method, headers, credentials: "same-origin", cache: "no-store",
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });
  if (response.status === 204) return null;
  const data = await response.json();
  if (!response.ok) {
    let message = typeof data.detail === "string" ? data.detail : "Please check the form and try again.";
    if (response.status === 429) message += ` Wait ${response.headers.get("Retry-After") || "a few"} seconds.`;
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return data;
}
