import { element } from "./catalog-ui.js";
import { SPORTS } from "./media.js";

export function sportKey(name) {
  const value=String(name||"").trim().toLowerCase();
  return Object.keys(SPORTS).find(key=>key===value||SPORTS[key].name.toLowerCase()===value)||"other";
}
export function applySport(node,name) {node.dataset.sport=sportKey(name);}
export function sportCourt(name) {
  const art=element("div","comfort-court"),slab=element("div","court-slab"),key=sportKey(name);art.setAttribute("aria-hidden","true");
  const svg=document.createElementNS("http://www.w3.org/2000/svg","svg");svg.setAttribute("viewBox","0 0 180 100");
  const path=document.createElementNS(svg.namespaceURI,"path");
  const lines={football:"M10 10H170V90H10ZM90 10V90M10 30H35V70H10M170 30H145V70H170M106 50A16 16 0 1 0 74 50A16 16 0 1 0 106 50",basketball:"M10 10H170V90H10ZM90 10V90M10 30H40V70H10M170 30H140V70H170M105 50A15 15 0 1 0 75 50A15 15 0 1 0 105 50",tennis:"M10 10H170V90H10ZM90 10V90M10 24H170M10 76H170M45 24V76M135 24V76M45 50H135"};
  path.setAttribute("d",lines[key]||lines.football);svg.append(path);slab.append(svg);art.append(slab);return art;
}
export function sportBadge(name) {
  const badge=element("span","sport-tag"),key=sportKey(name);
  applySport(badge,name);
  const icon=document.createElementNS("http://www.w3.org/2000/svg","svg");
  icon.setAttribute("viewBox","0 0 24 24");icon.setAttribute("aria-hidden","true");
  icon.setAttribute("fill","none");icon.setAttribute("stroke","currentColor");icon.setAttribute("stroke-width","1.6");
  const circle=document.createElementNS(icon.namespaceURI,"circle");circle.setAttribute("cx","12");circle.setAttribute("cy","12");circle.setAttribute("r","9");icon.append(circle);
  const lines={football:"M12 7 17 11 15 17H9L7 11ZM12 3V7M21 9 17 11M18 20 15 17M6 20 9 17M3 9 7 11",basketball:"M3 12H21M12 3V21M6 5C16 10 16 14 6 19M18 5C8 10 8 14 18 19",tennis:"M5 6C14 6 14 18 5 18M19 6C10 6 10 18 19 18"};
  if(lines[key]){const path=document.createElementNS(icon.namespaceURI,"path");path.setAttribute("d",lines[key]);icon.append(path);}
  badge.append(icon,element("span","",SPORTS[key]?.name||name||"Facility"));return badge;
}
