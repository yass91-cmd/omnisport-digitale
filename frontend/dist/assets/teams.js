import { accountRequest } from "./auth-api.js";
import { element } from "./catalog-ui.js";

const $=selector=>document.querySelector(selector);
let account=null,busy=false,offset=0,owned=[],activity={members:[],requests:[],has_more:false},selectedTeamId=null;

const status=text=>{$("#team-status").textContent=text;};
const setBusy=value=>{busy=value;document.querySelectorAll("button").forEach(button=>button.disabled=value);};

function row(title,subtitle=""){
  const node=element("article","team-row"),copy=element("div","team-copy"),actions=element("div","team-actions");
  copy.append(element("h3","",title));
  if(subtitle)copy.append(element("p","",subtitle));
  node.append(copy,actions);
  return {node,actions};
}

function confirmAction(container,label,path,body={},message=""){
  const button=element("button","secondary-button",label);button.type="button";
  button.addEventListener("click",()=>{
    if(busy)return;
    if(!message){mutate(path,body);return;}
    if(container.querySelector(".team-confirmation"))return;
    const box=element("div","team-confirmation"),confirm=element("button","primary-button",label),cancel=element("button","secondary-button","Cancel");
    confirm.type=cancel.type="button";
    confirm.addEventListener("click",()=>mutate(path,body));
    cancel.addEventListener("click",()=>box.remove());
    box.append(element("p","",message),confirm,cancel);container.append(box);confirm.focus();
  });
  container.append(button);
}

async function mutate(path,body={}){
  if(busy)return;
  setBusy(true);
  try{
    await accountRequest(path,{method:"POST",body,csrfToken:account.csrf_token});
    if(path==="/api/v1/teams"){$("#create-team").reset();$("#create-team").hidden=true;}
    if(path.includes("/players")&&path.endsWith("/players")){$("#add-player-form").reset();$("#add-player-form").hidden=true;}
    await load();status("Saved successfully.");
  }catch(error){status(error.message);if(error.status===401){$("#team-content").hidden=true;$("#team-login").hidden=false;}}
  finally{setBusy(false);}
}

function showHome(panel="teams"){
  selectedTeamId=null;
  $("#teams-home").hidden=false;$("#team-detail").hidden=true;$("#add-player-view").hidden=true;
  $("#teams-panel").hidden=panel!=="teams";$("#discover-panel").hidden=panel!=="discover";
  $("#create-team").hidden=true;
  window.scrollTo({top:0,behavior:"smooth"});
}

function teamMembers(teamId){return activity.members.filter(member=>member.team_id===teamId);}

function drawTeamCards(){
  const coach=account.client_role==="coach";
  const teams=coach?owned:activity.members.map(member=>({id:member.team_id,name:member.team_name,sport:member.sport}));
  const unique=[...new Map(teams.map(team=>[team.id,team])).values()];
  const cards=unique.map(team=>{
    const card=element("button","team-card");card.type="button";
    card.append(element("h2","",team.name),element("span","team-card-arrow","→"));
    card.addEventListener("click",()=>showTeam(team.id));return card;
  });
  $("#owned-teams").replaceChildren(...cards);
  if(!cards.length)$("#owned-teams").append(element("p","empty-state",coach?"No teams yet.":"You have not joined a team yet."));
}

function showTeam(teamId){
  const coach=account.client_role==="coach";
  const team=coach?owned.find(item=>item.id===teamId):activity.members.find(item=>item.team_id===teamId);
  if(!team)return;
  selectedTeamId=teamId;$("#teams-home").hidden=true;$("#team-detail").hidden=false;$("#add-player-view").hidden=true;
  $("#detail-name").textContent=team.name||team.team_name;$("#detail-sport").textContent=team.sport;
  $("#add-player-toggle").hidden=!coach;
  const members=teamMembers(teamId);$("#player-count").textContent=String(members.length);
  const visibleMembers=coach?members:members.filter(member=>member.team_id===teamId);
  const roster=visibleMembers.map(member=>{
    const item=element("article","roster-row");
    item.append(element("span","roster-name",member.player_name));
    item.append(element("span","roster-contact",coach?(member.phone||member.email||"Registered player"):"Team member"));
    const actions=element("div","team-actions");
    const path=member.contact_member?`/api/v1/teams/players/${member.id}/remove`:`/api/v1/teams/memberships/${member.id}/leave`;
    confirmAction(actions,coach?"Remove":"Leave",path,{},coach?`Remove ${member.player_name} from this team?`:`Leave ${team.team_name}?`);
    item.append(actions);return item;
  });
  $("#team-roster").replaceChildren(...roster);
  if(!roster.length)$("#team-roster").append(element("p","empty-state","No players yet."));
  window.scrollTo({top:0,behavior:"smooth"});
}

function showAddPlayer(){
  if(!selectedTeamId||account.client_role!=="coach")return;
  $("#teams-home").hidden=true;$("#team-detail").hidden=true;$("#add-player-view").hidden=false;
  $("#add-player-form").hidden=false;
  $("#player-name").focus();window.scrollTo({top:0,behavior:"smooth"});
}

function updateInboxLink(){
  const pending=activity.requests.filter(item=>item.status==="pending").length;
  $("#requests-toggle").textContent=pending?`Inbox (${pending})`:"Inbox";
}

async function discover(){
  const filter=$("#sport-filter").value;
  const page=await accountRequest(`/api/v1/teams?offset=${offset}${filter?`&sport_id=${encodeURIComponent(filter)}`:""}`);
  const items=page.items.map(team=>{
    const {node,actions}=row(team.name,`${team.sport} · ${team.coach_name}`);
    if(activity.members.some(member=>member.team_id===team.id))actions.append(element("span","status-badge","Your team"));
    else if(activity.requests.some(request=>request.team_id===team.id&&request.status==="pending"))actions.append(element("span","status-badge","Requested"));
    else confirmAction(actions,"Request to join",`/api/v1/teams/${team.id}/join`,{},`Send a request to ${team.name}?`);
    return node;
  });
  $("#open-teams").replaceChildren(...items);
  if(!items.length)$("#open-teams").append(element("p","empty-state","No teams found."));
  $("#teams-prev").hidden=offset===0;$("#teams-next").hidden=!page.has_more;
}

async function load(){
  try{
    account=await accountRequest("/api/v1/auth/me");
    $("#team-login").hidden=true;$("#team-content").hidden=false;
    const coach=account.client_role==="coach";
    $("#create-toggle").hidden=!coach;$("#find-toggle").hidden=coach;
    activity=await accountRequest("/api/v1/teams/activity");
    if(coach){
      owned=[];let pageOffset=0;
      while(true){const page=await accountRequest(`/api/v1/teams?mine=true&offset=${pageOffset}`);owned.push(...page.items);if(!page.has_more)break;pageOffset+=50;}
    }
    drawTeamCards();updateInboxLink();
    if(!coach)await discover();
    if(selectedTeamId)showTeam(selectedTeamId);
    status("");
  }catch(error){status(error.message);if(error.status===401){$("#team-content").hidden=true;$("#team-login").hidden=false;}}
}

$("#create-toggle").addEventListener("click",()=>{$("#create-team").hidden=!$("#create-team").hidden;if(!$("#create-team").hidden)$("#team-name").focus();});
$("#create-cancel").addEventListener("click",()=>{$("#create-team").hidden=true;});
$("#create-team").addEventListener("submit",event=>{event.preventDefault();mutate("/api/v1/teams",{name:$("#team-name").value.trim(),sport_id:$("#team-sport").value});});
$("#detail-back").addEventListener("click",()=>showHome());
$("#find-toggle").addEventListener("click",()=>showHome("discover"));$("#find-back").addEventListener("click",()=>showHome());
$("#add-player-toggle").addEventListener("click",showAddPlayer);
$("#add-player-back").addEventListener("click",()=>showTeam(selectedTeamId));
$("#add-player-cancel").addEventListener("click",()=>showTeam(selectedTeamId));
$("#add-player-form").addEventListener("submit",event=>{event.preventDefault();mutate(`/api/v1/teams/${selectedTeamId}/players`,{name:$("#player-name").value.trim(),phone:$("#player-phone").value.trim(),email:$("#player-email").value.trim()||null});});
$("#sport-filter").addEventListener("change",()=>{offset=0;discover();});
for(const [id,delta] of [["teams-prev",-50],["teams-next",50]])$("#"+id).addEventListener("click",()=>{offset+=delta;discover();});

async function start(){
  try{const sports=await accountRequest("/api/v1/sports");for(const sport of sports){for(const id of ["team-sport","sport-filter"]){const option=element("option","",sport.name);option.value=sport.id;$("#"+id).append(option);}}await load();}
  catch(error){status(error.message);}
}
window.addEventListener("pageshow",event=>{if(event.persisted)load();});
start();
