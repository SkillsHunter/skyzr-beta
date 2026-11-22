"""Phase 3F: the AI readings snapshot file (fake clients only; no key, no network)."""

import csv
import json

import pytest

import ai
import engine
import fake_ai
import snapshot_io

REPORTS = snapshot_io.reports_by_id()
NS = "scripted"


def filled_cache():
    """A cache filled by the scripted client, as Prepare would fill it."""
    cache = ai.SharedCache()
    intake = ai.Intake(fake_ai.client(), cache=cache)
    for r in REPORTS.values():
        assert intake.read(r).status == "ok"
    return cache


def snapshot_of(cache):
    return ai.export_snapshot(REPORTS, snapshot_io.reports_sha256(), NS, cache)


def results(cache):
    intake = ai.Intake(fake_ai.client(fail=False), cache=cache)
    return {rid: intake.read(r) for rid, r in REPORTS.items()}


def write(tmp_path, data):
    p = tmp_path / "ai_readings.json"
    p.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return p


# 1. Round trip ------------------------------------------------------------------------------

def test_round_trip_gives_identical_intake_results(tmp_path):
    source = filled_cache()
    before = results(source)
    empty = ai.SharedCache()
    res = snapshot_io.load_snapshot(write(tmp_path, snapshot_of(source)), NS, empty)
    assert res.loaded == len(REPORTS) and res.rejected == 0 and not res.error
    after = results(empty)
    for rid in REPORTS:
        assert after[rid].accepted == before[rid].accepted
        assert after[rid].rejected == before[rid].rejected
        assert after[rid].from_cache and after[rid].source == "snapshot"
        assert after[rid].source_created_at == res.created_at


def test_snapshot_readings_are_labelled_with_the_snapshot_model(tmp_path):
    snap = snapshot_of(filled_cache())
    snap["model"] = "gemini-other-flash"
    empty = ai.SharedCache()
    res = snapshot_io.load_snapshot(write(tmp_path, snap), NS, empty)
    assert res.loaded == len(REPORTS) and res.model == "gemini-other-flash"
    r = results(empty)["R13"]
    assert r.source == "snapshot" and r.source_model == "gemini-other-flash"


# 2. One changed character rejects that entry only ---------------------------------------------

def test_changed_report_text_rejects_only_that_entry(tmp_path):
    snap = snapshot_of(filled_cache())
    reports = {k: dict(v) for k, v in REPORTS.items()}
    reports["R13"]["text"] = reports["R13"]["text"].replace("three", "thrEe", 1)
    empty = ai.SharedCache()
    res = ai.load_snapshot_data(snap, reports, NS, cache=empty)
    assert res.rejected == 1 and res.loaded == len(REPORTS) - 1
    assert res.reasons == {"report text changed since the snapshot": 1}


# 3. An invented quote is rejected by the quote check -------------------------------------------

def test_entry_with_invented_quote_is_rejected_by_the_quote_check(tmp_path):
    snap = snapshot_of(filled_cache())
    baseline = ai.load_snapshot_data(snap, REPORTS, NS, cache=ai.SharedCache()).quote_rejections
    assert baseline == 1  # the test double's R04 already carries one invented quote
    entry = next(e for e in snap["entries"] if e["report_id"] == "R13")
    entry["facts"][0]["quote"] = "every water system in the county has exploded"
    empty = ai.SharedCache()
    res = snapshot_io.load_snapshot(write(tmp_path, snap), NS, empty)
    assert res.quote_rejections == baseline + 1
    r13 = ai.Intake(fake_ai.client(), cache=empty).read(REPORTS["R13"])
    assert r13.source == "snapshot"
    assert [why for _, why in r13.rejected] == ["quote not found word for word in the report"]
    assert all(f.quote != "every water system in the county has exploded" for f in r13.accepted)


def test_entry_that_does_not_fit_the_schema_is_rejected():
    snap = snapshot_of(filled_cache())
    entry = next(e for e in snap["entries"] if e["report_id"] == "R13")
    entry["facts"][0]["lifeline_or_resource"] = "Power"
    res = ai.load_snapshot_data(snap, REPORTS, NS, cache=ai.SharedCache())
    assert res.rejected == 1 and "schema" in next(iter(res.reasons))


# 4. prompt_version mismatch loads nothing --------------------------------------------------------

def test_prompt_version_mismatch_loads_nothing(tmp_path):
    snap = snapshot_of(filled_cache())
    snap["prompt_version"] = "0000000000000000"
    empty = ai.SharedCache()
    res = snapshot_io.load_snapshot(write(tmp_path, snap), NS, empty)
    assert res.loaded == 0 and res.error == "snapshot made with a different prompt"
    assert empty.keys_in(NS) == []


# 5. Missing file, malformed JSON, unknown format -------------------------------------------------

@pytest.mark.parametrize("content,error", [
    (None, "no snapshot file"),
    ("{not json", "could not read the snapshot"),
    ({"format_version": 99}, "unknown format_version"),
    ([1, 2, 3], "not a snapshot"),
])
def test_bad_or_missing_file_loads_nothing_and_does_not_crash(tmp_path, content, error):
    path = tmp_path / "ai_readings.json" if content is None else write(
        tmp_path, content if isinstance(content, str) else json.dumps(content))
    empty = ai.SharedCache()
    res = snapshot_io.load_snapshot(path, NS, empty)
    assert res.loaded == 0 and res.error.startswith(error) and empty.keys_in(NS) == []


# 6. No key-like strings and no answer-key columns -------------------------------------------------

def test_export_has_no_key_and_no_answer_key_columns(monkeypatch):
    import streamlit as st
    key = "AIza" + "SyEXAMPLEexampleEXAMPLE_0123456789-xyz"
    monkeypatch.setattr(st, "secrets", {"GEMINI_API_KEY": key})
    cache = filled_cache()
    # Even a key that somehow reached a cached answer is removed on export.
    k0 = cache.keys_in(NS)[0]
    poisoned = [dict(f, county=f["county"] + " " + key) for f in cache.get(k0)] or [{"x": key}]
    cache.put(k0, poisoned, cache.meta(k0))
    text = json.dumps(snapshot_of(cache))
    assert key not in text and "AIza" not in text
    with open(engine.DATA_DIR / "answer_key.csv", encoding="utf-8") as f:
        ak_columns = next(csv.reader(f))
    ak_only = set(ak_columns) - {"hour", "fips", "county"}
    snap = snapshot_of(filled_cache())
    keys = set(snap) | {k for e in snap["entries"] for k in e}
    assert not keys & ak_only
    assert set(snap) == {"format_version", "model", "prompt_version", "created_at",
                         "reports_sha256", "entries"}


# 7. Prepare after a 47-entry snapshot reads only the 3 missing reports -----------------------------

def test_prepare_after_47_entry_snapshot_calls_only_for_the_3_missing(tmp_path):
    snap = snapshot_of(filled_cache())
    missing = {"R05", "R21", "R40"}
    snap["entries"] = [e for e in snap["entries"] if e["report_id"] not in missing]
    assert len(snap["entries"]) == len(REPORTS) - 3 == 47
    cache = ai.SharedCache()
    res = snapshot_io.load_snapshot(write(tmp_path, snap), NS, cache)
    assert res.loaded == 47
    client = fake_ai.client()
    prep = ai.prepare(ai.Intake(client, cache=cache), REPORTS.values(), pace=0)
    assert prep.ok == len(REPORTS)
    assert sorted(p["text"] for p in client.payloads) == sorted(
        REPORTS[r]["text"] for r in missing)


def test_ai_module_still_never_reads_files():
    from pathlib import Path
    source = (Path(ai.__file__)).read_text(encoding="utf-8")
    code = source[source.index('"""', 3) + 3:]
    assert "answer_key" not in code and "open(" not in code and "read_text" not in code


# App: the snapshot label line and the download button ----------------------------------------------

def _ai_app():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file("../app.py", default_timeout=60)
    at.session_state["mode"] = "AI mode"
    return at.run()


def test_app_labels_snapshot_readings_and_offers_the_download(tmp_path, monkeypatch):
    monkeypatch.setenv("SKYZR_FAKE_AI", "1")
    snap = snapshot_of(filled_cache())
    snap["entries"] = [e for e in snap["entries"] if e["report_id"] != "R40"]
    res = snapshot_io.load_snapshot(write(tmp_path, snap), NS, ai.SHARED_CACHE)
    ai.SHARED_CACHE.snapshot_result = res  # as the app does once per server start
    at = _ai_app()
    assert not at.exception
    line = next(c.value for c in at.caption if c.value.startswith("Readings:"))
    assert line.startswith(f"Readings: 49 of {len(REPORTS)} from snapshot · Gemini scripted · read ")
    assert line.endswith("Prepare reads only missing reports.")
    dl = [w for w in at.get("download_button") if "snapshot" in str(w.proto.label)]
    assert dl and not dl[0].proto.disabled


def test_app_without_snapshot_shows_no_label_and_disables_the_download(monkeypatch, tmp_path):
    monkeypatch.setenv("SKYZR_FAKE_AI", "1")
    monkeypatch.setattr(snapshot_io, "SNAPSHOT_PATH", tmp_path / "none.json")
    at = _ai_app()
    assert not at.exception
    assert not any(c.value.startswith("Readings:") for c in at.caption)
    dl = [w for w in at.get("download_button") if "snapshot" in str(w.proto.label)]
    assert dl and dl[0].proto.disabled


# Phase 3G: cots count as Shelter ------------------------------------------------------------

def test_prompt_names_cots_as_shelter():
    line = ('  Shelter means cots and shelter kits: a request for cots is Shelter, Requested, with '
            'the number of cots as value (e.g. "We need about forty cots" = Shelter, Requested, 40). '
            'If a report corrects an earlier number, record the corrected number only.')
    assert line in ai.SYSTEM_PROMPT


# Phase 3H: resource words mapped to categories ---------------------------------------------

def test_prompt_maps_resource_words_to_categories():
    line = '  What each resource covers: Water = water tankers; Generators = generators; Utility crews = utility or line crews; Search-and-rescue teams = search-and-rescue teams; Food = pallets of meals or food; Shelter = cots and shelter kits; Medical teams = medical teams; Hygiene items = hygiene kits; Sanitation = portable toilets and handwashing units. One report can request several resources: return one fact per resource (e.g. "Please send three generators and six hygiene kits" = Generators, Requested, 3 and Hygiene items, Requested, 6).'
    assert line in ai.SYSTEM_PROMPT
    shelter = ai.SYSTEM_PROMPT.index("Shelter means cots and shelter kits")
    assert ai.SYSTEM_PROMPT.index("What each resource covers") > shelter  # right after 3G's line


def test_prompt_example_is_not_taken_from_the_reports():
    example = "Please send three generators and six hygiene kits"
    assert example in ai.SYSTEM_PROMPT
    assert all(example.lower() not in r["text"].lower() for r in REPORTS.values())


def _committed_snapshot_is_older():
    data = json.loads(snapshot_io.SNAPSHOT_PATH.read_text(encoding="utf-8"))
    return data.get("prompt_version") != ai.PROMPT_VERSION


def test_committed_snapshot_made_with_an_older_prompt_loads_nothing():
    if not snapshot_io.SNAPSHOT_PATH.exists() or not _committed_snapshot_is_older():
        pytest.skip("the committed snapshot matches the current prompt")
    res = snapshot_io.load_snapshot(snapshot_io.SNAPSHOT_PATH, ai.GEMINI_CACHE_NAME, ai.SharedCache())
    assert res.loaded == 0 and res.error == "snapshot made with a different prompt"


def test_app_starts_and_shows_why_the_snapshot_did_not_load():
    if not snapshot_io.SNAPSHOT_PATH.exists() or not _committed_snapshot_is_older():
        pytest.skip("the committed snapshot matches the current prompt")
    at = _ai_app()  # real (non-fake) client path: no key here, so the stand-in client
    assert not at.exception
    assert any(c.value == "Readings snapshot not loaded: snapshot made with a different prompt."
               for c in at.caption)
