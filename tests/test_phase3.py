"""Phase 3: AI mode, with fake clients only (no key, no network)."""

import os

import pytest
from streamlit.testing.v1 import AppTest

import ai
import engine
import fake_ai

SC = engine.default_scenario()
FIPS = {v: k for k, v in SC.names.items()}
ALL = sorted(SC.reports.values(), key=lambda r: r["sim_hour"])


def read_all(client, upto=engine.LAST_HOUR):
    intake = ai.Intake(client)
    return {str(r["report_id"]): intake.read(r) for r in ALL if r["sim_hour"] <= upto}


def county(hour, name, reads, events=()):
    return engine.state_at(hour, events, SC, reads)[FIPS[name]]


# ---- Fix 5: a fact with an invented quote is rejected ---------------------------------

def test_invented_quote_is_rejected_and_changes_nothing():
    reads = read_all(fake_ai.client(), upto=6)
    res = reads["R04"]
    assert res.accepted == ()
    assert [why for _, why in res.rejected] == ["quote not found word for word in the report"]
    s = county(6, "New Hanover", reads)
    assert s["lifelines"]["Health and Medical"] is None  # the rejected fact set nothing


# ---- A failing client: the run completes and nothing changes ---------------------------

def test_failing_client_full_run_changes_nothing():
    failed = read_all(ai.UnavailableClient("no key"))
    assert all(r.status == "unavailable" and r.message == ai.AI_UNAVAILABLE
               for r in failed.values())
    assert all(r.report_text for r in failed.values())  # raw reports stay visible
    for h in range(engine.FIRST_HOUR, engine.LAST_HOUR + 1):
        a = engine.state_at(h, (), SC, failed)
        b = engine.state_at(h, (), SC, {})  # nothing read at all
        for f in SC.hit:
            assert a[f]["color"] == b[f]["color"]
            assert a[f]["lifelines"] == b[f]["lifelines"]
            assert a[f]["resources"] == b[f]["resources"]


# ---- An unverified report never turns a county green ----------------------------------

class AllGreenClient:
    """Says every lifeline is back to normal in every report, quoting the whole text."""

    cache_name = "all-green"

    def extract(self, payload):
        county = None
        for r in ALL:
            if r["text"] == payload["text"]:
                county = r["county"]  # test double only; the real model gets no county
        return [
            {"county": county, "lifeline_or_resource": ll, "metric": m, "value": v,
             "status_word": w, "quote": payload["text"]}
            for ll, m, v, w in (("Roads", "Route status", "Open", "Open"),
                                ("Water", "System status", "Normal", "Normal"),
                                ("Health and Medical", "Hospital status", "Normal", "Normal"))
        ]


def test_unverified_report_never_turns_a_county_green():
    reads = read_all(AllGreenClient())
    verified_only = {rid: res for rid, res in reads.items()
                     if str(SC.reports[rid]["verified"]).lower() == "yes"}
    unverified = [rid for rid in reads if rid not in verified_only]
    assert unverified, "the data has unverified reports"
    for h in range(engine.FIRST_HOUR, engine.LAST_HOUR + 1):
        with_all = engine.state_at(h, (), SC, reads)
        without = engine.state_at(h, (), SC, verified_only)
        for f in SC.hit:
            s = with_all[f]
            for ll in engine.AI_LIFELINES:
                src = s["lifeline_sources"][ll]
                if s["lifelines"][ll] == engine.GREEN and src.get("kind") == "report":
                    assert src["verified"] == "Yes", (h, f, ll)
            if s["color"] == engine.GREEN:
                assert without[f]["color"] == engine.GREEN, (h, SC.names[f])


def test_unverified_scotland_post_does_not_turn_water_green():
    reads = read_all(fake_ai.client(), upto=45)
    s = county(45, "Scotland", reads)
    assert s["lifelines"]["Water"] == engine.RED
    assert "unverified" in s["lifeline_sources"]["Water"]["note"]


# ---- Resolution ---------------------------------------------------------------------------

def test_ai_contradiction_shows_side_by_side_then_resolves():
    reads = read_all(fake_ai.client(), upto=26)
    s = county(26, "Moore", reads)
    assert len(s["contradictions"]) == 1
    c = s["contradictions"][0]
    assert {c["a"]["value"], c["b"]["value"]} == {2, 5}
    assert s["lifeline_sources"]["Water"]["kind"] == "contradiction"

    clock = engine.Clock(26, 26)
    pick = "a" if c["a"]["value"] == 2 else "b"
    events, msg, ok = engine.submit_resolve(
        (), clock, FIPS["Moore"], "Water", "ai", c["key"], pick, "Logistics",
        "Utility count is the direct source", SC, "kept 2")
    assert ok, msg
    s2 = county(26, "Moore", reads, events)
    assert s2["contradictions"] == []
    assert s2["lifeline_sources"]["Water"]["value"] == 2
    row = engine.log_rows(events, 26, SC)[0]
    assert row["Action"] == "Resolved contradiction"
    assert row["Role"] == "Logistics" and row["Reason"] == "Utility count is the direct source"
    assert "Resolved contradiction" in engine.log_csv(events, 26, SC)


def test_resolve_refused_without_role_reason_or_off_live_hour():
    c = county(26, "Moore", read_all(fake_ai.client(), upto=26))["contradictions"][0]
    args = (FIPS["Moore"], "Water", "ai", c["key"])
    ev, msg, ok = engine.submit_resolve((), engine.Clock(26, 26), *args, "a", None, "r", SC)
    assert not ok and ev == ()
    ev, msg, ok = engine.submit_resolve((), engine.Clock(26, 26), *args, "a", "Logistics", " ", SC)
    assert not ok and ev == ()
    ev, msg, ok = engine.submit_resolve((), engine.Clock(26, 20), *args, "a", "Logistics", "r", SC)
    assert not ok and ev == ()


def test_manual_vs_report_contradiction_resolves_and_status_is_recalculated():
    alamance = FIPS["Alamance"]
    clock = engine.Clock(22, 22)
    events = engine.change_status((), clock, alamance, "Communications", engine.RED,
                                  "Logistics", "Carrier says towers down", SC)
    s = engine.state_at(23, events, SC)[alamance]
    assert s["contradictions"] and s["lifelines"]["Communications"] == engine.RED
    events, msg, ok = engine.submit_resolve(
        events, engine.Clock(23, 23), alamance, "Communications", "manual", "Communications",
        "report", "Logistics", "Carrier confirmed partial service", SC, "kept the report")
    assert ok, msg
    s2 = engine.state_at(23, events, SC)[alamance]
    assert s2["contradictions"] == []
    assert s2["lifelines"]["Communications"] == SC.lifelines[(alamance, 23)]["Communications"]


# ---- Known need (Fix 4) -----------------------------------------------------------------------

def test_need_comes_from_requests_and_no_request_means_unknown():
    reads = read_all(fake_ai.client(), upto=22)
    s = county(22, "Robeson", reads)
    assert s["resources"]["Water"]["need"] == 4
    assert s["resources"]["Sanitation"]["need"] == 16
    assert s["resources"]["Food"]["need"] is None  # shown as "need unknown", never 0


# ---- Cache and payload --------------------------------------------------------------------------

class CountingClient:
    cache_name = "counting"

    def __init__(self, fail_first=0):
        self.calls = 0
        self.fail_first = fail_first

    def extract(self, payload):
        self.calls += 1
        if self.calls <= self.fail_first:
            raise RuntimeError("boom")
        return []


def test_cache_is_shared_across_tabs_and_failures_are_retried():
    client = CountingClient()
    tab1, tab2 = ai.Intake(client), ai.Intake(client)
    tab1.read(ALL[0])
    res = tab2.read(ALL[0])
    assert client.calls == 1 and res.from_cache and tab2.calls_made == 0

    flaky = CountingClient(fail_first=1)
    t = ai.Intake(flaky)
    assert t.read(ALL[1]).status == "unavailable"
    assert ai.Intake(flaky).read(ALL[1]).status == "ok"  # not cached, so retried
    assert flaky.calls == 2


def test_model_receives_only_sim_hour_source_verified_text():
    client = fake_ai.client()
    read_all(client)
    assert client.payloads
    for p in client.payloads:
        assert set(p) == {"sim_hour", "source", "verified", "text"}
    req = ai.ClaudeClient(api_key="test-not-a-key").request(client.payloads[0])
    assert req["messages"][0]["content"] == ai.user_message(client.payloads[0])


def test_accepted_facts_csv_has_report_id_and_nine_fields():
    text = engine.accepted_facts_csv(read_all(fake_ai.client(), upto=22))
    lines = text.strip().splitlines()
    assert lines[0].split(",") == list(engine.FACT_CSV_COLUMNS)
    assert any(line.startswith("R13,Robeson,Water") for line in lines)


# ---- The real app, headless, with the scripted client ----------------------------------------

@pytest.fixture
def fake_env(monkeypatch):
    monkeypatch.setenv("SKYZR_FAKE_AI", "1")


def ai_app(hour, county_name):
    at = AppTest.from_file("../app.py", default_timeout=60)
    at.session_state["clock"] = engine.Clock(hour, hour)
    at.session_state["mode"] = "AI mode"
    at.run()
    at.selectbox(key="county_select").set_value(county_name).run()
    assert not at.exception
    return at


def html_of(at):
    return " ".join(str(h.proto) for h in at.get("html"))


def test_ai_mode_panel_shows_colors_and_quotes(fake_env):
    at = ai_app(22, "Robeson")
    html = html_of(at)
    assert "three municipal water systems are offline" in html
    assert "a hospital in Lumberton is on generator" in html
    assert "No request received, need unknown" in html
    assert "AI mode:" in html
    s = engine.state_at(22, (), SC, at.session_state["ai_reads"])[FIPS["Robeson"]]
    assert s["lifelines"]["Water"] == engine.RED
    assert s["lifelines"]["Health and Medical"] == engine.YELLOW


def test_ai_mode_with_failing_client_shows_unavailable(monkeypatch):
    monkeypatch.setenv("SKYZR_FAKE_AI", "fail")
    at = ai_app(22, "Robeson")
    reads = at.session_state["ai_reads"]
    assert reads and all(r.status == "unavailable" for r in reads.values())
    expanders = " ".join(e.label for e in at.expander)
    assert ai.AI_UNAVAILABLE in expanders
    s = engine.state_at(22, (), SC, reads)[FIPS["Robeson"]]
    assert s["lifelines"]["Water"] is None and s["resources"]["Water"]["need"] is None
