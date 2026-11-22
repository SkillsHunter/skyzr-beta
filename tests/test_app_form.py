"""The Direct supplies form in the real app, run headless with Streamlit's
AppTest (no browser, no network, no API key)."""

import pytest
from streamlit.testing.v1 import AppTest

ROBESON, WAKE = "37155", "37183"
K = {"resource": f"ds_resource_{ROBESON}", "qty": f"ds_qty_{ROBESON}",
     "from": f"ds_from_{ROBESON}_Water", "reason": f"ds_reason_{ROBESON}"}


def confirm(at):
    return next(b for b in at.button if b.label == "Confirm")


@pytest.fixture
def at():
    app = AppTest.from_file("../app.py", default_timeout=60).run()
    assert not app.exception
    app.selectbox(key="role").set_value("Logistics").run()
    app.selectbox(key="county_select").set_value("Robeson").run()
    app.selectbox(key=K["resource"]).set_value("Water").run()
    return app


def fill(at, qty=2, sender=WAKE, reason=""):
    at.number_input(key=K["qty"]).set_value(qty)
    at.selectbox(key=K["from"]).set_value(sender)
    at.text_area(key=K["reason"]).set_value(reason)


def test_refused_send_keeps_every_field(at):
    fill(at, reason="")
    confirm(at).click().run()
    assert not at.exception
    assert len(at.session_state["events"]) == 0
    assert "Type a reason first" in at.session_state["ds_message"]
    # Nothing has to be retyped.
    assert at.selectbox(key=K["resource"]).value == "Water"
    assert at.number_input(key=K["qty"]).value == 2
    assert at.selectbox(key=K["from"]).value == WAKE

    # Type the reason, one click, logged.
    at.text_area(key=K["reason"]).set_value("Robeson reports water systems down")
    confirm(at).click().run()
    assert len(at.session_state["events"]) == 1
    assert at.session_state["ds_message"].startswith("Logged: 2 water tankers, Wake to Robeson")


def test_successful_send_clears_the_form(at):
    fill(at, reason="Robeson reports water systems down")
    confirm(at).click().run()
    assert len(at.session_state["events"]) == 1
    assert at.selectbox(key=K["resource"]).value is None
    assert at.number_input(key=K["qty"]).value is None
    assert at.text_area(key=K["reason"]).value == ""
