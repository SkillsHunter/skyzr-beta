"""Phase 3E: the Gaps view (read-only; SKYZR ranks and recommends nothing)."""

import pytest
from streamlit.testing.v1 import AppTest

import ai
import engine
import fake_ai
import ui

SC = engine.default_scenario()
FIPS = {v: k for k, v in SC.names.items()}
RYG_FILLS = [ui.STATUS_FILL[c] for c in ("red", "yellow", "green")]


@pytest.mark.parametrize("need,on_hand,in_transit,gap", [
    (4, 0, 0, 4), (4, 1, 2, 1), (4, 3, 3, 0), (0, 5, 0, 0), (None, 2, 0, None)])
def test_gap_arithmetic_never_below_zero_and_unknown_stays_unknown(need, on_hand, in_transit, gap):
    assert engine.gap_of(need, on_hand, in_transit) == gap


def test_rows_are_storm_path_counties_alphabetical_by_default():
    rows = engine.gaps_rows(engine.state_at(22, (), SC))
    names = [r["county"] for r in rows]
    assert len(rows) == len(SC.hit) and names == sorted(names)
    assert engine.sort_gaps(rows, "County name") == rows


def test_person_can_sort_by_a_resource_gap_unknown_last():
    reads = {rid: ai.Intake(fake_ai.client()).read(r)
             for rid, r in SC.reports.items() if r["sim_hour"] <= 22}
    rows = engine.sort_gaps(engine.gaps_rows(engine.state_at(22, (), SC, reads)), "Water")
    gaps = [r["resources"]["Water"]["gap"] for r in rows]
    known = [g for g in gaps if g is not None]
    assert known == sorted(known, reverse=True)
    assert gaps[len(known):] == [None] * (len(gaps) - len(known))  # unknown after known


def test_ai_mode_unknown_need_gives_unknown_gap():
    reads = {rid: ai.Intake(fake_ai.client()).read(r)
             for rid, r in SC.reports.items() if r["sim_hour"] <= 22}
    row = next(r for r in engine.gaps_rows(engine.state_at(22, (), SC, reads))
               if r["county"] == "Robeson")
    assert row["resources"]["Food"]["need"] is None and row["resources"]["Food"]["gap"] is None
    assert row["resources"]["Water"]["gap"] == 4


def test_silent_county_row_is_marked_last_known():
    row = next(r for r in engine.gaps_rows(engine.state_at(22, (), SC)) if r["county"] == "Pender")
    assert row["silent"] and row["as_of"] == 8


def test_delivery_confirmation_lowers_the_gap_and_keeps_the_color():
    wake, robeson = FIPS["Wake"], FIPS["Robeson"]
    clock = engine.Clock(22, 22)
    events = engine.direct_supplies((), clock, wake, robeson, "Water", 4, "Logistics",
                                    "Water systems out", SC)
    arrives = events[-1].arrives
    before = next(r for r in engine.gaps_rows(engine.state_at(22, (), SC)) if r["fips"] == robeson)
    at_send = next(r for r in engine.gaps_rows(engine.state_at(22, events, SC)) if r["fips"] == robeson)
    after = next(r for r in engine.gaps_rows(engine.state_at(arrives, events, SC))
                 if r["fips"] == robeson)
    assert before["resources"]["Water"]["gap"] == 4
    assert at_send["resources"]["Water"]["in_transit"] == 4 and at_send["resources"]["Water"]["gap"] == 0
    assert after["resources"]["Water"]["need"] == 0 and after["resources"]["Water"]["gap"] == 0
    assert (engine.state_at(arrives, events, SC)[robeson]["color"]
            == engine.state_at(arrives, (), SC)[robeson]["color"])


def gaps_html(at):
    blocks = [str(h.proto) for h in at.get("html")]
    return " ".join(b for b in blocks if "County (storm path)" in b)


@pytest.mark.parametrize("mode", ["Answer-key mode", "AI mode"])
def test_gaps_view_renders_in_both_modes(monkeypatch, mode):
    monkeypatch.setenv("SKYZR_FAKE_AI", "1")
    at = AppTest.from_file("../app.py", default_timeout=60)
    at.session_state["clock"] = engine.Clock(22, 22)
    at.session_state["mode"] = mode
    at.run()
    assert not at.exception
    html = gaps_html(at)
    assert "Robeson" in html and "Stock held in grey counties" in html
    assert "last known (hour 8)" in html  # Pender, silent at hour 22
    for fill in RYG_FILLS:
        assert fill not in html  # no colored chips in the Gaps view
    if mode == "AI mode":
        assert "unknown" in html
    labels = [b.label for b in at.button]
    assert not any(label.startswith("Gaps tab") for label in labels)
    assert "Ask SKYZR · Coming next" in labels
    assert any(engine.GAPS_NOTE in c.value for c in at.caption)
