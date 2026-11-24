export const weekdays = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"];

export function groupOpeningHours(hours) {
  const groups = new Map();
  for (const hour of hours) {
    const closes = hour.closes_at === "24:00" ? "00:00" : hour.closes_at;
    const key = `${hour.opens_at}/${closes}`;
    if (!groups.has(key)) groups.set(key,{weekdays:[],opens_at:hour.opens_at,closes_at:closes});
    groups.get(key).weekdays.push(hour.weekday);
  }
  return [...groups.values()].map(group => ({...group,weekdays:[...new Set(group.weekdays)].sort((a,b) => a-b)}));
}

export function expandOpeningHours(groups) {
  const hours = groups.flatMap((group,index) => {
    if (!group.weekdays.length) throw new Error(`Choose at least one day for opening interval ${index+1}, or remove that interval.`);
    return [...new Set(group.weekdays)].map(weekday => {
      if (!Number.isInteger(weekday) || weekday < 0 || weekday > 6) throw new Error("Choose a valid weekday.");
      return {weekday,opens_at:group.opens_at,closes_at:group.closes_at};
    });
  });
  if (hours.length > 56) throw new Error("Use no more than 56 daily opening intervals.");
  return hours.sort((a,b) => a.weekday-b.weekday || a.opens_at.localeCompare(b.opens_at));
}

export function weeklyPlan(hours) {
  const grouped = weekdays.map((_,weekday) => hours.filter(row => row.weekday === weekday).map(row=>({opens_at:row.opens_at,closes_at:row.closes_at === "24:00" ? "00:00" : row.closes_at})));
  const counts = new Map();
  grouped.filter(rows=>rows.length===1).forEach(([row])=>{const key=JSON.stringify(row);counts.set(key,(counts.get(key)||0)+1);});
  const common = [...counts].sort((a,b)=>b[1]-a[1])[0]?.[0];
  const usual = common ? JSON.parse(common) : grouped.find(rows=>rows.length)?.[0] || {opens_at:"09:00",closes_at:"23:00"};
  return {usual,days:grouped.map((rows,weekday)=>({weekday,open:!!rows.length,custom:rows.length>1 || (rows.length===1 && JSON.stringify(rows[0])!==JSON.stringify(usual)),intervals:rows.length?rows:[{...usual}]}))};
}

export function weeklyHours(plan) {
  return expandOpeningHours(plan.days.filter(day=>day.open).flatMap(day=>(day.custom?day.intervals:[plan.usual]).map(row=>({...row,weekdays:[day.weekday]}))));
}
