"""Phase 2C: Pause must not leave the screen one hour behind the live head.

Headless (Streamlit AppTest; no browser, no key). The browser bug: Pause was
pressed while a tick's rerun was still drawing, so the browser sent the
slider's old value (live head - 1) with the click, and the slider's on_change
moved the cursor back one hour.
"""

from streamlit.testing.v1 import AppTest

import engine

FAR_FUTURE = 1e12  # last_tick in the future: no tick fires during these runs


def playing_at(hour):
    at = AppTest.from_file("../app.py", default_timeout=60)
    at.session_state["clock"] = engine.Clock(hour, hour, playing=True)
    at.session_state["last_tick"] = FAR_FUTURE
    at.run()
    assert not at.exception
    return at


def button(at, label):
    return next(b for b in at.button if b.label == label)


def time_slider(at):
    return next(s for s in at.slider if s.label.startswith("Time slider"))


def clock_html(at):
    return next(str(h.proto) for h in at.get("html") if "sk-clock" in str(h.proto))


def test_pause_with_a_lagging_slider_keeps_the_cursor_at_the_live_head():
    at = playing_at(30)
    assert time_slider(at).value == 30

    # What the browser holds: the page drawn at hour 30. Pause is pressed on it.
    unclicked = at._tree.get_widget_states()
    button(at, "Pause").click()
    stale_with_pause = at._tree.get_widget_states()

    # Meanwhile the app's own playback fragment ticks to hour 31 and redraws;
    # the browser hasn't received that redraw when the click is sent.
    at.session_state["last_tick"] = 0.0
    at._run(unclicked)
    assert at.session_state["clock"] == engine.Clock(31, 31, playing=True)

    # The click arrives carrying the slider's old value, 30 (live head - 1).
    at.session_state["last_tick"] = FAR_FUTURE
    at._run(stale_with_pause)
    assert not at.exception
    assert at.session_state["clock"] == engine.Clock(31, 31, playing=False)
    html = clock_html(at)
    assert "Hour 31" in html and "LIVE" in html and "Reviewing" not in html
    assert time_slider(at).value == 31


def test_a_real_drag_sent_while_a_tick_redraw_is_on_its_way_still_counts():
    at = playing_at(30)
    unclicked = at._tree.get_widget_states()
    # The person drags the slider they see (drawn at hour 30) back to 25...
    time_slider(at).set_value(25)
    stale_with_drag = at._tree.get_widget_states()
    # ...while the playback fragment ticks to 31 and redraws.
    at.session_state["last_tick"] = 0.0
    at._run(unclicked)
    assert at.session_state["clock"] == engine.Clock(31, 31, playing=True)
    at.session_state["last_tick"] = FAR_FUTURE
    at._run(stale_with_drag)
    assert not at.exception
    assert at.session_state["clock"] == engine.Clock(31, 25, playing=True)
    assert "Reviewing · live is hour 31" in clock_html(at)
    assert time_slider(at).value == 25


def test_a_real_drag_while_paused_still_reviews_and_back_to_live_returns():
    at = AppTest.from_file("../app.py", default_timeout=60)
    at.session_state["clock"] = engine.Clock(30, 30)
    at.run()

    time_slider(at).set_value(27).run()
    assert at.session_state["clock"] == engine.Clock(30, 27)
    assert "Reviewing · live is hour 30" in clock_html(at)
    assert time_slider(at).value == 27

    # Past the live head: snaps back to it, with the one-line note.
    time_slider(at).set_value(40).run()
    assert at.session_state["clock"] == engine.Clock(30, 30)
    assert time_slider(at).value == 30
    assert any("Hour 40 hasn't been played yet" in c.value for c in at.caption)

    time_slider(at).set_value(26).run()
    assert at.session_state["clock"] == engine.Clock(30, 26)
    button(at, "Back to live").click().run()
    assert at.session_state["clock"] == engine.Clock(30, 30)
    assert "LIVE" in clock_html(at) and "Reviewing" not in clock_html(at)
    assert time_slider(at).value == 30


def test_a_real_drag_during_playback_holds_the_view_while_play_continues():
    at = playing_at(30)
    time_slider(at).set_value(25).run()
    assert at.session_state["clock"] == engine.Clock(30, 25, playing=True)
    # A tick moves the live head; the view held for review stays put.
    at.session_state["clock"] = engine.tick(at.session_state["clock"])
    at.run()
    assert at.session_state["clock"] == engine.Clock(31, 25, playing=True)
    assert time_slider(at).value == 25
    button(at, "Pause").click().run()
    assert at.session_state["clock"] == engine.Clock(31, 25, playing=False)
