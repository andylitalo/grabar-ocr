"use strict";

// Phase 10: type the text of sampled verified lines (docs/phase_10_ocr_test_set.md).
// The queue comes from the server; a later "correct the OCR" task would serve a
// different queue and prefill the text box, with the same screen.

// Characters a standard Armenian keyboard makes awkward to type.
const PALETTE = [
  ["՟", "pativ (abbreviation mark)"], ["֊", "hyphen"], ["։", "full stop"],
  ["՝", "comma (but)"], ["՛", "emphasis"], ["՜", "exclamation"],
  ["՞", "question"], ["․", "one-dot leader"], ["«", "«"], ["»", "»"],
  ["և", "ligature եւ"],
];
const STATUS_LABEL = { pending: "not typed", done: "done", illegible: "illegible", "bad-crop": "bad crop" };

const $ = (id) => document.getElementById(id);
const state = {
  picks: [], strata: {}, mode: "first", queue: [], index: 0, current: null,
};

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

// ---- queue ----
function buildQueue() {
  // First pass: every sampled line. Recheck: queued lines whose first pass is done.
  state.queue = state.mode === "first"
    ? state.picks.map((p) => p.id)
    : state.picks.filter((p) => p.recheck && p.status === "done").map((p) => p.id);
}

const pickById = (id) => state.picks.find((p) => p.id === id);
const isDone = (p) => (state.mode === "first" ? p.status !== "pending" : p.rechecked);

function firstOpen() {
  const i = state.queue.findIndex((id) => !isDone(pickById(id)));
  return i >= 0 ? i : 0;
}

// ---- render ----
function renderStrata() {
  $("strata").innerHTML = Object.entries(state.strata).map(([name, s]) =>
    `<span><b>${name}</b> ${s.done}/${s.picked} typed &middot; quota ${s.quota} &middot; ${s.pool} available</span>`
  ).join("");
  const done = state.picks.filter((p) => p.status !== "pending").length;
  $("progress").textContent = `${done}/${state.picks.length} typed`;
  const rq = state.picks.filter((p) => p.recheck && p.status === "done");
  $("recheck-count").textContent = `(${rq.filter((p) => p.rechecked).length}/${rq.length})`;
}

function renderPills() {
  $("pill-strip").innerHTML = state.queue.map((id, i) => {
    const p = pickById(id);
    const cls = ["pill", p.status, p.rechecked ? "rechecked" : "", i === state.index ? "current" : ""].join(" ");
    return `<span class="${cls}" data-i="${i}" title="${id} (${p.stratum}): ${STATUS_LABEL[p.status]}"></span>`;
  }).join("");
}

async function showLine(i) {
  if (!state.queue.length) {
    $("line-id").textContent = state.mode === "first"
      ? "No lines sampled yet: verify pages in line review, then Top up sample."
      : "Nothing to recheck yet.";
    $("crop").removeAttribute("src");
    $("context").removeAttribute("src");
    return;
  }
  state.index = Math.max(0, Math.min(i, state.queue.length - 1));
  const id = state.queue[state.index];
  const line = await api("GET", `/api/lines/${id}`);
  state.current = line;
  const p = pickById(id);
  $("line-id").textContent = `${id}  (page ${line.page})`;
  $("line-stratum").textContent = p.stratum;
  $("line-status").textContent = state.mode === "first" ? STATUS_LABEL[p.status]
    : (p.rechecked ? "rechecked" : "recheck: type it fresh");
  $("crop").src = `/api/lines/${id}/crop.png`;
  $("context").src = `/api/lines/${id}/context.png`;
  const t = line.transcription;
  // Blind recheck: never show the first pass.
  $("text").value = state.mode === "first" ? (t ? t.text : "")
    : (t && t.recheck ? t.recheck.text : "");
  renderPills();
  $("text").focus();
}

async function refresh(keepIndex) {
  const s = await api("GET", "/api/transcribe/state");
  state.picks = s.picks;
  state.strata = s.strata;
  buildQueue();
  renderStrata();
  $("banner").textContent = s.missing.length
    ? `${s.missing.length} sampled line(s) no longer exist after re-verification: ${s.missing.join(", ")}.` : "";
  await showLine(keepIndex ? state.index : firstOpen());
}

// ---- saving ----
async function save(status) {
  const id = state.queue[state.index];
  if (!id) return;
  const text = $("text").value.replace(/\s+$/, "");
  if (status === "done" && !text) { flash("Empty line: use Illegible, or Bad crop", "err"); return; }
  try {
    if (state.mode === "first") {
      const rec = await api("PUT", `/api/transcribe/lines/${id}`, { text, status });
      pickById(id).status = rec.status;
    } else {
      await api("PUT", `/api/transcribe/lines/${id}/recheck`, { text });
      pickById(id).rechecked = true;
    }
    flash("saved", "ok");
  } catch (e) {
    flash(e.message, "err");
    return;
  }
  const s = await api("GET", "/api/transcribe/state");
  state.strata = s.strata;
  renderStrata();
  // advance to the next line not yet done, else just the next one
  const next = state.queue.findIndex((qid, j) => j > state.index && !isDone(pickById(qid)));
  await showLine(next >= 0 ? next : state.index + 1);
}

function insertAtCursor(ch) {
  const ta = $("text");
  const { selectionStart: a, selectionEnd: b, value } = ta;
  ta.value = value.slice(0, a) + ch + value.slice(b);
  ta.selectionStart = ta.selectionEnd = a + ch.length;
  ta.focus();
}

// ---- controls ----
$("palette").innerHTML = PALETTE.map(([ch, name]) =>
  `<button data-ch="${ch}" title="${name}">${ch}</button>`).join("");
$("palette").addEventListener("click", (ev) => {
  const b = ev.target.closest("button[data-ch]");
  if (b) insertAtCursor(b.dataset.ch);
});
$("submit").addEventListener("click", () => save("done"));
$("illegible").addEventListener("click", () => save("illegible"));
$("bad-crop").addEventListener("click", () => save("bad-crop"));
$("back").addEventListener("click", () => showLine(state.index - 1));
$("next").addEventListener("click", () => showLine(state.index + 1));
$("pill-strip").addEventListener("click", (ev) => {
  const p = ev.target.closest(".pill");
  if (p) showLine(Number(p.dataset.i));
});
$("top-up").addEventListener("click", async () => {
  const before = state.picks.length;
  await api("POST", "/api/transcribe/sample");
  await refresh(true);
  flash(`${state.picks.length - before} line(s) added`, "ok");
});
document.querySelectorAll(".mode").forEach((b) => b.addEventListener("click", async () => {
  state.mode = b.dataset.mode;
  document.querySelectorAll(".mode").forEach((x) => x.classList.toggle("active", x === b));
  document.body.classList.toggle("recheck", state.mode === "recheck");
  buildQueue();
  await showLine(firstOpen());
}));
// Recheck mode hides the first pass, so illegible/bad-crop belong to the first pass only.
$("text").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); save("done"); }
  else if (ev.key === "Escape") $("text").blur();
});
document.addEventListener("keydown", (ev) => {
  if (!ev.altKey) return;
  // Alt+letter yields a special character on macOS, so match the physical key.
  if (ev.code === "ArrowLeft") { ev.preventDefault(); showLine(state.index - 1); }
  else if (ev.code === "ArrowRight") { ev.preventDefault(); showLine(state.index + 1); }
  else if (ev.code === "KeyI" && state.mode === "first") { ev.preventDefault(); save("illegible"); }
  else if (ev.code === "KeyB" && state.mode === "first") { ev.preventDefault(); save("bad-crop"); }
});

refresh(false);
