"""Phase 2A (plan v2 Phase 2, engine only): Direct supplies and the action log.

Delivery confirmation, "Unconfirmed", Change status and contradictions wait
for the team call, so they aren't tested here.
"""

import dataclasses

import pytest

import engine
from engine import ActionRefused, Clock, RED

HOUR = 22
WAKE = "37183"  # grey sender with water to send (plan v2 demo path)


@pytest.fixture(scope="module")
def sc():
    return engine.build_scenario(engine.load_geojson(), engine.load_scenario_csvs())


@pytest.fixture(scope="module")
def receivers(sc):
    """At HOUR: one non-silent hit county with Roads red, one with Roads not red."""
    s = engine.state_at(HOUR, (), sc)
    live = [f for f in sorted(sc.hit) if s[f]["color"] != engine.PURPLE]
    red = next(f for f in live if s[f]["lifelines"]["Roads"] == RED)
    not_red = next(f for f in live if s[f]["lifelines"]["Roads"] != RED)
    return {"roads_red": red, "roads_ok": not_red}


def live(hour=HOUR):
    return Clock(live_head=hour, cursor=hour)


def send(sc, events=(), clock=None, frm=WAKE, to=None, resource="Water", qty=2,
         role="Logistics", reason="Reported water systems down"):
    return engine.direct_supplies(events, clock or live(), frm, to, resource, qty,
                                  role, reason, sc)


def totals(state):
    return {
        r: sum(c["resources"][r]["on_hand"] + c["resources"][r]["in_transit"]
               for c in state.values())
        for r in engine.RESOURCE_NAMES
    }


# ---- Dispatch ----------------------------------------------------------------

def test_sender_stock_drops_at_once(sc, receivers):
    before = engine.state_at(HOUR, (), sc)[WAKE]["resources"]["Water"]["on_hand"]
    assert before >= 2
    log = send(sc, to=receivers["roads_ok"])
    after = engine.state_at(HOUR, log, sc)[WAKE]["resources"]["Water"]["on_hand"]
    assert after == before - 2


def test_in_transit_for_6_hours_when_roads_not_red(sc, receivers):
    to = receivers["roads_ok"]
    log = send(sc, to=to)
    assert log[-1].transit_hours == 6
    for h in range(HOUR, HOUR + 6):
        s = engine.state_at(h, log, sc)[to]
        assert s["resources"]["Water"]["in_transit"] == 2
        assert s["incoming"][0]["status"] == "In transit"
    assert engine.state_at(HOUR + 6, log, sc)[to]["incoming"][0]["status"] != "In transit"


def test_in_transit_for_12_hours_when_receiver_roads_red(sc, receivers):
    to = receivers["roads_red"]
    log = send(sc, to=to)
    assert log[-1].transit_hours == 12
    assert engine.state_at(HOUR + 11, log, sc)[to]["incoming"][0]["status"] == "In transit"
    assert engine.state_at(HOUR + 12, log, sc)[to]["incoming"][0]["status"] != "In transit"


@pytest.mark.parametrize("which", ["roads_ok", "roads_red"])
def test_receiver_need_and_color_unchanged_on_dispatch_and_arrival(sc, receivers, which):
    to = receivers[which]
    log = send(sc, to=to)
    for h in (HOUR, HOUR + 3, HOUR + 6, HOUR + 12, HOUR + 20):
        with_log = engine.state_at(h, log, sc)[to]
        without = engine.state_at(h, (), sc)[to]
        assert with_log["color"] == without["color"]
        assert with_log["lifelines"] == without["lifelines"]
        assert {r: v["need"] for r, v in with_log["resources"].items()} == \
               {r: v["need"] for r, v in without["resources"].items()}
        # Unconfirmed shipments never reach on-hand stock.
        assert with_log["resources"]["Water"]["on_hand"] == without["resources"]["Water"]["on_hand"]


def test_review_before_dispatch_shows_no_shipment(sc, receivers):
    log = send(sc, to=receivers["roads_ok"])
    earlier = engine.state_at(HOUR - 1, log, sc)
    assert earlier[WAKE]["resources"]["Water"]["on_hand"] == \
        engine.state_at(HOUR - 1, (), sc)[WAKE]["resources"]["Water"]["on_hand"]
    assert earlier[receivers["roads_ok"]]["incoming"] == []


# ---- Refusals ------------------------------------------------------------------

def test_send_larger_than_stock_is_refused(sc, receivers):
    have = engine.state_at(HOUR, (), sc)[WAKE]["resources"]["Water"]["on_hand"]
    with pytest.raises(ActionRefused):
        send(sc, to=receivers["roads_ok"], qty=have + 1)


def test_second_send_cant_overdraw_and_stock_never_negative(sc, receivers):
    have = engine.state_at(HOUR, (), sc)[WAKE]["resources"]["Water"]["on_hand"]
    log = send(sc, to=receivers["roads_ok"], qty=have)  # send everything
    with pytest.raises(ActionRefused):
        send(sc, events=log, to=receivers["roads_red"], qty=1)
    for h in range(HOUR, engine.LAST_HOUR + 1):
        for c in engine.state_at(h, log, sc).values():
            assert all(v["on_hand"] >= 0 for v in c["resources"].values())


@pytest.mark.parametrize("clock", [Clock(live_head=22, cursor=10),
                                   Clock(live_head=22, cursor=21, playing=True)])
def test_actions_refused_when_cursor_not_at_live_head(sc, receivers, clock):
    with pytest.raises(ActionRefused):
        send(sc, clock=clock, to=receivers["roads_ok"])


@pytest.mark.parametrize("field,value", [("reason", ""), ("reason", "   "),
                                         ("role", ""), ("qty", 0), ("qty", -1),
                                         ("qty", 1.5), ("resource", "Gold")])
def test_bad_inputs_are_refused(sc, receivers, field, value):
    kwargs = {"to": receivers["roads_ok"], field: value}
    with pytest.raises(ActionRefused):
        send(sc, **kwargs)


def test_refused_action_leaves_log_unchanged(sc, receivers):
    log = send(sc, to=receivers["roads_ok"])
    with pytest.raises(ActionRefused):
        send(sc, events=log, to=receivers["roads_ok"], reason="")
    assert len(log) == 1


# ---- Action log ------------------------------------------------------------------

def test_log_entries_carry_role_time_and_reason(sc, receivers):
    log = send(sc, to=receivers["roads_ok"], role="Logistics", reason="Water systems down")
    log = send(sc, events=log, clock=live(), to=receivers["roads_red"], qty=1,
               role="Operations chief", reason="Hospital on generator")
    for entry in log:
        assert entry.role and entry.reason and entry.hour == HOUR
    rows = engine.log_rows(log, HOUR, sc)
    assert [r["Role"] for r in rows] == ["Operations chief", "Logistics"]  # newest first
    assert all(r["Simulated time"] == f"Hour {HOUR}" and r["Reason"] for r in rows)


def test_log_entries_cannot_be_edited(sc, receivers):
    log = send(sc, to=receivers["roads_ok"])
    with pytest.raises(dataclasses.FrozenInstanceError):
        log[0].quantity = 99
    with pytest.raises(TypeError):
        log[0] = None  # the log is a tuple
    with pytest.raises(TypeError):
        del log[0]


def test_appending_returns_a_new_log_and_keeps_the_old_one(sc, receivers):
    first = send(sc, to=receivers["roads_ok"])
    second = send(sc, events=first, to=receivers["roads_ok"], qty=1)
    assert len(first) == 1 and len(second) == 2
    assert second[0] is first[0]


def test_no_engine_function_edits_or_deletes_entries():
    public = [n for n in dir(engine) if not n.startswith("_")]
    assert not [n for n in public if any(w in n.lower() for w in ("edit", "delete", "remove"))]


def test_reset_clears_all_actions(sc, receivers):
    log = send(sc, to=receivers["roads_ok"])
    clock, events = engine.reset_run()
    assert clock == Clock() and events == ()
    assert engine.state_at(HOUR, events, sc) == engine.state_at(HOUR, (), sc)


# ---- Conservation ----------------------------------------------------------------

def test_total_stock_is_conserved(sc, receivers):
    base = totals(engine.state_at(HOUR, (), sc))
    log = send(sc, to=receivers["roads_ok"], qty=2)
    log = send(sc, events=log, to=receivers["roads_red"], qty=1)
    log = send(sc, events=log, to=receivers["roads_ok"], resource="Generators",
               frm=next(f for f in sorted(sc.names) if f not in sc.hit
                        and sc.stock[f]["Generators"] > 0), qty=1)
    for h in range(HOUR, engine.LAST_HOUR + 1):
        assert totals(engine.state_at(h, log, sc)) == base, f"hour {h}"
