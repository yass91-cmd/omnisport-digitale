import { accountRequest } from "./auth-api.js";
import { element } from "./catalog-ui.js";

const $=selector=>document.querySelector(selector);
let account=null,busy=false,offset=0;
const status=text=>{$("#inbox-status").textContent=text;};

function setBusy(value){busy=value;document.querySelectorAll("button").forEach(button=>button.disabled=value);}

async function decide(requestId,decision){
  if(busy)return;
  setBusy(true);
  try{
    await accountRequest(`/api/v1/teams/requests/${requestId}/decide`,{method:"POST",body:{action:decision},csrfToken:account.csrf_token});
    await load();status(decision==="accept"?"Player accepted.":decision==="decline"?"Request declined.":"Request withdrawn.");
  }catch(error){status(error.message);}
  finally{setBusy(false);}
}

function requestRow(item){
  const coach=account.client_role==="coach";
  const node=element("article","team-row"),copy=element("div","team-copy"),actions=element("div","team-actions");
  copy.append(element("h3","",coach?item.player_name:item.team_name));
  copy.append(element("p","",coach?`${item.team_name} · ${item.sport}`:`${item.sport} · ${item.kind==="invite"?"Invitation":"Join request"}`));
  if(item.status==="pending"){
    const recipient=coach?item.kind==="join":item.kind==="invite";
    if(recipient){
      const accept=element("button","primary-button","Accept"),decline=element("button","secondary-button","Decline");
      accept.type=decline.type="button";accept.addEventListener("click",()=>decide(item.id,"accept"));decline.addEventListener("click",()=>decide(item.id,"decline"));actions.append(accept,decline);
    }else{
      const withdraw=element("button","secondary-button","Withdraw");withdraw.type="button";withdraw.addEventListener("click",()=>decide(item.id,"withdraw"));actions.append(withdraw);
    }
  }else actions.append(element("span","status-badge",item.status));
  node.append(copy,actions);return node;
}

async function load(){
  try{
    account=await accountRequest("/api/v1/auth/me");
    const page=await accountRequest(`/api/v1/teams/activity?offset=${offset}`);
    $("#inbox-login").hidden=true;$("#inbox-content").hidden=false;
    const sorted=[...page.requests].sort((left,right)=>Number(right.status==="pending")-Number(left.status==="pending"));
    $("#team-requests").replaceChildren(...sorted.map(requestRow));
    if(!sorted.length)$("#team-requests").append(element("p","empty-state","No team requests."));
    $("#inbox-previous").hidden=offset===0;$("#inbox-next").hidden=!page.has_more;status("");
  }catch(error){status(error.message);if(error.status===401){$("#inbox-content").hidden=true;$("#inbox-login").hidden=false;}}
}

$("#inbox-previous").addEventListener("click",()=>{offset=Math.max(0,offset-50);load();});
$("#inbox-next").addEventListener("click",()=>{offset+=50;load();});
window.addEventListener("pageshow",event=>{if(event.persisted)load();});
load();
