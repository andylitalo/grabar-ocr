"use strict";

// ---- state -----------------------------------------------------------------
const state = {
  view: "pages",
  pages: [],            // [{n, page_id, status}]
  pageNum: null,
  pageId: null,
  imageW: 0,
  imageH: 0,
  // Ordered typed regions in FULL-RES px: {type, box:{x1,y1,x2,y2}}.
  // `box` is the single crop bound, drawn tight to the text.
  regions: [],
  activeRegion: 0,
  // Manual deskew reference line + applied residual angle (deg). The line is a
  // vertical guide, locked until the Deskew button unlocks its endpoints.
  deskewLine: null,     // {x1,y1,x2,y2} full-res px
  deskewUnlocked: false,
  deskewAngle: 0,
  scale: 1,             // full-res px per display px
  lines: [],            // [{index,column,line,status,text,image_url}]
  currentIndex: 0,
  // Phase A: "label" = normal transcription; "verify" = non-character verification
  // of an auto-sliced page (binary verdict per line, written to nonchar_truth.json).
  mode: "label",
  verdicts: {},         // line index -> "empty" | "character" (verify mode only)
  autoPageId: null,     // page_XXXX_auto, set when entering verify mode
  jobs: {},             // job_id -> {id,page,status,cost,error,enqueued_at,...}
  pageBlank: false,     // is the currently-loaded page marked blank?
};

// Canonical line-id is supplied by the backend (`<region_key>/line_NNN`); fall
// back to legacy column form only if an older payload lacks it.
const lineKey = (l) =>
  l.line_id || `column_${l.column}/line_${String(l.line).padStart(3, "0")}`;

const $ = (id) => document.getElementById(id);

async function api(method, url, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return res.status === 204 ? null : res.json();
}

function showView(name) {
  state.view = name;
  for (const v of ["pages", "crop", "label", "review"]) {
    $("view-" + v).classList.toggle("hidden", v !== name);
  }
  const crumb = name === "label" && state.mode === "verify"
    ? "Verify non-character"
    : {
        pages: "Select a page", crop: "Crop columns",
        label: "Label lines", review: "Review predictions",
      }[name];
  $("crumbs").textContent = state.pageId ? `${state.pageId} — ${crumb}` : crumb;
}

// Toggle the label view between transcription mode and non-character verify mode.
function applyModeChrome() {
  const verify = state.mode === "verify";
  $("transcribe-panel").classList.toggle("hidden", verify);
  $("verify-panel").classList.toggle("hidden", !verify);
  $("btn-back-crop").classList.toggle("hidden", verify);
  $("btn-review").classList.toggle("hidden", verify);
  $("label-counts").classList.toggle("hidden", verify);
  $("btn-verify-back").classList.toggle("hidden", !verify);
}

// ---- prediction diff (read-only) -------------------------------------------
const esc = (s) =>
  s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

// Char-level Levenshtein alignment → HTML for ref and pred. Lines are short
// (<64 chars), so the O(n*m) DP backtrace is cheap. eq = match, sub/del/ins
// flag the three jiwer error classes (del shown on ref, ins shown on pred).
function diffHTML(ref, pred) {
  const a = [...ref], b = [...pred];
  const n = a.length, m = b.length;
  const d = Array.from({ length: n + 1 }, () => new Int32Array(m + 1));
  for (let i = 0; i <= n; i++) d[i][0] = i;
  for (let j = 0; j <= m; j++) d[0][j] = j;
  for (let i = 1; i <= n; i++)
    for (let j = 1; j <= m; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost);
    }
  let i = n, j = m;
  const refOut = [], predOut = [];
  const wrap = (cls, ch) => `<span class="diff-${cls}">${esc(ch)}</span>`;
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && a[i - 1] === b[j - 1]) {
      refOut.push(esc(a[i - 1])); predOut.push(esc(b[j - 1])); i--; j--;
    } else if (i > 0 && j > 0 && d[i][j] === d[i - 1][j - 1] + 1) {
      refOut.push(wrap("sub", a[i - 1])); predOut.push(wrap("sub", b[j - 1])); i--; j--;
    } else if (i > 0 && d[i][j] === d[i - 1][j] + 1) {
      refOut.push(wrap("del", a[i - 1])); i--;            // in ref, missing from pred
    } else {
      predOut.push(wrap("ins", b[j - 1])); j--;           // in pred, absent from ref
    }
  }
  return { refHtml: refOut.reverse().join(""), predHtml: predOut.reverse().join("") };
}

const fmtCer = (c) => (c == null ? "—" : `${(c * 100).toFixed(1)}%`);

// ---- page select -----------------------------------------------------------
async function loadPagesIndex() {
  const data = await api("GET", "/api/pages");
  state.pages = data.pages;
  const meta = data.min == null
    ? "No page PDFs found in data/pages/."
    : `${data.pages.length} pages available (${data.min}–${data.max}).`;
  $("pages-meta").textContent = meta;
}

async function loadPage(n) {
  let data;
  try {
    data = await api("GET", `/api/pages/${n}`);
  } catch (e) {
    $("page-badge").textContent = e.message;
    $("btn-select").disabled = true;
    return;
  }
  state.pageNum = data.n;
  state.pageId = data.page_id;
  state.imageW = data.image_width;
  state.imageH = data.image_height;
  state.regions = seedRegions(data.default_regions || []);
  state.activeRegion = 0;
  state.deskewAngle = 0;
  state.deskewUnlocked = false;
  state.deskewLine = null;
  $("page-num").value = data.n;
  state.pageBlank = !!data.blank;
  const status = data.blank ? "blank" : data.status;
  const badge = $("page-badge");
  badge.textContent = `${data.page_id} · ${status}`;
  badge.className = "badge " + status;
  $("btn-blank").textContent = data.blank ? "Unmark blank" : "Mark blank";
  const img = $("page-preview");
  img.src = `${data.page_image_url}?t=${Date.now()}`;
  $("btn-select").disabled = false;
  // Already-segmented pages (done / in_progress) can be opened straight into the
  // label+review view without re-cropping (which would discard existing labels).
  $("btn-open-labels").classList.toggle("hidden", data.status === "unlabeled");
  // Phase A: offer non-character verification on auto-sliced pages.
  state.autoPageId = data.auto_page_id || null;
  const hasAuto = !!data.has_auto;
  const vbtn = $("btn-verify-auto");
  vbtn.classList.toggle("hidden", !hasAuto);
  if (hasAuto) {
    vbtn.textContent = data.auto_status === "verified"
      ? "Re-verify auto slice →" : "Verify auto slice →";
  }
}

function adjacentPage(dir) {
  const nums = state.pages.map((p) => p.n);
  if (!nums.length) return null;
  if (state.pageNum == null) return nums[0];
  const idx = nums.indexOf(state.pageNum);
  if (idx === -1) {
    // current not in list; pick nearest in direction
    return dir > 0 ? nums.find((x) => x > state.pageNum) ?? nums[nums.length - 1]
                   : [...nums].reverse().find((x) => x < state.pageNum) ?? nums[0];
  }
  const j = Math.min(nums.length - 1, Math.max(0, idx + dir));
  return nums[j];
}

// ---- crop canvas: region annotator -----------------------------------------
const canvas = $("crop-canvas");
const ctx = canvas.getContext("2d");
const pageImg = new Image();
let drag = null; // {kind, ...} for a region box corner/move or a deskew endpoint

const REGION_TYPES = ["header", "single", "left", "right"];
const REGION_COLORS = { left: "#4c8bf5", right: "#3fb37f", single: "#f5a623", header: "#b76cf5" };

function seedRegions(defaultRegions) {
  // Seed each region from the detector's suggested box; the human tightens it.
  return defaultRegions.map((r) => ({ type: r.type, box: { ...r.box } }));
}

function orderRegions() {
  // Reading order: top-to-bottom by box, left before right within a band.
  state.regions.sort((a, b) => (a.box.y1 - b.box.y1) || (a.box.x1 - b.box.x1));
}

function initDeskewLine() {
  const x = Math.round(0.85 * state.imageW);
  state.deskewLine = {
    x1: x, y1: Math.round(0.05 * state.imageH),
    x2: x, y2: Math.round(0.30 * state.imageH),
  };
}

function deskewLineAngle() {
  const l = state.deskewLine;
  if (!l) return 0;
  return (Math.atan2(l.x2 - l.x1, l.y2 - l.y1) * 180) / Math.PI; // 0 = vertical
}

function enterCrop() {
  $("crop-title").textContent = `${state.pageId} (${state.imageW}×${state.imageH}px)`;
  if (!state.deskewLine) initDeskewLine();
  reloadPreview();
  renderRegionControls();
  renderDeskewControls();
  showView("crop");
}

function reloadPreview() {
  pageImg.onload = () => {
    const maxW = Math.min(900, state.imageW);
    canvas.width = maxW;
    canvas.height = Math.round(state.imageH * (maxW / state.imageW));
    state.scale = state.imageW / canvas.width;
    drawCrop();
  };
  const a = state.deskewAngle;
  pageImg.src = `/api/pages/${state.pageNum}/image.png?angle=${a}&t=${Date.now()}`;
}

const toDisp = (v) => v / state.scale;
const toFull = (v) => v * state.scale;

function corners(b) {
  return [[b.x1, b.y1], [b.x2, b.y1], [b.x1, b.y2], [b.x2, b.y2]];
}

function strokeRectFull(b, color, dashed) {
  const x = toDisp(b.x1), y = toDisp(b.y1);
  const w = toDisp(b.x2 - b.x1), h = toDisp(b.y2 - b.y1);
  ctx.setLineDash(dashed ? [6, 4] : []);
  ctx.lineWidth = 2;
  ctx.strokeStyle = color;
  ctx.strokeRect(x, y, w, h);
  ctx.setLineDash([]);
  for (const [hx, hy] of corners(b)) {
    ctx.fillStyle = color;
    ctx.fillRect(toDisp(hx) - 4, toDisp(hy) - 4, 8, 8);
  }
}

function drawCrop() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(pageImg, 0, 0, canvas.width, canvas.height);
  state.regions.forEach((r, i) => {
    const color = REGION_COLORS[r.type] || "#888";
    const active = i === state.activeRegion;
    ctx.fillStyle = color + (active ? "22" : "11");
    ctx.fillRect(toDisp(r.box.x1), toDisp(r.box.y1),
                 toDisp(r.box.x2 - r.box.x1), toDisp(r.box.y2 - r.box.y1));
    strokeRectFull(r.box, color, false);      // the single crop box
    ctx.fillStyle = color;
    ctx.font = active ? "bold 14px sans-serif" : "14px sans-serif";
    ctx.fillText(`${i + 1} ${r.type}`, toDisp(r.box.x1) + 4, toDisp(r.box.y1) + 16);
  });
  // Deskew reference line
  const l = state.deskewLine;
  if (l) {
    ctx.setLineDash(state.deskewUnlocked ? [] : [4, 4]);
    ctx.lineWidth = 2;
    ctx.strokeStyle = state.deskewUnlocked ? "#e0533d" : "#e0533d88";
    ctx.beginPath();
    ctx.moveTo(toDisp(l.x1), toDisp(l.y1));
    ctx.lineTo(toDisp(l.x2), toDisp(l.y2));
    ctx.stroke();
    ctx.setLineDash([]);
    if (state.deskewUnlocked) {
      for (const [hx, hy] of [[l.x1, l.y1], [l.x2, l.y2]]) {
        ctx.fillStyle = "#e0533d";
        ctx.fillRect(toDisp(hx) - 4, toDisp(hy) - 4, 8, 8);
      }
    }
  }
}

function hitTest(dx, dy) {
  const fx = toFull(dx), fy = toFull(dy);
  const tol = toFull(8);
  // Deskew endpoints first (when unlocked).
  if (state.deskewUnlocked && state.deskewLine) {
    const l = state.deskewLine;
    const ends = [[l.x1, l.y1], [l.x2, l.y2]];
    for (let e = 0; e < 2; e++) {
      if (Math.abs(fx - ends[e][0]) < tol && Math.abs(fy - ends[e][1]) < tol) {
        return { kind: "deskew", end: e };
      }
    }
  }
  // Region box corners, active region first.
  const order = [state.activeRegion, ...state.regions.keys()].filter(
    (v, i, a) => v != null && a.indexOf(v) === i);
  for (const i of order) {
    const cs = corners(state.regions[i].box);
    for (let c = 0; c < 4; c++) {
      if (Math.abs(fx - cs[c][0]) < tol && Math.abs(fy - cs[c][1]) < tol) {
        return { kind: "rect", region: i, handle: c };
      }
    }
  }
  // Move: whichever region's box contains the point.
  for (let i = state.regions.length - 1; i >= 0; i--) {
    const b = state.regions[i].box;
    if (fx >= b.x1 && fx <= b.x2 && fy >= b.y1 && fy <= b.y2) {
      return { kind: "rect", region: i, handle: "move" };
    }
  }
  return null;
}

function canvasPos(ev) {
  const r = canvas.getBoundingClientRect();
  return { x: ev.clientX - r.left, y: ev.clientY - r.top };
}

canvas.addEventListener("pointerdown", (ev) => {
  const p = canvasPos(ev);
  const hit = hitTest(p.x, p.y);
  if (!hit) return;
  if (hit.kind === "rect") {
    state.activeRegion = hit.region;
    renderRegionControls();
    drag = { ...hit, startX: toFull(p.x), startY: toFull(p.y),
             orig: { ...state.regions[hit.region].box } };
  } else {
    drag = { ...hit, orig: { ...state.deskewLine } };
  }
  canvas.setPointerCapture(ev.pointerId);
});

canvas.addEventListener("pointermove", (ev) => {
  if (!drag) return;
  const p = canvasPos(ev);
  const cx = clamp(toFull(p.x), 0, state.imageW), cy = clamp(toFull(p.y), 0, state.imageH);
  if (drag.kind === "deskew") {
    const l = state.deskewLine;
    if (drag.end === 0) { l.x1 = cx; l.y1 = cy; } else { l.x2 = cx; l.y2 = cy; }
    renderDeskewControls();
  } else {
    const b = state.regions[drag.region].box;
    const o = drag.orig;
    if (drag.handle === "move") {
      const dx = cx - drag.startX, dy = cy - drag.startY;
      b.x1 = clamp(o.x1 + dx, 0, state.imageW); b.x2 = clamp(o.x2 + dx, 0, state.imageW);
      b.y1 = clamp(o.y1 + dy, 0, state.imageH); b.y2 = clamp(o.y2 + dy, 0, state.imageH);
    } else if (drag.handle === 0) { b.x1 = cx; b.y1 = cy; }
    else if (drag.handle === 1) { b.x2 = cx; b.y1 = cy; }
    else if (drag.handle === 2) { b.x1 = cx; b.y2 = cy; }
    else { b.x2 = cx; b.y2 = cy; }
  }
  drawCrop();
});

canvas.addEventListener("pointerup", () => { drag = null; });

function clamp(v, lo, hi) { return Math.max(lo, Math.min(v, hi)); }

const normRect = (b) => ({
  x1: Math.round(Math.min(b.x1, b.x2)), y1: Math.round(Math.min(b.y1, b.y2)),
  x2: Math.round(Math.max(b.x1, b.x2)), y2: Math.round(Math.max(b.y1, b.y2)),
});

// ---- region + deskew controls ----------------------------------------------
function renderRegionControls() {
  orderRegions();
  const list = $("region-list");
  if (!list) return;
  list.innerHTML = "";
  state.regions.forEach((r, i) => {
    const row = document.createElement("div");
    row.className = "region-row" + (i === state.activeRegion ? " active" : "");
    const swatch = `<span class="region-swatch" style="background:${REGION_COLORS[r.type] || "#888"}"></span>`;
    const opts = REGION_TYPES.map(
      (t) => `<option value="${t}"${t === r.type ? " selected" : ""}>${t}</option>`).join("");
    row.innerHTML =
      `${swatch}<b>${i + 1}</b>` +
      `<select data-i="${i}" class="region-type">${opts}</select>` +
      `<button data-i="${i}" class="ghost region-del" title="remove region">✕</button>`;
    row.querySelector(".region-type").onchange = (e) => {
      state.regions[i].type = e.target.value; drawCrop(); renderRegionControls();
    };
    row.querySelector(".region-del").onclick = () => {
      state.regions.splice(i, 1);
      state.activeRegion = Math.max(0, state.activeRegion - (i <= state.activeRegion ? 1 : 0));
      drawCrop(); renderRegionControls();
    };
    row.onclick = (e) => {
      if (e.target.closest("select,button")) return;
      state.activeRegion = i; drawCrop(); renderRegionControls();
    };
    list.appendChild(row);
  });
}

function addRegion(type) {
  const W = state.imageW, H = state.imageH;
  const box = { x1: Math.round(0.15 * W), y1: Math.round(0.08 * H),
                x2: Math.round(0.85 * W), y2: Math.round(0.22 * H) };
  state.regions.push({ type, box: { ...box } });
  state.activeRegion = state.regions.length - 1;
  drawCrop(); renderRegionControls();
}

function renderDeskewControls() {
  const btn = $("btn-deskew");
  if (!btn) return;
  btn.textContent = state.deskewUnlocked ? "Lock reference line" : "Deskew (align reference line)";
  btn.classList.toggle("primary", state.deskewUnlocked);
  const live = state.deskewUnlocked ? deskewLineAngle() : 0;
  $("deskew-angle").textContent =
    `applied ${state.deskewAngle.toFixed(2)}°` +
    (state.deskewUnlocked ? ` · line ${live.toFixed(2)}° (Apply to add)` : "");
  $("btn-deskew-apply").classList.toggle("hidden", !state.deskewUnlocked);
}

function toggleDeskew() {
  state.deskewUnlocked = !state.deskewUnlocked;
  if (state.deskewUnlocked && !state.deskewLine) initDeskewLine();
  drawCrop(); renderDeskewControls();
}

function applyDeskew() {
  state.deskewAngle = +(state.deskewAngle + deskewLineAngle()).toFixed(3);
  state.deskewUnlocked = false;
  initDeskewLine();                 // reset the guide vertical in the corrected frame
  reloadPreview();                  // re-render at the new total angle
  renderDeskewControls();
}

function resetDeskew() {
  state.deskewAngle = 0;
  state.deskewUnlocked = false;
  initDeskewLine();
  reloadPreview();
  renderDeskewControls();
}

function cropBody(force) {
  return {
    regions: state.regions.map((r) => ({ type: r.type, box: normRect(r.box) })),
    deskew: $("chk-deskew").checked,
    force: !!force,
    manual_angle: state.deskewAngle,
  };
}

async function segment(force) {
  if (!state.regions.length) { alert("Add at least one region."); return; }
  orderRegions();
  $("btn-segment").disabled = true;
  try {
    await api("POST", `/api/pages/${state.pageNum}/columns`, cropBody(force));
    await startLabeling();
  } catch (e) {
    if (e.status === 409) {
      if (confirm(e.message + "\n\nRe-crop and discard existing labels?")) {
        await segment(true);
      }
    } else {
      alert("Segmentation failed: " + e.message);
    }
  } finally {
    $("btn-segment").disabled = false;
  }
}

async function labelAndTranslate(force) {
  // Crop the page now, then queue OCR→correct→translate in the background so the
  // human can move straight to the next page. Does NOT enter the label view.
  if (!state.regions.length) { alert("Add at least one region."); return; }
  orderRegions();
  $("btn-label-translate").disabled = true;
  try {
    const res = await api("POST", `/api/pages/${state.pageNum}/label-and-translate`, cropBody(force));
    if (res.job) state.jobs[res.job.id] = res.job;
    renderJobs();
    startJobPolling();
    goToPages();   // back to the page browser, ready for the next page
  } catch (e) {
    if (e.status === 409) {
      if (confirm(e.message + "\n\nRe-crop and discard existing labels?")) {
        await labelAndTranslate(true);
      }
    } else {
      alert("Label and Translate failed: " + e.message);
    }
  } finally {
    $("btn-label-translate").disabled = false;
  }
}

// ---- background jobs panel --------------------------------------------------
let jobPollTimer = null;

function startJobPolling() {
  if (jobPollTimer) return;
  jobPollTimer = setInterval(pollJobsOnce, 1500);
}

async function pollJobsOnce() {
  let data;
  try {
    data = await api("GET", "/api/jobs");
  } catch (e) {
    return;  // transient; try again next tick
  }
  for (const j of data.jobs) state.jobs[j.id] = j;
  renderJobs();
  const busy = data.jobs.some((j) => j.status === "queued" || j.status === "running");
  if (!busy) { clearInterval(jobPollTimer); jobPollTimer = null; }
}

function renderJobs() {
  const panel = $("jobs-panel"), list = $("jobs-list");
  if (!panel || !list) return;
  const jobs = Object.values(state.jobs).sort((a, b) => b.enqueued_at - a.enqueued_at);
  panel.classList.toggle("hidden", jobs.length === 0);
  list.innerHTML = "";
  for (const j of jobs) {
    const row = document.createElement("div");
    row.className = "job-row";
    const extra = j.status === "done" && j.cost != null ? ` ($${j.cost.toFixed(4)})`
                : j.status === "failed" && j.error ? ` — ${j.error}` : "";
    row.innerHTML =
      `<span class="job-badge job-${j.status}">${j.status}</span>` +
      `<span>page ${j.page}</span><span class="job-extra">${extra}</span>`;
    list.appendChild(row);
  }
}

// ---- labeling --------------------------------------------------------------
async function startLabeling() {
  state.mode = "label";
  applyModeChrome();
  const data = await api("GET", `/api/page/${state.pageId}/lines`);
  state.lines = data.lines;
  state.modelTag = data.model_tag || null;
  state.currentIndex = firstPendingIndex();
  $("done-summary").classList.add("hidden");
  showView("label");
  renderLine();
}

// ---- verify non-character (Phase A) ----------------------------------------
async function startVerify() {
  if (!state.autoPageId) return;
  state.mode = "verify";
  state.pageId = state.autoPageId;
  applyModeChrome();
  const data = await api("GET", `/api/page/${state.pageId}/lines`);
  state.lines = data.lines;
  // Seed each verdict: a saved human truth wins; else the detector's guess
  // (non_character -> "empty", otherwise "character").
  state.verdicts = {};
  state.lines.forEach((l, i) => {
    state.verdicts[i] = l.truth ? l.truth : (l.non_character ? "empty" : "character");
  });
  state.currentIndex = 0;
  $("verify-summary").classList.add("hidden");
  showView("label");
  renderLine();
}

function setVerdict(verdict) {
  if (state.mode !== "verify") return;
  state.verdicts[state.currentIndex] = verdict;
  if (state.currentIndex < state.lines.length - 1) state.currentIndex++;
  renderLine();
}

function renderVerify() {
  const l = state.lines[state.currentIndex];
  $("label-progress").textContent =
    `Line ${state.currentIndex + 1} / ${state.lines.length}  (col ${l.column}, line ${l.line})`;
  const verdict = state.verdicts[state.currentIndex];
  const badge = $("line-badge");
  badge.textContent = verdict === "empty" ? "non-character" : "character";
  badge.className = "badge " + (verdict === "empty" ? "empty" : "labeled");
  $("line-image").src = l.image_url + "?t=" + Date.now();

  const vc = $("verdict-current");
  vc.textContent = verdict === "empty" ? "Marked: empty / non-char" : "Marked: character";
  vc.className = "badge " + (verdict === "empty" ? "empty" : "labeled");
  const det = l.non_character ? "detector: non-character" : "detector: character";
  const feats = (l.glyph_count != null)
    ? ` · glyph ${l.glyph_count}${l.ink_ratio != null ? ` · ink ${(+l.ink_ratio).toFixed(2)}×` : ""}`
    : "";
  $("verdict-detector").textContent = det + feats;
  $("btn-verdict-empty").classList.toggle("primary", verdict === "empty");
  $("btn-verdict-char").classList.toggle("primary", verdict === "character");

  renderVerifyPills();
  updateVerifyCounts();
}

// Pills colored by the human verdict; lines still at the detector's seeded guess
// get the faded "suggested" treatment so confirmed verdicts stand out.
function renderVerifyPills() {
  const strip = $("pill-strip");
  strip.innerHTML = "";
  state.lines.forEach((l, i) => {
    const verdict = state.verdicts[i];
    const seeded = (l.truth == null) &&
      ((verdict === "empty") === !!l.non_character);  // unchanged from detector guess
    let cls;
    if (verdict === "empty") cls = seeded ? "suggest-empty" : "truth-empty";
    else cls = "truth-char";
    const pill = document.createElement("div");
    pill.className = "pill " + cls + (i === state.currentIndex ? " current" : "");
    pill.textContent = i + 1;
    pill.title = `#${i + 1} · col ${l.column} line ${l.line} · ${verdict}` +
      (l.non_character ? " · detector: non-char" : " · detector: char");
    pill.onclick = () => { state.currentIndex = i; renderLine(); };
    strip.appendChild(pill);
  });
}

function updateVerifyCounts() {
  let empty = 0, character = 0, flips = 0;
  state.lines.forEach((l, i) => {
    const v = state.verdicts[i];
    if (v === "empty") empty++; else character++;
    if ((v === "empty") !== !!l.non_character) flips++;
  });
  $("verify-counts").textContent =
    `${empty} non-character · ${character} character · ${flips} disagreement(s) with detector`;
}

async function submitTruth() {
  const verdicts = {};
  state.lines.forEach((l, i) => { verdicts[lineKey(l)] = state.verdicts[i]; });
  $("btn-submit-truth").disabled = true;
  try {
    const res = await api("POST", `/api/page/${state.pageId}/nonchar-truth`, { verdicts });
    showVerifySummary(res);
    state.lines.forEach((l, i) => { l.truth = state.verdicts[i]; });
    renderVerifyPills();
  } catch (e) {
    alert("Submit failed: " + e.message);
  } finally {
    $("btn-submit-truth").disabled = false;
  }
}

function showVerifySummary(res) {
  const c = res.counts;
  const box = $("verify-summary");
  box.classList.remove("hidden");
  const fpBad = c.fp > 0;
  box.classList.toggle("warn", fpBad);
  box.classList.toggle("done", !fpBad);
  const pct = (x) => (x == null ? "—" : `${(x * 100).toFixed(1)}%`);
  box.innerHTML =
    `<div><b>${res.page_id} verified.</b> ` +
    `TP ${c.tp} · <span style="color:${fpBad ? "var(--danger)" : "var(--ok)"}">FP ${c.fp}</span> · ` +
    `FN ${c.fn} · TN ${c.tn} &nbsp;(of ${c.total} lines)<br>` +
    `precision ${pct(res.precision)} · recall ${pct(res.recall)}` +
    (fpBad
      ? ` — <span style="color:var(--danger)">a real line was flagged (regression)</span>.`
      : `.`) +
    `</div><div class="meta">Saved to data/lines/${res.page_id}/nonchar_truth.json · ` +
    `run <code>data_prep/score_nonchar_detector.py</code> for the overall gate.</div>`;
}

function firstPendingIndex() {
  const i = state.lines.findIndex((l) => l.status === "pending");
  return i === -1 ? 0 : i;
}

function renderPills() {
  const strip = $("pill-strip");
  strip.innerHTML = "";
  state.lines.forEach((l, i) => {
    const pill = document.createElement("div");
    pill.className = "pill " + l.status + (i === state.currentIndex ? " current" : "");
    pill.textContent = i + 1;
    pill.title = `#${i + 1} · col ${l.column} line ${l.line} · ${l.status}`;
    pill.onclick = () => { state.currentIndex = i; renderLine(); };
    strip.appendChild(pill);
  });
}

function updateCounts() {
  const c = { labeled: 0, empty: 0, rejected: 0, pending: 0 };
  state.lines.forEach((l) => { c[l.status]++; });
  $("label-counts").textContent =
    `${c.labeled} labeled · ${c.empty} empty · ${c.rejected} rejected · ${c.pending} pending`;
}

function renderLine() {
  if (!state.lines.length) return;
  if (state.mode === "verify") { renderVerify(); return; }
  const l = state.lines[state.currentIndex];
  $("label-progress").textContent =
    `Line ${state.currentIndex + 1} / ${state.lines.length}  (col ${l.column}, line ${l.line})`;
  const badge = $("line-badge");
  badge.textContent = l.status;
  badge.className = "badge " + l.status;
  $("line-image").src = l.image_url + "?t=" + Date.now();
  const ta = $("line-text");
  ta.value = l.text || "";
  ta.disabled = l.status === "rejected";
  renderPrediction(l);
  renderPills();
  updateCounts();
  if (state.view === "label") ta.focus();
}

// Read-only prediction shown beneath the textarea for reference (never autofills).
function renderPrediction(l) {
  const box = $("line-pred");
  if (l.pred == null) {
    box.classList.add("hidden");
    return;
  }
  box.classList.remove("hidden");
  const cerStr = l.cer == null ? "" : ` · CER ${fmtCer(l.cer)}`;
  const tag = state.modelTag ? ` (${state.modelTag})` : "";
  box.innerHTML =
    `<span class="pred-label">prediction${esc(tag)}${cerStr}</span> ` +
    `<span class="pred-text">${esc(l.pred)}</span>`;
}

async function doLabel(action) {
  const l = state.lines[state.currentIndex];
  const text = $("line-text").value;
  const res = await api(
    "POST",
    `/api/page/${state.pageId}/region/${l.region}/line/${l.line}/label`,
    { action, text }
  );
  l.status = res.status;
  l.text = res.text;
}

async function labelAndAdvance(action) {
  await doLabel(action);
  if (state.currentIndex < state.lines.length - 1) {
    state.currentIndex++;
  }
  renderLine();
  // Surface the completion banner the moment the last pending line is filled,
  // regardless of where in the page it was (jumping around still completes).
  const pending = state.lines.filter((l) => l.status === "pending").length;
  if (pending === 0) showSummary();
  else hideSummary();
}

function showSummary() {
  const c = { labeled: 0, empty: 0, rejected: 0, pending: 0 };
  state.lines.forEach((l) => { c[l.status]++; });
  const box = $("done-summary");
  box.classList.remove("hidden");
  box.classList.toggle("warn", c.pending > 0);
  box.classList.toggle("done", c.pending === 0);
  const excluded = [];
  if (c.empty) excluded.push(`${c.empty} empty`);
  if (c.rejected) excluded.push(`${c.rejected} rejected`);
  $("done-summary-text").innerHTML = `<b>${state.pageId} complete.</b> ` +
    `${c.labeled} line${c.labeled === 1 ? "" : "s"} labeled` +
    (excluded.length ? ` (excludes ${excluded.join(", ")})` : "") +
    (c.pending > 0
      ? ` — <span style="color:var(--warn)">${c.pending} still pending</span>.`
      : ".");
}

function hideSummary() {
  $("done-summary").classList.add("hidden");
}

async function goToPages() {
  await loadPagesIndex();
  showView("pages");
}

// ---- review ----------------------------------------------------------------
function enterReview() {
  const withPred = state.lines.filter((l) => l.pred != null);
  if (!withPred.length) {
    alert(
      "No predictions found for this page.\n\nRun an offline pass first:\n" +
      `  .venv_ml/bin/python ml_vision/scripts/predict_lines.py --page ${state.pageId}`
    );
    return;
  }
  // Worst-CER-first; lines without ground truth (no CER yet) sink to the bottom.
  const ranked = [...withPred].sort((x, y) => {
    const cx = x.cer == null ? -1 : x.cer, cy = y.cer == null ? -1 : y.cer;
    return cy - cx;
  });
  const scored = withPred.filter((l) => l.cer != null);
  const mean = scored.length
    ? scored.reduce((s, l) => s + l.cer, 0) / scored.length : null;

  const badge = $("review-badge");
  badge.textContent = state.modelTag || "predictions";
  badge.className = "badge labeled";
  $("review-summary").textContent =
    `${withPred.length} lines · ${scored.length} scored` +
    (mean == null ? "" : ` · mean CER ${fmtCer(mean)}`);

  const list = $("review-list");
  list.innerHTML = "";
  for (const l of ranked) {
    const { refHtml, predHtml } = l.cer == null
      ? { refHtml: '<span class="muted">(not yet labeled)</span>', predHtml: esc(l.pred) }
      : diffHTML(l.text.trim(), l.pred);
    const row = document.createElement("div");
    row.className = "review-row";
    row.innerHTML =
      `<img class="review-thumb" src="${l.image_url}?t=${Date.now()}" alt="line crop" />` +
      `<div class="review-cer ${l.cer != null && l.cer > 0.15 ? "bad" : ""}">${fmtCer(l.cer)}</div>` +
      `<div class="review-text">` +
        `<div class="rt-line"><span class="rt-tag">GT</span><span>${refHtml}</span></div>` +
        `<div class="rt-line"><span class="rt-tag">PR</span><span>${predHtml}</span></div>` +
      `</div>` +
      `<div class="review-loc meta">col ${l.column} · line ${l.line}</div>`;
    row.onclick = () => {
      state.currentIndex = state.lines.findIndex((x) => x === l);
      showView("label");
      renderLine();
    };
    list.appendChild(row);
  }
  showView("review");
}

function navLine(dir) {
  const ni = state.currentIndex + dir;
  if (ni >= 0 && ni < state.lines.length) {
    state.currentIndex = ni;
    renderLine();
  }
}

// ---- wiring ----------------------------------------------------------------
$("btn-load").onclick = () => { const n = parseInt($("page-num").value, 10); if (n) loadPage(n); };
$("page-num").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); const n = parseInt($("page-num").value, 10); if (n) loadPage(n); }
});
$("btn-prev").onclick = () => { const n = adjacentPage(-1); if (n != null) loadPage(n); };
$("btn-next").onclick = () => { const n = adjacentPage(1); if (n != null) loadPage(n); };
$("btn-blank").onclick = async () => {
  if (state.pageNum == null) return;
  const next = !state.pageBlank;
  try {
    await api("POST", `/api/pages/${state.pageNum}/blank`, { blank: next });
  } catch (e) {
    alert("Could not update blank status: " + e.message);
    return;
  }
  const p = state.pages.find((x) => x.n === state.pageNum);
  if (p) p.blank = next;            // keep the cached list in sync (next-unlabeled skip)
  await loadPage(state.pageNum);     // refresh badge + button label
};

$("btn-next-unlabeled").onclick = () => {
  // Skip blank pages — they're handled, not pending work.
  const pending = (x) => x.status === "unlabeled" && !x.blank;
  const p = state.pages.find((x) => pending(x) && (state.pageNum == null || x.n > state.pageNum))
        || state.pages.find(pending);
  if (p) loadPage(p.n); else alert("No unlabeled pages remaining.");
};
$("btn-select").onclick = () => enterCrop();
$("btn-open-labels").onclick = () => startLabeling();  // skip re-crop for labeled pages
$("btn-verify-auto").onclick = () => startVerify();    // verify auto-slice non-char flags

$("btn-back-pages").onclick = () => goToPages();
$("btn-reset-boxes").onclick = () => {
  // re-fetch the detector's suggested regions
  api("GET", `/api/pages/${state.pageNum}`).then((d) => {
    state.regions = seedRegions(d.default_regions || []);
    state.activeRegion = 0;
    drawCrop(); renderRegionControls();
  });
};
$("btn-add-single").onclick = () => addRegion("single");
$("btn-add-header").onclick = () => addRegion("header");
$("btn-deskew").onclick = () => toggleDeskew();
$("btn-deskew-apply").onclick = () => applyDeskew();
$("btn-deskew-reset").onclick = () => resetDeskew();
$("btn-segment").onclick = () => segment(false);
$("btn-label-translate").onclick = () => labelAndTranslate(false);

$("btn-to-pages").onclick = () => goToPages();
$("btn-back-crop").onclick = () => enterCrop();
$("btn-submit").onclick = () => labelAndAdvance("submit");
$("btn-empty").onclick = () => labelAndAdvance("empty");
$("btn-reject").onclick = () => labelAndAdvance("reject");
$("btn-back-line").onclick = () => navLine(-1);
$("btn-next-line").onclick = () => navLine(1);
$("btn-review").onclick = () => enterReview();
$("btn-back-label").onclick = () => { showView("label"); renderLine(); };

// verify-mode controls
$("btn-verdict-empty").onclick = () => setVerdict("empty");
$("btn-verdict-char").onclick = () => setVerdict("character");
$("btn-back-line-v").onclick = () => navLine(-1);
$("btn-next-line-v").onclick = () => navLine(1);
$("btn-submit-truth").onclick = () => submitTruth();
$("btn-verify-back").onclick = () => goToPages();

$("line-text").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); labelAndAdvance("submit"); }
});

document.addEventListener("keydown", (e) => {
  if (state.view !== "label") return;
  if (state.mode === "verify") {
    if (e.altKey && e.code === "KeyE") { e.preventDefault(); setVerdict("empty"); }
    else if (e.altKey && e.code === "KeyC") { e.preventDefault(); setVerdict("character"); }
    else if (e.code === "Space") { e.preventDefault(); setVerdict("character"); }
    else if (e.altKey && e.key === "ArrowLeft") { e.preventDefault(); navLine(-1); }
    else if (e.altKey && e.key === "ArrowRight") { e.preventDefault(); navLine(1); }
    return;
  }
  if (e.altKey) {
    if (e.code === "KeyE") { e.preventDefault(); labelAndAdvance("empty"); }
    else if (e.code === "KeyR") { e.preventDefault(); labelAndAdvance("reject"); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); navLine(-1); }
    else if (e.key === "ArrowRight") { e.preventDefault(); navLine(1); }
  } else if (e.key === "Escape") {
    $("line-text").blur();
  }
});

// ---- boot ------------------------------------------------------------------
loadPagesIndex().then(() => showView("pages"));
pollJobsOnce();  // surface any jobs still running from a previous session
