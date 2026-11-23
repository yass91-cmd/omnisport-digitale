import { accountRequest } from "./auth-api.js";

export function watchNotificationCounts(render) {
  let stopped = false, pending = false;
  async function refresh() {
    if (stopped || pending || document.hidden) return;
    pending = true;
    try { const data = await accountRequest("/api/v1/staff/notifications/summary"); if (!stopped) render(data); }
    catch (error) {if ([401,403].includes(error.status)) {render({total:0,complexes:[]});stop();}}
    finally {pending = false;}
  }
  const timer = setInterval(refresh,30000);
  function stop() {stopped = true;clearInterval(timer);document.removeEventListener("visibilitychange",refresh);window.removeEventListener("pagehide",stop);}
  document.addEventListener("visibilitychange",refresh);window.addEventListener("pagehide",stop,{once:true});refresh();
  return stop;
}
