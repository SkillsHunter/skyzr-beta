"""Phase 2B (plan v2 Phase 2 tests): delivery confirmation, Log confirmation,
Change status, silence, reset, the log and stock conservation."""

import csv
import dataclasses
import io

import pytest

import engine
from engine import ActionRefused, Clock, GREEN, PURPLE, RED, YELLOW

WAKE, ROBESON, PENDER = "37183", "37155", "37141"
SILENT = {"37141", "37017", "37123", "37033"}  # Pender, Bladen, Montgomery, Caswell


@pytest.fixture(scope="module")
def sc():
    return engine.build_scenario(engine.load_geojson(), engine.load_scenario_csvs())


def at(h):
    return Clock(live_head=h, cursor=h)


def send(sc, events=(), hour=22, frm=WAKE, to=ROBESON, resource="Water", qty=4):
    return engine.direct_supplies(events, at(hour), frm, to, resource, qty,
                                  "Logistics", "demo reason", sc)


def totals(state):
    return {r: sum(c["resources"][r]["on_hand"] + c["resources"][r]["in_transit"]
                   for c in state.values()) for r in engine.RESOURCE_NAMES}


# ---- Full shipment cycle (answer-key confirmation) -------------------------------

def test_full_shipment_cycle(sc):
    log = send(sc)
    arrives = log[-1].arrives
    base_before = engine.state_at(arrives - 1, (), sc)
    base_at = engine.state_at(arrives, (), sc)
    before = engine.state_at(arrives - 1, log, sc)
    after = engine.state_at(arrives, log, sc)

    # Before arrival: in transit; receiver need and on-hand unchanged.
    assert before[ROBESON]["resources"]["Water"]["in_transit"] == 4
    assert before[ROBESON]["incoming"][0]["status"] == "In transit"
    assert before[ROBESON]["resources"]["Water"]["need"] == \
        base_before[ROBESON]["resources"]["Water"]["need"]

    # At arrival: on-hand +4 of the same resource, in transit -4, need -4 (not below 0).
    r = after[ROBESON]["resources"]["Water"]
    b = base_at[ROBESON]["resources"]["Water"]
    assert r["on_hand"] == b["on_hand"] + 4
    assert r["in_transit"] == 0
    assert r["need"] == max(0, b["need"] - 4)
    assert after[ROBESON]["incoming"][0]["status"] == f"Delivered (hour {arrives})"
    # Other resources untouched.
    for other in engine.RESOURCE_NAMES:
        if other != "Water":
            assert after[ROBESON]["resources"][other] == base_at[ROBESON]["resources"][other]

    # Colors never change because of a shipment or a confirmation.
    for h in range(22, engine.LAST_HOUR + 1):
        with_log, without = engine.state_at(h, log, sc), engine.state_at(h, (), sc)
        assert with_log[ROBESON]["color"] == without[ROBESON]["color"]
        assert with_log[ROBESON]["lifelines"] == without[ROBESON]["lifelines"]


def test_need_never_goes_below_zero(sc):
    log = send(sc, qty=8)  # Wake has 8; Robeson needs fewer
    after = engine.state_at(log[-1].arrives, log, sc)
    assert after[ROBESON]["resources"]["Water"]["need"] == 0


def test_log_status_moves_from_in_transit_to_delivered(sc):
    log = send(sc)
    arrives = log[-1].arrives
    assert engine.log_rows(log, arrives - 1, sc)[0]["Status"] == "In transit"
    assert engine.log_rows(log, arrives, sc)[0]["Status"] == f"Delivered (hour {arrives})"


def test_over_send_refused_and_no_negative_stock(sc):
    have = engine.state_at(22, (), sc)[WAKE]["resources"]["Water"]["on_hand"]
    with pytest.raises(ActionRefused):
        send(sc, qty=have + 1)
    log = send(sc, qty=have)
    for h in range(22, engine.LAST_HOUR + 1):
        for c in engine.state_at(h, log, sc).values():
            assert all(v["on_hand"] >= 0 and v["in_transit"] >= 0
                       for v in c["resources"].values())


def test_delivered_stock_can_be_sent_on(sc):
    log = send(sc)
    arrives = log[-1].arrives
    cumberland = "37051"
    log = engine.direct_supplies(log, at(arrives), ROBESON, cumberland,
                                 "Water", 4, "Logistics", "onward", sc)
    assert engine.state_at(arrives, log, sc)[ROBESON]["resources"]["Water"]["on_hand"] == \
        engine.state_at(arrives, (), sc)[ROBESON]["resources"]["Water"]["on_hand"]


# ---- Silent receiver -> Unconfirmed -> hand confirmation --------------------------

@pytest.fixture(scope="module")
def pender_log(sc):
    log = send(sc, hour=10, to=PENDER, qty=1)  # Pender is purple 20 to 35
    assert engine.silent_at(sc, PENDER, log[-1].arrives)
    return log


def test_silent_receiver_shipment_is_unconfirmed(sc, pender_log):
    arrives = pender_log[-1].arrives
    s = engine.state_at(arrives, pender_log, sc)[PENDER]
    assert s["incoming"][0]["status"] == "Unconfirmed"
    assert s["resources"]["Water"]["in_transit"] == 1  # stays in transit
    base = engine.state_at(arrives, (), sc)[PENDER]["resources"]["Water"]
    assert s["resources"]["Water"]["on_hand"] == base["on_hand"]
    assert engine.log_rows(pender_log, arrives, sc)[0]["Status"] == "Unconfirmed"
    # Still Unconfirmed at the end of the run without a hand confirmation.
    assert engine.state_at(72, pender_log, sc)[PENDER]["incoming"][0]["status"] == "Unconfirmed"


def test_hand_confirmation_is_logged_with_role_and_reason(sc, pender_log):
    ship = pender_log[-1]
    log = engine.confirm_delivery(pender_log, at(30), ship.seq, "Operations chief",
                                  "Courier reached the shelter", sc)
    entry = log[-1]
    assert entry.action == "Confirmed delivery"
    assert (entry.role, entry.hour, entry.reason) == ("Operations chief", 30,
                                                      "Courier reached the shelter")
    s = engine.state_at(30, log, sc)[PENDER]
    assert s["incoming"][0]["status"] == "Delivered (hour 30, by hand)"
    assert s["resources"]["Water"]["in_transit"] == 0
    rows = engine.log_rows(log, 30, sc)
    assert rows[0]["Action"] == "Confirmed delivery" and rows[0]["Status"] == "Delivered"
    assert rows[1]["Status"] == "Delivered (hour 30, by hand)"
    # A hand confirmation doesn't end the silence or change the color.
    assert s["color"] == PURPLE


def test_hand_confirmation_refused_unless_unconfirmed(sc, pender_log):
    log = send(sc)  # Robeson, not silent
    with pytest.raises(ActionRefused):  # still in transit
        engine.confirm_delivery(log, at(23), log[-1].seq, "Logistics", "x", sc)
    with pytest.raises(ActionRefused):  # already delivered
        engine.confirm_delivery(log, at(log[-1].arrives), log[-1].seq, "Logistics", "x", sc)
    with pytest.raises(ActionRefused):  # reviewing, not at the live head
        engine.confirm_delivery(pender_log, Clock(30, 25), pender_log[-1].seq,
                                "Logistics", "x", sc)


@pytest.mark.parametrize("role,reason", [("", "x"), ("Logistics", ""), ("Logistics", "  ")])
def test_hand_confirmation_needs_role_and_reason(sc, pender_log, role, reason):
    with pytest.raises(ActionRefused):
        engine.confirm_delivery(pender_log, at(30), pender_log[-1].seq, role, reason, sc)


# ---- Change status -----------------------------------------------------------------

@pytest.fixture(scope="module")
def next_change(sc):
    """A non-silent county and lifeline whose answer-key value changes after hour 22,
    found directly from the answer key (independently of the engine)."""
    for f in sorted(sc.hit - SILENT):
        for ll in engine.LIFELINES:
            v0 = sc.lifelines[(f, 22)][ll]
            for h in range(23, 73):
                if sc.lifelines[(f, h)][ll] != v0:
                    return f, ll, v0, h, sc.lifelines[(f, h)][ll]
    raise AssertionError("no lifeline change found")


def change(sc, fips, target, color, hour=22, events=()):
    return engine.change_status(events, at(hour), fips, target, color, "Situation analyst",
                                "Field call says otherwise", sc)


def test_manual_status_holds_until_the_next_value(sc, next_change):
    f, ll, v0, h, v1 = next_change
    other = next(c for c in (RED, YELLOW, GREEN) if c not in (v0, v1))
    log = change(sc, f, ll, other)
    for hour in range(22, h):
        s = engine.state_at(hour, log, sc)[f]
        assert s["lifelines"][ll] == other and s["manual_marker"]
        assert s["manual"][ll]["outcome"] == "holding"


def test_disagreeing_value_raises_contradiction_and_overwrites_nothing(sc, next_change):
    f, ll, v0, h, v1 = next_change
    other = next(c for c in (RED, YELLOW, GREEN) if c not in (v0, v1))
    log = change(sc, f, ll, other)
    s = engine.state_at(h, log, sc)[f]
    assert s["lifelines"][ll] == other  # the manual value stays shown
    assert s["manual_marker"]
    [c] = s["contradictions"]
    assert c["target"] == ll
    assert (c["manual"]["color"], c["manual"]["hour"]) == (other, 22)
    assert (c["report"]["color"], c["report"]["hour"]) == (v1, h)
    assert c["manual"]["source"] and c["report"]["source"]
    assert engine.log_rows(log, h, sc)[0]["Status"] == f"Contradiction (hour {h})"


def test_agreeing_value_clears_manual(sc, next_change):
    f, ll, v0, h, v1 = next_change
    log = change(sc, f, ll, v1)
    assert engine.state_at(h - 1, log, sc)[f]["manual_marker"]
    s = engine.state_at(h, log, sc)[f]
    assert not s["manual_marker"] and s["contradictions"] == []
    assert s["lifelines"] == engine.state_at(h, (), sc)[f]["lifelines"]
    assert engine.log_rows(log, h, sc)[0]["Status"].startswith(f"Cleared (hour {h})")


def test_manual_overall_sets_the_county_color(sc, next_change):
    f = next_change[0]
    base = engine.state_at(22, (), sc)[f]["color"]
    other = next(c for c in (RED, YELLOW, GREEN) if c != base)
    s = engine.state_at(22, change(sc, f, "Overall", other), sc)[f]
    assert s["color"] == other and s["status_word"] == engine.STATUS_WORD[other]


def test_change_status_refused_on_a_silent_county(sc):
    with pytest.raises(ActionRefused) as err:
        change(sc, PENDER, "Water", GREEN, hour=22)
    assert str(err.value) == "Pender is silent; its status can't be set until contact returns."


def test_change_status_refused_off_live_head_grey_or_blank(sc, next_change):
    f = next_change[0]
    with pytest.raises(ActionRefused):
        engine.change_status((), Clock(22, 20), f, "Water", RED, "Logistics", "x", sc)
    with pytest.raises(ActionRefused):
        change(sc, WAKE, "Water", RED)  # grey county
    with pytest.raises(ActionRefused):
        engine.change_status((), at(22), f, "Water", RED, "Logistics", "", sc)
    with pytest.raises(ActionRefused):
        engine.change_status((), at(22), f, "Water", PURPLE, "Logistics", "x", sc)


def test_submit_handlers_name_what_is_missing_and_log_nothing(sc, pender_log):
    ev, msg, ok = engine.submit_change_status((), at(22), ROBESON, None, None, None, "", sc)
    assert not ok and ev == ()
    for words in ("role", "Overall or a lifeline", "new color", "reason"):
        assert words in msg
    ev, msg, ok = engine.submit_confirm_delivery(pender_log, at(30), None, "Logistics", "", sc)
    assert not ok and ev == pender_log and "shipment" in msg and "reason" in msg


# ---- Reset, log, conservation ----------------------------------------------------

@pytest.fixture(scope="module")
def all_three(sc, pender_log, next_change):
    """A log with all three action types."""
    log = engine.confirm_delivery(pender_log, at(30), pender_log[-1].seq,
                                  "Operations chief", "Courier reached the shelter", sc)
    log = send(sc, events=log, hour=30)
    return engine.change_status(log, at(30), next_change[0], "Water", RED,
                                "Situation analyst", "Field call", sc)


def test_reset_clears_all_actions(sc, all_three):
    clock, events = engine.reset_run()
    assert events == () and clock == Clock()
    assert engine.state_at(40, events, sc) == engine.state_at(40, (), sc)


def test_log_entries_cannot_be_edited_and_carry_role_time_reason(sc, all_three):
    assert {type(e).__name__ for e in all_three} == {"DirectSupplies", "ConfirmDelivery",
                                                     "ChangeStatus"}
    for entry in all_three:
        assert entry.role.strip() and entry.reason.strip() and isinstance(entry.hour, int)
        with pytest.raises(dataclasses.FrozenInstanceError):
            entry.reason = "edited"
    with pytest.raises(TypeError):
        all_three[0] = None


def test_csv_shows_all_three_action_types(sc, all_three):
    rows = list(csv.DictReader(io.StringIO(engine.log_csv(all_three, 30, sc))))
    assert {r["Action"] for r in rows} == {"Directed supplies", "Confirmed delivery",
                                           "Changed status"}
    assert all(r["Role"] and r["Reason"] and r["Simulated time"] for r in rows)


def test_stock_conserved_through_confirmations(sc, all_three):
    base = totals(engine.state_at(10, (), sc))
    for h in range(10, engine.LAST_HOUR + 1):
        assert totals(engine.state_at(h, all_three, sc)) == base, f"hour {h}"


# ---- Silent county display data and sender label --------------------------------

def test_silent_sender_is_listed_with_last_known_hour(sc):
    s = engine.state_at(22, (), sc)
    labels = {f: engine.sender_label(s, f, "Water") for f, _, _ in
              engine.sender_options(s, "Water", ROBESON)}
    assert PENDER in labels
    assert labels[PENDER].endswith("on hand (last known, hour 8)")
    assert labels[WAKE] == "Wake · 8 water tankers on hand"


def test_log_survives_a_module_reload(sc, all_three):
    """A session keeps its log across a code reload; entries made with the old
    classes must still be read correctly (found in the browser check)."""
    import importlib
    import sys

    rows_before = engine.log_rows(all_three, 30, sc)
    state_before = engine.state_at(30, all_three, sc)
    fresh = importlib.reload(sys.modules["engine"])
    try:
        sc2 = fresh.build_scenario(fresh.load_geojson(), fresh.load_scenario_csvs())
        assert fresh.log_rows(all_three, 30, sc2) == rows_before
        assert fresh.state_at(30, all_three, sc2) == state_before
    finally:
        importlib.reload(sys.modules["engine"])
