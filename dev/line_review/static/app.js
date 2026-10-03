"use strict";

// Phase 9 review: fix the paddle-filled baseline with ops, then verify the result.
// The server materializes the ops on every save; this page only draws what it returns.

const COLORS = {  // must match the --paddle/--fill/--edited/--ghost/--clean vars in CSS
  paddle: "#3fb37f", fill: "#4c8bf5", edited: "#e05ac4", ghost: "#9aa0ac",
  clean: "#ff9f1c", select: "#ffffff", initial: "#a06cff", title: "#f0b429", split: "#ff5d5d",
  pageno: "#2fbfbf",
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
// In-progress reshape of the one selected line: drag a vertex, an edge, or the body.
let edit = null;           // {key, kind: "vertex"|"edge"|"move", index, start:[fx,fy], orig, preview}
const HANDLE_R = 7;        // display px: grab radius for a vertex dot
const EDGE_R = 5;          // display px: grab distance for an edge
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

// kraken polygons carry ~100 points (many duplicates), too dense to drag one by one.
// Before showing handles, drop duplicates and simplify (Ramer-Douglas-Peucker) to
// within SIMPLIFY_TOL full-res px of the original; Paddle's 4-point boxes pass through.
const SIMPLIFY_TOL = 2.5;
const MAX_RAW_POINTS = 12;

// Ramer-Douglas-Peucker on an open path; keeps both endpoints.
function simplifyPath(path) {
  let far = -1, farD = 0;
  for (let i = 1; i < path.length - 1; i++) {
    const d = segmentDistance(path[i][0], path[i][1], path[0], path[path.length - 1]);
    if (d > farD) { far = i; farD = d; }
  }
  if (farD <= SIMPLIFY_TOL) return [path[0], path[path.length - 1]];
  return [...simplifyPath(path.slice(0, far + 1)).slice(0, -1), ...simplifyPath(path.slice(far))];
}

function simplifyRing(pts) {
  const dedup = pts.filter((p, i) => i === 0 || p[0] !== pts[i - 1][0] || p[1] !== pts[i - 1][1]);
  if (dedup.length <= MAX_RAW_POINTS) return dedup;
  // Cut the ring at the point farthest from the first, simplify both halves as paths.
  let split = 1, best = 0;
  dedup.forEach((p, i) => {
    const d = Math.hypot(p[0] - dedup[0][0], p[1] - dedup[0][1]);
    if (d > best) { best = d; split = i; }
  });
  const a = simplifyPath(dedup.slice(0, split + 1));
  const b = simplifyPath([...dedup.slice(split), dedup[0]]);
  return [...a, ...b.slice(1, -1)];
}

// Points shown as handles (and edited) for a line.
const handlePoints = (l) => simplifyRing(l.boundary);

// The single selected line, if exactly one is selected (only then are handles shown).
function soleSelected() {
  if (state.selection.size !== 1) return null;
  return lineByKey([...state.selection][0]);
}

function segmentDistance(px, py, [ax, ay], [bx, by]) {
  const dx = bx - ax, dy = by - ay;
  const len2 = dx * dx + dy * dy;
  const t = len2 ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2)) : 0;
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

// What a press at display (x, y) grabs on the selected line: a vertex, an edge, or the body.
function hitHandle(dispX, dispY) {
  const l = soleSelected();
  if (!l) return null;
  const pts = handlePoints(l);
  for (let i = 0; i < pts.length; i++) {
    if (Math.hypot(toDisp(pts[i][0]) - dispX, toDisp(pts[i][1]) - dispY) <= HANDLE_R) {
      return { key: l.key, kind: "vertex", index: i };
    }
  }
  for (let i = 0; i < pts.length; i++) {
    const a = pts[i].map(toDisp), b = pts[(i + 1) % pts.length].map(toDisp);
    if (segmentDistance(dispX, dispY, a, b) <= EDGE_R) return { key: l.key, kind: "edge", index: i };
  }
  if (pointInPolygon(toFull(dispX), toFull(dispY), pts)) return { key: l.key, kind: "move", index: -1 };
  return null;
}

// The boundary after dragging ``edit`` by (dx, dy) full-res px.
function draggedBoundary(e, dx, dy) {
  const pts = clone(e.orig);
  const n = pts.length;
  const move = (i) => { pts[i][0] = Math.round(pts[i][0] + dx); pts[i][1] = Math.round(pts[i][1] + dy); };
  if (e.kind === "vertex") move(e.index);
  else if (e.kind === "edge") { move(e.index); move((e.index + 1) % n); }
  else for (let i = 0; i < n; i++) move(i);
  return pts;
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

const SELECT_HINT = "Drag a dot, an edge or the box to reshape it. Option-drag adds missed ink. P = it's the page number.";

function draw() {
  if (state.tool === "select" && editable()) {
    const hint = $("tool-hint");
    if (soleSelected()) hint.textContent = SELECT_HINT;
    else if (hint.textContent === SELECT_HINT) hint.textContent = "";
  }
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
    const selected = !clean && state.selection.has(l.key);
    const boundary = edit && edit.key === l.key ? edit.preview : l.boundary;
    tracePolygon(boundary);
    if (selected) { ctx.fillStyle = color + "55"; ctx.fill(); }
    else if (hover) { ctx.fillStyle = color + "33"; ctx.fill(); }
    ctx.lineWidth = selected ? 2.5 : clean ? 2 : (hover ? 2.5 : 1.5);
    ctx.strokeStyle = selected ? COLORS.select : color;
    ctx.stroke();
    if (selected && state.selection.size === 1) {
      for (const [x, y] of (edit && edit.key === l.key ? edit.preview : handlePoints(l))) {
        ctx.beginPath();
        ctx.arc(toDisp(x), toDisp(y), 4, 0, 2 * Math.PI);
        ctx.fillStyle = COLORS.select;
        ctx.fill();
        ctx.lineWidth = 1.5;
        ctx.strokeStyle = color;
        ctx.stroke();
      }
    }
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
  if (state.data.page_number) {
    const { box, value } = state.data.page_number;
    strokeBox(box, COLORS.pageno, 2.5, [6, 3]);
    ctx.fillStyle = COLORS.pageno;
    ctx.font = "bold 12px sans-serif";
    ctx.fillText(`page no. ${value}`, toDisp(box[0]), toDisp(box[1]) - 4);
  }
  for (const t of state.titles) {
    strokeBox(t.box, COLORS.title, 2.5);
    ctx.fillStyle = COLORS.title;
    ctx.font = "bold 12px sans-serif";
    ctx.fillText(t.letter, toDisp(t.box[0]) + 2, toDisp(t.box[1]) + 13);
  }

  if (drag && drag.moved && state.tool !== "split") {
    const x = Math.min(drag.startX, drag.curX), y = Math.min(drag.startY, drag.curY);
    const c = state.tool === "title" ? COLORS.title : state.tool === "initial" || drag.grow ? COLORS.initial : COLORS.edited;
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
    case "grow": return `grow ${op.line}`;
    case "page_number": return `page number ${op.value}`;
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
  if (d.page_number && d.page_number.value !== d.expected_page_number) {
    warn.push(`Printed page number ${d.page_number.value} isn't the expected ${d.expected_page_number} (PDF page \u2212 4): check it.`);
  }
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

// Save a reshape. Back-to-back reshapes of the same line collapse into one op, so a
// box adjusted in several drags is still one edit (undo steps back drag by drag).
function commitReshape(key, boundary) {
  const last = state.ops[state.ops.length - 1];
  const op = { op: "reshape", line: key, boundary };
  const ops = last && last.op === "reshape" && last.line === key
    ? [...state.ops.slice(0, -1), op] : [...state.ops, op];
  commit(ops, state.titles);
}

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
  $("letter-title").textContent = { title: "Section-title letter", initial: "Initial letter",
    page: "Printed page number" }[tool];
  $("letter-hint").textContent = {
    title: "Type the section letter (required), then Enter.",
    initial: "Type the letter (optional), then Enter. It joins the upper line on its right.",
    page: "The number printed on the page. Pre-filled with PDF page \u2212 4; Enter to confirm.",
  }[tool];
  $("letter-input").value = tool === "page" ? state.data.expected_page_number : "";
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
  if (tool === "page") {
    if (!letter) { $("letter-input").focus(); return; }
    closeLetterModal();
    pushOp({ op: "page_number", line: lineKey, value: letter });
    return;
  }
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
  drag.grow = state.tool === "select" && ev.altKey && soleSelected() ? soleSelected().key : null;
  const h = state.tool === "select" && !ev.shiftKey && !drag.grow ? hitHandle(x, y) : null;
  if (h) {
    const l = lineByKey(h.key);
    const pts = handlePoints(l);
    edit = { ...h, start: [toFull(x), toFull(y)], orig: clone(pts), preview: clone(pts) };
  }
});

canvas.addEventListener("mousemove", (ev) => {
  if (!state.data) return;
  const { x, y } = canvasPos(ev);
  if (drag) {
    drag.curX = x; drag.curY = y;
    if (Math.abs(x - drag.startX) > DRAG_THRESHOLD || Math.abs(y - drag.startY) > DRAG_THRESHOLD) drag.moved = true;
    if (drag.moved && edit) {
      edit.preview = draggedBoundary(edit, toFull(x) - edit.start[0], toFull(y) - edit.start[1]);
      draw();
      return;
    }
    if (drag.moved) { draw(); return; }
  }
  if (editable() && state.tool === "select") {
    const h = hitHandle(x, y);
    canvas.style.cursor = !h ? "crosshair" : h.kind === "move" ? "move" : "grab";
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
  const e = edit;
  drag = null;
  edit = null;
  if (!editable() || !d) return;
  const { x, y } = canvasPos(ev);
  const line = hitLine(x, y);

  if (e && d.moved) { commitReshape(e.key, e.preview); return; }
  if (d.grow && d.moved) {
    const box = dragToBox(d);
    if (box) pushOp({ op: "grow", line: d.grow, box }); else draw();
    return;
  }

  if (state.tool === "select") {
    if (d.moved) {
      const box = dragToBox(d);
      if (box) pushOp({ op: "add", key: nextKey("add"), boundary: boxPolygon(box) });
      else draw();
      return;
    }
    if (!line) { state.selection.clear(); draw(); return; }
    if (!ev.shiftKey) state.selection = new Set([line.key]);
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
  if (edit) { edit = null; draw(); }
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
  if (k === "p") {
    const l = soleSelected();
    if (!l) { setHint("Select the page-number box first (drag one if it's missing), then press P."); return; }
    if (state.data.page_number) { setHint("This page already has a page number; remove that edit first."); return; }
    openLetterModal("page", l.bbox, l.key);
    return;
  }
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
