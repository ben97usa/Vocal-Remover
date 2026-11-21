"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const COLORS = {
  Vocals: "#8b6cff", Instrumental: "#2ee88a", Drums: "#ff6b6b", Bass: "#ffb84d",
  Guitar: "#4dc9ff", Piano: "#f472d0", Other: "#a3e635",
};
const MODE_COPY = {
  vocal: { title: "Vocal Remover", sub: "Separate the vocals from the music. Preview both tracks, adjust their volume, then download." },
  stems: { title: "Stem Splitter", sub: "Split a song into vocals, drums, bass, guitar, piano and other sounds. Mix them live, then download." },
};
let CONFIG = null;
let currentMode = "vocal";

const fmtTime = s => { s = Math.max(0, s | 0); return `${(s / 60) | 0}:${String(s % 60).padStart(2, "0")}`; };
const api = async (url, opts) => {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  return r.headers.get("content-type")?.includes("json") ? r.json() : r;
};
function toast(msg, ms = 2600) {
  const t = $("#toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), ms);
}
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
};

// ------------------------------------------------------------------ routing
function route() {
  const h = location.hash.replace(/^#\/?/, "") || "vocal";
  const [view, arg] = h.split("/");
  if (view !== "job") mixer.destroy();
  $$(".view").forEach(v => (v.hidden = true));
  $$(".sidebar nav a").forEach(a => a.classList.toggle("active", a.dataset.nav === view ||
    (view === "job" && a.dataset.nav === job.mode)));
  if (view === "vocal" || view === "stems") { currentMode = view; showHome(); }
  else if (view === "scan") $("#view-scan").hidden = false;
  else if (view === "library") showLibrary();
  else if (view === "job" && arg) openJob(decodeURIComponent(arg));
  else location.hash = "#/vocal";
}
window.addEventListener("hashchange", route);

// ------------------------------------------------------------------ home
function showHome() {
  $("#view-home").hidden = false;
  $("#home-title").textContent = MODE_COPY[currentMode].title;
  $("#home-sub").textContent = MODE_COPY[currentMode].sub;
  const tracks = CONFIG.modes[currentMode].tracks;
  $("#stem-preview").innerHTML = "<span style='border:0;background:none'>You'll get:</span>" +
    tracks.map(t => `<span><i style="background:${COLORS[t]}"></i>${t}</span>`).join("");
  loadRecent();
}
async function loadRecent() {
  const items = (await api("/api/library")).filter(j => j.mode === currentMode).slice(0, 5);
  $("#recent-wrap").hidden = !items.length;
  $("#recent").innerHTML = "";
  items.forEach(j => $("#recent").append(libItem(j)));
}
function libItem(j) {
  const b = document.createElement("button");
  b.className = "lib-item";
  const a = j.analysis || {};
  const meta = [CONFIG.modes[j.mode].label, a.bpm ? `${a.bpm} BPM` : "", a.camelot ? `${a.key_short} · ${a.camelot}` : "",
    j.finished ? new Date(j.finished * 1000).toLocaleDateString() : ""].filter(Boolean).join("  ·  ");
  b.innerHTML = `<span class="name"></span><span class="meta"></span>`;
  $(".name", b).textContent = j.song;
  $(".meta", b).textContent = meta;
  b.onclick = () => (location.hash = `#/job/${encodeURIComponent(j.id)}`);
  return b;
}
async function showLibrary() {
  $("#view-library").hidden = false;
  $("#out-dir").textContent = CONFIG.output_dir;
  const items = await api("/api/library");
  const el = $("#library"); el.innerHTML = "";
  if (!items.length) el.innerHTML = `<div class="lib-empty">Nothing here yet. Separate a song and it will show up here.</div>`;
  items.forEach(j => el.append(libItem(j)));
}

// upload
const fileInput = $("#file");
$("#browse").onclick = e => { e.stopPropagation(); fileInput.click(); };
$("#dropzone").onclick = () => fileInput.click();
fileInput.onchange = () => fileInput.files[0] && startUpload(fileInput.files[0]);
["dragenter", "dragover"].forEach(ev => $("#dropzone").addEventListener(ev, e => { e.preventDefault(); $("#dropzone").classList.add("over"); }));
["dragleave", "drop"].forEach(ev => $("#dropzone").addEventListener(ev, e => { e.preventDefault(); $("#dropzone").classList.remove("over"); }));
$("#dropzone").addEventListener("drop", e => { const f = e.dataTransfer.files[0]; if (f) startUpload(f); });
document.addEventListener("dragover", e => e.preventDefault());
document.addEventListener("drop", e => e.preventDefault());

async function startUpload(file) {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("mode", currentMode);
  fd.append("model", $("#model").value);
  fd.append("hq", $("#hq").checked);
  store.set("model", $("#model").value);
  store.set("hq", $("#hq").checked);
  toast("Uploading…");
  try {
    const r = await api("/api/upload", { method: "POST", body: fd });
    fileInput.value = "";
    if (r.cached) toast("Already separated: loaded from your library");
    location.hash = `#/job/${encodeURIComponent(r.id)}`;
  } catch (e) { toast("Upload failed: " + e.message, 5000); }
}

// ------------------------------------------------------------------ job view
const job = { id: null, mode: null, timer: null, data: null };
async function openJob(id) {
  $("#view-job").hidden = false;
  if (job.id === id && job.data?.status === "done" && mixer.jobId === id) return;
  clearInterval(job.timer);
  job.id = id; job.data = null;
  $("#mixer").hidden = true; $("#processing").hidden = true; $("#job-error").hidden = true;
  $("#chips").innerHTML = '<span class="chip skeleton">&nbsp;</span>'.repeat(4);
  $("#verdict").hidden = true; $("#spectro").hidden = true;
  await poll();
  job.timer = setInterval(poll, 1000);
}
async function poll() {
  let d;
  try { d = await api(`/api/jobs/${encodeURIComponent(job.id)}`); }
  catch { clearInterval(job.timer); $("#job-error").hidden = false; $("#job-error").textContent = "This song is no longer available."; return; }
  if (d.id !== job.id) return;
  const first = !job.data;
  job.data = d; job.mode = d.mode;
  $$(".sidebar nav a").forEach(a => a.classList.toggle("active", a.dataset.nav === d.mode));
  if (first) {
    $("#job-song").textContent = d.song;
    $("#job-mode").textContent = CONFIG.modes[d.mode].label + (d.hq ? " · High quality" : "");
    document.title = `${d.song} · StemSplitter`;
  }
  renderAnalysis(d.analysis);
  if (d.status === "done") {
    clearInterval(job.timer);
    $("#processing").hidden = true;
    if (mixer.jobId !== d.id) mixer.load(d);
  } else if (d.status === "error" || d.status === "cancelled") {
    clearInterval(job.timer);
    $("#processing").hidden = true;
    $("#job-error").hidden = false;
    $("#job-error").textContent = d.status === "cancelled" ? "Separation cancelled." : "Separation failed:\n" + (d.error || "unknown error");
  } else {
    $("#processing").hidden = false;
    const pct = Math.round((d.progress || 0) * 100);
    $("#proc-bar").style.width = pct + "%";
    $("#proc-pct").textContent = pct + "%";
    $("#proc-msg").textContent = d.message || "Working…";
    const el = d.started ? Date.now() / 1000 - d.started : 0;
    $("#proc-time").textContent = d.status === "queued" ? "Queued" :
      `Elapsed ${fmtTime(el)}` + (d.eta != null ? `  ·  about ${fmtTime(d.eta)} left` : "");
  }
}
function renderAnalysis(a) {
  if (!a) return;
  if (a.error) { $("#chips").innerHTML = `<span class="chip">Analysis unavailable</span>`; return; }
  const chips = [
    ["Format", `${a.codec} · ${(a.sample_rate / 1000).toFixed(1)} kHz`],
    ["Length", fmtTime(a.duration)],
    ["Tagged", a.bitrate ? `${a.bitrate} kbps` : "n/a"],
    ["Real quality", a.quality, a.status],
    ["Cutoff", a.full_band ? "full band" : `${a.cutoff_khz} kHz`],
  ];
  if (a.bpm) chips.push(["Tempo", `${a.bpm} BPM`]);
  else chips.push(["Tempo", "…"]);
  if (a.key) chips.push(["Key", `${a.key} · ${a.camelot}`]);
  else chips.push(["Key", "…"]);
  $("#chips").innerHTML = chips.map(([k, v, cls]) => `<span class="chip ${cls || ""}">${k}<b>${v}</b></span>`).join("");
  const v = $("#verdict");
  v.hidden = false; v.className = "verdict " + a.status; v.textContent = a.verdict +
    (a.key_alt && a.key_alt !== "—" ? `   ·   Key could also be ${a.key_alt}` : "");
  if (a.spectrogram && $("#spectro").hidden) {
    $("#spectro").hidden = false;
    $("#spectro-img").src = `/api/jobs/${encodeURIComponent(job.id)}/spectrogram`;
  }
}
$("#back").onclick = () => (location.hash = `#/${job.mode || "vocal"}`);
$("#reveal").onclick = () => job.id && api(`/api/jobs/${encodeURIComponent(job.id)}/reveal`, { method: "POST" });
$("#cancel").onclick = async () => {
  if (!confirm("Cancel this separation?")) return;
  await api(`/api/jobs/${encodeURIComponent(job.id)}/cancel`, { method: "POST" });
  toast("Cancelling…");
};

// ------------------------------------------------------------------ mixer
const mixer = {
  ctx: null, master: null, tracks: [], duration: 0, playing: false, offset: 0, t0: 0, raf: 0, jobId: null,
  fmt: store.get("fmt", "mp3"), extras: [],

  async load(d) {
    this.destroy();
    this.jobId = d.id;
    $("#mixer").hidden = false;
    $("#tracks").innerHTML = "";
    $("#loading").hidden = false;
    this.ctx = new AudioContext();
    this.master = this.ctx.createGain();
    this.master.gain.value = $("#master").value / 100;
    this.master.connect(this.ctx.destination);
    this.extras = d.extra_stems || [];
    const names = d.stems;
    let loaded = 0;
    const bufs = await Promise.all(names.map(async n => {
      const r = await fetch(`/api/jobs/${encodeURIComponent(d.id)}/audio/${encodeURIComponent(n)}`);
      const buf = await this.ctx.decodeAudioData(await r.arrayBuffer());
      $("#loading").textContent = `Loading stems for preview… ${++loaded}/${names.length}`;
      return buf;
    }));
    if (this.jobId !== d.id) return;
    $("#loading").hidden = true;
    this.duration = Math.max(...bufs.map(b => b.duration));
    $("#t-dur").textContent = fmtTime(this.duration);
    const peaksList = bufs.map(b => computePeaks(b, 2400));
    const globalMax = Math.max(0.01, ...peaksList.map(p => p.max));
    names.forEach((name, i) => this.addTrack(name, bufs[i], peaksList[i], globalMax));
    this.extras.forEach(name => this.addExtraRow(name));
    this.offset = 0;
    this.applyGains();
    this.drawAll();
  },

  addTrack(name, buffer, peaks, globalMax) {
    const gain = this.ctx.createGain();
    gain.connect(this.master);
    const row = document.createElement("div");
    row.className = "trk";
    row.style.setProperty("--c", COLORS[name] || "#999");
    row.innerHTML = `
      <div class="trk-ctl">
        <div class="trk-top">
          <span class="trk-name">${name}</span>
          <button class="ms mute" title="Mute">M</button>
          <button class="ms solo" title="Solo">S</button>
          <span class="dl"><button data-f="wav" title="Download ${name} as WAV">WAV</button><button data-f="mp3" title="Download ${name} as MP3 320">MP3</button></span>
        </div>
        <div class="vol"><input type="range" min="0" max="150" value="100" title="Double-click to reset"><output>100%</output></div>
      </div>
      <div class="trk-wave"><canvas></canvas></div>`;
    $("#tracks").append(row);
    const t = { name, buffer, gain, vol: 100, mute: false, solo: false, row, peaks, globalMax,
      canvas: $("canvas", row), src: null, imgDim: null, imgLit: null };
    const slider = $("input", row), out = $("output", row);
    slider.oninput = () => { t.vol = +slider.value; out.textContent = t.vol + "%"; this.applyGains(); };
    slider.ondblclick = () => { slider.value = 100; slider.oninput(); };
    $(".mute", row).onclick = e => { t.mute = !t.mute; e.currentTarget.classList.toggle("on", t.mute); this.applyGains(); };
    $(".solo", row).onclick = e => { t.solo = !t.solo; e.currentTarget.classList.toggle("on", t.solo); this.applyGains(); };
    $$(".dl button", row).forEach(b => (b.onclick = () => downloadUrl(
      `/api/jobs/${encodeURIComponent(this.jobId)}/download/${encodeURIComponent(name)}?fmt=${b.dataset.f}`)));
    $(".trk-wave", row).addEventListener("pointerdown", e => {
      const r = e.currentTarget.getBoundingClientRect();
      this.seek(((e.clientX - r.left) / r.width) * this.duration);
    });
    this.tracks.push(t);
    this.renderWave(t);
  },

  addExtraRow(name) {
    const row = document.createElement("div");
    row.className = "trk";
    row.style.setProperty("--c", COLORS[name] || "#999");
    row.innerHTML = `<div class="trk-ctl"><div class="trk-top"><span class="trk-name">${name}</span>
      <span class="dl"><button data-f="wav">WAV</button><button data-f="mp3">MP3</button></span></div></div>
      <div class="trk-wave" style="cursor:default;display:flex;align-items:center;padding:0 16px;color:var(--muted);font-size:13px">
      Full beat (everything except vocals), ready to download.</div>`;
    $$(".dl button", row).forEach(b => (b.onclick = () => downloadUrl(
      `/api/jobs/${encodeURIComponent(this.jobId)}/download/${encodeURIComponent(name)}?fmt=${b.dataset.f}`)));
    $("#tracks").append(row);
  },

  effGain(t) {
    const anySolo = this.tracks.some(x => x.solo);
    if (t.mute || (anySolo && !t.solo)) return 0;
    return t.vol / 100;
  },
  applyGains() {
    if (!this.ctx) return;
    for (const t of this.tracks) {
      const g = this.effGain(t);
      t.gain.gain.setTargetAtTime(g, this.ctx.currentTime, 0.015);
      t.row.classList.toggle("silent", g === 0);
    }
  },

  position() { return this.playing ? this.ctx.currentTime - this.t0 : this.offset; },
  play() {
    if (!this.ctx || !this.tracks.length) return;
    if (this.ctx.state === "suspended") this.ctx.resume();
    if (this.offset >= this.duration - 0.05) this.offset = 0;
    const when = this.ctx.currentTime + 0.04;
    for (const t of this.tracks) {
      const s = this.ctx.createBufferSource();
      s.buffer = t.buffer; s.connect(t.gain); s.start(when, this.offset); t.src = s;
    }
    this.t0 = when - this.offset;
    this.playing = true;
    $("#play").classList.add("playing");
    this.loop();
  },
  stopSources() {
    for (const t of this.tracks) { try { t.src?.stop(); } catch {} t.src?.disconnect(); t.src = null; }
  },
  pause() {
    if (!this.playing) return;
    this.offset = this.position();
    this.stopSources();
    this.playing = false;
    $("#play").classList.remove("playing");
    cancelAnimationFrame(this.raf);
    this.drawAll();
  },
  toggle() { this.playing ? this.pause() : this.play(); },
  seek(sec) {
    sec = Math.min(Math.max(0, sec), this.duration);
    const was = this.playing;
    if (was) { this.stopSources(); this.playing = false; }
    this.offset = sec;
    if (was) this.play(); else this.drawAll();
  },
  loop() {
    cancelAnimationFrame(this.raf);
    const step = () => {
      if (!this.playing) return;
      if (this.position() >= this.duration) { this.pause(); this.offset = this.duration; this.drawAll(); return; }
      this.drawAll();
      this.raf = requestAnimationFrame(step);
    };
    this.raf = requestAnimationFrame(step);
  },

  renderWave(t) {
    const c = t.canvas, dpr = devicePixelRatio || 1;
    const w = Math.max(10, c.clientWidth), h = Math.max(10, c.clientHeight);
    c.width = w * dpr; c.height = h * dpr;
    const make = (color, alpha) => {
      const off = document.createElement("canvas"); off.width = c.width; off.height = c.height;
      const g = off.getContext("2d"); g.scale(dpr, dpr); g.fillStyle = color; g.globalAlpha = alpha;
      const bar = 2, gap = 1, n = Math.floor(w / (bar + gap)), mid = h / 2;
      for (let i = 0; i < n; i++) {
        const a = (i / n) * t.peaks.data.length, b = ((i + 1) / n) * t.peaks.data.length;
        let m = 0; for (let j = a | 0; j < Math.min(b, t.peaks.data.length); j++) m = Math.max(m, t.peaks.data[j]);
        const amp = Math.max(1, (m / t.globalMax) * (h * 0.46));
        g.fillRect(i * (bar + gap), mid - amp, bar, amp * 2);
      }
      return off;
    };
    const color = COLORS[t.name] || "#999";
    t.imgDim = make(color, 0.28);
    t.imgLit = make(color, 0.95);
  },
  drawAll() {
    const pos = this.duration ? this.position() / this.duration : 0;
    $("#t-cur").textContent = fmtTime(this.position());
    for (const t of this.tracks) {
      const c = t.canvas, g = c.getContext("2d");
      if (!t.imgDim) continue;
      g.clearRect(0, 0, c.width, c.height);
      g.drawImage(t.imgDim, 0, 0);
      const x = Math.round(pos * c.width);
      if (x > 0) g.drawImage(t.imgLit, 0, 0, x, c.height, 0, 0, x, c.height);
      g.fillStyle = "#fff"; g.fillRect(x, 0, Math.max(1, devicePixelRatio), c.height);
    }
  },
  resize() { this.tracks.forEach(t => this.renderWave(t)); this.drawAll(); },

  setPreset(p) {
    for (const t of this.tracks) {
      t.mute = p === "acapella" ? t.name !== "Vocals" : p === "karaoke" ? t.name === "Vocals" : false;
      t.solo = false;
      if (p === "all") { t.vol = 100; $("input", t.row).value = 100; $("output", t.row).textContent = "100%"; }
      $(".mute", t.row).classList.toggle("on", t.mute);
      $(".solo", t.row).classList.remove("on");
    }
    this.applyGains();
  },
  mixName() {
    const audible = this.tracks.filter(t => this.effGain(t) > 0);
    const full = audible.every(t => t.vol === 100);
    if (audible.length === 1 && full) return audible[0].name;
    if (full && audible.length === this.tracks.length - 1 && !audible.some(t => t.name === "Vocals")) return "Instrumental";
    if (full && audible.length === this.tracks.length) return "Full Mix";
    return "Custom Mix";
  },
  destroy() {
    if (!this.ctx) return;
    this.pause();
    this.stopSources();
    this.ctx.close();
    this.ctx = null; this.tracks = []; this.jobId = null; this.duration = 0; this.offset = 0;
    $("#play").classList.remove("playing");
  },
};

function computePeaks(buffer, n) {
  const chs = [...Array(buffer.numberOfChannels).keys()].map(i => buffer.getChannelData(i));
  const len = chs[0].length, step = len / n, data = new Float32Array(n);
  let max = 0;
  for (let i = 0; i < n; i++) {
    const a = Math.floor(i * step), b = Math.min(len, Math.floor((i + 1) * step));
    const stride = Math.max(1, Math.floor((b - a) / 160));
    let m = 0;
    for (const ch of chs) for (let j = a; j < b; j += stride) { const v = Math.abs(ch[j]); if (v > m) m = v; }
    data[i] = m; if (m > max) max = m;
  }
  return { data, max };
}

async function downloadUrl(url, label) {
  toast(label ? `Preparing ${label}…` : "Preparing download…", 60000);
  try {
    const r = await fetch(url);
    if (!r.ok) throw new Error(await r.text());
    const cd = r.headers.get("content-disposition") || "";
    const m = /filename\*=utf-8''([^;]+)/i.exec(cd) || /filename="?([^";]+)"?/i.exec(cd);
    const name = m ? decodeURIComponent(m[1]) : "download";
    const blobUrl = URL.createObjectURL(await r.blob());
    const a = Object.assign(document.createElement("a"), { href: blobUrl, download: name });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(blobUrl), 30000);
    toast(`Downloaded “${name}”`);
  } catch (e) { toast("Download failed: " + e.message, 5000); }
}

$("#play").onclick = () => mixer.toggle();
$("#master").oninput = e => { if (mixer.master) mixer.master.gain.value = e.target.value / 100; };
$$(".presets .chip-btn").forEach(b => (b.onclick = () => mixer.setPreset(b.dataset.preset)));
$$("#fmt button").forEach(b => {
  b.classList.toggle("on", b.dataset.fmt === mixer.fmt);
  b.onclick = () => { mixer.fmt = b.dataset.fmt; store.set("fmt", mixer.fmt); $$("#fmt button").forEach(x => x.classList.toggle("on", x === b)); };
});
$("#dl-mix").onclick = () => {
  if (!mixer.tracks.length) return;
  const gains = Object.fromEntries(mixer.tracks.map(t => [t.name, mixer.effGain(t)]));
  if (!Object.values(gains).some(g => g > 0)) return toast("All tracks are muted.");
  const name = mixer.mixName();
  downloadUrl(`/api/jobs/${encodeURIComponent(mixer.jobId)}/mix?fmt=${mixer.fmt}&name=${encodeURIComponent(name)}&gains=${encodeURIComponent(JSON.stringify(gains))}`, name);
};
$("#dl-zip").onclick = () => mixer.jobId && downloadUrl(`/api/jobs/${encodeURIComponent(mixer.jobId)}/zip?fmt=${mixer.fmt}`, "ZIP");
document.addEventListener("keydown", e => {
  if (e.code === "Space" && !$("#mixer").hidden && !$("#view-job").hidden &&
      !["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName)) {
    e.preventDefault(); mixer.toggle();
  }
});
let rz; window.addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(() => mixer.resize(), 120); });

// ------------------------------------------------------------------ quality scan
const scan = { id: null, rows: [], filter: "all", timer: null, music: false };
$("#scan-browse").onclick = async () => {
  const r = await api("/api/choose-folder", { method: "POST" });
  if (r.path) $("#scan-folder").value = r.path;
};
$("#scan-start").onclick = async () => {
  const folder = $("#scan-folder").value.trim();
  if (!folder) return toast("Choose a folder first.");
  scan.music = $("#scan-music").checked;
  let r;
  try { r = await api("/api/scan", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ folder, music: scan.music }) }); }
  catch (e) { return toast("Cannot scan: " + e.message, 4000); }
  if (!r.total) return toast("No audio files found in that folder.");
  store.set("scanFolder", folder);
  Object.assign(scan, { id: r.id, rows: [], filter: "all" });
  $("#scan-table tbody").innerHTML = "";
  $("#scan-table").hidden = false;
  $("#scan-table").classList.toggle("nomusic", !scan.music);
  $("#scan-progress").hidden = false; $("#scan-summary").hidden = false; $("#scan-csv").hidden = true;
  $("#scan-start").disabled = true;
  $$(".sum").forEach(s => s.classList.toggle("on", s.dataset.filter === "all"));
  clearInterval(scan.timer);
  scan.timer = setInterval(pollScan, 700);
};
$("#scan-stop").onclick = () => scan.id && api(`/api/scan/${scan.id}/cancel`, { method: "POST" });
async function pollScan() {
  const d = await api(`/api/scan/${scan.id}?since=${scan.rows.length}`);
  d.rows.forEach(r => { scan.rows.push(r); addScanRow(r); });
  const c = { all: scan.rows.length, ok: 0, fake: 0, low: 0, error: 0 };
  scan.rows.forEach(r => (c[r.status] = (c[r.status] || 0) + 1));
  Object.entries(c).forEach(([k, v]) => { const el = $(`#n-${k}`); if (el) el.textContent = v; });
  $("#scan-bar").style.width = (d.total ? (d.count / d.total) * 100 : 100) + "%";
  $("#scan-count").textContent = `${d.count} / ${d.total} files`;
  if (d.done) {
    clearInterval(scan.timer);
    $("#scan-start").disabled = false;
    $("#scan-count").textContent = `Finished: ${d.count} files scanned`;
    if (d.csv) { $("#scan-csv").hidden = false; $("#scan-csv").onclick = () => downloadUrl(`/api/scan/${scan.id}/csv`, "CSV"); }
  }
}
const BADGE = { ok: "Genuine 320", fake: "Fake 320", low: "Low quality", error: "Error" };
function addScanRow(r) {
  const tr = document.createElement("tr");
  tr.dataset.status = r.status;
  const cells = [`<span class="badge ${r.status}">${BADGE[r.status] || r.status}</span>`, "", r.bitrate ? `${r.bitrate} kbps` : "–",
    r.cutoff_khz ? `${r.cutoff_khz} kHz` : (r.status === "error" ? "–" : "full"), "", r.bpm ?? "", r.key ? `${r.key} (${r.camelot})` : ""];
  tr.innerHTML = cells.map((c, i) => `<td class="${i === 1 ? "file" : ""}${i >= 5 ? " mcol" : ""}">${c}</td>`).join("");
  tr.children[1].textContent = r.file;
  tr.children[4].textContent = r.status === "error" ? r.verdict : r.quality;
  tr.title = (r.verdict || "") + "\nClick to show in Finder";
  tr.onclick = () => api("/api/reveal-path", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path: r.path }) });
  tr.hidden = scan.filter !== "all" && scan.filter !== r.status;
  $("#scan-table tbody").append(tr);
}
$$(".sum").forEach(b => (b.onclick = () => {
  scan.filter = b.dataset.filter;
  $$(".sum").forEach(s => s.classList.toggle("on", s === b));
  $$("#scan-table tbody tr").forEach(tr => (tr.hidden = scan.filter !== "all" && tr.dataset.status !== scan.filter));
}));

// ------------------------------------------------------------------ boot
(async function boot() {
  CONFIG = await api("/api/config");
  const sel = $("#model");
  CONFIG.models.forEach(m => sel.append(new Option(m.label, m.id)));
  sel.value = store.get("model", CONFIG.default_model);
  if (!sel.value) sel.value = CONFIG.default_model;
  $("#hq").checked = store.get("hq", false);
  $("#scan-folder").value = store.get("scanFolder", "");
  route();
})();
