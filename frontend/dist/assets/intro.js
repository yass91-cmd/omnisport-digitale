import { MEDIA } from "./media.js";

const SEEN_KEY = "omnisport:intro-seen:v1";

export function createIntroPlayer({ onOpen, onClose, announce }) {
  const dialog = document.querySelector("#intro-dialog");
  const video = document.querySelector("#intro-video");
  const replay = document.querySelector("#replay-intro");
  const play = document.querySelector("#intro-play");
  const sound = document.querySelector("#intro-sound");
  const soundLabel = document.querySelector("#intro-sound-label");
  const source = MEDIA.intro?.video;
  let active = false;
  let closing = false;
  let returnFocus = null;
  let version = 0;

  function setMuted(muted) {
    video.muted = muted;
    sound.setAttribute("aria-pressed", String(!muted));
    sound.setAttribute("aria-label", muted ? "Turn intro sound on" : "Turn intro sound off");
    soundLabel.textContent = muted ? "Sound off" : "Sound on";
  }

  async function startPlayback() {
    const attempt = version;
    try {
      await video.play();
      if (!active || closing || attempt !== version) {
        video.pause();
        return;
      }
      play.hidden = true;
    } catch {
      if (active && !closing && attempt === version) play.hidden = false;
    }
  }

  function finish() {
    if (!active || closing) return;
    closing = true;
    version++;
    video.pause();
    setMuted(true);
    try { sessionStorage.setItem(SEEN_KEY, "1"); } catch { /* Storage is optional. */ }
    dialog.classList.add("is-closing");
    window.setTimeout(() => {
      dialog.close();
      dialog.classList.remove("is-closing");
      active = false;
      closing = false;
      onClose();
      const target = returnFocus?.isConnected ? returnFocus : document.querySelector("#find-place");
      target?.focus({ preventScroll: true });
    }, 220);
  }

  function open(userRequested = false) {
    if (!source || active) return;
    active = true;
    version++;
    returnFocus = userRequested ? document.activeElement : null;
    play.hidden = true;
    setMuted(true);
    video.volume = .55;
    if (!video.getAttribute("src")) video.src = source;
    else video.currentTime = 0;
    onOpen();
    dialog.showModal();
    startPlayback();
  }

  replay.hidden = !source;
  replay.addEventListener("click", () => open(true));
  play.addEventListener("click", startPlayback);
  document.querySelector("#skip-intro").addEventListener("click", finish);
  dialog.addEventListener("cancel", event => { event.preventDefault(); finish(); });
  video.addEventListener("ended", finish);
  video.addEventListener("error", () => {
    if (!active) return;
    announce("The intro could not play. You can continue exploring.");
    finish();
  });
  sound.addEventListener("click", () => {
    setMuted(!video.muted);
    if (video.paused) startPlayback();
  });
  document.addEventListener("visibilitychange", () => {
    if (!active || closing) return;
    if (document.hidden) video.pause();
    else startPlayback();
  });

  return {
    startIfNeeded() {
      let seen = false;
      try { seen = sessionStorage.getItem(SEEN_KEY) === "1"; } catch { /* No storage requirement. */ }
      if (!seen && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) open();
    },
  };
}
