"use strict";

// ---- state -----------------------------------------------------------------
const state = {
  view: "pages",
  pages: [],            // [{n, page_id, status}]
  pageNum: null,
  pageId: null,
  imageW: 0,
  imageH: 0,
  boxes: [],            // two boxes in FULL-RES pixels: {x1,y1,x2,y2}
  scale: 1,             // full-res px per display px
  lines: [],            // [{index,column,line,status,text,image_url}]
  currentIndex: 0,
};

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
  const crumb = {
    pages: "Select a page", crop: "Crop columns",
    label: "Label lines", review: "Review predictions",
  }[name];
  $("crumbs").textContent = state.pageId ? `${state.pageId} — ${crumb}` : crumb;
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
  state.boxes = data.default_columns.map((b) => ({ ...b }));
  $("page-num").value = data.n;
  const badge = $("page-badge");
  badge.textContent = `${data.page_id} · ${data.status}`;
  badge.className = "badge " + data.status;
  const img = $("page-preview");
  img.src = `${data.page_image_url}?t=${Date.now()}`;
  $("btn-select").disabled = false;
  // Already-segmented pages (done / in_progress) can be opened straight into the
  // label+review view without re-cropping (which would discard existing labels).
  $("btn-open-labels").classList.toggle("hidden", data.status === "unlabeled");
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

// ---- crop canvas -----------------------------------------------------------
const canvas = $("crop-canvas");
const ctx = canvas.getContext("2d");
const pageImg = new Image();
let drag = null; // {box, handle, startX, startY, orig}

function enterCrop() {
  $("crop-title").textContent = `${state.pageId} (${state.imageW}×${state.imageH}px)`;
  pageImg.onload = () => {
    const maxW = Math.min(900, state.imageW);
    canvas.width = maxW;
    canvas.height = Math.round(state.imageH * (maxW / state.imageW));
    state.scale = state.imageW / canvas.width;
    drawCrop();
  };
  pageImg.src = `/api/pages/${state.pageNum}/image.png?t=${Date.now()}`;
  showView("crop");
}

const toDisp = (v) => v / state.scale;
const toFull = (v) => v * state.scale;

function drawCrop() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(pageImg, 0, 0, canvas.width, canvas.height);
  const colors = ["#4c8bf5", "#3fb37f"];
  state.boxes.forEach((b, i) => {
    const x = toDisp(b.x1), y = toDisp(b.y1);
    const w = toDisp(b.x2 - b.x1), h = toDisp(b.y2 - b.y1);
    ctx.lineWidth = 2;
    ctx.strokeStyle = colors[i];
    ctx.fillStyle = colors[i] + "22";
    ctx.fillRect(x, y, w, h);
    ctx.strokeRect(x, y, w, h);
    ctx.fillStyle = colors[i];
    ctx.font = "14px sans-serif";
    ctx.fillText(`col ${i + 1}`, x + 4, y + 16);
    for (const [hx, hy] of corners(b)) {
      ctx.fillRect(toDisp(hx) - 4, toDisp(hy) - 4, 8, 8);
    }
  });
}

function corners(b) {
  return [[b.x1, b.y1], [b.x2, b.y1], [b.x1, b.y2], [b.x2, b.y2]];
}

function hitTest(dx, dy) {
  const fx = toFull(dx), fy = toFull(dy);
  const tol = toFull(8);
  for (let i = state.boxes.length - 1; i >= 0; i--) {
    const b = state.boxes[i];
    const cs = corners(b);
    for (let c = 0; c < 4; c++) {
      if (Math.abs(fx - cs[c][0]) < tol && Math.abs(fy - cs[c][1]) < tol) {
        return { box: i, handle: c };
      }
    }
  }
  for (let i = state.boxes.length - 1; i >= 0; i--) {
    const b = state.boxes[i];
    if (fx >= b.x1 && fx <= b.x2 && fy >= b.y1 && fy <= b.y2) {
      return { box: i, handle: "move" };
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
  drag = {
    ...hit,
    startX: toFull(p.x),
    startY: toFull(p.y),
    orig: { ...state.boxes[hit.box] },
  };
  canvas.setPointerCapture(ev.pointerId);
});

canvas.addEventListener("pointermove", (ev) => {
  if (!drag) return;
  const p = canvasPos(ev);
  const fx = toFull(p.x), fy = toFull(p.y);
  const b = state.boxes[drag.box];
  const o = drag.orig;
  if (drag.handle === "move") {
    const dx = fx - drag.startX, dy = fy - drag.startY;
    b.x1 = clamp(o.x1 + dx, 0, state.imageW);
    b.x2 = clamp(o.x2 + dx, 0, state.imageW);
    b.y1 = clamp(o.y1 + dy, 0, state.imageH);
    b.y2 = clamp(o.y2 + dy, 0, state.imageH);
  } else {
    const cx = clamp(fx, 0, state.imageW), cy = clamp(fy, 0, state.imageH);
    if (drag.handle === 0) { b.x1 = cx; b.y1 = cy; }
    else if (drag.handle === 1) { b.x2 = cx; b.y1 = cy; }
    else if (drag.handle === 2) { b.x1 = cx; b.y2 = cy; }
    else { b.x2 = cx; b.y2 = cy; }
  }
  drawCrop();
});

canvas.addEventListener("pointerup", () => { drag = null; });

function clamp(v, lo, hi) { return Math.max(lo, Math.min(v, hi)); }

function normalizedBoxes() {
  return state.boxes.map((b) => ({
    x1: Math.round(Math.min(b.x1, b.x2)),
    y1: Math.round(Math.min(b.y1, b.y2)),
    x2: Math.round(Math.max(b.x1, b.x2)),
    y2: Math.round(Math.max(b.y1, b.y2)),
  }));
}

async function segment(force) {
  $("btn-segment").disabled = true;
  try {
    const body = { columns: normalizedBoxes(), deskew: $("chk-deskew").checked, force: !!force };
    const res = await api("POST", `/api/pages/${state.pageNum}/columns`, body);
    await startLabeling();
    void res;
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

// ---- labeling --------------------------------------------------------------
async function startLabeling() {
  const data = await api("GET", `/api/page/${state.pageId}/lines`);
  state.lines = data.lines;
  state.modelTag = data.model_tag || null;
  state.currentIndex = firstPendingIndex();
  $("done-summary").classList.add("hidden");
  showView("label");
  renderLine();
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
    `/api/page/${state.pageId}/column/${l.column}/line/${l.line}/label`,
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
$("btn-next-unlabeled").onclick = () => {
  const p = state.pages.find((x) => x.status === "unlabeled" && (state.pageNum == null || x.n > state.pageNum))
        || state.pages.find((x) => x.status === "unlabeled");
  if (p) loadPage(p.n); else alert("No unlabeled pages remaining.");
};
$("btn-select").onclick = () => enterCrop();
$("btn-open-labels").onclick = () => startLabeling();  // skip re-crop for labeled pages

$("btn-back-pages").onclick = () => goToPages();
$("btn-reset-boxes").onclick = () => {
  // re-fetch defaults
  api("GET", `/api/pages/${state.pageNum}`).then((d) => {
    state.boxes = d.default_columns.map((b) => ({ ...b }));
    drawCrop();
  });
};
$("btn-segment").onclick = () => segment(false);

$("btn-to-pages").onclick = () => goToPages();
$("btn-back-crop").onclick = () => enterCrop();
$("btn-submit").onclick = () => labelAndAdvance("submit");
$("btn-empty").onclick = () => labelAndAdvance("empty");
$("btn-reject").onclick = () => labelAndAdvance("reject");
$("btn-back-line").onclick = () => navLine(-1);
$("btn-next-line").onclick = () => navLine(1);
$("btn-review").onclick = () => enterReview();
$("btn-back-label").onclick = () => { showView("label"); renderLine(); };

$("line-text").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); labelAndAdvance("submit"); }
});

document.addEventListener("keydown", (e) => {
  if (state.view !== "label") return;
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
