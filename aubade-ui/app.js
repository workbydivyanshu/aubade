/* Aubade UI v1 — concept data + real local playback. No build, no deps. */
"use strict";
const $ = (s) => document.querySelector(s);

/* ---------- concept data (from Dribbble 16889199 reference) ---------- */
const ICONS = {
  home: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 10.5L12 3l9 7.5V21H3z"/></svg>',
  discover: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M15 9l-2 5-4 1 2-5z"/></svg>',
  browse: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>',
  podcasts: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="3" width="6" height="10" rx="3"/><path d="M5 11a7 7 0 0014 0M12 18v3"/></svg>',
  radio: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="2"/><path d="M8.5 15.5a5 5 0 010-7M15.5 8.5a5 5 0 010 7M5.6 18.4a9 9 0 010-12.8M18.4 5.6a9 9 0 010 12.8"/></svg>',
  albums: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="2.5"/></svg>',
  song: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18V5l10-2v13"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="16.5" cy="16" r="2.5"/></svg>',
  artists: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.5-6.5 8-6.5s8 2.5 8 6.5"/></svg>',
};
const MENU = [
  { icon: "home", label: "Home", active: true },
  { icon: "discover", label: "Discover" },
  { icon: "browse", label: "Browse" },
  { icon: "podcasts", label: "Podcasts", badge: "new" },
  { icon: "radio", label: "Radio" },
];
const LIB = [
  { icon: "albums", label: "Albums" },
  { icon: "song", label: "Song" },
  { icon: "artists", label: "Artists" },
];
const TRACKS = [
  { n: "01", title: "Sleep 4Ever", artist: "Blackbear", time: "4:12", album: "HoneyWorks" },
  { n: "02", title: "Time is Ticking Out", artist: "The Cranberries", time: "4:20", album: "Wake Up And Smell T..." },
  { n: "03", title: "If I were u", artist: "Lauv", time: "3:12", album: "The Ecstatic" },
  { n: "04", title: "One Minute More", artist: "Gun Kelly", time: "2:56", album: "Supercell" },
];
const TAGS = [
  { label: "Accoustic", c: "#ff5f57" }, { label: "Piano jazz", c: "#c9a86a" },
  { label: "Jazz", c: "#b48cff" }, { label: "Indie pop", c: "#ff9f43" },
];
const PLAYED = [
  { t: "Blank Space", a: "Taylor Swift", w: "4 min ago", g: "linear-gradient(135deg,#e08a3c,#8a4b1f)", ch: "T" },
  { t: "Side Effects", a: "The Chainsmokers", w: "20 min ago", g: "linear-gradient(135deg,#d8b93c,#7a6216)", ch: "S" },
  { t: "No One Like You", a: "Scorpions", w: "2 hr ago", g: "linear-gradient(135deg,#4c6fff,#1c2f7a)", ch: "N" },
  { t: "Always Love You", a: "Elton John", w: "3 hr ago", g: "linear-gradient(135deg,#b44cc9,#4a1c6b)", ch: "A" },
];

/* ---------- state ---------- */
const audio = $("#audio");
let files = [];          // object URLs in playlist order
let idx = 1;             // default highlighted row (02, per concept)
let playing = false, shuffle = false, repeat = false, liked = false;
const order = () => TRACKS.map((_, i) => i);

/* ---------- render: nav ---------- */
function nav(el, items) {
  el.innerHTML = items.map((m) =>
    `<button class="nav-item${m.active ? " active" : ""}" data-nav="${m.label}">
       ${ICONS[m.icon]}<span class="lbl">${m.label}</span>${m.badge ? `<span class="badge">${m.badge}</span>` : ""}
     </button>`).join("");
  el.querySelectorAll(".nav-item").forEach((b) => b.onclick = () => {
    document.querySelectorAll(".nav-item").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
  });
}
nav($("#menuNav"), MENU); nav($("#libNav"), LIB);

/* ---------- render: tracks ---------- */
function renderTracks(filter = "") {
  const tb = $("#trackBody");
  tb.innerHTML = TRACKS.map((t, i) => {
    if (filter && !(t.title + t.artist + t.album).toLowerCase().includes(filter)) return "";
    const cls = i === idx ? (playing ? "playing" : "playing paused") : "";
    const mark = i === idx ? '<span class="eq"><i></i><i></i><i></i></span>' : "";
    return `<tr class="${cls}" data-i="${i}"><td class="idx">${t.n}</td>
      <td class="tt">${mark}${t.title}</td><td>${t.artist}</td><td>${t.time}</td><td>${t.album}</td></tr>`;
  }).join("");
  tb.querySelectorAll("tr").forEach((r) => r.onclick = () => { idx = +r.dataset.i; playIdx(); });
}

/* ---------- render: tags + played ---------- */
$("#chips").innerHTML = TAGS.map((t) =>
  `<button class="chip"><i style="background:${t.c}"></i>${t.label}</button>`).join("");
document.querySelectorAll(".chip").forEach((c) => c.onclick = () => c.classList.toggle("on"));
$("#played").innerHTML = PLAYED.map((p) =>
  `<div class="ritem"><div class="thumb" style="background:${p.g}">${p.ch}</div>
   <div><div class="t">${p.t}</div><div class="a">${p.a}</div></div>
   <div class="when">${p.w}</div></div>`).join("");

/* ---------- stars ---------- */
$("#stars").innerHTML = Array.from({ length: 40 }, () =>
  `<i style="left:${Math.random() * 100}%;top:${Math.random() * 55}%;animation-delay:${(Math.random() * 3).toFixed(1)}s"></i>`).join("");

/* ---------- playback ---------- */
function fmt(s) { if (!isFinite(s)) return "0:00"; s = Math.floor(s); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; }
function setIcon() { $("#playBtn").textContent = playing ? "⏸" : "▶"; }

function playIdx() {
  if (files[idx]) { if (audio.src !== files[idx]) audio.src = files[idx]; audio.play().catch(() => {}); }
  playing = true; setIcon(); renderTracks($("#searchInput").value.trim().toLowerCase());
  $("#emptyMsg").style.display = files[idx] ? "none" : "";
}
function toggle() {
  if (!files[idx]) { $("#emptyMsg").style.display = ""; $("#loadBox").style.borderColor = "#ff4d6d"; return; }
  if (playing) audio.pause(); else audio.play().catch(() => {});
}
audio.onplay = () => { playing = true; setIcon(); renderTracks($("#searchInput").value.trim().toLowerCase()); };
audio.onpause = () => { playing = false; setIcon(); renderTracks($("#searchInput").value.trim().toLowerCase()); };
audio.onended = () => { if (repeat) { audio.currentTime = 0; audio.play().catch(() => {}); } else step(1); };
audio.ontimeupdate = () => {
  if (audio.duration) $("#seek").value = Math.round((audio.currentTime / audio.duration) * 1000);
  $("#tCur").textContent = fmt(audio.currentTime); $("#tDur").textContent = fmt(audio.duration);
};
audio.onloadedmetadata = () => { $("#tDur").textContent = fmt(audio.duration); $("#emptyMsg").style.display = "none"; };

function step(d) {
  let ids = order();
  if (shuffle) idx = ids[Math.floor(Math.random() * ids.length)];
  else idx = (idx + d + TRACKS.length) % TRACKS.length;
  playIdx();
}
$("#playBtn").onclick = toggle;
$("#heroPlay").onclick = () => { idx = 1; playIdx(); };
$("#nextBtn").onclick = () => step(1);
$("#prevBtn").onclick = () => { if (audio.currentTime > 3) audio.currentTime = 0; else step(-1); };
$("#seek").oninput = (e) => { if (audio.duration) audio.currentTime = (e.target.value / 1000) * audio.duration; };
$("#vol").oninput = (e) => { audio.volume = e.target.value / 100; };
audio.volume = 0.8;
$("#shuffleBtn").onclick = (e) => { shuffle = !shuffle; e.currentTarget.classList.toggle("on", shuffle); };
$("#repeatBtn").onclick = (e) => { repeat = !repeat; e.currentTarget.classList.toggle("on", repeat); };
$("#likeBtn").onclick = (e) => {
  liked = !liked; const b = e.currentTarget;
  b.textContent = liked ? "♥" : "♡"; b.classList.toggle("liked", liked);
};

/* ---------- search / collapse / load ---------- */
$("#searchInput").oninput = (e) => renderTracks(e.target.value.trim().toLowerCase());
$("#collapseBtn").onclick = () => {
  const w = $("#window"); w.classList.toggle("collapsed");
  $("#collapseBtn").textContent = w.classList.contains("collapsed") ? "›" : "‹";
};
function takeFiles(list) {
  const aud = [...list].filter((f) => f.type.startsWith("audio") || /\.(mp3|flac|ogg|m4a|wav|opus)$/i.test(f.name));
  if (!aud.length) return;
  aud.sort((a, b) => a.name.localeCompare(b.name));
  files = aud.map((f) => URL.createObjectURL(f));
  // map onto concept rows in order; extra files extend the table
  aud.forEach((f, i) => {
    if (i < TRACKS.length) { TRACKS[i].title = f.name.replace(/\.[^.]+$/, ""); TRACKS[i].artist = "Local file"; }
    else TRACKS.push({ n: String(i + 1).padStart(2, "0"), title: f.name.replace(/\.[^.]+$/, ""), artist: "Local file", time: "--:--", album: "Local" });
  });
  idx = 0; renderTracks(); playIdx();
}
$("#loadBox").onclick = () => $("#filePick").click();
$("#filePick").onchange = (e) => takeFiles(e.target.files);
addEventListener("dragover", (e) => e.preventDefault());
addEventListener("drop", (e) => { e.preventDefault(); if (e.dataTransfer.files.length) takeFiles(e.dataTransfer.files); });
document.addEventListener("keydown", (e) => { if (e.code === "Space" && document.activeElement.tagName !== "INPUT") { e.preventDefault(); toggle(); } });

renderTracks(); setIcon();
