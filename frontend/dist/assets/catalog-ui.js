export function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export async function readApi(path, signal) {
  const response = await fetch(path, { signal, headers: { Accept: "application/json" } });
  if (!response.ok) {
    const error = new Error("The catalogue is unavailable.");
    error.status = response.status;
    throw error;
  }
  return response.json();
}

export function sportLabels(sports) {
  const list = element("div", "sport-labels");
  sports.forEach(sport => list.append(element("span", "sport-label", sport.name)));
  return list;
}
