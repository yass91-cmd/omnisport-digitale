import { element } from "./catalog-ui.js";
import { weekdays, weeklyPlan, weeklyHours } from "./opening-hours.js";

const select = value=>document.querySelector(value);
let sequence=0;
function timeSelect(value,closing=false) {
  const node=element("select"), values=Array.from({length:48},(_,i)=>`${String(Math.floor(i/2)).padStart(2,"0")}:${i%2?"30":"00"}`);
  if(value&&!values.includes(value)) values.push(value);
  values.sort().forEach(time=>{const option=element("option","",time==="00:00"&&closing?"00:00 · midnight":time);option.value=time;node.append(option);});
  node.value=value;node.required=true;return node;
}
function control(parent,label,node) {
  const wrapper=element("div","settings-field"), caption=element("label","",label);node.id=`week-setting-${++sequence}`;caption.htmlFor=node.id;wrapper.append(caption,node);parent.append(wrapper);return node;
}
function usual() {return {opens_at:select("#usual-opens").value,closes_at:select("#usual-closes").value};}
function summary(row) {
  const open=row.querySelector('[data-week-open]').checked, custom=row.dataset.custom==="true";
  row.querySelector(".day-hours-summary").textContent=!open?"Closed":custom?"Different hours":`${usual().opens_at}–${usual().closes_at}`;
  row.querySelector(".day-hours-change").hidden=!open;
  row.querySelector(".day-hours-change").textContent=custom?"Use usual hours":"Change hours";
  row.querySelector(".day-hours-change").setAttribute("aria-label",`${custom?"Use usual":"Change"} ${weekdays[Number(row.dataset.weekday)]} hours`);
  row.querySelector(".day-hours-periods").hidden=!open||!custom;
}
function period(row,data) {
  const line=element("div","day-hour-period"), start=timeSelect(data.opens_at),end=timeSelect(data.closes_at,true);
  start.dataset.weekField="opens_at";end.dataset.weekField="closes_at";
  control(line,"Opens",start);control(line,"Closes",end);
  const remove=element("button","remove-setting","Remove period");remove.type="button";
  remove.addEventListener("click",()=>{if(row.querySelectorAll(".day-hour-period").length>1)line.remove();row.querySelectorAll(".day-hour-period .remove-setting").forEach(button=>{button.disabled=row.querySelectorAll(".day-hour-period").length<2;});});line.append(remove);
  row.querySelector(".day-hours-period-list").append(line);
  row.querySelectorAll(".day-hour-period .remove-setting").forEach(button=>{button.disabled=row.querySelectorAll(".day-hour-period").length<2;});
}
export function renderWeeklyHours(hours) {
  const plan=weeklyPlan(hours);sequence=0;
  const start=timeSelect(plan.usual.opens_at),end=timeSelect(plan.usual.closes_at,true);
  const defaults=select("#usual-hours");defaults.replaceChildren();
  control(defaults,"Usual opening time",start);start.id="usual-opens";start.previousElementSibling?.setAttribute("for","usual-opens");
  control(defaults,"Usual closing time",end);end.id="usual-closes";end.previousElementSibling?.setAttribute("for","usual-closes");
  const rows=select("#weekly-hours");rows.replaceChildren();
  plan.days.forEach(day=>{
    const row=element("div","weekday-hours-row"), label=element("label","day-open-label"),checkbox=element("input");
    row.dataset.weekday=String(day.weekday);row.dataset.custom=String(day.custom);checkbox.type="checkbox";checkbox.checked=day.open;checkbox.dataset.weekOpen="";
    label.append(checkbox,element("strong","",weekdays[day.weekday]));
    const status=element("span","day-hours-summary"),change=element("button","text-link day-hours-change","Change hours");change.type="button";change.setAttribute("aria-label",`Change ${weekdays[day.weekday]} hours`);
    const header=element("div","day-hours-header");header.append(label,status,change);row.append(header);
    const periods=element("div","day-hours-periods"),list=element("div","day-hours-period-list"),add=element("button","text-link","Add another period");add.type="button";add.setAttribute("aria-label",`Add another ${weekdays[day.weekday]} period`);periods.append(list,add);row.append(periods);rows.append(row);
    day.intervals.forEach(data=>period(row,data));
    checkbox.addEventListener("change",()=>summary(row));
    change.addEventListener("click",()=>{
      const custom=row.dataset.custom!=="true";row.dataset.custom=String(custom);
      if(custom&&!day.custom){list.replaceChildren();period(row,usual());}
      summary(row);
    });
    add.addEventListener("click",()=>{const last=list.lastElementChild?.querySelector('[data-week-field="closes_at"]').value;period(row,{opens_at:last&&last!=="00:00"?last:usual().opens_at,closes_at:"00:00"});});
    summary(row);
  });
  for(const node of [start,end])node.addEventListener("change",()=>rows.querySelectorAll(".weekday-hours-row").forEach(summary));
}
export function readWeeklyHours() {
  return weeklyHours({usual:usual(),days:[...select("#weekly-hours").children].map(row=>({
    weekday:Number(row.dataset.weekday),open:row.querySelector('[data-week-open]').checked,custom:row.dataset.custom==="true",
    intervals:[...row.querySelectorAll(".day-hour-period")].map(line=>({opens_at:line.querySelector('[data-week-field="opens_at"]').value,closes_at:line.querySelector('[data-week-field="closes_at"]').value})),
  }))});
}
