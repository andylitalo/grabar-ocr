"use strict";

const CATEGORY_COLORS = { 1: "#e0a64f", 2: "#4c8bf5", 3: "#e0564f" };
const CATEGORY_LABELS = { 1: "over-segmentation", 2: "under-segmentation", 3: "non-text" };
const NEUTRAL = "#3fb37f";
const MISSED_COLOR = "#e05ac4"; // human drag-drawn missed line (matches --missed in CSS)
// correction-op colors (must match the --initial/--merge/--split/--title vars in CSS)
const INITIAL_COLOR = "#a06cff";
const MERGE_COLOR = "#2fbf9f";
const SPLIT_COLOR = "#ff5d5d";
const TITLE_COLOR = "#f0b429";
const SELECT_COLOR = "#ffffff";

const DRAG_THRESHOLD = 5;       // display px of movement before a press counts as a drag
const MIN_BOX = 8;              // ignore full-res boxes smaller than this (stray clicks)

const TOOLS = ["flag", "initial", "merge", "split", "title"];

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
  // correction ops layered on kraken's immutable lines:
  initials: [],       // [{id, key, box, target_line_id}] drop-cap initials
  merges: [],         // [{id, line_ids:[...]}] rejoined lines
  splits: [],         // [{id, line_id, at_x}] vertical cuts
  sectionTitles: [],  // [{id, key, box, source_line_id}] titular letters
  tool: "flag",
  selection: [],      // merge tool: selected line ids
  splitLineId: null,  // split tool: line awaiting a cut-x click
  history: [],        // per-page undo stack: snapshots of the editable state
  imageW: 0,
  imageH: 0,
  scale: 1,
  modalLineId: null,
  missedModalId: null,
  hoverLineId: null,
  hoverMissedId: null,
};

// In-progress drag for drawing a box (display px).
let drag = null;
// Pending box + context awaiting a letter (Initial / Title tools).
let pendingLetter = null;   // {tool, box, hitLineId}

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

// ---- id helpers ----
function nextId(prefix, list) {
  let max = 0;
  for (const item of list) {
    const n = parseInt((String(item.id).match(/(\d+)$/) || [])[1] || "0", 10);
    if (n > max) max = n;
  }
  return `${prefix}_${String(max + 1).padStart(3, "0")}`;
}
const nextMissedId = () => nextId("missed", state.missed);

// ---- geometry helpers ----
function lineById(id) { return state.lines.find((l) => l.id === id) || null; }

// union bbox of a set of line ids
function unionBox(ids) {
  let box = null;
  for (const id of ids) {
    const l = lineById(id);
    if (!l || !l.bbox) continue;
    box = box
      ? [Math.min(box[0], l.bbox[0]), Math.min(box[1], l.bbox[1]),
         Math.max(box[2], l.bbox[2]), Math.max(box[3], l.bbox[3])]
      : l.bbox.slice();
  }
  return box;
}

function boxesOverlap(a, b) {
  return a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3];
}

// The upper of the lines adjacent to the right of an initial box. Among lines that
// extend past the box on the right and vertically overlap it, keep only those in the
// NEAREST column to the right (so a far right-column line on a two-column page can't
// win), then pick the topmost (smallest y1) — the line the drop-cap begins.
function computeTargetLine(box) {
  const [bx1, by1, bx2, by2] = box;
  const boxH = by2 - by1;
  const boxW = bx2 - bx1;
  const cands = state.lines.filter((l) => {
    if (!l.bbox) return false;
    const [x1, y1, x2, y2] = l.bbox;
    const toRight = x2 > bx2 && x1 >= bx1;
    const vOverlap = Math.min(by2, y2) - Math.max(by1, y1) > 0.2 * boxH;
    return toRight && vOverlap;
  });
  if (!cands.length) return null;
  const minLeft = Math.min(...cands.map((l) => l.bbox[0]));
  const tol = Math.max(boxW, 60);
  const nearest = cands.filter((l) => l.bbox[0] <= minLeft + tol);
  nearest.sort((a, b) => a.bbox[1] - b.bbox[1]);
  return nearest[0];
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

function strokeBox(box, color, width, dash) {
  const [x1, y1, x2, y2] = box;
  ctx.setLineDash(dash || []);
  ctx.lineWidth = width;
  ctx.strokeStyle = color;
  ctx.strokeRect(toDisp(x1), toDisp(y1), toDisp(x2 - x1), toDisp(y2 - y1));
  ctx.setLineDash([]);
}

function label(text, x, y, color) {
  ctx.fillStyle = color;
  ctx.font = "bold 12px sans-serif";
  ctx.fillText(text, toDisp(x) + 2, toDisp(y) + 13);
}

function draw() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (pageImg.complete && pageImg.naturalWidth) {
    ctx.drawImage(pageImg, 0, 0, canvas.width, canvas.height);
  }
  const selected = new Set(state.selection);
  for (const line of state.lines) {
    const cat = state.flags[line.id];
    const color = cat ? CATEGORY_COLORS[cat] : NEUTRAL;
    const hover = line.id === state.hoverLineId;
    drawLinePath(line.boundary, line.bbox);
    if (cat || hover) {
      ctx.fillStyle = color + (hover ? "55" : "33");
      ctx.fill();
    }
    ctx.lineWidth = (cat ? 2.5 : 1.5) + (hover ? 1.5 : 0);
    ctx.strokeStyle = hover ? color : (cat ? color : color + "cc");
    ctx.setLineDash([]);
    ctx.stroke();
    if (selected.has(line.id) && line.bbox) strokeBox(line.bbox, SELECT_COLOR, 3);
    if (line.id === state.splitLineId && line.bbox) strokeBox(line.bbox, SPLIT_COLOR, 3, [4, 3]);
    if (line.bbox) {
      ctx.fillStyle = color;
      ctx.font = "12px sans-serif";
      ctx.fillText(String(line.index), toDisp(line.bbox[0]) + 2, toDisp(line.bbox[1]) + 12);
    }
  }

  // merges: dashed outline around the union of their member lines
  for (const m of state.merges) {
    const box = unionBox(m.line_ids);
    if (!box) continue;
    strokeBox(box, MERGE_COLOR, 2.5, [8, 4]);
    label(m.id.replace("merge_", "G"), box[0], box[1], MERGE_COLOR);
  }

  // splits: vertical cut line across the line's bbox
  for (const s of state.splits) {
    const l = lineById(s.line_id);
    if (!l || !l.bbox) continue;
    ctx.setLineDash([]);
    ctx.lineWidth = 2.5;
    ctx.strokeStyle = SPLIT_COLOR;
    ctx.beginPath();
    ctx.moveTo(toDisp(s.at_x), toDisp(l.bbox[1]));
    ctx.lineTo(toDisp(s.at_x), toDisp(l.bbox[3]));
    ctx.stroke();
  }

  // initials: the box, an arrow to its target line, and a carved-out marker on overlapped lines
  for (const it of state.initials) {
    ctx.fillStyle = INITIAL_COLOR + "33";
    const [x1, y1, x2, y2] = it.box;
    ctx.fillRect(toDisp(x1), toDisp(y1), toDisp(x2 - x1), toDisp(y2 - y1));
    strokeBox(it.box, INITIAL_COLOR, 2.5);
    label(it.key || it.id.replace("initial_", "I"), x1, y1, INITIAL_COLOR);
    const target = it.target_line_id ? lineById(it.target_line_id) : null;
    if (target && target.bbox) {
      // connector from the initial box to the target line
      ctx.setLineDash([3, 3]);
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = INITIAL_COLOR;
      ctx.beginPath();
      ctx.moveTo(toDisp(x2), toDisp((y1 + y2) / 2));
      ctx.lineTo(toDisp(target.bbox[0]), toDisp((target.bbox[1] + target.bbox[3]) / 2));
      ctx.stroke();
      ctx.setLineDash([]);
    }
    // show the ink is subtracted from any OTHER line the box overlaps
    for (const l of state.lines) {
      if (!l.bbox || l.id === it.target_line_id || !boxesOverlap(it.box, l.bbox)) continue;
      const ox1 = Math.max(it.box[0], l.bbox[0]), oy1 = Math.max(it.box[1], l.bbox[1]);
      const ox2 = Math.min(it.box[2], l.bbox[2]), oy2 = Math.min(it.box[3], l.bbox[3]);
      strokeBox([ox1, oy1, ox2, oy2], SPLIT_COLOR, 1.5, [3, 2]);
    }
  }

  // section-title letters
  for (const t of state.sectionTitles) {
    const [x1, y1, x2, y2] = t.box;
    ctx.fillStyle = TITLE_COLOR + "33";
    ctx.fillRect(toDisp(x1), toDisp(y1), toDisp(x2 - x1), toDisp(y2 - y1));
    strokeBox(t.box, TITLE_COLOR, 2.5);
    label(t.key, x1, y1, TITLE_COLOR);
  }

  // human-drawn missed-line boxes (dashed magenta)
  for (const m of state.missed) {
    const [x1, y1, x2, y2] = m.box;
    const hover = m.id === state.hoverMissedId;
    ctx.fillStyle = MISSED_COLOR + (hover ? "55" : "22");
    ctx.fillRect(toDisp(x1), toDisp(y1), toDisp(x2 - x1), toDisp(y2 - y1));
    strokeBox(m.box, MISSED_COLOR, hover ? 3 : 2, [6, 4]);
    label(m.id.replace("missed_", "M"), x1, y1, MISSED_COLOR);
  }

  // live rubber-band while dragging a new box
  if (drag && drag.moved) {
    const x = Math.min(drag.startX, drag.curX), y = Math.min(drag.startY, drag.curY);
    const w = Math.abs(drag.curX - drag.startX), h = Math.abs(drag.curY - drag.startY);
    const c = state.tool === "title" ? TITLE_COLOR : state.tool === "initial" ? INITIAL_COLOR : MISSED_COLOR;
    ctx.fillStyle = c + "22";
    ctx.fillRect(x, y, w, h);
    ctx.setLineDash([5, 3]);
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = c;
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
  for (const line of state.lines) {
    if (line.boundary && line.boundary.length >= 3 && pointInPolygon(fx, fy, line.boundary)) {
      return line;
    }
  }
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

function canvasPos(ev) {
  const r = canvas.getBoundingClientRect();
  return { x: ev.clientX - r.left, y: ev.clientY - r.top };
}

function dragToBox(d) {
  const x1 = toFull(Math.min(d.startX, d.curX));
  const y1 = toFull(Math.min(d.startY, d.curY));
  const x2 = toFull(Math.max(d.startX, d.curX));
  const y2 = toFull(Math.max(d.startY, d.curY));
  if (x2 - x1 < MIN_BOX || y2 - y1 < MIN_BOX) return null;
  return [Math.round(x1), Math.round(y1), Math.round(x2), Math.round(y2)];
}

// ---- side panel ----
function delBtn(kind, id) {
  return `<button class="del" data-del="${kind}" data-id="${id}" title="Delete">&times;</button>`;
}
function section(title, rows) {
  let html = `<h2 style="margin-top:1rem">${title} (${rows.length})</h2>`;
  if (!rows.length) html += "<p>None.</p>";
  for (const r of rows) html += `<div class="flag">${r}</div>`;
  return html;
}
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
  html += section("Missed lines", state.missed.map((m) =>
    `<span>${m.id.replace("missed_", "M")}</span>` +
    `<span style="color:${MISSED_COLOR}">missed ${delBtn("missed", m.id)}</span>`));
  html += section("Initials", state.initials.map((it) =>
    `<span>${it.id.replace("initial_", "I")} &ldquo;${it.key || "?"}&rdquo;</span>` +
    `<span style="color:${INITIAL_COLOR}">&rarr; ${it.target_line_id || "?"} ${delBtn("initial", it.id)}</span>`));
  html += section("Merges", state.merges.map((m) =>
    `<span>${m.id.replace("merge_", "G")}</span>` +
    `<span style="color:${MERGE_COLOR}">${m.line_ids.length} lines ${delBtn("merge", m.id)}</span>`));
  html += section("Splits", state.splits.map((s) =>
    `<span>${s.line_id}</span>` +
    `<span style="color:${SPLIT_COLOR}">@${Math.round(s.at_x)} ${delBtn("split", s.id)}</span>`));
  html += section("Section titles", state.sectionTitles.map((t) =>
    `<span>${t.id.replace("title_", "T")} &ldquo;${t.key}&rdquo;</span>` +
    `<span style="color:${TITLE_COLOR}">title ${delBtn("title", t.id)}</span>`));
  el.innerHTML = html;
}

// ---- flag modal ----
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

// ---- missed-line box (Flag tool): add via drag, delete via modal ----
function addMissedBox(box) {
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

// ---- letter modal (Initial / Title tools) ----
function openLetterModal(tool, box, hitLineId) {
  pendingLetter = { tool, box, hitLineId };
  const isTitle = tool === "title";
  $("letter-title").textContent = isTitle ? "Section-title letter" : "Initial letter";
  $("letter-hint").textContent = isTitle
    ? "Type the section letter (required), then Enter. Esc to cancel."
    : "Type the initial letter (optional), then Enter. It auto-assigns to the line on its right.";
  const input = $("letter-input");
  input.value = "";
  $("letter-backdrop").classList.add("show");
  setTimeout(() => input.focus(), 0);
}
function closeLetterModal() {
  pendingLetter = null;
  $("letter-backdrop").classList.remove("show");
}
async function confirmLetter() {
  if (!pendingLetter) return;
  const key = $("letter-input").value.trim();
  const { tool, box, hitLineId } = pendingLetter;
  if (tool === "title" && !key) { $("letter-input").focus(); return; }  // title letter is required
  pushHistory();
  if (tool === "initial") {
    const target = computeTargetLine(box);
    state.initials.push({
      id: nextId("initial", state.initials),
      key,
      box,
      target_line_id: target ? target.id : null,
    });
  } else {
    state.sectionTitles.push({
      id: nextId("title", state.sectionTitles),
      key,
      box,
      source_line_id: hitLineId || null,
    });
  }
  closeLetterModal();
  draw();
  renderFlagList();
  await saveReview();
}

// ---- merge tool ----
function toggleSelection(id) {
  const i = state.selection.indexOf(id);
  if (i >= 0) state.selection.splice(i, 1);
  else state.selection.push(id);
  updateMergeButton();
  draw();
}
function updateMergeButton() {
  const btn = $("merge-commit");
  btn.textContent = `Merge selected (${state.selection.length})`;
  btn.disabled = state.selection.length < 2;
}
async function commitMerge() {
  if (state.selection.length < 2) return;
  pushHistory();
  state.merges.push({ id: nextId("merge", state.merges), line_ids: state.selection.slice() });
  state.selection = [];
  updateMergeButton();
  draw();
  renderFlagList();
  await saveReview();
}

// ---- split tool ----
async function recordSplit(lineId, atX) {
  pushHistory();
  state.splits.push({ id: nextId("split", state.splits), line_id: lineId, at_x: atX });
  state.splitLineId = null;
  setToolHint("");
  draw();
  renderFlagList();
  await saveReview();
}

// ---- generic op deletion (side panel) ----
async function deleteOp(kind, id) {
  pushHistory();
  if (kind === "missed") state.missed = state.missed.filter((m) => m.id !== id);
  else if (kind === "initial") state.initials = state.initials.filter((x) => x.id !== id);
  else if (kind === "merge") state.merges = state.merges.filter((x) => x.id !== id);
  else if (kind === "split") state.splits = state.splits.filter((x) => x.id !== id);
  else if (kind === "title") state.sectionTitles = state.sectionTitles.filter((x) => x.id !== id);
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
    initials: JSON.parse(JSON.stringify(state.initials)),
    merges: JSON.parse(JSON.stringify(state.merges)),
    splits: JSON.parse(JSON.stringify(state.splits)),
    sectionTitles: JSON.parse(JSON.stringify(state.sectionTitles)),
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
  Object.assign(state, prev);
  state.selection = [];
  state.splitLineId = null;
  closeModal();
  closeMissedModal();
  closeLetterModal();
  updateMergeButton();
  draw();
  renderFlagList();
  updateUndoButton();
  await saveReview();
}

// ---- persistence ----
let saveTimer = null;
async function saveReview() {
  try {
    await api("POST", `/api/pages/${state.page}/review`, {
      flags: state.flags,
      missed: state.missed,
      initials: state.initials,
      merges: state.merges,
      splits: state.splits,
      section_titles: state.sectionTitles,
    });
    const s = $("saved");
    s.textContent = "saved";
    s.classList.add("ok");
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => { s.textContent = ""; s.classList.remove("ok"); }, 1500);
  } catch (e) {
    $("saved").textContent = "save failed: " + e.message;
  }
}

// ---- tools ----
function setTool(tool) {
  if (!TOOLS.includes(tool)) return;
  state.tool = tool;
  state.selection = [];
  state.splitLineId = null;
  updateMergeButton();
  setToolHint(tool === "split" ? "Click a line to split, then click the cut position."
    : tool === "merge" ? "Click lines to select; then Merge selected."
    : tool === "initial" ? "Drag a box around the initial letter."
    : tool === "title" ? "Drag a box (or click a line) over the title letter."
    : "");
  document.querySelectorAll(".tool").forEach((b) =>
    b.classList.toggle("active", b.dataset.tool === tool));
  canvas.style.cursor = tool === "flag" ? "crosshair" : "cell";
  draw();
}
function setToolHint(text) { $("tool-hint").textContent = text; }

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
  for (const [id, info] of Object.entries(review.flags || {})) state.flags[id] = info.category;
  state.missed = (review.missed_lines || []).map((m) => ({ id: m.id, box: m.box.slice() }));
  state.initials = (review.initials || []).map((x) => ({ ...x, box: x.box.slice() }));
  state.merges = (review.merges || []).map((x) => ({ ...x, line_ids: x.line_ids.slice() }));
  state.splits = (review.splits || []).map((x) => ({ ...x }));
  state.sectionTitles = (review.section_titles || []).map((x) => ({ ...x, box: x.box.slice() }));
  state.selection = [];
  state.splitLineId = null;
  state.history = [];   // undo is scoped to the current page
  state.hoverLineId = null;
  state.hoverMissedId = null;
  drag = null;
  updateUndoButton();
  updateMergeButton();
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

// ---- canvas interaction ----
function updateHover(x, y) {
  if (state.tool !== "flag") return;   // hover highlight only matters for the Flag tool
  const m = hitMissed(x, y);
  const line = m ? null : hitTest(x, y);
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
    // box-drawing tools show a live rubber-band; others fall through to hover
    if (drag.moved && (state.tool === "flag" || state.tool === "initial" || state.tool === "title")) {
      draw(); return;
    }
  }
  updateHover(x, y);
});

canvas.addEventListener("mouseup", (ev) => {
  const { x, y } = canvasPos(ev);
  const d = drag;
  drag = null;
  const movedFar = d && (Math.abs(x - d.startX) > DRAG_THRESHOLD || Math.abs(y - d.startY) > DRAG_THRESHOLD);
  const isDrag = d && (d.moved || movedFar);
  const line = hitTest(x, y);

  if (state.tool === "flag") {
    if (isDrag) { const box = dragToBox(d); if (box) addMissedBox(box); return; }
    const m = hitMissed(x, y);
    if (m) { openMissedModal(m); return; }
    if (line) openModal(line);
    return;
  }
  if (state.tool === "initial") {
    const box = isDrag ? dragToBox(d) : (line && line.bbox ? line.bbox.slice() : null);
    if (box) openLetterModal("initial", box, line ? line.id : null);
    return;
  }
  if (state.tool === "title") {
    const box = isDrag ? dragToBox(d) : (line && line.bbox ? line.bbox.slice() : null);
    if (box) openLetterModal("title", box, line ? line.id : null);
    return;
  }
  if (state.tool === "merge") {
    if (line) toggleSelection(line.id);
    return;
  }
  if (state.tool === "split") {
    if (!state.splitLineId) {
      if (line) {
        state.splitLineId = line.id;
        setToolHint(`Click the cut position inside ${line.id}.`);
        draw();
      }
    } else {
      const target = lineById(state.splitLineId);
      const fx = toFull(x);
      if (target && target.bbox && fx > target.bbox[0] + 3 && fx < target.bbox[2] - 3) {
        recordSplit(state.splitLineId, Math.round(fx));
      } else {
        state.splitLineId = null; setToolHint("Click a line to split, then click the cut position."); draw();
      }
    }
    return;
  }
});

canvas.addEventListener("mouseleave", () => {
  drag = null;
  if (state.hoverLineId !== null || state.hoverMissedId !== null) {
    state.hoverLineId = null;
    state.hoverMissedId = null;
    draw();
  }
});

// ---- flag modal buttons ----
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

$("letter-ok").addEventListener("click", confirmLetter);
$("letter-cancel").addEventListener("click", closeLetterModal);
$("letter-input").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter") { ev.preventDefault(); confirmLetter(); }
  else if (ev.key === "Escape") { ev.preventDefault(); closeLetterModal(); }
  ev.stopPropagation();  // keep letters/shortcuts from reaching the global handler
});
$("letter-backdrop").addEventListener("click", (ev) => {
  if (ev.target === $("letter-backdrop")) closeLetterModal();
});

// side-panel delete buttons (event delegation)
$("flag-list").addEventListener("click", (ev) => {
  const btn = ev.target.closest("button.del");
  if (btn) deleteOp(btn.dataset.del, btn.dataset.id);
});

// tool buttons
document.querySelectorAll(".tool").forEach((btn) => {
  btn.addEventListener("click", () => setTool(btn.dataset.tool));
});
$("merge-commit").addEventListener("click", commitMerge);

document.addEventListener("keydown", (ev) => {
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
    return;
  }
  if (pendingLetter) return;  // the letter input handles its own keys
  // tool shortcuts
  const k = ev.key.toLowerCase();
  const shortcut = { f: "flag", i: "initial", m: "merge", s: "split", t: "title" }[k];
  if (shortcut) { setTool(shortcut); return; }
  if (ev.key === "Enter" && state.tool === "merge") { ev.preventDefault(); commitMerge(); return; }
  if (ev.key === "Escape") {
    if (state.selection.length || state.splitLineId) {
      state.selection = []; state.splitLineId = null; updateMergeButton(); setToolHint(""); draw();
    }
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
