"""The Direct supplies form handler: one click sends everything; a missing
field is named and nothing is logged."""

import pytest

import engine
from engine import Clock

HOUR = 22
WAKE, ROBESON = "37183", "37155"
GOOD = dict(role="Logistics", resource="Water", quantity=2, from_fips=WAKE,
            reason="Robeson reports water systems down")


@pytest.fixture(scope="module")
def sc():
    return engine.build_scenario(engine.load_geojson(), engine.load_scenario_csvs())


def submit(sc, events=(), clock=None, **over):
    fields = {**GOOD, **over}
    return engine.submit_direct_supplies(
        events, clock or Clock(live_head=HOUR, cursor=HOUR), ROBESON,
        fields["role"], fields["resource"], fields["quantity"],
        fields["from_fips"], fields["reason"], sc)


def test_complete_form_logs_one_entry(sc):
    events, message, logged = submit(sc)
    assert logged and len(events) == 1
    assert message == "Logged: 2 water tankers, Wake to Robeson. In transit."


@pytest.mark.parametrize("field,blank,words", [
    ("role", None, "Choose your role"),
    ("role", "", "Choose your role"),
    ("resource", None, "Choose a resource"),
    ("quantity", None, "Type a quantity"),
    ("from_fips", None, "Choose the sending county"),
    ("reason", None, "Type a reason first: every action needs one."),
    ("reason", "", "Type a reason first: every action needs one."),
    ("reason", "  \n ", "Type a reason first: every action needs one."),
])
def test_each_missing_field_is_refused_named_and_logs_nothing(sc, field, blank, words):
    prior, _, _ = submit(sc)  # a log that already has one entry
    events, message, logged = submit(sc, events=prior, **{field: blank})
    assert not logged
    assert events == prior  # nothing added, nothing changed
    assert message.startswith("Not sent.")
    assert words in message


def test_every_missing_field_is_named_at_once(sc):
    events, message, logged = submit(sc, role=None, resource=None, quantity=None,
                                     from_fips=None, reason="")
    assert not logged and events == ()
    for words in ("role", "resource", "quantity", "sending county", "reason"):
        assert words in message


def test_rule_refusals_come_back_as_messages_and_log_nothing(sc):
    have = engine.state_at(HOUR, (), sc)[WAKE]["resources"]["Water"]["on_hand"]
    events, message, logged = submit(sc, quantity=have + 1)
    assert not logged and events == () and message.startswith("Not sent:")


def test_refused_when_not_at_live_head(sc):
    events, message, logged = submit(sc, clock=Clock(live_head=HOUR, cursor=HOUR - 5))
    assert not logged and events == () and "live hour" in message


def test_quantity_from_number_input_as_float_is_accepted(sc):
    events, _, logged = submit(sc, quantity=2.0)
    assert logged and events[-1].quantity == 2


def test_handler_never_fills_in_a_missing_value(sc):
    """No default sender, quantity or reason is ever supplied by SKYZR."""
    for field in ("from_fips", "quantity", "reason"):
        events, _, logged = submit(sc, **{field: None})
        assert not logged and events == ()
