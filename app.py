"""SKYZR beta: Streamlit app. Phase 1: answer-key mode replay.

Hurricane Kestrel and every report, figure and source here is fictional.
County boundaries are real public data. All state comes from
engine.state_at(cursor, events); this file only draws it.
"""

import time

import plotly.graph_objects as go
import streamlit as st

import engine
import ui

st.set_page_config(page_title="SKYZR", layout="wide")
ui.inject_styles()
ui.banner()

SPEEDS = {"Normal": 10, "Fast": 2}  # real seconds per simulated hour
OVERLAYS = ("Overall",) + engine.LIFELINES
COLOR_CODE = {"grey": 0, "green": 1, "yellow": 2, "red": 3, "purple": 4}


@st.cache_data
def load_everything():
    geojson = engine.load_geojson()
    tables = engine.load_scenario_csvs()
    return geojson, tables


geojson, tables = load_everything()
problems = engine.startup_checks(geojson, tables)
if problems:
    st.error("Startup checks failed. SKYZR will not run on data it can't trust.")
    for p in problems:
        st.write(f"- {p}")
    st.stop()


@st.cache_resource
def scenario():
    return engine.build_scenario(geojson, tables)


sc = scenario()
shapes = sc.names
fips_sorted = sorted(shapes, key=lambda f: shapes[f])
name_to_fips = {shapes[f]: f for f in fips_sorted}

# ---- Session state (one run per browser tab, plan v2 Fix 3) ---------------
ss = st.session_state
ss.setdefault("clock", engine.Clock())
ss.setdefault("events", [])  # the action log; Phase 2 adds entries
ss.setdefault("selected_fips", None)
ss.setdefault("speed", "Normal")
ss.setdefault("overlay", "Overall")
ss.setdefault("confirm_reset", False)
ss.setdefault("last_tick", 0.0)
ss.setdefault("slider_note", "")


# ---- Callbacks ---------------------------------------------------------------
def _clicked_fips(event):
    if not event:
        return None
    points = event.get("selection", {}).get("points", [])
    if not points:
        return None
    pt = points[0]
    fips = pt.get("location")
    if fips is None:
        cd = pt.get("customdata")
        fips = cd[0] if isinstance(cd, (list, tuple)) else cd
    return fips if fips in shapes else None


def on_map_click():
    clicked = _clicked_fips(ss.get("map"))
    if clicked:  # a deselect (empty selection) changes nothing
        ss.selected_fips = clicked
        ss.county_select = shapes[clicked]


def on_select_county():
    name = ss.county_select
    ss.selected_fips = name_to_fips.get(name) if name else None


def on_play_pause():
    if ss.clock.playing:
        ss.clock = engine.pause(ss.clock)
    else:
        ss.clock = engine.play(ss.clock)
        ss.last_tick = time.monotonic()
    ss.slider_note = ""


def on_go_live():
    ss.clock = engine.move_cursor(ss.clock, ss.clock.live_head)
    ss.slider_note = ""


def on_slider():
    wanted = ss.cursor_slider
    ss.clock = engine.move_cursor(ss.clock, wanted)
    ss.slider_note = (
        f"Hour {wanted} hasn't been played yet. The slider stops at the live hour, "
        f"{ss.clock.live_head}. Press Play to move forward."
        if wanted > ss.clock.live_head
        else ""
    )


def on_reset_ask():
    ss.confirm_reset = True


def on_reset_cancel():
    ss.confirm_reset = False


def on_reset_confirm():
    ss.clock = engine.reset()
    ss.events = []  # clears test-mode actions (none exist until Phase 2)
    ss.confirm_reset = False
    ss.slider_note = ""


# ---- Playback: one fragment advances the live head -------------------------
clock = ss.clock
interval = SPEEDS[ss.speed] if clock.playing else None


@st.fragment(run_every=interval)
def playback_tick():
    """Advance one simulated hour per interval, then redraw the whole page.

    The fragment also runs during every full rerun; the time check makes sure
    those runs never advance the clock, so no hour is skipped or applied twice.
    """
    c = ss.clock
    if not c.playing or interval is None:
        return
    if time.monotonic() - ss.last_tick < interval * 0.9:
        return
    ss.clock = engine.tick(c)
    ss.last_tick = time.monotonic()
    st.rerun()


playback_tick()
clock = ss.clock
state = engine.state_at(clock.cursor, ss.events, sc)

# ---- Header ------------------------------------------------------------------
silent_now = sum(1 for s in state.values() if s["color"] == engine.PURPLE)
reports_so_far = int((tables["reports.csv"]["sim_hour"] <= clock.cursor).sum())
ui.header(
    "SKYZR",
    "North Carolina county operations · Hurricane Kestrel (fictional)",
    "Answer-key mode: colors come from the scenario answer key, not from AI. "
    "SKYZR shows what is known and records what people decide. It never makes the decision.",
    [
        ("Counties", str(len(shapes))),
        ("In storm path", str(len(sc.hit))),
        ("Silent now", str(silent_now)),
        ("Reports so far", f"{reports_so_far} of {len(tables['reports.csv'])}"),
    ],
)

# ---- Playback controls ---------------------------------------------------------
with st.container(border=True):
    ui.eyebrow("Playback")
    ui.clock(clock.cursor, engine.LAST_HOUR, clock.at_live_head, clock.live_head)

    with st.container(horizontal=True, gap="small", vertical_alignment="center"):
        if clock.finished and not clock.playing:
            st.button("Play", disabled=True, help="The storm has finished at hour 72. Reset to replay.")
        else:
            st.button(
                "Pause" if clock.playing else "Play",
                type="primary",
                on_click=on_play_pause,
                icon=":material/pause:" if clock.playing else ":material/play_arrow:",
            )
        st.button(
            "Back to live",
            on_click=on_go_live,
            disabled=clock.at_live_head,
            help="Move the view back to the latest hour played.",
        )
        st.radio(
            "Speed",
            list(SPEEDS),
            key="speed",
            horizontal=True,
            format_func=lambda s: f"{s} ({SPEEDS[s]} s per hour)",
        )
        st.button("Reset", on_click=on_reset_ask, icon=":material/restart_alt:")

    if ss.confirm_reset:
        with st.container(border=True):
            st.markdown(
                "**Reset the storm?** This restarts at hour 0 and clears this tab's run."
            )
            with st.container(horizontal=True, gap="small"):
                st.button("Yes, reset", type="primary", on_click=on_reset_confirm)
                st.button("Cancel", on_click=on_reset_cancel)

    ss.cursor_slider = clock.cursor
    st.slider(
        "Time slider (simulated hour on screen)",
        min_value=engine.FIRST_HOUR,
        max_value=engine.LAST_HOUR,
        key="cursor_slider",
        on_change=on_slider,
        help="Review any hour already played. You can't drag past the live hour.",
    )
    if ss.slider_note:
        st.caption(ss.slider_note)

with st.container(horizontal=True, gap="small"):
    for i, label in enumerate(
        ["Role picker", "Action log and CSV export", "Gaps tab", "AI report reading", "Ask SKYZR"]
    ):
        st.button(f"{label} · Coming next", key=f"coming_{i}", disabled=True,
                  help="Not built yet. It will be added in a later phase.")

# ---- Map and county panel ------------------------------------------------------
map_col, panel_col = st.columns([7, 5], gap="medium")

with map_col:
    with st.container(border=True):
        ui.eyebrow(f"Map · hour {clock.cursor}")
        overlay = st.radio("Lifeline overlay", OVERLAYS, key="overlay", horizontal=True)

        selected = ss.selected_fips
        colors = [engine.overlay_color(state[f], overlay) for f in fips_sorted]
        hover = []
        for f in fips_sorted:
            s = state[f]
            line = s["status_word"]
            if overlay != "Overall" and s["color"] not in (engine.GREY, engine.PURPLE):
                ll = s["lifelines"][overlay]
                line += f"<br>{overlay}: {engine.LIFELINE_WORDS[overlay][ll]}"
            hover.append(line)

        # z is a whole-number code, so each county lands exactly on its color.
        colorscale = sorted(
            ([code / 4, ui.STATUS_FILL[name]] for name, code in COLOR_CODE.items()),
            key=lambda x: x[0],
        )

        fig = go.Figure(
            go.Choropleth(
                geojson=geojson,
                locations=fips_sorted,
                z=[COLOR_CODE[c] for c in colors],
                zmin=0,
                zmax=4,
                colorscale=colorscale,
                showscale=False,
                # The selection is an outline, never a fill.
                marker_line_color=["#0B0F14" if f == selected else "#FFFFFF" for f in fips_sorted],
                marker_line_width=[3.5 if f == selected else 0.7 for f in fips_sorted],
                customdata=[[f, shapes[f], h] for f, h in zip(fips_sorted, hover)],
                hovertemplate="<b>%{customdata[1]} County</b><br>%{customdata[2]}<extra></extra>",
            )
        )
        fig.update_geos(
            visible=False, bgcolor="rgba(0,0,0,0)", projection_type="mercator",
            lonaxis_range=[-84.4, -75.4], lataxis_range=[33.8, 36.65],
        )
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=0, r=0, t=0, b=0),
            height=320,
            clickmode="event+select",
            dragmode=False,
            hoverlabel=dict(bgcolor="#FFFFFF", bordercolor="#1F4E79",
                            font=dict(color="#1B2430", size=13)),
        )
        st.plotly_chart(
            fig,
            key="map",
            on_select=on_map_click,  # a callback; Streamlit reruns after it
            selection_mode="points",
            width="stretch",
            config={"displayModeBar": False, "scrollZoom": False},
        )
        ui.legend(engine.LEGEND)
        if overlay != "Overall":
            ui.note(
                f"Showing {overlay} only. Grey and purple counties keep their colors "
                "in every overlay."
            )
        st.caption("Click a county for its panel, or use the county list below.")


def hours_ago(h):
    return "now" if h == 0 else f"{h} h ago"


with panel_col:
    with st.container(border=True):
        ui.eyebrow("County panel")
        fips = ss.selected_fips
        if not fips:
            ui.empty_state(
                "No county selected",
                "Click a county on the map, or choose one from the county list, "
                "to see what is known about it.",
            )
        else:
            s = state[fips]
            # 1. Header
            st.subheader(f"{s['county']} County", anchor=False)
            st.html(
                ui.chip(s["status_word"], color=s["color"]) + "&nbsp;"
                + ui.chip(f"FIPS {fips}") + "&nbsp;"
                + ui.chip("In storm path" if s["hit"] else "Outside storm path")
            )
            if s["hit"]:
                ui.rows([
                    ("Last report",
                     f"Hour {s['last_report_hour']}" if s["last_report_hour"] is not None
                     else "No report yet"),
                    ("Last contact (report or feed)",
                     f"Hour {s['last_contact_hour']} · {hours_ago(s['hours_since_contact'])}"),
                ])
            else:
                ui.rows([("Last report", "Not in the storm path; no reports expected")])

            # 2. Lifelines
            ui.section("Lifelines")
            if not s["hit"]:
                ui.note("Not hit. Lifelines are tracked only for counties in the storm path.")
            else:
                if s["color"] == engine.PURPLE:
                    ui.note(
                        f"No contact for {s['hours_since_contact']} hours. Status unknown. "
                        f"Below is the last known picture, from hour {s['lifelines_as_of']}."
                    )
                body = []
                for ll in engine.LIFELINES:
                    c = s["lifelines"][ll]
                    body.append([
                        ui.e(ll),
                        ui.status_cell(c, c.capitalize(), engine.LIFELINE_WORDS[ll][c]),
                        '<span class="sk-muted">AI mode only</span>',
                    ])
                ui.table(["Lifeline", "Color", "Source report and quote"], body)

            # 3. Resources
            ui.section("Resources" if s["hit"] else "Stock available to send")
            body = []
            for name, unit, _ in engine.RESOURCES:
                r = s["resources"][name]
                if s["hit"]:
                    body.append([f"{ui.e(name)}<br><small class='sk-muted'>{ui.e(unit)}</small>",
                                 str(r["need"]), str(r["on_hand"]), str(r["in_transit"])])
                else:
                    body.append([f"{ui.e(name)}<br><small class='sk-muted'>{ui.e(unit)}</small>",
                                 str(r["on_hand"])])
            if s["hit"]:
                ui.table(["Resource", "Need", "On hand", "In transit"], body, num_cols=(1, 2, 3),
                         caption=("Need is true need from the answer key"
                                  + (f", as last known at hour {s['lifelines_as_of']}."
                                     if s["color"] == engine.PURPLE else ".")))
            else:
                ui.table(["Resource", "On hand"], body, num_cols=(1,))

            # 4. Contradictions
            ui.section("Contradictions")
            ui.note("AI mode only. Contradictions come from reports the AI reads (Phase 3).")

            with st.container(horizontal=True, gap="small"):
                for i, label in enumerate(["Direct supplies", "Change status", "Log confirmation"]):
                    st.button(f"{label} · Coming next", key=f"panel_{i}", disabled=True,
                              help="Not built yet. It will be added in Phase 2.")

# ---- County list: the accessible route and the fallback for map clicks ----------
with st.container(border=True):
    ui.eyebrow(f"County list · hour {clock.cursor}")
    st.selectbox(
        "Choose a county",
        options=[shapes[f] for f in fips_sorted],
        index=None,
        placeholder="Type a county name",
        key="county_select",
        on_change=on_select_county,
    )
    st.dataframe(
        {
            "County": [shapes[f] for f in fips_sorted],
            "Status": [state[f]["status_word"] for f in fips_sorted],
            "Last report": [
                (f"Hour {state[f]['last_report_hour']}" if state[f]["last_report_hour"] is not None
                 else ("No report yet" if state[f]["hit"] else "Not in storm path"))
                for f in fips_sorted
            ],
            "Hours since contact": [
                state[f]["hours_since_contact"] if state[f]["hit"] else None for f in fips_sorted
            ],
        },
        hide_index=True,
        width="stretch",
        height=320,
    )
