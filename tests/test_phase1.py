"""Phase 1 (plan v2 §5): answer-key mode, silence, colors, playback clock.

No Streamlit, no browser, no API key.
"""

import pytest

import engine
from engine import GREEN, GREY, PURPLE, RED, YELLOW

HOURS = range(engine.FIRST_HOUR, engine.LAST_HOUR + 1)

# From app/data/README.md, "Silent windows": (last contact, next contact).
# Purple runs from last contact + 12 until the next contact arrives, so a
# county is purple for hours last+12 <= h < next.
SILENT = {
    "Pender": (8, 36),
    "Bladen": (12, 36),
    "Montgomery": (15, 39),
    "Caswell": (27, 51),
}
# The README's "Purple" column, written out so the tests don't reuse the
# engine's own threshold constant.
PURPLE_FROM = {"Pender": 20, "Bladen": 24, "Montgomery": 27, "Caswell": 39}


@pytest.fixture(scope="module")
def tables():
    return engine.load_scenario_csvs()


@pytest.fixture(scope="module")
def sc(tables):
    return engine.build_scenario(engine.load_geojson(), tables)


@pytest.fixture(scope="module")
def states(sc):
    """state_at for every hour, computed once."""
    return {h: engine.state_at(h, (), sc) for h in HOURS}


@pytest.fixture(scope="module")
def fips_of(sc):
    return {name: f for f, name in sc.names.items()}


def _purple_hours(county):
    return set(range(PURPLE_FROM[county], SILENT[county][1]))


# ---- Contact gaps ----------------------------------------------------------

def _gaps(hours):
    """Gaps between consecutive contacts, plus start-of-run and end-of-run."""
    pts = [engine.FIRST_HOUR] + list(hours) + [engine.LAST_HOUR]
    return [(a, b) for a, b in zip(pts, pts[1:])]


def test_scenario_has_29_hit_counties(sc):
    assert len(sc.hit) == 29
    assert len(sc.names) == 100


def test_non_silent_counties_never_go_12_hours_without_contact(sc):
    non_silent = [f for f in sc.hit if sc.names[f] not in SILENT]
    assert len(non_silent) == 25
    for f in non_silent:
        worst = max(b - a for a, b in _gaps(sc.contacts[f]))
        assert worst < 12, f"{sc.names[f]}: {worst} h without contact"


@pytest.mark.parametrize("county", sorted(SILENT))
def test_silent_window_is_the_only_gap_of_12_or_more(sc, fips_of, county):
    long_gaps = [(a, b) for a, b in _gaps(sc.contacts[fips_of[county]]) if b - a >= 12]
    assert long_gaps == [SILENT[county]]


# ---- Silence rule ----------------------------------------------------------

@pytest.mark.parametrize("county", sorted(SILENT))
def test_purple_exactly_during_the_silent_window(states, fips_of, county):
    f = fips_of[county]
    purple = {h for h in HOURS if states[h][f]["color"] == PURPLE}
    assert purple == _purple_hours(county)


def test_pender_is_purple_at_hour_22_with_14_hours_since_contact(states, fips_of):
    pender = states[22][fips_of["Pender"]]
    assert pender["color"] == PURPLE
    assert pender["hours_since_contact"] == 14


def test_silent_counties_never_grey_or_green(states, fips_of):
    for county in SILENT:
        f = fips_of[county]
        for h in HOURS:
            assert states[h][f]["color"] != GREY
            if h in _purple_hours(county):
                assert states[h][f]["color"] == PURPLE


def test_purple_holds_in_every_overlay(states, fips_of):
    f = fips_of["Pender"]
    for overlay in ("Overall",) + engine.LIFELINES:
        assert engine.overlay_color(states[22][f], overlay) == PURPLE


def test_no_other_county_ever_goes_purple(states, sc):
    for f in sc.hit:
        if sc.names[f] in SILENT:
            continue
        assert all(states[h][f]["color"] != PURPLE for h in HOURS), sc.names[f]


# ---- Colors ----------------------------------------------------------------

def test_overall_is_most_urgent_lifeline_outside_purple(states, sc):
    rank = {GREEN: 0, YELLOW: 1, RED: 2}
    for h in HOURS:
        for f in sc.hit:
            s = states[h][f]
            if s["color"] == PURPLE:
                continue
            assert s["color"] == max(s["lifelines"].values(), key=rank.get)


@pytest.mark.parametrize("hour", [6, 24, 48])
def test_colors_match_answer_key(states, tables, hour):
    ak = tables["answer_key.csv"]
    rows = ak[ak["hour"] == hour]
    assert len(rows) == 29
    for row in rows.to_dict("records"):
        s = states[hour][row["fips"]]
        if row["county"] in SILENT and hour in _purple_hours(row["county"]):
            assert s["color"] == PURPLE, row["county"]
            continue
        assert s["color"] == row["overall_before_silence"], row["county"]
        assert s["lifelines"] == {
            "Power": row["power"],
            "Communications": row["communications"],
            "Roads": row["roads"],
            "Water": row["water"],
            "Health and Medical": row["health"],
        }, row["county"]


def test_hour_24_has_bladen_and_pender_purple(states, fips_of):
    # README: Pender 20-36, Bladen 24-36, Montgomery 27-39, Caswell 39-51.
    purple = {c for c in SILENT if states[24][fips_of[c]]["color"] == PURPLE}
    assert purple == {"Pender", "Bladen"}


def test_grey_counties_never_change_color(states, sc):
    grey = [f for f in sc.names if f not in sc.hit]
    assert len(grey) == 71
    for h in HOURS:
        for f in grey:
            assert states[h][f]["color"] == GREY
            assert engine.overlay_color(states[h][f], "Water") == GREY


def test_hit_counties_are_never_grey(states, sc):
    for h in HOURS:
        for f in sc.hit:
            assert states[h][f]["color"] != GREY


def test_overlay_recolors_by_that_lifeline_only(states, sc):
    for f in sc.hit:
        s = states[6][f]
        if s["color"] == PURPLE:
            continue
        for ll in engine.LIFELINES:
            assert engine.overlay_color(s, ll) == s["lifelines"][ll]


def test_every_color_has_a_status_word(states, sc):
    for h in (0, 22, 48):
        for f in sc.names:
            s = states[h][f]
            assert s["status_word"] == engine.STATUS_WORD[s["color"]]


# ---- Resources and report times ------------------------------------------

def test_resources_answer_key_mode(states, tables, sc):
    ak = tables["answer_key.csv"].set_index(["fips", "hour"])
    for f in sc.names:
        res = states[30][f]["resources"]
        assert len(res) == 9
        for name, _, suffix in engine.RESOURCES:
            assert res[name]["on_hand"] == sc.stock[f][name]
            assert res[name]["in_transit"] == 0
            if f in sc.hit and states[30][f]["color"] != PURPLE:
                assert res[name]["need"] == int(ak.loc[(f, 30), f"true_need_{suffix}"])
            elif f not in sc.hit:
                assert res[name]["need"] is None


def test_last_report_hour_comes_from_reports_only(states, tables, fips_of):
    reports = tables["reports.csv"]
    f = fips_of["Robeson"]
    hours = sorted(reports.loc[reports["fips"] == f, "sim_hour"])
    for h in HOURS:
        expected = max((x for x in hours if x <= h), default=None)
        assert states[h][f]["last_report_hour"] == expected


def test_state_at_rejects_hours_outside_the_run(sc):
    with pytest.raises(ValueError):
        engine.state_at(73, (), sc)
    with pytest.raises(ValueError):
        engine.state_at(-1, (), sc)


# ---- Playback clock (Fix 2) -----------------------------------------------

def test_playback_visits_every_hour_exactly_once():
    clock = engine.play(engine.Clock())
    seen = [clock.live_head]
    while clock.playing:
        clock = engine.tick(clock)
        seen.append(clock.live_head)
    assert seen == list(HOURS)
    assert clock.live_head == engine.LAST_HOUR
    assert not clock.playing
    # Further ticks change nothing.
    assert engine.tick(clock).live_head == engine.LAST_HOUR


def test_cursor_follows_live_head_while_playing():
    clock = engine.play(engine.Clock())
    for _ in range(5):
        clock = engine.tick(clock)
    assert clock.cursor == clock.live_head == 5


def test_cursor_cannot_pass_live_head():
    clock = engine.Clock(live_head=10, cursor=10)
    assert engine.move_cursor(clock, 40).cursor == 10
    assert engine.move_cursor(clock, -5).cursor == 0
    assert engine.move_cursor(clock, 4).cursor == 4


def test_slider_moves_only_the_cursor():
    clock = engine.Clock(live_head=10, cursor=10)
    moved = engine.move_cursor(clock, 3)
    assert moved.live_head == 10


def test_reviewing_while_playing_keeps_cursor_and_head_moves_on():
    clock = engine.play(engine.Clock(live_head=10, cursor=10))
    clock = engine.move_cursor(clock, 4)
    clock = engine.tick(clock)
    assert (clock.live_head, clock.cursor) == (11, 4)


def test_pause_stops_the_live_head():
    clock = engine.pause(engine.play(engine.Clock(live_head=10, cursor=10)))
    assert engine.tick(clock).live_head == 10


def test_play_snaps_cursor_back_to_live_head():
    clock = engine.Clock(live_head=20, cursor=5)
    played = engine.play(clock)
    assert played.cursor == 20 and played.playing


def test_reset_returns_to_hour_zero():
    assert engine.reset(engine.Clock(live_head=50, cursor=30, playing=True)) == engine.Clock()
