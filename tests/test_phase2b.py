"""Phase 2B-safe: action log fields, CSV export, sender list order, roles."""

import csv
import io

import pytest

import engine
from engine import Clock

HOUR = 22
WAKE, ROBESON = "37183", "37155"
SIX = ["Simulated time", "Role", "Action", "Details", "Reason", "Status"]


@pytest.fixture(scope="module")
def sc():
    return engine.build_scenario(engine.load_geojson(), engine.load_scenario_csvs())


@pytest.fixture(scope="module")
def log(sc):
    clock = Clock(live_head=HOUR, cursor=HOUR)
    events = engine.direct_supplies((), clock, WAKE, ROBESON, "Water", 2,
                                    "Logistics", "Robeson reports water systems down", sc)
    return engine.direct_supplies(events, clock, WAKE, ROBESON, "Generators", 1,
                                  "Operations chief", "Hospital on generator", sc)


def test_log_has_exactly_the_six_design_doc_fields(sc, log):
    assert list(engine.LOG_COLUMNS) == SIX
    for row in engine.log_rows(log, HOUR, sc):
        assert list(row) == SIX
        assert all(str(v).strip() for v in row.values())


def test_log_row_reads_like_the_design_doc_example(sc, log):
    oldest = engine.log_rows(log, HOUR, sc)[-1]
    assert oldest == {
        "Simulated time": "Hour 22",
        "Role": "Logistics",
        "Action": "Directed supplies",
        "Details": "2 water tankers, Wake to Robeson",
        "Reason": "Robeson reports water systems down",
        "Status": "In transit",
    }


def test_log_is_newest_first(sc, log):
    assert [r["Role"] for r in engine.log_rows(log, HOUR, sc)] == ["Operations chief", "Logistics"]


def test_status_never_says_arrived_not_confirmed(sc, log):
    """Phase 2B: In transit, then Delivered (hour N) or Unconfirmed. Never "Arrived"."""
    for h in range(HOUR, engine.LAST_HOUR + 1):
        for row in engine.log_rows(log, h, sc):
            assert row["Status"] == "In transit" or row["Status"].startswith(
                ("Delivered (hour ", "Unconfirmed"))
        assert "Arrived" not in engine.log_csv(log, h, sc)


def test_log_shows_only_entries_up_to_the_cursor(sc, log):
    assert engine.log_rows(log, HOUR - 1, sc) == []


def test_csv_has_the_same_six_columns_and_rows(sc, log):
    text = engine.log_csv(log, HOUR, sc)
    reader = csv.DictReader(io.StringIO(text))
    assert reader.fieldnames == SIX
    assert list(reader) == engine.log_rows(log, HOUR, sc)


def test_empty_log_csv_still_has_header(sc):
    assert engine.log_csv((), 0, sc).strip() == ",".join(SIX)


def test_sender_list_is_alphabetical_regardless_of_stock(sc):
    state = engine.state_at(HOUR, (), sc)
    for resource in engine.RESOURCE_NAMES:
        options = engine.sender_options(state, resource, ROBESON)
        names = [name for _, name, _ in options]
        assert names == sorted(names)
        assert len(options) == 99 and ROBESON not in [f for f, _, _ in options]
        stocks = [on_hand for _, _, on_hand in options]
        assert stocks == [state[f]["resources"][resource]["on_hand"] for f, _, _ in options]


def test_sender_order_ignores_stock_changes(sc):
    """Draining one sender's stock must not move it in the list."""
    clock = Clock(live_head=HOUR, cursor=HOUR)
    before = engine.state_at(HOUR, (), sc)
    have = before[WAKE]["resources"]["Water"]["on_hand"]
    drained = engine.direct_supplies((), clock, WAKE, ROBESON, "Water", have,
                                     "Logistics", "test", sc)
    after = engine.state_at(HOUR, drained, sc)
    order = lambda st: [f for f, _, _ in engine.sender_options(st, "Water", ROBESON)]
    assert order(before) == order(after)
    assert dict((f, n) for f, _, n in engine.sender_options(after, "Water", ROBESON))[WAKE] == 0


def test_demo_step_wake_to_robeson(sc):
    """Plan v2 demo step 6: 2 tankers Wake to Robeson; Robeson stays the same color."""
    clock = Clock(live_head=HOUR, cursor=HOUR)
    base = engine.state_at(HOUR, (), sc)
    events = engine.direct_supplies((), clock, WAKE, ROBESON, "Water", 2,
                                    "Logistics", "reason", sc)
    now = engine.state_at(HOUR, events, sc)
    assert now[WAKE]["resources"]["Water"]["on_hand"] == base[WAKE]["resources"]["Water"]["on_hand"] - 2
    assert now[ROBESON]["color"] == base[ROBESON]["color"]
    assert now[ROBESON]["resources"]["Water"]["in_transit"] == 2


def test_roles_are_the_four_design_doc_labels():
    assert engine.ROLES == ("Situation analyst", "Logistics", "Operations chief", "Other")
