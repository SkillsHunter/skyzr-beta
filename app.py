"""SKYZR beta: Streamlit app. Phase 0: map, county list, startup checks.

Hurricane Kestrel and every report, figure and source here is fictional.
County boundaries are real public data.
"""

import plotly.graph_objects as go
import streamlit as st

import engine
import ui

st.set_page_config(page_title="SKYZR", layout="wide")
ui.inject_styles()
ui.banner()


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

shapes = engine.county_shapes(geojson)  # fips -> name
fips_sorted = sorted(shapes, key=lambda f: shapes[f])
name_to_fips = {shapes[f]: f for f in fips_sorted}
stock = tables["stock.csv"].set_index("fips")
in_path = {f for f, v in stock["hit_or_grey"].items() if v == "hit"}

# Phase 0 placeholders. Phase 1 replaces these with engine.state_at(...).
PLACEHOLDER_STATUS = "Not computed yet"
PLACEHOLDER_LAST_REPORT = "Not computed yet"

# ---- Session state -------------------------------------------------------
ss = st.session_state
ss.setdefault("selected_fips", None)


def _clicked_fips(event):
    """Return the FIPS of the clicked county from the map's selection state."""
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


def _on_map_click():
    """Runs only when the map selection changes. A deselect (empty) changes nothing."""
    clicked = _clicked_fips(ss.get("map"))
    if clicked:
        ss.selected_fips = clicked
        ss.county_select = shapes[clicked]  # keep the list in step with the map


def _on_select_county():
    name = ss.county_select
    ss.selected_fips = name_to_fips.get(name) if name else None


def coming_next(label: str, key: str) -> None:
    st.button(
        f"{label} · Coming next",
        key=key,
        disabled=True,
        width="content",
        help="Not built yet. It will be added in a later phase.",
    )


# ---- Header --------------------------------------------------------------
ui.header(
    "SKYZR",
    "North Carolina county operations · Hurricane Kestrel (fictional)",
    "Shows what is known and records what people decide. It never makes the decision.",
    [
        ("Counties", str(len(shapes))),
        ("In storm path", str(len(in_path))),
        ("Field reports", str(len(tables["reports.csv"]))),
    ],
)

# ---- Controls that are not built yet --------------------------------------
with st.container(border=True):
    ui.eyebrow("Controls")
    with st.container(horizontal=True, gap="small"):
        for i, label in enumerate(
            [
                "Play / pause",
                "Speed",
                "Time slider",
                "Reset",
                "Lifeline overlays",
                "Role picker",
                "Action log and CSV export",
                "Gaps tab",
                "AI report reading",
                "Ask SKYZR",
            ]
        ):
            coming_next(label, f"coming_{i}")

# ---- Map and county panel --------------------------------------------------
map_col, panel_col = st.columns([7, 4], gap="medium")

with map_col:
    with st.container(border=True):
        ui.eyebrow("Map · all 100 counties")
        selected = ss.selected_fips
        fig = go.Figure(
            go.Choropleth(
                geojson=geojson,
                locations=fips_sorted,
                z=[0] * len(fips_sorted),
                colorscale=[[0, "#E3E9F0"], [1, "#E3E9F0"]],
                showscale=False,
                # The selection is an outline, so it never competes with the
                # status fill colors that arrive in Phase 1.
                marker_line_color=[
                    "#0B1F33" if f == selected else "#97A3B3" for f in fips_sorted
                ],
                marker_line_width=[3 if f == selected else 0.6 for f in fips_sorted],
                customdata=[[f, shapes[f]] for f in fips_sorted],
                hovertemplate=(
                    "<b>%{customdata[1]} County</b><br>Status: "
                    + PLACEHOLDER_STATUS
                    + "<extra></extra>"
                ),
            )
        )
        # Explicit NC bounds: fitbounds left the state small inside the frame.
        fig.update_geos(
            visible=False, bgcolor="rgba(0,0,0,0)", projection_type="mercator",
            lonaxis_range=[-84.4, -75.4], lataxis_range=[33.8, 36.65],
        )
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=0, r=0, t=0, b=0),
            height=300,
            clickmode="event+select",
            dragmode=False,
            hoverlabel=dict(bgcolor="#FFFFFF", bordercolor="#1F4E79",
                            font=dict(color="#1B2430", size=13)),
        )
        st.plotly_chart(
            fig,
            key="map",
            on_select=_on_map_click,  # a callback; Streamlit reruns after it, as with "rerun"
            selection_mode="points",
            width="stretch",
            # No scroll zoom: scrolling the page over the map must scroll the page.
            config={"displayModeBar": False, "scrollZoom": False},
        )
        st.caption(
            "Status colors and their legend arrive in Phase 1; until then every county "
            "is drawn the same. A dark outline marks the selected county. "
            "Click a county, or use the county list below."
        )

with panel_col:
    with st.container(border=True):
        ui.eyebrow("County panel")
        if ss.selected_fips:
            fips = ss.selected_fips
            st.subheader(f"{shapes[fips]} County", anchor=False)
            st.html(
                ui.chip(f"FIPS {fips}") + "&nbsp;"
                + ui.chip("In storm path" if fips in in_path else "Outside storm path")
            )
            ui.rows(
                [
                    ("Status", PLACEHOLDER_STATUS),
                    ("Last report", PLACEHOLDER_LAST_REPORT),
                    ("Lifelines", "Coming next"),
                    ("Resources", "Coming next"),
                    ("Contradictions", "Coming next"),
                    ("Action log", "Coming next"),
                ]
            )
            with st.container(horizontal=True, gap="small"):
                for i, label in enumerate(
                    ["Direct supplies", "Change status", "Log confirmation"]
                ):
                    coming_next(label, f"panel_{i}")
        else:
            ui.empty_state(
                "No county selected",
                "Click a county on the map, or choose one from the county list, "
                "to see what is known about it.",
            )

# ---- County list: the accessible route and the fallback for map clicks ----
with st.container(border=True):
    ui.eyebrow("County list")
    st.selectbox(
        "Choose a county",
        options=[shapes[f] for f in fips_sorted],
        index=None,
        placeholder="Type a county name",
        key="county_select",
        on_change=_on_select_county,
    )
    st.dataframe(
        {
            "County": [shapes[f] for f in fips_sorted],
            "Storm path": ["In path" if f in in_path else "Outside" for f in fips_sorted],
            "Status": [PLACEHOLDER_STATUS] * len(fips_sorted),
            "Last report": [PLACEHOLDER_LAST_REPORT] * len(fips_sorted),
        },
        hide_index=True,
        width="stretch",
        height=320,
    )
