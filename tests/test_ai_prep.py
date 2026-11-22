"""Phase 3 prep: the AI's plain-code parts, tested with a FakeClient.

No API key, no network, no real AI calls. The reports used here are the
public, synthetic reports.csv rows plus a few synthetic one-line reports.
"""

import time
from pathlib import Path

import pytest

import ai
import engine
from ai import Fact


@pytest.fixture(scope="module")
def reports():
    df = engine.load_csv("reports.csv")
    return {r["report_id"]: r for r in df.to_dict("records")}


class FakeClient:
    """Returns canned raw facts; records every payload it was sent."""

    def __init__(self, facts=None, raises=None, delay=0.0):
        self.facts = facts or []
        self.raises = raises
        self.delay = delay
        self.payloads = []

    def extract(self, payload):
        self.payloads.append(payload)
        if self.delay:
            time.sleep(self.delay)
        if self.raises:
            raise self.raises
        return list(self.facts)


def raw(quote, **over):
    base = {"county": "New Hanover", "lifeline_or_resource": "Roads",
            "metric": "Route status", "value": "No open route to county seat",
            "status_word": "No route", "source": "whatever the model says",
            "sim_hour": 99, "quote": quote, "verified": "Yes"}
    return {**base, **over}


def fact(source="A", hour=10, status="Out", value=3, county="Robeson",
         lr="Water", metric="Systems out of service"):
    return Fact(county, lr, metric, value, status, source, hour, "q", "Yes")


# ---- Schema and what the model sees ------------------------------------------------

def test_fact_schema_is_the_design_doc_fields():
    assert ai.FACT_FIELDS == ("county", "lifeline_or_resource", "metric", "value",
                              "status_word", "source", "sim_hour", "quote", "verified")
    assert tuple(Fact.__dataclass_fields__) == ai.FACT_FIELDS


def test_model_gets_only_hour_source_verified_and_text(reports):
    client = FakeClient()
    ai.read_report(reports["R01"], client)
    assert list(client.payloads[0]) == ["sim_hour", "source", "verified", "text"]
    assert "county" not in client.payloads[0] and "fips" not in client.payloads[0]


def test_ai_module_never_reads_files_or_the_answer_key():
    source = (Path(__file__).parent.parent / "ai.py").read_text(encoding="utf-8")
    docstring_end = source.index('"""', 3) + 3
    code = source[docstring_end:]
    assert "answer_key" not in code  # only the module docstring names it, as a rule
    for reader in ("read_csv", "load_csv", "open(", "import engine", "pandas"):
        assert reader not in code


# ---- Quote check (Fix 5) --------------------------------------------------------------

def test_fact_with_quote_not_in_the_unchanged_report_is_rejected(reports):
    report = dict(reports["R01"])
    before = report["text"]
    result = ai.read_report(report, FakeClient([raw("both bridges have collapsed")]))
    assert report["text"] == before  # the report itself is never edited
    assert result.accepted == ()
    assert result.rejected[0][1] == "quote not found word for word in the report"


def test_real_quote_is_accepted(reports):
    result = ai.read_report(reports["R01"], FakeClient(
        [raw("there is no open route into Wilmington, the county seat")]))
    assert len(result.accepted) == 1


def test_real_quote_with_extra_whitespace_is_accepted(reports):
    result = ai.read_report(reports["R01"], FakeClient(
        [raw("there is  no open\nroute into   Wilmington")]))
    assert len(result.accepted) == 1


def test_curly_quotes_match_straight_and_back():
    report = {"report_id": "T1", "sim_hour": 4, "source": "Test EM (fictional)",
              "verified": "yes", "text": 'Crews said the "east plant" isn\'t running.'}
    curly = "the “east plant” isn’t running"
    assert len(ai.read_report(report, FakeClient([raw(curly)])).accepted) == 1
    report_curly = dict(report, text="Crews said the “east plant” isn’t running.")
    straight = "the \"east plant\" isn't running"
    assert len(ai.read_report(report_curly, FakeClient([raw(straight)])).accepted) == 1


def test_case_is_not_folded(reports):
    result = ai.read_report(reports["R01"], FakeClient([raw("THERE IS NO OPEN ROUTE")]))
    assert result.accepted == ()


def test_quote_must_match_whole_words(reports):
    # "here is no open" sits inside "there is no open" but isn't word for word.
    result = ai.read_report(reports["R01"], FakeClient([raw("here is no open route")]))
    assert result.accepted == ()


def test_empty_quote_is_rejected(reports):
    for blank in ("", "   "):
        result = ai.read_report(reports["R01"], FakeClient([raw(blank)]))
        assert result.accepted == () and len(result.rejected) == 1


# ---- Fields code fills from the report ----------------------------------------------

def test_unofficial_source_is_verified_no_even_if_model_says_yes(reports):
    r02 = reports["R02"]
    result = ai.read_report(r02, FakeClient(
        [raw("nobody can get in or out of brunswick county", county="Brunswick",
             verified="Yes")]))
    f = result.accepted[0]
    assert f.verified == "No"
    assert f.source == "Social media post (unverified)" and f.sim_hour == r02["sim_hour"]


def test_official_source_is_verified_yes(reports):
    result = ai.read_report(reports["R01"], FakeClient(
        [raw("no open route into Wilmington", verified="No")]))
    assert result.accepted[0].verified == "Yes"


# ---- Failures --------------------------------------------------------------------------

@pytest.mark.parametrize("error", [RuntimeError("boom"), TimeoutError(), ConnectionError()])
def test_client_failure_changes_nothing(reports, error):
    intake = ai.Intake(FakeClient(raises=error))
    result = intake.read(reports["R03"])
    assert result.status == "unavailable"
    assert result.message == "AI unavailable: report not processed"
    assert result.accepted == () and result.rejected == ()
    assert result.report_text == reports["R03"]["text"]  # raw report stays visible
    assert intake._cache == {}  # a failure is never cached


def test_client_timeout_changes_nothing(reports, monkeypatch):
    monkeypatch.setattr(ai, "CALL_TIMEOUT_SECONDS", 0.05)
    result = ai.Intake(FakeClient([raw("no open route")], delay=0.5)).read(reports["R01"])
    assert result.status == "unavailable" and result.accepted == ()


def test_real_client_is_not_built():
    with pytest.raises(NotImplementedError):
        ai.ClaudeClient().extract({})


# ---- Cache and call cap ----------------------------------------------------------------

def test_cache_hit_makes_no_second_call(reports):
    client = FakeClient([raw("no open route into Wilmington")])
    intake = ai.Intake(client)
    first = intake.read(reports["R01"])
    second = intake.read(dict(reports["R01"]))
    assert len(client.payloads) == 1 and intake.calls_made == 1
    assert second.from_cache and second.accepted == first.accepted


def test_81st_call_is_refused_and_changes_nothing():
    client = FakeClient()
    intake = ai.Intake(client)
    def rep(i):
        return {"report_id": f"T{i}", "sim_hour": 1, "source": "Test (fictional)",
                "verified": "yes", "text": f"Synthetic report number {i}."}
    for i in range(80):
        assert intake.read(rep(i)).status == "ok"
    result = intake.read(rep(80))
    assert result.status == "limit" and result.message == "AI call limit reached"
    assert result.accepted == () and len(client.payloads) == 80
    assert intake.read(rep(3)).from_cache  # cached reports still work after the cap


# ---- Contradictions (design doc p. 9) -------------------------------------------------

def test_status_words_differ_is_flagged():
    a = fact("A", 10, "Out", 3)
    b = fact("B", 12, "Boil notice", 3)
    assert ai.find_contradictions([a, b]) == [(a, b)]


def test_values_25_percent_apart_are_flagged():
    a, b = fact("A", 10, value=75), fact("B", 12, value=100)  # |75-100|/100 = 0.25
    assert ai.find_contradictions([a, b]) == [(a, b)]


def test_values_15_percent_apart_are_not_flagged():
    a, b = fact("A", 10, value=85), fact("B", 12, value=100)  # 0.15
    assert ai.find_contradictions([a, b]) == []


def test_7_hours_apart_is_not_flagged():
    a, b = fact("A", 10, "Out"), fact("B", 17, "Normal")
    assert ai.find_contradictions([a, b]) == []


def test_6_hours_apart_is_flagged():
    a, b = fact("A", 10, "Out"), fact("B", 16, "Normal")
    assert len(ai.find_contradictions([a, b])) == 1


def test_same_source_later_replaces_and_does_not_conflict():
    early, late = fact("A", 10, "Out", 3), fact("A", 12, "Normal", 0)
    current, replaced = ai.supersede([early, late])
    assert current == (late,) and replaced == (early,)
    assert ai.find_contradictions([early, late]) == []


def test_different_county_or_metric_never_conflicts():
    a = fact("A", 10, "Out")
    assert ai.find_contradictions([a, fact("B", 10, "Normal", county="Bladen")]) == []
    assert ai.find_contradictions([a, fact("B", 10, "Normal", metric="System status")]) == []


def test_resource_request_conflict_follows_the_constant(monkeypatch):
    a = fact("A", 10, "Requested", 2, lr="Water", metric="Requested")
    b = fact("B", 11, "Requested", 6, lr="Water", metric="Requested")
    monkeypatch.setattr(ai, "CONTRADICTIONS_COVER_RESOURCE_REQUESTS", True)
    assert ai.find_contradictions([a, b]) == [(a, b)]
    monkeypatch.setattr(ai, "CONTRADICTIONS_COVER_RESOURCE_REQUESTS", False)
    assert ai.find_contradictions([a, b]) == []


def test_relative_difference_formula():
    assert ai.relative_difference(75, 100) == 0.25
    assert ai.relative_difference(100, 75) == 0.25
    assert ai.relative_difference(0, 0) == 0.0
    assert ai.relative_difference(0, 4) == 1.0
