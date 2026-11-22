"""Phase 2B in the real app, headless (Streamlit AppTest; no browser, no key)."""

import pytest
from streamlit.testing.v1 import AppTest

import engine
import ui

ROBESON, PENDER = "37155", "37141"
RYG_FILLS = [ui.STATUS_FILL[c] for c in ("red", "yellow", "green")]


def app_at(hour, county):
    at = AppTest.from_file("../app.py", default_timeout=60)
    at.session_state["clock"] = engine.Clock(hour, hour)
    at.run()
    at.selectbox(key="role").set_value("Logistics").run()
    at.selectbox(key="county_select").set_value(county).run()
    assert not at.exception
    return at


def panel_html(at):
    """The HTML blocks between the County panel and the Action log eyebrows."""
    blocks = [str(h.proto) for h in at.get("html")]
    start = next(i for i, b in enumerate(blocks) if "County panel" in b)
    end = next(i for i, b in enumerate(blocks) if "Action log" in b)
    return " ".join(blocks[start:end])


def test_silent_panel_is_muted_with_no_red_yellow_green():
    at = app_at(22, "Pender")
    html = panel_html(at)
    assert html.count("Last known (hour 8)") == len(engine.LIFELINES)
    assert "Pender is silent; its status can" in html
    for fill in RYG_FILLS:
        assert fill not in html


def test_change_status_refused_keeps_fields_then_one_click_logs():
    at = app_at(22, "Robeson")
    at.selectbox(key=f"cs_target_{ROBESON}").set_value("Water")
    at.selectbox(key=f"cs_color_{ROBESON}").set_value("green")
    at.text_area(key=f"cs_reason_{ROBESON}").set_value("")
    next(b for b in at.button if b.label == "Change status").click().run()
    assert at.session_state["events"] == ()
    assert "Type a reason first" in at.session_state["form_msgs"][f"cs_{ROBESON}"][0]
    assert at.selectbox(key=f"cs_target_{ROBESON}").value == "Water"
    assert at.selectbox(key=f"cs_color_{ROBESON}").value == "green"

    at.text_area(key=f"cs_reason_{ROBESON}").set_value("Utility says the plant is back")
    next(b for b in at.button if b.label == "Change status").click().run()
    events = at.session_state["events"]
    assert len(events) == 1 and events[0].action == "Changed status"
    assert "Manual" in panel_html(at)
