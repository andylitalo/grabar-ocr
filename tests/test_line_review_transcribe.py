"""
Tests for the Phase 10 OCR test set (dev.line_review.transcribe, dev.line_review.crops):
stratified, append-only sampling from verified lines; transcription storage; line crops.
"""

from __future__ import annotations

import json

import pytest
from PIL import Image

from dev.line_review import crops
from dev.line_review import transcribe as tr


def vline(lid: str, box: list[float], initial: str | None = None) -> dict:
    x1, y1, x2, y2 = box
    return {"id": lid, "order": 0, "boundary": [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
            "bbox": box, "initial": initial}


def verified(page: int, lines: list[dict]) -> dict:
    return {"page": page, "lines": lines}


def body_page(page: int, n: int) -> dict:
    return verified(page, [vline(f"p{page}.{i:03d}", [100, 100 * i, 900, 100 * i + 50])
                           for i in range(1, n + 1)])


# --- strata ---------------------------------------------------------------------------


def test_strata_by_volume_display_and_drop_cap():
    page = verified(500, [
        vline("p500.001", [100, 100, 900, 150]),
        vline("p500.002", [100, 200, 900, 250]),
        vline("p500.003", [100, 300, 900, 380]),             # 80 px vs median 50: display
        vline("p500.004", [100, 400, 900, 450], initial="Ա"),
    ])
    pool = {l["id"]: l["stratum"] for l in tr.candidates([page])}
    assert pool == {"p500.001": "vol1-body", "p500.002": "vol1-body",
                    "p500.003": "display", "p500.004": "drop-cap"}
    assert tr.candidates([body_page(600, 2)])[0]["stratum"] == "vol2-body"


def test_paschal_table_is_excluded():
    assert tr.candidates([body_page(641, 3)]) == []


# --- sampling -------------------------------------------------------------------------


QUOTAS = {"vol1-body": 3, "vol2-body": 2, "display": 1, "drop-cap": 1}
WIDE = {name: 100 for name in QUOTAS}  # no page cap: these tests are about ranking


def test_top_up_fills_quotas_with_lowest_ranked_lines():
    sample = tr.top_up(tr.new_sample(seed="s", quotas=QUOTAS, per_page=WIDE), tr.candidates([body_page(500, 10)]))
    picked = [p["id"] for p in sample["picks"]]
    assert len(picked) == 3 and all(p["stratum"] == "vol1-body" for p in sample["picks"])
    ranked = sorted((f"p500.{i:03d}" for i in range(1, 11)), key=lambda i: tr.rank("s", i))
    assert picked == ranked[:3]


def test_picks_are_stable_as_the_pool_grows():
    first = tr.top_up(tr.new_sample(seed="s", quotas=QUOTAS, per_page=WIDE), tr.candidates([body_page(500, 4)]))
    grown = tr.top_up(first, tr.candidates([body_page(500, 4), body_page(501, 40), body_page(600, 5)]))
    assert grown["picks"][:3] == first["picks"]
    assert sum(p["stratum"] == "vol2-body" for p in grown["picks"]) == 2


def test_retired_picks_are_reported_not_dropped():
    sample = tr.top_up(tr.new_sample(seed="s", quotas=QUOTAS, per_page=WIDE), tr.candidates([body_page(500, 4)]))
    gone = sample["picks"][0]["id"]
    still = [l for l in body_page(500, 4)["lines"] if l["id"] != gone]
    pool = tr.candidates([verified(500, still)])
    assert tr.missing_picks(sample, pool) == [gone]
    assert len(tr.top_up(sample, pool)["picks"]) == 3  # the retired pick still counts


def test_recheck_queue_is_deterministic_and_capped():
    sample = tr.top_up(tr.new_sample(seed="s", quotas={"vol1-body": 200}, per_page={"vol1-body": 200}),
                       tr.candidates([body_page(500, 200)]))
    q = tr.recheck_ids(sample, every=10, cap=5)
    assert q == tr.recheck_ids(sample, every=10, cap=5)
    assert len(q) == 5 and set(q) <= {p["id"] for p in sample["picks"]}


# --- transcription storage ---------------------------------------------------------------


@pytest.fixture
def tmp_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(tr, "TRANSCRIPTIONS_DIR", tmp_path / "t")
    return tmp_path


def test_save_and_load_a_transcription(tmp_dirs):
    tr.save_line("p457.023", text="Աւետարան", status="done", by="maintainer")
    rec = tr.load_line("p457.023")
    assert rec["text"] == "Աւետարան" and rec["status"] == "done"
    assert rec["by"] == "maintainer" and rec["prefill"] is None  # typed blank
    page = json.loads((tmp_dirs / "t" / "testset" / "page_457.json").read_text())
    assert list(page) == ["p457.023"]


def test_tasks_are_kept_apart(tmp_dirs):
    tr.save_line("p457.023", text="Աւետարան", status="done")
    tr.save_line("p457.023", text="Աւետարան", status="done", task="corrections",
                 prefill={"engine": "paddle-calfa-tiny", "text": "Աետարան"})
    assert tr.load_line("p457.023")["prefill"] is None
    assert tr.load_line("p457.023", task="corrections")["prefill"]["engine"] == "paddle-calfa-tiny"


def test_recheck_is_stored_beside_the_first_pass(tmp_dirs):
    tr.save_line("p457.023", text="Աւետարան", status="done")
    tr.save_recheck("p457.023", text="Աւետարան։")
    rec = tr.load_line("p457.023")
    assert rec["text"] == "Աւետարան" and rec["recheck"]["text"] == "Աւետարան։"


def test_unknown_status_is_rejected(tmp_dirs):
    with pytest.raises(ValueError):
        tr.save_line("p457.023", text="", status="maybe")


# --- crops ------------------------------------------------------------------------------


def test_crop_whitens_ink_outside_the_polygon():
    page = Image.new("L", (300, 200), 0)  # all ink
    tri = {"boundary": [[50, 50], [250, 50], [50, 150]], "bbox": [50, 50, 250, 150]}
    img = crops.line_crop(page, tri, pad=0)
    assert img.size == (200, 100)
    assert img.getpixel((10, 10)) == 0        # inside the triangle: ink kept
    assert img.getpixel((190, 90)) == 255     # outside it: whitened


def test_picks_per_page_are_capped_so_the_sample_spreads():
    sample = tr.top_up(tr.new_sample(seed="s", quotas={"vol1-body": 50}, per_page={"vol1-body": 4}),
                       tr.candidates([body_page(500, 30), body_page(501, 30)]))
    assert len(sample["picks"]) == 8
    later = tr.top_up(sample, tr.candidates([body_page(500, 30), body_page(501, 30),
                                             body_page(502, 30)]))
    assert len(later["picks"]) == 12 and later["picks"][:8] == sample["picks"]


def test_each_stratum_has_its_own_page_cap():
    lines = [vline(f"p500.{i:03d}", [100, 100 * i, 900, 100 * i + 50]) for i in range(1, 10)]
    lines.append(vline("p500.010", [100, 1000, 900, 1050], initial="Ա"))
    # body filling its own cap doesn't stop the page's drop-cap line getting in
    sample = tr.top_up(tr.new_sample(seed="s", quotas={"vol1-body": 10, "drop-cap": 1},
                                     per_page={"vol1-body": 4, "drop-cap": 1}),
                       tr.candidates([verified(500, lines)]))
    assert "p500.010" in [p["id"] for p in sample["picks"]]
