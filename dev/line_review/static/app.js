"use strict";

// Phase 9 review: fix the paddle-filled baseline with ops, then verify the result.
// The server materializes the ops on every save; this page only draws what it returns.

const COLORS = {  // must match the --paddle/--fill/--edited/--ghost/--clean vars in CSS
  paddle: "#3fb37f", fill: "#4c8bf5", edited: "#e05ac4", ghost: "#9aa0ac",
  clean: "#ff9f1c", select: "#ffffff", initial: "#a06cff", title: "#f0b429", split: "#ff5d5d",
};
const STATUS_GLYPH = { unreviewed: "·", fixing: "✎", fixed: "◐", verified: "✓" };
const DRAG_THRESHOLD = 5;  // display px of movement before a press counts as a drag
const MIN_BOX = 8;         // ignore full-res boxes smaller than this (stray clicks)
const CUT_OVERHANG = 20;   // full-res px a split cut extends past the line on each side

const $ = (id) => document.getElementById(id);
const canvas = $("canvas");
const ctx = canvas.getContext("2d");
const pageImg = new Image();

const state = {
  pages: [], statuses: {}, page: null,
  data: null,           // server payload: lines, ghosts, ops, status, ...
  ops: [], titles: [],  // editable copies (ops are the source of truth)
  tool: "select",
  selection: new Set(), // selected line keys
  splitKey: null,       // split tool: line awaiting its cut
  history: [],          // undo stack of {ops, titles}
  hoverKey: null,
  scale: 1,
};
let drag = null;           // in-progress press/drag (display px)
let pendingLetter = null;  // {tool, box, lineKey}

const editable = () => state.data && ["unreviewed", "fixing"].includes(state.data.status)
  && !state.data.baseline_changed;
const toDisp = (v) => v / state.scale;
const toFull = (v) => v * state.scale;
const clone = (x) => JSON.parse(JSON.stringify(x));

// ---- API ----
async function api(method, url, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(url, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

function flash(text, kind) {
  const el = $("saved");
  el.textContent = text;
  el.className = kind || "";
  clearTimeout(flash.t);
  if (kind === "ok") flash.t = setTimeout(() => { el.textContent = ""; el.className = ""; }, 1500);
}

// ---- geometry ----
const lineByKey = (key) => state.data.lines.find((l) => l.key === key) || null;

function pointInPolygon(px, py, poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > py) !== (yj > py) && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function hitLine(dispX, dispY) {
  const fx = toFull(dispX), fy = toFull(dispY);
  let best = null, bestArea = Infinity;
  for (const l of state.data.lines) {
    if (!pointInPolygon(fx, fy, l.boundary)) continue;
    const area = (l.bbox[2] - l.bbox[0]) * (l.bbox[3] - l.bbox[1]);
    if (area < bestArea) { best = l; bestArea = area; }
  }
  return best;
}

function dragToBox(d) {
  const x1 = toFull(Math.min(d.startX, d.curX)), y1 = toFull(Math.min(d.startY, d.curY));
  const x2 = toFull(Math.max(d.startX, d.curX)), y2 = toFull(Math.max(d.startY, d.curY));
  if (x2 - x1 < MIN_BOX || y2 - y1 < MIN_BOX) return null;
  return [Math.round(x1), Math.round(y1), Math.round(x2), Math.round(y2)];
}

const boxPolygon = ([x1, y1, x2, y2]) => [[x1, y1], [x2, y1], [x2, y2], [x1, y2]];

// The upper of the lines adjacent to the right of an initial box, in the nearest
// column to the right (same rule as the survey UI).
function computeTargetLine(box) {
  const [bx1, by1, bx2, by2] = box;
  const cands = state.data.lines.filter((l) => {
    const [x1, y1, x2, y2] = l.bbox;
    return x2 > bx2 && x1 >= bx1 && Math.min(by2, y2) - Math.max(by1, y1) > 0.2 * (by2 - by1);
  });
  if (!cands.length) return null;
  const minLeft = Math.min(...cands.map((l) => l.bbox[0]));
  const nearest = cands.filter((l) => l.bbox[0] <= minLeft + Math.max(bx2 - bx1, 60));
  nearest.sort((a, b) => a.bbox[1] - b.bbox[1]);
  return nearest[0];
}

function nextKey(prefix) {
  let max = 0;
  for (const op of state.ops) {
    const m = op.op === "add" && String(op.key).match(new RegExp(`^${prefix}_(\\d+)$`));
    if (m) max = Math.max(max, parseInt(m[1], 10));
  }
  return `${prefix}_${String(max + 1).padStart(3, "0")}`;
}

function nextTitleId() {
  let max = 0;
  for (const t of state.titles) max = Math.max(max, parseInt((t.id.match(/(\d+)$/) || [])[1] || "0", 10));
  return `title_${String(max + 1).padStart(3, "0")}`;
}

// ---- drawing ----
function tracePolygon(points) {
  ctx.beginPath();
  ctx.moveTo(toDisp(points[0][0]), toDisp(points[0][1]));
  for (const [x, y] of points.slice(1)) ctx.lineTo(toDisp(x), toDisp(y));
  ctx.closePath();
}

function strokeBox(box, color, width, dash) {
  const [x1, y1, x2, y2] = box;
  ctx.setLineDash(dash || []);
  ctx.lineWidth = width;
  ctx.strokeStyle = color;
  ctx.strokeRect(toDisp(x1), toDisp(y1), toDisp(x2 - x1), toDisp(y2 - y1));
  ctx.setLineDash([]);
}

function lineColor(l) {
  if (!editable()) return COLORS.clean;
  if (l.edited || l.source === "human") return COLORS.edited;
  return l.source === "kraken-fill" ? COLORS.fill : COLORS.paddle;
}

function draw() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (pageImg.complete && pageImg.naturalWidth) ctx.drawImage(pageImg, 0, 0, canvas.width, canvas.height);
  if (!state.data) return;
  const clean = !editable();

  if (!clean) {
    for (const g of state.data.ghosts) {
      tracePolygon(g.boundary);
      ctx.setLineDash([5, 4]);
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = COLORS.ghost;
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }

  for (const l of state.data.lines) {
    const color = lineColor(l);
    const hover = l.key === state.hoverKey;
    tracePolygon(l.boundary);
    if (hover) { ctx.fillStyle = color + "44"; ctx.fill(); }
    ctx.lineWidth = clean ? 2 : (hover ? 2.5 : 1.5);
    ctx.strokeStyle = color;
    ctx.stroke();
    if (state.selection.has(l.key)) strokeBox(l.bbox, COLORS.select, 3);
    if (l.key === state.splitKey) strokeBox(l.bbox, COLORS.split, 3, [4, 3]);
    // reading-order number at the line's left edge
    ctx.font = clean ? "bold 13px sans-serif" : "11px sans-serif";
    const tag = String(l.order);
    const tx = toDisp(l.bbox[0]) - (clean ? ctx.measureText(tag).width + 6 : -2);
    const ty = toDisp(l.bbox[1]) + (clean ? toDisp(l.bbox[3] - l.bbox[1]) / 2 + 5 : 11);
    if (clean) {
      ctx.fillStyle = "#000000aa";
      ctx.fillRect(tx - 2, ty - 12, ctx.measureText(tag).width + 4, 15);
    }
    ctx.fillStyle = color;
    ctx.fillText(tag, tx, ty);
  }

  if (!clean) {
    for (const op of state.ops) {
      if (op.op !== "initial") continue;
      const [x1, y1] = op.box;
      strokeBox(op.box, COLORS.initial, 2, [3, 3]);
      ctx.fillStyle = COLORS.initial;
      ctx.font = "bold 12px sans-serif";
      ctx.fillText(op.letter || "I", toDisp(x1) + 2, toDisp(y1) + 13);
    }
  }
  for (const t of state.titles) {
    strokeBox(t.box, COLORS.title, 2.5);
    ctx.fillStyle = COLORS.title;
    ctx.font = "bold 12px sans-serif";
    ctx.fillText(t.letter, toDisp(t.box[0]) + 2, toDisp(t.box[1]) + 13);
  }

  if (drag && drag.moved && state.tool !== "split") {
    const x = Math.min(drag.startX, drag.curX), y = Math.min(drag.startY, drag.curY);
    const c = state.tool === "title" ? COLORS.title : state.tool === "initial" ? COLORS.initial : COLORS.edited;
    ctx.setLineDash([5, 3]);
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = c;
    ctx.strokeRect(x, y, Math.abs(drag.curX - drag.startX), Math.abs(drag.curY - drag.startY));
    ctx.setLineDash([]);
  }
}

// ---- side panel ----
function opLabel(op) {
  switch (op.op) {
    case "delete": return `delete ${op.line}`;
    case "add": return `add ${op.key}`;
    case "reshape": return `reshape ${op.line}`;
    case "split": return `split ${op.line}`;
    case "merge": return `merge ${op.lines.join(" + ")}`;
    case "initial": return `initial ${op.letter || "?"} → ${op.line}`;
    case "order": return "reading order";
    case "dismiss_ink": return "dismiss ink";
    default: return op.op;
  }
}

function renderPanel() {
  const d = state.data;
  const help = {
    unreviewed: "Fix the boxes: click to select (Shift adds), <b>Delete</b> removes, <b>M</b> merges, drag adds a line. <b>Enter</b> = Mark fixed.",
    fixing: "Fix the boxes: click to select (Shift adds), <b>Delete</b> removes, <b>M</b> merges, drag adds a line. <b>Enter</b> = Mark fixed.",
    fixed: "Clean view: the boxes as they will be saved, numbered in reading order. <b>Enter</b> = Mark verified, <b>R</b> = Resume fixing.",
    verified: "Verified and locked. Ids are minted; hover a line to see its id. <b>R</b> = Resume fixing.",
  };
  $("help").innerHTML = help[d.status];
  let html = `<h2>Edits (${state.ops.length})</h2>`;
  if (!state.ops.length) html += "<p>None.</p>";
  state.ops.forEach((op, i) => {
    html += `<div class="op"><span>${i + 1}. ${opLabel(op)}</span>` +
      `<button class="del" data-op="${i}" title="Remove this edit">&times;</button></div>`;
  });
  html += `<h2>Section titles (${state.titles.length})</h2>`;
  if (!state.titles.length) html += "<p>None.</p>";
  state.titles.forEach((t, i) => {
    html += `<div class="op"><span>${t.letter}</span>` +
      `<button class="del" data-title="${i}" title="Remove">&times;</button></div>`;
  });
  $("op-list").innerHTML = html;
}

function renderHeader() {
  const d = state.data;
  document.body.classList.toggle("clean", !editable());
  const badge = $("status-badge");
  badge.textContent = d.status;
  badge.className = d.status;
  const adv = $("advance");
  adv.style.display = d.status === "verified" ? "none" : "";
  adv.textContent = d.status === "fixed" ? "Mark verified" : "Mark fixed";
  $("resume").style.display = ["fixed", "verified"].includes(d.status) ? "" : "none";
  $("undo").disabled = !editable() || !state.history.length;
  $("count").textContent = `${d.lines.length} lines`;
  const opt = $("page-select").querySelector(`option[value="${state.page}"]`);
  if (opt) opt.textContent = pageLabel(state.page);
  const vals = Object.values(state.statuses);
  const n = (s) => vals.filter((v) => v === s).length;
  $("progress").textContent = `${n("verified")} verified · ${n("fixed")} fixed · ${vals.length} pages`;

  const warn = [];
  if (d.baseline_changed) warn.push("paddle-filled changed since this page's review began, so its edits can't be applied safely. Edits are disabled.");
  if (d.error) warn.push(`Edits failed to apply: ${d.error}`);
  if (d.blank_marker && d.lines.length) warn.push(`This page has a blank marker (data/pages/blank/), but ${d.lines.length} lines remain: delete them, or the marker is wrong.`);
  if (!d.blank_marker && !d.lines.length) warn.push("No lines and no blank marker: is this page really blank?");
  $("banner").textContent = warn.join("  ");
}

const pageLabel = (p) => `${STATUS_GLYPH[state.statuses[p] || "unreviewed"]} page ${p}`;

function render() {
  renderHeader();
  renderPanel();
  draw();
}

function applyPayload(d) {
  state.data = d;
  state.ops = clone(d.ops);
  state.titles = clone(d.section_titles);
  state.statuses[state.page] = d.status;
  const keys = new Set(d.lines.map((l) => l.key));
  state.selection = new Set([...state.selection].filter((k) => keys.has(k)));
  if (state.splitKey && !keys.has(state.splitKey)) state.splitKey = null;
}

// ---- saving edits ----
async function commit(ops, titles) {
  if (!editable()) return;
  const before = { ops: clone(state.ops), titles: clone(state.titles) };
  try {
    const d = await api("PUT", `/api/pages/${state.page}/ops`, { ops, section_titles: titles });
    state.history.push(before);
    applyPayload(d);
    flash("saved", "ok");
  } catch (e) {
    flash(e.message, "err");
  }
  render();
}

const pushOp = (op) => commit([...state.ops, op], state.titles);

async function undo() {
  if (!editable() || !state.history.length) return;
  const prev = state.history.pop();
  try {
    applyPayload(await api("PUT", `/api/pages/${state.page}/ops`, { ops: prev.ops, section_titles: prev.titles }));
    flash("undone", "ok");
  } catch (e) {
    state.history.push(prev);
    flash(e.message, "err");
  }
  render();
}

function deleteSelected() {
  if (!state.selection.size) return;
  const ops = [...state.ops, ...[...state.selection].map((k) => ({ op: "delete", line: k }))];
  state.selection.clear();
  commit(ops, state.titles);
}

function mergeSelected() {
  if (state.selection.size < 2) { setHint("Select 2 or more lines (Shift-click) to merge."); return; }
  const order = state.data.lines.map((l) => l.key).filter((k) => state.selection.has(k));
  state.selection.clear();
  pushOp({ op: "merge", lines: order });
}

function deleteAll() {
  if (!state.data.lines.length) return;
  commit([...state.ops, ...state.data.lines.map((l) => ({ op: "delete", line: l.key }))], state.titles);
}

// ---- status ----
async function setStatus(status) {
  try {
    applyPayload(await api("POST", `/api/pages/${state.page}/status`, { status }));
    state.history = [];
    state.selection.clear();
    state.splitKey = null;
    flash(status, "ok");
  } catch (e) {
    flash(e.message, "err");
    return false;
  }
  render();
  return true;
}

async function advance() {
  const s = state.data.status;
  if (s === "unreviewed" || s === "fixing") await setStatus("fixed");
  else if (s === "fixed" && await setStatus("verified")) step(1);
}

// ---- tools ----
function setHint(text) { $("tool-hint").textContent = text; }

function setTool(tool) {
  state.tool = tool;
  state.selection.clear();
  state.splitKey = null;
  setHint({
    select: "", split: "Click a line to split.",
    initial: "Drag a box around the drop-cap.", title: "Drag a box (or click a line) over the title letter.",
  }[tool]);
  document.querySelectorAll(".tool").forEach((b) => b.classList.toggle("active", b.dataset.tool === tool));
  draw();
}

function openLetterModal(tool, box, lineKey) {
  pendingLetter = { tool, box, lineKey };
  const isTitle = tool === "title";
  $("letter-title").textContent = isTitle ? "Section-title letter" : "Initial letter";
  $("letter-hint").textContent = isTitle
    ? "Type the section letter (required), then Enter."
    : "Type the letter (optional), then Enter. It joins the upper line on its right.";
  $("letter-input").value = "";
  $("letter-backdrop").classList.add("show");
  setTimeout(() => $("letter-input").focus(), 0);
}

function closeLetterModal() {
  pendingLetter = null;
  $("letter-backdrop").classList.remove("show");
}

function confirmLetter() {
  if (!pendingLetter) return;
  const letter = $("letter-input").value.trim();
  const { tool, box, lineKey } = pendingLetter;
  if (tool === "title") {
    if (!letter) { $("letter-input").focus(); return; }
    closeLetterModal();
    commit(state.ops, [...state.titles, { id: nextTitleId(), letter, box, source_line: lineKey || null }]);
    return;
  }
  closeLetterModal();
  const target = computeTargetLine(box);
  if (!target) { setHint("No line to the right of that box to attach the initial to."); return; }
  pushOp({ op: "initial", box, line: target.key, letter });
}

// ---- canvas interaction ----
function canvasPos(ev) {
  const r = canvas.getBoundingClientRect();
  return { x: ev.clientX - r.left, y: ev.clientY - r.top };
}

canvas.addEventListener("mousedown", (ev) => {
  if (!editable()) return;
  const { x, y } = canvasPos(ev);
  drag = { startX: x, startY: y, curX: x, curY: y, moved: false };
});

canvas.addEventListener("mousemove", (ev) => {
  if (!state.data) return;
  const { x, y } = canvasPos(ev);
  if (drag) {
    drag.curX = x; drag.curY = y;
    if (Math.abs(x - drag.startX) > DRAG_THRESHOLD || Math.abs(y - drag.startY) > DRAG_THRESHOLD) drag.moved = true;
    if (drag.moved) { draw(); return; }
  }
  const l = hitLine(x, y);
  const key = l ? l.key : null;
  if (key !== state.hoverKey) {
    state.hoverKey = key;
    if (!editable() && l) setHint(l.id ? `${l.id}  (${l.key})` : l.key);
    draw();
  }
});

canvas.addEventListener("mouseup", (ev) => {
  const d = drag;
  drag = null;
  if (!editable() || !d) return;
  const { x, y } = canvasPos(ev);
  const line = hitLine(x, y);

  if (state.tool === "select") {
    if (d.moved) {
      const box = dragToBox(d);
      if (box) pushOp({ op: "add", key: nextKey("add"), boundary: boxPolygon(box) });
      else draw();
      return;
    }
    if (!line) { state.selection.clear(); draw(); return; }
    if (!ev.shiftKey) state.selection = new Set(state.selection.has(line.key) && state.selection.size === 1 ? [] : [line.key]);
    else if (state.selection.has(line.key)) state.selection.delete(line.key);
    else state.selection.add(line.key);
    draw();
    return;
  }
  if (state.tool === "split") {
    if (!state.splitKey) {
      if (line) { state.splitKey = line.key; setHint("Click the cut: vertical, or Shift-click for horizontal."); draw(); }
      return;
    }
    const target = lineByKey(state.splitKey);
    const [x1, y1, x2, y2] = target.bbox;
    const fx = toFull(x), fy = toFull(y);
    state.splitKey = null;
    setHint("Click a line to split.");
    const cut = ev.shiftKey
      ? [[x1 - CUT_OVERHANG, Math.round(fy)], [x2 + CUT_OVERHANG, Math.round(fy)]]
      : [[Math.round(fx), y1 - CUT_OVERHANG], [Math.round(fx), y2 + CUT_OVERHANG]];
    pushOp({ op: "split", line: target.key, cut });
    return;
  }
  if (state.tool === "initial" || state.tool === "title") {
    const box = d.moved ? dragToBox(d) : (line ? line.bbox.map(Math.round) : null);
    if (box) openLetterModal(state.tool, box, line ? line.key : null);
    else draw();
  }
});

canvas.addEventListener("mouseleave", () => {
  drag = null;
  if (state.hoverKey) { state.hoverKey = null; draw(); }
});

// ---- controls ----
$("op-list").addEventListener("click", (ev) => {
  const btn = ev.target.closest("button.del");
  if (!btn || !editable()) return;
  if (btn.dataset.op !== undefined) commit(state.ops.filter((_, i) => i !== Number(btn.dataset.op)), state.titles);
  else commit(state.ops, state.titles.filter((_, i) => i !== Number(btn.dataset.title)));
});
document.querySelectorAll(".tool").forEach((b) => b.addEventListener("click", () => setTool(b.dataset.tool)));
$("delete-all").addEventListener("click", deleteAll);
$("advance").addEventListener("click", advance);
$("resume").addEventListener("click", () => setStatus("fixing"));
$("undo").addEventListener("click", undo);
$("prev").addEventListener("click", () => step(-1));
$("next").addEventListener("click", () => step(1));
$("page-select").addEventListener("change", (ev) => loadPage(Number(ev.target.value)));
$("letter-ok").addEventListener("click", confirmLetter);
$("letter-cancel").addEventListener("click", closeLetterModal);
$("letter-input").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter") { ev.preventDefault(); confirmLetter(); }
  else if (ev.key === "Escape") { ev.preventDefault(); closeLetterModal(); }
  ev.stopPropagation();
});

document.addEventListener("keydown", (ev) => {
  if (pendingLetter || !state.data) return;
  if (ev.target.tagName === "SELECT") return;
  if ((ev.metaKey || ev.ctrlKey) && (ev.key === "z" || ev.key === "Z")) { ev.preventDefault(); undo(); return; }
  if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
  if (ev.key === "ArrowLeft") { step(-1); return; }
  if (ev.key === "ArrowRight") { step(1); return; }
  if (ev.key === "Enter") { ev.preventDefault(); advance(); return; }
  if (!editable()) {
    if (ev.key === "r" || ev.key === "R") setStatus("fixing");
    return;
  }
  if (ev.key === "Delete" || ev.key === "Backspace") { ev.preventDefault(); deleteSelected(); return; }
  if (ev.key === "Escape") { state.selection.clear(); state.splitKey = null; setHint(""); draw(); return; }
  const k = ev.key.toLowerCase();
  if (k === "m") { mergeSelected(); return; }
  const tool = { v: "select", s: "split", i: "initial", t: "title" }[k];
  if (tool) setTool(tool);
});

// ---- pages ----
function fitCanvas() {
  const w = Math.min(900, state.data.width);
  canvas.width = w;
  canvas.height = Math.round(state.data.height * (w / state.data.width));
  state.scale = state.data.width / w;
}

async function loadPage(page) {
  state.page = page;
  $("page-select").value = String(page);
  state.history = [];
  state.selection.clear();
  state.splitKey = null;
  state.hoverKey = null;
  applyPayload(await api("GET", `/api/pages/${page}`));
  await new Promise((resolve) => {
    pageImg.onload = resolve;
    pageImg.onerror = resolve;
    pageImg.src = `/api/pages/${page}/image.png`;
  });
  fitCanvas();
  setHint("");
  render();
}

function step(delta) {
  const j = state.pages.indexOf(state.page) + delta;
  if (j >= 0 && j < state.pages.length) loadPage(state.pages[j]);
}

async function init() {
  const { statuses } = await api("GET", "/api/pages");
  state.statuses = Object.fromEntries(Object.entries(statuses).map(([p, s]) => [Number(p), s]));
  state.pages = Object.keys(state.statuses).map(Number).sort((a, b) => a - b);
  $("page-select").innerHTML = state.pages.map((p) => `<option value="${p}">${pageLabel(p)}</option>`).join("");
  const first = state.pages.find((p) => state.statuses[p] !== "verified") ?? state.pages[0];
  if (first !== undefined) loadPage(first);
  else $("count").textContent = "No paddle-filled pages found.";
}

init();
