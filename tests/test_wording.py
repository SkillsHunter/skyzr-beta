"""Singular wording for a quantity of 1, plural otherwise, for all nine resources."""

import csv
import io

import pytest

import engine
from engine import Clock

ONE = {
    "Water": "1 water tanker",
    "Generators": "1 generator",
    "Utility crews": "1 utility crew",
    "Search-and-rescue teams": "1 search-and-rescue team",
    "Food": "1 pallet of meals",
    "Shelter": "1 cot or shelter kit",
    "Medical teams": "1 medical team",
    "Hygiene items": "1 hygiene kit",
    "Sanitation": "1 portable toilet and handwashing unit",
}
TWO = {
    "Water": "2 water tankers",
    "Generators": "2 generators",
    "Utility crews": "2 utility crews",
    "Search-and-rescue teams": "2 search-and-rescue teams",
    "Food": "2 pallets of meals",
    "Shelter": "2 cots and shelter kits",
    "Medical teams": "2 medical teams",
    "Hygiene items": "2 hygiene kits",
    "Sanitation": "2 portable toilet and handwashing units",
}
ROBESON = "37155"


@pytest.fixture(scope="module")
def sc():
    return engine.build_scenario(engine.load_geojson(), engine.load_scenario_csvs())


def test_tables_cover_all_nine_resources():
    assert set(ONE) == set(TWO) == set(engine.RESOURCE_NAMES)


@pytest.mark.parametrize("resource", sorted(ONE))
@pytest.mark.parametrize("qty,expected", [(1, ONE), (2, TWO)])
def test_quantity_phrase(resource, qty, expected):
    assert engine.quantity_phrase(qty, resource) == expected[resource]


@pytest.mark.parametrize("resource", sorted(ONE))
@pytest.mark.parametrize("qty,expected", [(1, ONE), (2, TWO)])
def test_log_csv_and_message_use_the_phrase(sc, resource, qty, expected):
    hour = 30
    state = engine.state_at(hour, (), sc)
    sender = next(f for f in sorted(sc.names) if f != ROBESON
                  and state[f]["resources"][resource]["on_hand"] >= qty)
    clock = Clock(live_head=hour, cursor=hour)
    events, message, logged = engine.submit_direct_supplies(
        (), clock, ROBESON, "Logistics", resource, qty, sender, "test", sc)
    assert logged
    phrase = f"{expected[resource]}, {sc.names[sender]} to Robeson"
    assert message == f"Logged: {phrase}. In transit."
    assert engine.log_rows(events, hour, sc)[0]["Details"] == phrase
    row = next(csv.DictReader(io.StringIO(engine.log_csv(events, hour, sc))))
    assert row["Details"] == phrase


@pytest.mark.parametrize("qty,expected", [(0, "0 tankers"), (1, "1 tanker"), (8, "8 tankers")])
def test_stock_label_units(qty, expected):
    assert engine.unit_phrase(qty, "Water") == expected
