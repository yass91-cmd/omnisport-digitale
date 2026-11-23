import { MEDIA, SPORTS } from "./media.js";
import { createSportsScene } from "./scene.js";
import { createIntroPlayer } from "./intro.js";

const reducedMotion=window.matchMedia("(prefers-reduced-motion: reduce)");
const scene=createSportsScene(document.querySelector("#sport-scene"),reducedMotion.matches);
const video=document.querySelector("#sport-video");
const status=document.querySelector("#experience-status");
const motionButton=document.querySelector("#motion-toggle");
const soundButton=document.querySelector("#sound-toggle");
let selectedSport="football",paused=reducedMotion.matches,mediaVersion=0,introActive=false;

function setSport(value,announce=true){
  if(!Object.hasOwn(SPORTS,value))return;
  selectedSport=value;
  const sport=SPORTS[value];
  document.body.dataset.sport=value;
  document.querySelectorAll("[data-sport-choice]").forEach(button=>{
    const active=button.dataset.sportChoice===value;
    button.classList.toggle("is-active",active);
    button.setAttribute("aria-pressed",String(active));
  });
  document.querySelector("#scene-label").textContent=sport.caption;
  document.querySelector("#find-place").href=`complexes.html?sport=${value}`;
  document.querySelector("[data-explore]").href=`complexes.html?sport=${value}`;
  scene.setSport(value);
  loadVideo(value);
  if(announce)status.textContent=`${sport.name} selected.`;
}

function loadVideo(sport){
  const version=++mediaVersion;
  const media=MEDIA[sport];
  video.pause();
  video.classList.remove("is-ready");
  video.parentElement.classList.remove("has-video");
  video.removeAttribute("src");
  video.removeAttribute("poster");
  if(!media.video){video.load();return;}
  video.src=media.video;
  if(media.poster)video.poster=media.poster;
  video.onloadeddata=async()=>{
    if(version!==mediaVersion)return;
    try{
      if(!paused&&!introActive)await video.play();
      if(version!==mediaVersion)return;
      video.classList.add("is-ready");
      video.parentElement.classList.add("has-video");
    }catch{
      // Keep the animated/static geometry if video playback is unavailable.
    }
  };
  video.onerror=()=>{
    video.classList.remove("is-ready");
    video.parentElement.classList.remove("has-video");
  };
  video.load();
}

function setPaused(value){
  paused=value;scene.setPaused(value||introActive);
  motionButton.setAttribute("aria-pressed",String(value));
  motionButton.textContent=value?"Play motion":"Pause motion";
  if(value||introActive)video.pause();
  else if(MEDIA[selectedSport].video)video.play().catch(()=>{});
}

document.querySelectorAll("[data-sport-choice]").forEach(button=>button.addEventListener("click",()=>setSport(button.dataset.sportChoice)));
motionButton.addEventListener("click",()=>setPaused(!paused));
reducedMotion.addEventListener("change",event=>setPaused(event.matches));

// Original quiet preview beat. A supplied soundtrack replaces it via MEDIA.
class PreviewSound{
  constructor(){this.context=null;this.timer=null;this.audio=null;this.playing=false;this.nextBeat=0;this.step=0;}
  async start(){
    if(MEDIA.soundtrack){
      this.audio??=new Audio(MEDIA.soundtrack);
      this.audio.loop=true;this.audio.volume=.22;
      await this.audio.play();this.playing=true;return;
    }
    const AudioContext=window.AudioContext||window.webkitAudioContext;
    if(!AudioContext)throw new Error("Audio is unavailable");
    this.context??=new AudioContext();
    await this.context.resume();
    if(!this.master){this.master=this.context.createGain();this.master.gain.value=.11;this.master.connect(this.context.destination);}
    this.playing=true;this.nextBeat=this.context.currentTime+.05;this.step=0;
    this.timer=window.setInterval(()=>this.schedule(),70);this.schedule();
  }
  schedule(){
    while(this.playing&&this.nextBeat<this.context.currentTime+.15){
      const at=this.nextBeat;
      if(this.step%4===0)this.tone(at,125,42,.22,.9,"sine");
      if(this.step%2===0)this.hat(at);
      if(this.step%8===2)this.tone(at,110,110,.13,.25,"triangle");
      if(this.step%16===10)this.tone(at,164.81,164.81,.32,.16,"sine");
      this.nextBeat+=60/108/4;this.step++;
    }
  }
  tone(at,frequency,end,duration,volume,type){
    const oscillator=this.context.createOscillator(),gain=this.context.createGain();
    oscillator.type=type;oscillator.frequency.setValueAtTime(frequency,at);
    oscillator.frequency.exponentialRampToValueAtTime(end,at+duration);
    gain.gain.setValueAtTime(.001,at);gain.gain.exponentialRampToValueAtTime(volume,at+.008);gain.gain.exponentialRampToValueAtTime(.001,at+duration);
    oscillator.connect(gain);gain.connect(this.master);oscillator.start(at);oscillator.stop(at+duration+.02);
    oscillator.onended=()=>{oscillator.disconnect();gain.disconnect();};
  }
  hat(at){
    const duration=.045,buffer=this.context.createBuffer(1,this.context.sampleRate*duration,this.context.sampleRate);
    const samples=buffer.getChannelData(0);
    for(let i=0;i<samples.length;i++)samples[i]=(Math.random()*2-1)*(1-i/samples.length);
    const source=this.context.createBufferSource(),filter=this.context.createBiquadFilter(),gain=this.context.createGain();
    source.buffer=buffer;filter.type="highpass";filter.frequency.value=8500;gain.gain.value=.13;
    source.connect(filter);filter.connect(gain);gain.connect(this.master);source.start(at);
    source.onended=()=>{source.disconnect();filter.disconnect();gain.disconnect();};
  }
  async stop(){
    this.playing=false;clearInterval(this.timer);this.timer=null;
    this.audio?.pause();
    if(this.context?.state==="running")await this.context.suspend();
  }
}

const sound=new PreviewSound();
let soundBusy=false;
async function toggleSound(){
  if(soundBusy)return;soundBusy=true;
  try{
    if(sound.playing)await sound.stop();else await sound.start();
    soundButton.setAttribute("aria-pressed",String(sound.playing));
    soundButton.setAttribute("aria-label",sound.playing?"Turn background sound off":"Turn background sound on");
    document.querySelector("#sound-label").textContent=sound.playing?"Sound on":"Sound off";
    status.textContent=sound.playing?"Background sound on.":"Background sound off.";
  }catch{
    await sound.stop();status.textContent="Sound could not start. You can keep exploring without sound.";
  }finally{soundBusy=false;}
}
soundButton.addEventListener("click",toggleSound);
document.addEventListener("visibilitychange",async()=>{
  if(document.hidden&&sound.playing){await sound.stop();soundButton.setAttribute("aria-pressed","false");soundButton.setAttribute("aria-label","Turn background sound on");document.querySelector("#sound-label").textContent="Sound off";}
});

window.addEventListener("pagehide",()=>sound.stop());

const intro=createIntroPlayer({
  onOpen(){
    introActive=true;
    scene.setPaused(true);
    video.pause();
    if(sound.playing){
      void sound.stop();
      soundButton.setAttribute("aria-pressed","false");
      soundButton.setAttribute("aria-label","Turn background sound on");
      document.querySelector("#sound-label").textContent="Sound off";
    }
  },
  onClose(){introActive=false;setPaused(paused);},
  announce(message){status.textContent=message;},
});

setSport("football",false);setPaused(paused);intro.startIfNeeded();
