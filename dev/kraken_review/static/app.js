"use strict";

const CATEGORY_COLORS = { 1: "#e0a64f", 2: "#4c8bf5", 3: "#e0564f" };
const CATEGORY_LABELS = { 1: "over-segmentation", 2: "under-segmentation", 3: "non-text" };
const NEUTRAL = "#3fb37f";
const MISSED_COLOR = "#e05ac4"; // human drag-drawn missed line (matches --missed in CSS)
const DRAG_THRESHOLD = 5;       // display px of movement before a press counts as a drag
const MIN_BOX = 8;              // ignore full-res boxes smaller than this (stray clicks)

const $ = (id) => document.getElementById(id);
const canvas = $("canvas");
const ctx = canvas.getContext("2d");
const pageImg = new Image();

const state = {
  pages: [],
  page: null,
  lines: [],        // segmentation lines: {index, id, boundary, baseline, bbox}
  flags: {},        // line_id -> category number
  missed: [],       // [{id, box:[x1,y1,x2,y2]}] human-drawn missed-line boxes
  history: [],      // per-page undo stack: snapshots of {flags, missed} before each save
  imageW: 0,
  imageH: 0,
  scale: 1,
  modalLineId: null,
  missedModalId: null,
  hoverLineId: null,
  hoverMissedId: null,
};

// In-progress drag for drawing a missed-line box (display px).
let drag = null;

// ---- coordinate helpers (full-res page px <-> display px) ----
const toDisp = (v) => v / state.scale;
const toFull = (v) => v * state.scale;

// ---- API ----
async function api(method, url, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(url, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

// ---- drawing ----
function drawLinePath(boundary, bbox) {
  ctx.beginPath();
  if (boundary && boundary.length >= 3) {
    ctx.moveTo(toDisp(boundary[0][0]), toDisp(boundary[0][1]));
    for (let i = 1; i < boundary.length; i++) {
      ctx.lineTo(toDisp(boundary[i][0]), toDisp(boundary[i][1]));
    }
    ctx.closePath();
  } else if (bbox) {
    const [x1, y1, x2, y2] = bbox;
    ctx.rect(toDisp(x1), toDisp(y1), toDisp(x2 - x1), toDisp(y2 - y1));
  }
}

function draw() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (pageImg.complete && pageImg.naturalWidth) {
    ctx.drawImage(pageImg, 0, 0, canvas.width, canvas.height);
  }
  for (const line of state.lines) {
    const cat = state.flags[line.id];
    const color = cat ? CATEGORY_COLORS[cat] : NEUTRAL;
    const hover = line.id === state.hoverLineId;
    drawLinePath(line.boundary, line.bbox);
    // Hover darkens the fill (and gives unflagged lines a fill) so the boundary
    // you're about to categorize stands out before you click.
    if (cat || hover) {
      ctx.fillStyle = color + (hover ? "55" : "33");
      ctx.fill();
    }
    ctx.lineWidth = (cat ? 2.5 : 1.5) + (hover ? 1.5 : 0);
    ctx.strokeStyle = hover ? color : (cat ? color : color + "cc");
    ctx.stroke();
    // index label at bbox top-left
    if (line.bbox) {
      ctx.fillStyle = color;
      ctx.font = "12px sans-serif";
      ctx.fillText(String(line.index), toDisp(line.bbox[0]) + 2, toDisp(line.bbox[1]) + 12);
    }
  }
  // human-drawn missed-line boxes (dashed magenta)
  for (const m of state.missed) {
    const [x1, y1, x2, y2] = m.box;
    const hover = m.id === state.hoverMissedId;
    ctx.fillStyle = MISSED_COLOR + (hover ? "55" : "22");
    ctx.fillRect(toDisp(x1), toDisp(y1), toDisp(x2 - x1), toDisp(y2 - y1));
    ctx.setLineDash([6, 4]);
    ctx.lineWidth = hover ? 3 : 2;
    ctx.strokeStyle = MISSED_COLOR;
    ctx.strokeRect(toDisp(x1), toDisp(y1), toDisp(x2 - x1), toDisp(y2 - y1));
    ctx.setLineDash([]);
    ctx.fillStyle = MISSED_COLOR;
    ctx.font = "bold 12px sans-serif";
    ctx.fillText(m.id.replace("missed_", "M"), toDisp(x1) + 2, toDisp(y1) + 13);
  }
  // live rubber-band while dragging a new box
  if (drag && drag.moved) {
    const x = Math.min(drag.startX, drag.curX), y = Math.min(drag.startY, drag.curY);
    const w = Math.abs(drag.curX - drag.startX), h = Math.abs(drag.curY - drag.startY);
    ctx.fillStyle = MISSED_COLOR + "22";
    ctx.fillRect(x, y, w, h);
    ctx.setLineDash([5, 3]);
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = MISSED_COLOR;
    ctx.strokeRect(x, y, w, h);
    ctx.setLineDash([]);
  }
}

// ---- hit testing ----
function pointInPolygon(px, py, poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const xi = poly[i][0], yi = poly[i][1];
    const xj = poly[j][0], yj = poly[j][1];
    const intersect = (yi > py) !== (yj > py) &&
      px < ((xj - xi) * (py - yi)) / (yj - yi) + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}

function inBbox(px, py, bbox) {
  return bbox && px >= bbox[0] && px <= bbox[2] && py >= bbox[1] && py <= bbox[3];
}

function hitTest(dispX, dispY) {
  const fx = toFull(dispX), fy = toFull(dispY);
  // polygon-precise first
  for (const line of state.lines) {
    if (line.boundary && line.boundary.length >= 3 && pointInPolygon(fx, fy, line.boundary)) {
      return line;
    }
  }
  // fall back to bbox-contains (smallest matching box wins)
  let best = null, bestArea = Infinity;
  for (const line of state.lines) {
    if (inBbox(fx, fy, line.bbox)) {
      const [x1, y1, x2, y2] = line.bbox;
      const area = (x2 - x1) * (y2 - y1);
      if (area < bestArea) { best = line; bestArea = area; }
    }
  }
  return best;
}

// Smallest missed-line box under a display-space point, or null.
function hitMissed(dispX, dispY) {
  const fx = toFull(dispX), fy = toFull(dispY);
  let best = null, bestArea = Infinity;
  for (const m of state.missed) {
    if (inBbox(fx, fy, m.box)) {
      const [x1, y1, x2, y2] = m.box;
      const area = (x2 - x1) * (y2 - y1);
      if (area < bestArea) { best = m; bestArea = area; }
    }
  }
  return best;
}

function nextMissedId() {
  let max = 0;
  for (const m of state.missed) {
    const n = parseInt((m.id.match(/(\d+)$/) || [])[1] || "0", 10);
    if (n > max) max = n;
  }
  return `missed_${String(max + 1).padStart(3, "0")}`;
}

function canvasPos(ev) {
  const r = canvas.getBoundingClientRect();
  return { x: ev.clientX - r.left, y: ev.clientY - r.top };
}

// ---- flag list panel ----
function renderFlagList() {
  const el = $("flag-list");
  const ids = Object.keys(state.flags).sort();
  let html = `<h2>Flags (${ids.length})</h2>`;
  if (!ids.length) html += "<p>None yet.</p>";
  for (const id of ids) {
    const cat = state.flags[id];
    html += `<div class="flag"><span>${id}</span>` +
      `<span style="color:${CATEGORY_COLORS[cat]}">${cat} ${CATEGORY_LABELS[cat]}</span></div>`;
  }
  html += `<h2 style="margin-top:1rem">Missed lines (${state.missed.length})</h2>`;
  if (!state.missed.length) html += "<p>None. Drag on the page to add one.</p>";
  for (const m of state.missed) {
    html += `<div class="flag"><span>${m.id.replace("missed_", "M")}</span>` +
      `<span style="color:${MISSED_COLOR}">missed</span></div>`;
  }
  el.innerHTML = html;
}

// ---- modal ----
function openModal(line) {
  state.modalLineId = line.id;
  $("modal-title").textContent = `Flag ${line.id} (#${line.index})`;
  $("modal-backdrop").classList.add("show");
}
function closeModal() {
  state.modalLineId = null;
  $("modal-backdrop").classList.remove("show");
}
async function applyCategory(cat) {
  const id = state.modalLineId;
  if (!id) return;
  pushHistory();
  if (cat === null) { delete state.flags[id]; }
  else { state.flags[id] = cat; }
  closeModal();
  draw();
  renderFlagList();
  await saveReview();
}

// ---- missed-line box: add (via drag) and delete (via modal) ----
function addMissedBox(d) {
  const x1 = toFull(Math.min(d.startX, d.curX));
  const y1 = toFull(Math.min(d.startY, d.curY));
  const x2 = toFull(Math.max(d.startX, d.curX));
  const y2 = toFull(Math.max(d.startY, d.curY));
  if (x2 - x1 < MIN_BOX || y2 - y1 < MIN_BOX) return; // ignore stray tiny boxes
  const box = [Math.round(x1), Math.round(y1), Math.round(x2), Math.round(y2)];
  pushHistory();
  state.missed.push({ id: nextMissedId(), box });
  draw();
  renderFlagList();
  saveReview();
}

function openMissedModal(m) {
  state.missedModalId = m.id;
  $("missed-title").textContent = `Missed-line box (${m.id.replace("missed_", "M")})`;
  $("missed-backdrop").classList.add("show");
}
function closeMissedModal() {
  state.missedModalId = null;
  $("missed-backdrop").classList.remove("show");
}
async function deleteMissed() {
  const id = state.missedModalId;
  if (!id) return;
  pushHistory();
  state.missed = state.missed.filter((m) => m.id !== id);
  closeMissedModal();
  draw();
  renderFlagList();
  await saveReview();
}

// ---- mark blank: flag every kraken line as non-text (3) in one undoable step ----
async function markBlank() {
  if (!state.lines.length) return;
  pushHistory();
  for (const line of state.lines) state.flags[line.id] = 3;
  closeModal();
  closeMissedModal();
  draw();
  renderFlagList();
  await saveReview();
}

// ---- undo (Cmd+Z / Ctrl+Z / button): revert the last saved change on this page ----
function snapshot() {
  return {
    flags: JSON.parse(JSON.stringify(state.flags)),
    missed: JSON.parse(JSON.stringify(state.missed)),
  };
}
function pushHistory() {
  state.history.push(snapshot());
  updateUndoButton();
}
function updateUndoButton() {
  const btn = $("undo");
  if (btn) btn.disabled = state.history.length === 0;
}
async function undo() {
  if (!state.history.length) return;
  const prev = state.history.pop();
  state.flags = prev.flags;
  state.missed = prev.missed;
  closeModal();
  closeMissedModal();
  draw();
  renderFlagList();
  updateUndoButton();
  await saveReview();
}

// ---- persistence ----
let saveTimer = null;
async function saveReview() {
  try {
    await api("POST", `/api/pages/${state.page}/review`,
      { flags: state.flags, missed: state.missed });
    const s = $("saved");
    s.textContent = "saved";
    s.classList.add("ok");
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => { s.textContent = ""; s.classList.remove("ok"); }, 1500);
  } catch (e) {
    $("saved").textContent = "save failed: " + e.message;
  }
}

// ---- page loading ----
function fitCanvas() {
  const maxW = Math.min(900, state.imageW || 900);
  canvas.width = maxW;
  canvas.height = Math.round(state.imageH * (maxW / state.imageW));
  state.scale = state.imageW / canvas.width;
}

async function loadPage(page) {
  state.page = page;
  $("page-select").value = String(page);
  const seg = await api("GET", `/api/pages/${page}/segmentation`);
  const review = await api("GET", `/api/pages/${page}/review`);
  state.lines = seg.lines || [];
  state.imageW = seg.width;
  state.imageH = seg.height;
  state.flags = {};
  for (const [id, info] of Object.entries(review.flags || {})) {
    state.flags[id] = info.category;
  }
  state.missed = (review.missed_lines || []).map((m) => ({ id: m.id, box: m.box.slice() }));
  state.history = [];   // undo is scoped to the current page
  state.hoverLineId = null;
  state.hoverMissedId = null;
  drag = null;
  updateUndoButton();
  $("count").textContent = `${state.lines.length} lines`;
  await new Promise((resolve) => {
    pageImg.onload = resolve;
    pageImg.onerror = resolve;
    pageImg.src = `/api/pages/${page}/image.png?t=${Date.now()}`;
  });
  fitCanvas();
  draw();
  renderFlagList();
}

function step(delta) {
  const i = state.pages.indexOf(state.page);
  const j = i + delta;
  if (j >= 0 && j < state.pages.length) loadPage(state.pages[j]);
}

// ---- canvas interaction: plain click = flag/delete, drag = draw missed box ----
function updateHover(x, y) {
  const m = hitMissed(x, y);
  const line = m ? null : hitTest(x, y);   // missed boxes take click priority
  const mid = m ? m.id : null;
  const lid = line ? line.id : null;
  if (mid !== state.hoverMissedId || lid !== state.hoverLineId) {
    state.hoverMissedId = mid;
    state.hoverLineId = lid;
    canvas.style.cursor = (mid || lid) ? "pointer" : "crosshair";
    draw();
  }
}

canvas.addEventListener("mousedown", (ev) => {
  const { x, y } = canvasPos(ev);
  drag = { startX: x, startY: y, curX: x, curY: y, moved: false };
});

canvas.addEventListener("mousemove", (ev) => {
  const { x, y } = canvasPos(ev);
  if (drag) {
    drag.curX = x; drag.curY = y;
    if (!drag.moved &&
        (Math.abs(x - drag.startX) > DRAG_THRESHOLD || Math.abs(y - drag.startY) > DRAG_THRESHOLD)) {
      drag.moved = true;
    }
    if (drag.moved) { canvas.style.cursor = "crosshair"; draw(); return; }
  }
  updateHover(x, y);
});

canvas.addEventListener("mouseup", (ev) => {
  const { x, y } = canvasPos(ev);
  if (drag) {
    drag.curX = x; drag.curY = y;
    // Treat as a drag if the pointer moved far enough — checked against the
    // release point too, so it works even when no mousemove events fired.
    const movedFar = Math.abs(x - drag.startX) > DRAG_THRESHOLD ||
                     Math.abs(y - drag.startY) > DRAG_THRESHOLD;
    if (drag.moved || movedFar) {     // finished drawing a box
      addMissedBox(drag);
      drag = null;
      return;
    }
  }
  drag = null;                        // plain click
  const m = hitMissed(x, y);
  if (m) { openMissedModal(m); return; }
  const line = hitTest(x, y);
  if (line) openModal(line);
});

canvas.addEventListener("mouseleave", () => {
  drag = null;                        // cancel any in-progress drag
  if (state.hoverLineId !== null || state.hoverMissedId !== null) {
    state.hoverLineId = null;
    state.hoverMissedId = null;
  }
  draw();
});

document.querySelectorAll(".opt").forEach((btn) => {
  btn.addEventListener("click", () => applyCategory(Number(btn.dataset.cat)));
});
$("opt-clear").addEventListener("click", () => applyCategory(null));
$("opt-cancel").addEventListener("click", closeModal);
$("modal-backdrop").addEventListener("click", (ev) => {
  if (ev.target === $("modal-backdrop")) closeModal();
});

$("missed-delete").addEventListener("click", deleteMissed);
$("missed-cancel").addEventListener("click", closeMissedModal);
$("missed-backdrop").addEventListener("click", (ev) => {
  if (ev.target === $("missed-backdrop")) closeMissedModal();
});

document.addEventListener("keydown", (ev) => {
  // Undo: Cmd+Z (mac) / Ctrl+Z. (Shift = redo, not implemented.)
  if ((ev.metaKey || ev.ctrlKey) && !ev.shiftKey && (ev.key === "z" || ev.key === "Z")) {
    ev.preventDefault();
    undo();
    return;
  }
  if (state.modalLineId) {
    if (ev.key === "Escape") closeModal();
    else if (ev.key === "1" || ev.key === "2" || ev.key === "3") applyCategory(Number(ev.key));
    return;
  }
  if (state.missedModalId) {
    if (ev.key === "Escape") closeMissedModal();
    else if (ev.key === "Delete" || ev.key === "Backspace") { ev.preventDefault(); deleteMissed(); }
  }
});

$("prev").addEventListener("click", () => step(-1));
$("next").addEventListener("click", () => step(1));
$("blank").addEventListener("click", markBlank);
$("undo").addEventListener("click", undo);
$("page-select").addEventListener("change", (ev) => loadPage(Number(ev.target.value)));

async function init() {
  const { pages } = await api("GET", "/api/pages");
  state.pages = pages;
  const sel = $("page-select");
  sel.innerHTML = pages.map((p) => `<option value="${p}">page ${p}</option>`).join("");
  if (pages.length) loadPage(pages[0]);
  else $("count").textContent = "No segmented pages found. Run dev/kraken_segment.py first.";
}

init();
