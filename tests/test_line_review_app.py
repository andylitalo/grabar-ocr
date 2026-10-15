"""
Tests for the Phase 9 review server and the safety rails around it: the HTTP API
(dev.line_review.app), stale-save and add-key checks, the resumed marker on verified
files, the baseline manifest, and dev.line_review.rewrite_verified.

Each test points storage at a tmp dir holding one synthetic two-column baseline page.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from dev.line_review import app as app_mod
from dev.line_review import baseline_manifest as bm
from dev.line_review import materialize as mz
from dev.line_review import rewrite_verified, storage

PAGE = 500


def rect(x1, y1, x2, y2):
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def seg_line(lid, box):
    x1, y1, x2, y2 = box
    return {"id": lid, "boundary": rect(*box), "baseline": [[x1, y1 + 37.5], [x2, y1 + 37.5]],
            "bbox": list(box), "source": "hyocr-paddle"}


@pytest.fixture
def store(tmp_path, monkeypatch):
    base = tmp_path / "baseline"
    (base / f"page_{PAGE}").mkdir(parents=True)
    lines = [seg_line(f"line_00{i}", [100, 100 * i, 900, 100 * i + 50]) for i in range(1, 4)]
    lines += [seg_line(f"line_00{i}", [1100, 100 * (i - 3), 1900, 100 * (i - 3) + 50])
              for i in range(4, 7)]
    seg = {"page": PAGE, "tool": "paddle-filled", "width": 2000, "height": 3000, "lines": lines}
    (base / f"page_{PAGE}" / "segmentation.json").write_text(json.dumps(seg))
    monkeypatch.setattr(storage, "BASELINE_DIR", base)
    monkeypatch.setattr(storage, "REVIEWS_DIR", tmp_path / "reviews")
    monkeypatch.setattr(storage, "VERIFIED_DIR", tmp_path / "verified")
    monkeypatch.setattr(storage, "BLANK_DIR", tmp_path / "blank")
    monkeypatch.setattr(storage, "MANIFEST_PATH", tmp_path / "baseline_sha256.json")
    return tmp_path


@pytest.fixture
def client(store):
    return TestClient(app_mod.app)


def verify(page=PAGE):
    storage.set_status(page, "fixed")
    return storage.set_status(page, "verified")


ADD = {"op": "add", "key": "add_001", "boundary": rect(100, 400, 900, 450)}


# --- API --------------------------------------------------------------------------------


def test_get_page_reports_lines_revision_and_used_keys(client):
    d = client.get(f"/api/pages/{PAGE}").json()
    assert [l["key"] for l in d["lines"]] == [f"line_00{i}" for i in range(1, 7)]
    assert d["status"] == "unreviewed" and d["revision"] == 0 and d["used_add_keys"] == []
    assert d["expected_page_number"] == str(PAGE - storage.PRINTED_OFFSET)
    assert not d["baseline_changed"] and d["error"] is None


def test_put_ops_marks_edits_and_ghosts(client):
    d = client.put(f"/api/pages/{PAGE}/ops", json={"ops": [
        {"op": "delete", "line": "line_002"},
        {"op": "reshape", "line": "line_001", "boundary": rect(90, 90, 910, 160)}, ADD]}).json()
    by_key = {l["key"]: l for l in d["lines"]}
    assert by_key["line_001"]["edited"] and by_key["add_001"]["edited"]
    assert not by_key["line_003"]["edited"]
    assert [g["key"] for g in d["ghosts"]] == ["line_002"]
    assert d["status"] == "fixing" and d["revision"] == 1 and d["used_add_keys"] == ["add_001"]


def test_unknown_page_is_404(client):
    assert client.get("/api/pages/999").status_code == 404
    assert client.put("/api/pages/999/ops", json={"ops": []}).status_code == 404


def test_bad_op_is_400_and_not_saved(client):
    r = client.put(f"/api/pages/{PAGE}/ops", json={"ops": [{"op": "delete", "line": "line_404"}]})
    assert r.status_code == 400 and "line_404" in r.json()["detail"]
    assert not storage.review_path(PAGE).exists()


def test_bad_section_title_is_400_with_a_clear_message(client):
    r = client.put(f"/api/pages/{PAGE}/ops", json={
        "ops": [], "section_titles": [{"id": "title_001", "box": [10, 10, 50, 50], "letter": "A"}]})
    assert r.status_code == 400
    assert "Armenian letters" in r.json()["detail"]


def test_editing_a_fixed_page_is_409(client):
    client.post(f"/api/pages/{PAGE}/status", json={"status": "fixed"})
    assert client.put(f"/api/pages/{PAGE}/ops", json={"ops": []}).status_code == 409


def test_bad_status_transition_is_409(client):
    assert client.post(f"/api/pages/{PAGE}/status", json={"status": "verified"}).status_code == 409
    assert client.post(f"/api/pages/{PAGE}/status", json={"status": "done"}).status_code == 409


def test_verify_over_the_api_writes_the_verified_file(client):
    client.post(f"/api/pages/{PAGE}/status", json={"status": "fixed"})
    d = client.post(f"/api/pages/{PAGE}/status", json={"status": "verified"}).json()
    assert d["status"] == "verified"
    assert all(l["id"].startswith(f"p{PAGE}.") for l in d["lines"])
    assert storage.verified_path(PAGE).exists()
    assert client.get("/api/pages").json() == {"statuses": {str(PAGE): "verified"}}


def test_changed_baseline_shows_read_only_and_refuses_saves(client):
    storage.save_ops(PAGE, [], [])
    path = storage.baseline_path(PAGE)
    seg = json.loads(path.read_text())
    seg["lines"].pop()
    path.write_text(json.dumps(seg))
    assert client.get(f"/api/pages/{PAGE}").json()["baseline_changed"]
    assert client.put(f"/api/pages/{PAGE}/ops", json={"ops": []}).status_code == 409


# --- stale saves -------------------------------------------------------------------------


def test_save_built_on_an_old_revision_is_refused(client):
    first = client.put(f"/api/pages/{PAGE}/ops",
                       json={"ops": [{"op": "delete", "line": "line_002"}], "revision": 0})
    assert first.status_code == 200 and first.json()["revision"] == 1
    # a second tab still on revision 0 would drop the delete
    stale = client.put(f"/api/pages/{PAGE}/ops", json={"ops": [ADD], "revision": 0})
    assert stale.status_code == 409 and "reload" in stale.json()["detail"]
    assert storage.load_review(PAGE)["ops"] == [{"op": "delete", "line": "line_002"}]
    ok = client.put(f"/api/pages/{PAGE}/ops", json={
        "ops": [{"op": "delete", "line": "line_002"}, ADD], "revision": 1})
    assert ok.status_code == 200


def test_status_change_on_an_old_revision_is_refused(store):
    storage.save_ops(PAGE, [], [])
    with pytest.raises(storage.StateError, match="reload"):
        storage.set_status(PAGE, "fixed", revision=0)
    assert storage.set_status(PAGE, "fixed", revision=1)["status"] == "fixed"


def test_double_verify_is_refused(store):
    storage.set_status(PAGE, "fixed")
    rev = storage.load_review(PAGE)["revision"]
    storage.set_status(PAGE, "verified", revision=rev)
    with pytest.raises(storage.StateError):
        storage.set_status(PAGE, "verified", revision=rev)


# --- add keys are never handed to another box ---------------------------------------------


def test_reissued_add_key_for_a_new_box_is_refused(store):
    storage.save_ops(PAGE, [ADD], [])
    first_id = verify()["ids"]["add_001"]
    storage.set_status(PAGE, "fixing")
    storage.save_ops(PAGE, [], [])  # the add's edit removed
    moved = {**ADD, "boundary": rect(1100, 400, 1900, 450)}
    with pytest.raises(mz.OpError, match="add_001.*already used"):
        storage.save_ops(PAGE, [moved], [])
    review, _ = storage.save_ops(PAGE, [{**moved, "key": "add_002"}], [])
    ids = verify()["ids"]
    assert ids["add_002"] != first_id
    assert storage.load_review(PAGE)["retired"][first_id] == {"superseded_by": []}


def test_restoring_the_same_add_is_allowed(store):
    storage.save_ops(PAGE, [ADD], [])
    storage.save_ops(PAGE, [], [])  # removed ...
    storage.save_ops(PAGE, [ADD], [])  # ... and brought back by undo: same box, same key


def test_reviews_from_before_add_keys_keep_their_adds(store):
    storage.save_ops(PAGE, [ADD], [])
    verify()
    review = json.loads(storage.review_path(PAGE).read_text())
    del review["add_keys"]  # as committed before this field existed
    review["status"] = "fixing"
    storage.review_path(PAGE).write_text(json.dumps(review))
    assert storage.used_add_keys(review) == {"add_001": ADD["boundary"]}
    storage.save_ops(PAGE, [ADD, {"op": "delete", "line": "line_001"}], [])


def test_add_keys_known_only_from_ids_cannot_be_reused(store):
    review = storage.load_review(PAGE)
    review.update(ids={"add_004": "p500.009"}, retired_keys={"add_007": "p500.010"})
    assert storage.used_add_keys(review) == {"add_004": None, "add_007": None}


# --- resumed verified files --------------------------------------------------------------


def test_resume_marks_the_verified_file_and_reverify_rewrites_it(store):
    verify()
    original = json.loads(storage.verified_path(PAGE).read_text())
    storage.set_status(PAGE, "fixing")
    marked = json.loads(storage.verified_path(PAGE).read_text())
    assert "resumed_at" in marked
    assert {k: v for k, v in marked.items() if k != "resumed_at"} == original
    storage.save_ops(PAGE, [{"op": "delete", "line": "line_003"}], [])
    review = verify()
    rewritten = storage.verified_path(PAGE).read_text()
    assert "resumed_at" not in json.loads(rewritten)
    assert rewritten == mz.dumps(mz.verified_record(
        storage.load_baseline(PAGE), review, baseline_sha256=storage.baseline_sha256(PAGE)))


def test_resume_from_fixed_leaves_no_marker(store):
    storage.set_status(PAGE, "fixed")
    storage.set_status(PAGE, "fixing")
    assert not storage.verified_path(PAGE).exists()


# --- baseline manifest -------------------------------------------------------------------


def test_manifest_reports_changed_added_and_removed_pages(store):
    storage.write_manifest(storage.current_baseline_hashes())
    assert bm.changes(storage.baseline_manifest(), storage.current_baseline_hashes()) == {
        "changed": [], "added": [], "removed": []}
    storage.baseline_path(PAGE).write_text("{}")
    diff = bm.changes(storage.baseline_manifest() | {501: "x"}, storage.current_baseline_hashes())
    assert diff == {"changed": [PAGE], "added": [], "removed": [501]}


def test_manifest_report_names_reviewed_pages(store):
    storage.save_ops(PAGE, [], [])
    assert bm.report({"changed": [PAGE], "added": [], "removed": []}) == \
        f"changed: [{PAGE}]  (reviewed: [{PAGE}])"


def test_manifest_cli_accepts_the_current_hashes(store, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["baseline_manifest", "--accept"])
    bm.main()
    assert storage.baseline_manifest() == storage.current_baseline_hashes()
    monkeypatch.setattr("sys.argv", ["baseline_manifest"])
    bm.main()
    assert "matches the manifest (1 pages)" in capsys.readouterr().out


# --- rewrite_verified ----------------------------------------------------------------------


def test_rewrite_applies_a_format_only_change(store, capsys):
    verify()
    good = storage.verified_path(PAGE).read_text()
    old = json.loads(good)
    del old["retired"]  # e.g. a field the output format gained since
    storage.verified_path(PAGE).write_text(json.dumps(old, indent=4))
    assert rewrite_verified.main([]) == 0
    assert storage.verified_path(PAGE).read_text() == good
    assert f"page {PAGE}: rewritten" in capsys.readouterr().out
    assert rewrite_verified.main([]) == 0  # already current: untouched, nothing printed
    assert capsys.readouterr().out == ""


def changed_since_verify() -> str:
    """Make the committed file differ in content from what the code now produces, as
    a reading-order or geometry code change would."""
    verify()
    old = json.loads(storage.verified_path(PAGE).read_text())
    old["lines"][0]["order"], old["lines"][1]["order"] = 2, 1
    old["lines"][2]["bbox"] = [0, 0, 1, 1]
    text = mz.dumps(old)
    storage.verified_path(PAGE).write_text(text)
    return text


def test_rewrite_refuses_a_change_to_verified_content(store, capsys):
    before = changed_since_verify()
    assert rewrite_verified.main([]) == 1
    out = capsys.readouterr().out
    assert f"page {PAGE}: NOT rewritten" in out and "2 lines reordered" in out
    assert "geometry changed on ['p500.003']" in out
    assert storage.verified_path(PAGE).read_text() == before
    assert storage.load_review(PAGE)["status"] == "verified"


def test_rewrite_reopen_sends_changed_pages_back_for_review(store, capsys):
    changed_since_verify()
    assert rewrite_verified.main(["--reopen"]) == 0
    assert f"page {PAGE}: reopened for review" in capsys.readouterr().out
    assert storage.load_review(PAGE)["status"] == "fixing"
    assert "resumed_at" in json.loads(storage.verified_path(PAGE).read_text())


def test_rewrite_writes_a_missing_file(store):
    verify()
    good = storage.verified_path(PAGE).read_text()
    storage.verified_path(PAGE).unlink()
    assert rewrite_verified.main([]) == 0
    assert storage.verified_path(PAGE).read_text() == good


def test_rewrite_skips_a_resumed_page(store):
    verify()
    storage.set_status(PAGE, "fixing")
    marked = storage.verified_path(PAGE).read_text()
    rewrite_verified.main([])
    assert storage.verified_path(PAGE).read_text() == marked


def test_rewrite_skips_a_page_whose_baseline_changed(store, capsys):
    verify()
    storage.verified_path(PAGE).write_text("{}\n")
    seg = json.loads(storage.baseline_path(PAGE).read_text())
    seg["lines"].pop()
    storage.baseline_path(PAGE).write_text(json.dumps(seg))
    rewrite_verified.main([])
    assert storage.verified_path(PAGE).read_text() == "{}\n"
    assert "baseline changed" in capsys.readouterr().out


def test_copy_kept_alive_by_an_op_is_flagged(client):
    # line_001's twin: dedupe would drop it, but reshaping it keeps it on the page
    seg = json.loads(storage.baseline_path(PAGE).read_text())
    seg["lines"].append(seg_line("line_007", [101, 101, 899, 149]))
    storage.baseline_path(PAGE).write_text(json.dumps(seg))
    assert client.get(f"/api/pages/{PAGE}").json()["duplicates"] == []
    d = client.put(f"/api/pages/{PAGE}/ops", json={"ops": [
        {"op": "reshape", "line": "line_007", "boundary": rect(101, 101, 899, 149)}]}).json()
    assert d["duplicates"] == [[1, 2]]
