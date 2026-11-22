"""SKYZR beta: Streamlit app. Phase 0: map, county list, startup checks.

Hurricane Kestrel and every report, figure and source here is fictional.
County boundaries are real public data.
"""

import plotly.graph_objects as go
import streamlit as st

import engine

st.set_page_config(page_title="SKYZR", layout="wide")

# Banner wording is from the design doc and stays on screen the whole time.
st.warning("TEST MODE: fictional event, synthetic data")


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


# ---- Header and "Coming next" --------------------------------------------
st.title("SKYZR")
st.caption(
    "Hurricane Kestrel (fictional) over all 100 North Carolina counties. "
    "SKYZR shows what is known and records what people decide. It never makes the decision."
)

COMING_NEXT = [
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
st.markdown("**Coming next** (not built yet)")
cols = st.columns(3)
for i, label in enumerate(COMING_NEXT):
    cols[i % 3].button(
        f"{label}: Coming next",
        key=f"coming_{i}",
        disabled=True,
        width="stretch",
    )

# ---- Map and side panel --------------------------------------------------
map_col, panel_col = st.columns([3, 2])

with map_col:
    z = [1 if f == ss.selected_fips else 0 for f in fips_sorted]
    fig = go.Figure(
        go.Choropleth(
            geojson=geojson,
            locations=fips_sorted,
            z=z,
            zmin=0,
            zmax=1,
            colorscale=[[0, "#dbe7f3"], [1, "#2f6fb0"]],
            showscale=False,
            marker_line_color="#555555",
            marker_line_width=0.6,
            customdata=[[f, shapes[f]] for f in fips_sorted],
            hovertemplate=(
                "<b>%{customdata[1]}</b><br>Status: "
                + PLACEHOLDER_STATUS
                + "<extra></extra>"
            ),
        )
    )
    fig.update_geos(fitbounds="locations", visible=False, bgcolor="rgba(0,0,0,0)")
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=0, b=0),
        height=430,
        clickmode="event+select",
        dragmode=False,
    )
    st.plotly_chart(
        fig,
        key="map",
        on_select=_on_map_click,  # a callback; Streamlit reruns after it, as with "rerun"
        selection_mode="points",
        width="stretch",
        config={"displayModeBar": False},
    )
    st.caption(
        "Phase 0: status colors are not computed yet, so every county is drawn the same. "
        "The selected county is shaded dark blue. Click a county, or use the list below."
    )

with panel_col:
    st.subheader("County panel")
    if ss.selected_fips:
        st.markdown(f"### {shapes[ss.selected_fips]} County")
        st.write(f"FIPS: {ss.selected_fips}")
        st.write(f"Status: {PLACEHOLDER_STATUS}")
        st.write(f"Last report: {PLACEHOLDER_LAST_REPORT}")
        for label in ("Direct supplies", "Change status", "Log confirmation"):
            st.button(f"{label}: Coming next", disabled=True, width="stretch")
    else:
        st.info("No county selected. Click a county on the map or choose one from the list.")

# ---- County list: the accessible route and the fallback for map clicks ----
st.subheader("County list")
st.selectbox(
    "Choose a county",
    options=[shapes[f] for f in fips_sorted],
    index=None,
    placeholder="Type or pick a county name",
    key="county_select",
    on_change=_on_select_county,
)
st.dataframe(
    {
        "County": [shapes[f] for f in fips_sorted],
        "Status": [PLACEHOLDER_STATUS] * len(fips_sorted),
        "Last report": [PLACEHOLDER_LAST_REPORT] * len(fips_sorted),
    },
    hide_index=True,
    width="stretch",
    height=300,
)
