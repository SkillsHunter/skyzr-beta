"""SKYZR beta: Streamlit app. Phase 1: answer-key mode replay.

Hurricane Kestrel and every report, figure and source here is fictional.
County boundaries are real public data. All state comes from
engine.state_at(cursor, events); this file only draws it.
"""

import os
import time

import plotly.graph_objects as go
import streamlit as st

import ai
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
ss.setdefault("events", ())  # the action log: append-only tuple of entries
ss.setdefault("role", None)
ss.setdefault("ds_message", "")
ss.setdefault("selected_fips", None)
ss.setdefault("speed", "Normal")
ss.setdefault("overlay", "Overall")
ss.setdefault("confirm_reset", False)
ss.setdefault("last_tick", 0.0)
ss.setdefault("slider_note", "")
ss.setdefault("mode", "Answer-key mode")
ss.setdefault("ai_reads", {})  # report_id -> ai.ReadResult, for reports read so far
ss.setdefault("ai_fail_test", False)
ss.setdefault("slider_gen", 0)  # see slider_key
ss.setdefault("slider_held", {0: ss.clock.cursor})  # slider_gen -> value that slider holds


# ---- AI intake (Phase 3) -----------------------------------------------------------
FAKE_AI = os.environ.get("SKYZR_FAKE_AI", "")  # localhost test double only; never set on the deployed app


def make_client():
    """The real Claude client, or a client that always fails if there is no key.
    The key is read only inside ai.GeminiClient, from st.secrets."""
    if FAKE_AI:
        import fake_ai  # test double: scripted answers from the public report texts
        return fake_ai.client(fail=FAKE_AI == "fail" or ss.ai_fail_test)
    try:
        return ai.GeminiClient()
    except Exception:  # noqa: BLE001 - no key or no SDK: every report shows "AI unavailable"
        return ai.UnavailableClient("No API key")


if "intake" not in ss:
    ss.intake = ai.Intake(make_client())


def ai_mode():
    return ss.mode == "AI mode"


def reports_due(head):
    return [r for rid, r in sorted(sc.reports.items(), key=lambda kv: kv[1]["sim_hour"])
            if r["sim_hour"] <= head and rid not in ss.ai_reads]


def read_reports(reports):
    for r in reports:
        ss.ai_reads[str(r["report_id"])] = ss.intake.read(r)


def on_ai_fail_test():
    ss.intake.client = make_client()


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
        set_clock(engine.pause(ss.clock))
    else:
        set_clock(engine.play(ss.clock))
        ss.last_tick = time.monotonic()
    ss.slider_note = ""


def on_go_live():
    set_clock(engine.move_cursor(ss.clock, ss.clock.live_head))
    ss.slider_note = ""


def on_slider(key):
    """The slider reported a value. Only a value the person moved it to moves
    the cursor; the value a slider already held only lags behind playback
    (see slider_key), so it changes nothing."""
    gen = int(key.rsplit("_", 1)[1])
    wanted = ss[key]
    if wanted == ss.slider_held.get(gen):
        return
    ss.clock = engine.move_cursor(ss.clock, wanted)
    if key == slider_key() and ss.clock.cursor == wanted:
        ss.slider_held[gen] = wanted
    else:  # snapped back to the live head, or dragged on a slider since replaced
        renew_slider()
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
    clock, ss.events = engine.reset_run()  # clears every test-mode action
    set_clock(clock)
    ss.confirm_reset = False
    ss.slider_note = ""
    ss.ds_message = ""


def on_direct_supplies(to_fips):
    """Confirm (a form submit): every field arrives together on one click.
    The engine checks what's missing and applies the rules; nothing is guessed."""
    k = ds_keys(to_fips)
    resource = ss.get(k["resource"])
    ss.ds_message_for = (to_fips, ss.clock.live_head)
    ss.events, ss.ds_message, logged = engine.submit_direct_supplies(
        ss.events, ss.clock, to_fips, ss.get("role"), resource, ss.get(k["qty"]),
        ss.get(k["from"](resource)) if resource else None, ss.get(k["reason"]), sc,
    )
    if logged:
        # Clear only after a successful send. A refused send keeps every field,
        # so nothing has to be retyped.
        ss[k["resource"]] = None
        ss[k["qty"]] = None
        ss[k["from"](resource)] = None
        ss[k["reason"]] = ""


def set_form_msg(form, text):
    """Remember a form's result, tied to the live hour it happened at."""
    ss.setdefault("form_msgs", {})[form] = (text, ss.clock.live_head)


def show_form_msg(form):
    m = ss.get("form_msgs", {}).get(form)
    if m and m[1] == ss.clock.live_head:
        (st.error if m[0].startswith("Not") else st.success)(m[0])


def on_confirm_delivery(fips):
    """Log confirmation (one form, one click). Fields are kept if refused."""
    ship_k, reason_k = f"lc_ship_{fips}", f"lc_reason_{fips}"
    ss.events, msg, ok = engine.submit_confirm_delivery(
        ss.events, ss.clock, ss.get(ship_k), ss.get("role"), ss.get(reason_k), sc)
    set_form_msg(f"lc_{fips}", msg)
    if ok:
        ss[ship_k], ss[reason_k] = None, ""


def on_change_status(fips):
    """Change status (one form, one click). Fields are kept if refused."""
    t_k, c_k, r_k = f"cs_target_{fips}", f"cs_color_{fips}", f"cs_reason_{fips}"
    ss.events, msg, ok = engine.submit_change_status(
        ss.events, ss.clock, fips, ss.get(t_k), ss.get(c_k), ss.get("role"), ss.get(r_k), sc)
    set_form_msg(f"cs_{fips}", msg)
    if ok:
        ss[t_k], ss[c_k], ss[r_k] = None, None, ""


def slider_key():
    """The time slider's widget key.

    Phase 2C: a click sent while a tick's redraw is still on its way carries
    the slider's old value (live head - 1). With one fixed key, on_change took
    that for a drag and moved the cursor back an hour. Now the app draws a new
    slider (slider_gen + 1) whenever it moves the cursor itself (a tick, Play,
    Back to live, Reset, a snap back to the live head), and remembers the value
    each slider holds (slider_held). A lagging value arrives under the old key
    with the value that slider already held, so on_slider ignores it. A value
    the person dragged to is new for that slider, so it counts, even if the
    drag was made on a slider the app had just replaced.
    """
    return f"cursor_slider_{ss.slider_gen}"


def renew_slider():
    """Draw a new slider at the cursor (see slider_key)."""
    ss.slider_gen += 1
    ss.slider_held[ss.slider_gen] = ss.clock.cursor
    for old in [g for g in ss.slider_held if g < ss.slider_gen - 100]:
        del ss.slider_held[old]


def set_clock(new):
    """Every clock change except a slider drag goes through here."""
    moved = new.cursor != ss.clock.cursor
    ss.clock = new
    if moved:
        renew_slider()


def ds_keys(to_fips):
    """Widget keys for one county's Direct supplies form, so nothing typed for
    one county ever shows up in another county's form."""
    return {
        "resource": f"ds_resource_{to_fips}",
        "qty": f"ds_qty_{to_fips}",
        "reason": f"ds_reason_{to_fips}",
        "from": lambda resource: f"ds_from_{to_fips}_{resource}",
    }


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
    set_clock(engine.tick(c))
    ss.last_tick = time.monotonic()
    st.rerun()


playback_tick()
clock = ss.clock

# AI mode: each report is read when the live head reaches its hour. The clock
# waits while the AI reads (the next hour starts a full interval after reading).
if ai_mode():
    due = reports_due(clock.live_head)
    if due:
        hours = sorted({r["sim_hour"] for r in due})
        with st.spinner(f"AI is reading {len(due)} report(s) for hour "
                        f"{', '.join(map(str, hours))}. The clock waits until it's done."):
            read_reports(due)
        ss.last_tick = time.monotonic()

state = engine.state_at(clock.cursor, ss.events, sc, ss.ai_reads if ai_mode() else None)

# ---- Header ------------------------------------------------------------------
silent_now = sum(1 for s in state.values() if s["color"] == engine.PURPLE)
reports_so_far = int((tables["reports.csv"]["sim_hour"] <= clock.cursor).sum())
ui.header(
    "SKYZR",
    "North Carolina county operations · Hurricane Kestrel (fictional)",
    ("AI mode: AI reads each report into cited facts; code checks every quote and sets "
     "every color. Power and communications come from feeds. "
     if ai_mode() else
     "Answer-key mode: colors come from the scenario answer key, not from AI. ")
    + "SKYZR shows what is known and records what people decide. It never makes the decision.",
    [
        ("Counties", str(len(shapes))),
        ("In storm path", str(len(sc.hit))),
        ("Silent now", str(silent_now)),
        ("Reports so far", f"{reports_so_far} of {len(tables['reports.csv'])}"),
    ],
)

# ---- Mode switch (Phase 3) ------------------------------------------------------------
with st.container(border=True):
    st.radio("Mode", ["Answer-key mode", "AI mode"], key="mode", horizontal=True,
             help="Answer-key mode colors the map from the scenario answer key. AI mode "
                  "reads the reports with AI; code checks every quote.")
    if ai_mode():
        n_ok = sum(1 for r in ss.ai_reads.values() if r.status == "ok")
        n_bad = sum(1 for r in ss.ai_reads.values() if r.status != "ok")
        st.caption(f"AI mode is on. Reports read so far: {n_ok}"
                   + (f" · not processed: {n_bad}" if n_bad else "")
                   + f" · AI calls this tab: {ss.intake.calls_made} of {ai.MAX_CALLS_PER_SESSION}"
                   + f" · model {getattr(ss.intake.client, 'model', ai.MODEL_ID)}"
                   + (" (TEST DOUBLE)" if FAKE_AI else ""))
        if FAKE_AI:
            st.checkbox("Test only: make the AI fail", key="ai_fail_test",
                        on_change=on_ai_fail_test)
        if clock.live_head == engine.FIRST_HOUR:
            if st.button("Prepare AI reading", icon=":material/auto_awesome:",
                         help="Reads all 50 reports once, before playback, to fill the "
                              "server cache. Facts still take effect only at each report's hour."):
                all_reports = sorted(sc.reports.values(), key=lambda r: r["sim_hour"])
                pace = getattr(ss.intake.client, "prepare_seconds_per_call", 0)
                todo = sum(1 for r in all_reports if not ss.intake.cached(r))
                st.info(f"{todo} report(s) to read; {len(all_reports) - todo} already cached are "
                        "skipped. " + (f"Calls are paced one every {pace:g} s to stay under the "
                                       "free tier's per-minute limit: about "
                                       f"{max(1, round(todo * pace / 60))} minute(s). Keep this tab open."
                                       if pace and todo else ""))
                bar = st.progress(0.0, text="Reading reports…")
                prep = ai.prepare(
                    ss.intake, all_reports, pace=pace,
                    on_progress=lambda i, n: bar.progress(i / n, text=f"Read {i} of {n}"))
                summary = ai.prepare_summary(prep, len(all_reports))
                ok_all = prep.ok == len(all_reports)
                (st.success if ok_all else st.warning)(summary.split("\n")[0] + (
                    "" if ok_all else " Reports not read are tried again at their hour, or "
                    "press Prepare again to retry only those. ")
                    + "Facts take effect only when the clock reaches each report's hour.")
                if prep.reasons:
                    st.markdown("**Why calls failed (AI unavailable):**\n\n"
                                + "\n".join(f"- {ui.e(line)}" for line in summary.split("\n")[1:]))
                # Failed reads aren't kept, so each is tried again at its hour.
        st.download_button(
            "Export accepted facts (CSV)",
            data=engine.accepted_facts_csv(
                {k: v for k, v in ss.ai_reads.items()
                 if sc.reports[k]["sim_hour"] <= clock.live_head}),
            file_name="skyzr_accepted_facts.csv", mime="text/csv",
            icon=":material/download:",
            help="Every accepted fact so far: report_id plus the nine fact fields.")

# ---- Role picker (Proposal): a label, not a login ------------------------------
with st.container(horizontal=True, vertical_alignment="bottom"):
    st.selectbox(
        "Your role (a label stamped on every action, not a login)",
        engine.ROLES,
        index=None,
        placeholder="Choose your role",
        key="role",
        width=360,
        help="No password. The role controls nothing; it is recorded with each action.",
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

    key = slider_key()
    st.slider(
        "Time slider (simulated hour on screen)",
        min_value=engine.FIRST_HOUR,
        max_value=engine.LAST_HOUR,
        value=clock.cursor,
        key=key,
        on_change=on_slider,
        args=(key,),
        help="Review any hour already played. You can't drag past the live hour.",
    )
    if ss.slider_note:
        st.caption(ss.slider_note)

with st.container(horizontal=True, gap="small"):
    for i, label in enumerate(["Gaps tab", "AI report reading", "Ask SKYZR"]):
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
            line = s["status_word"] + (" · Manual" if s["manual_marker"] else "")
            if overlay != "Overall" and s["color"] not in (engine.GREY, engine.PURPLE):
                ll = s["lifelines"][overlay]
                line += (f"<br>{overlay}: {engine.LIFELINE_WORDS[overlay][ll]}" if ll
                         else f"<br>{overlay}: No report yet")
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


UNITS = {name: unit for name, unit, _ in engine.RESOURCES}


def direct_supplies_form(to_fips, state):
    """Design doc pp. 7-8. A person chooses everything; SKYZR suggests nothing:
    no preselected sender, no suggested quantity, senders in alphabetical order."""
    clock_now = ss.clock
    if not clock_now.at_live_head:
        st.info(
            f"Direct supplies is available only at the live hour ({clock_now.live_head}). "
            f"You're reviewing hour {clock_now.cursor}. Press Back to live to act."
        )
        return
    # Resource is outside the form, so changing it refreshes the sender list
    # with that resource's stock.
    k = ds_keys(to_fips)
    st.selectbox("Resource", engine.RESOURCE_NAMES, index=None,
                 placeholder="Choose a resource", key=k["resource"])
    resource = ss.get(k["resource"])

    # Everything else is one form: all fields are sent together on one click.
    with st.form(f"direct_supplies_{to_fips}", clear_on_submit=False, border=False):
        st.number_input("Quantity", min_value=1, step=1, value=None,
                        placeholder="Type a quantity", key=k["qty"])
        if resource:
            options = engine.sender_options(state, resource, to_fips)  # alphabetical only
            labels = {f: engine.sender_label(state, f, resource) for f, _, _ in options}
            st.selectbox("Sending county (alphabetical)", [f for f, _, _ in options],
                         index=None, format_func=labels.get,
                         placeholder="Choose the sending county", key=k["from"](resource))
        else:
            st.caption("Sending county: choose a resource above to see each county's stock.")
        st.text_area("Reason (required)", key=k["reason"], height=68,
                     placeholder="Why this move? It is recorded in the action log.")
        st.form_submit_button("Confirm", type="primary",
                              on_click=on_direct_supplies, args=(to_fips,))
    st.caption("Stock leaves the sender at once. When a report confirms delivery, this "
               "county's on-hand stock rises and its need drops. Its color doesn't change "
               "because of a delivery.")
    # Show the last result only on the county and live hour it belongs to.
    if ss.ds_message and ss.get("ds_message_for") == (to_fips, clock_now.live_head):
        (st.error if ss.ds_message.startswith("Not sent") else st.success)(ss.ds_message)


def source_cell(src, silent):
    """The "Source report and quote" cell (AI mode)."""
    if not src:
        return '<span class="sk-muted">No report yet</span>'
    muted = ' class="sk-muted"' if silent else ""
    if src.get("kind") == "report":
        both = src.get("both")
        items = both if both else [src]
        parts = [f"{ui.e(v['source'])} · hour {v['hour']} · verified: {ui.e(v['verified'])}"
                 f"<br>“{ui.e(v['quote'])}”" for v in items]
        note = f"<br><small>{ui.e(src['note'])}</small>" if src.get("note") else ""
        label = "<b>Both kept:</b><br>" if both else ""
        return f"<span{muted}>{label}{'<br>'.join(parts)}{note}</span>"
    return f"<span{muted}>{ui.e(src.get('note', ''))}</span>"


def need_cell(r):
    if r["need"] is None:
        return ('<span class="sk-muted">' + ui.e(engine.NEED_UNKNOWN) + "</span>"
                if "need_since" in r else "None")
    req = r.get("request") or {}
    if req.get("range"):
        lo, hi = req["range"]
        return f"{lo} to {hi}" + (" (contradiction)" if req.get("contradiction") else " (both kept)")
    return str(r["need"])


def on_resolve(fips, i, c):
    k = f"rs_{fips}_{i}"
    choice = ss.get(f"{k}_choice")
    detail = ""
    if choice:
        if c.get("kind") == "ai":
            pick = {"a": c["a"], "b": c["b"]}.get(choice)
            detail = (f"kept {pick['value']} (hour {pick['hour']}, {pick['source']})" if pick
                      else f"kept both ({c['a']['value']} and {c['b']['value']})")
        else:
            detail = {"manual": "kept the manual value", "report": "kept the report",
                      "both": "kept both"}[choice]
    key = c.get("key", c["target"])
    ss.events, msg, ok = engine.submit_resolve(
        ss.events, ss.clock, fips, c["target"], c.get("kind", "manual"), key, choice,
        ss.get("role"), ss.get(f"{k}_reason"), sc, detail)
    set_form_msg(k, msg)
    if ok:
        ss[f"{k}_choice"], ss[f"{k}_reason"] = None, ""


def resolve_form(fips, i, c, options):
    """Resolve: keep one value or both. Role and reason required; live hour only.
    Same one-click form pattern as Direct supplies."""
    k = f"rs_{fips}_{i}"
    if not ss.clock.at_live_head:
        not_live_note("Resolve")
        return
    with st.form(k, clear_on_submit=False, border=False):
        st.radio("Resolve: which value to keep?", list(options), key=f"{k}_choice",
                 index=None, format_func=lambda o: options[o])
        st.text_input("Reason (required)", key=f"{k}_reason",
                      placeholder="Why this value? Recorded in the log.")
        st.form_submit_button("Resolve", type="primary", on_click=on_resolve,
                              args=(fips, i, c))
    show_form_msg(k)


def not_live_note(action):
    c = ss.clock
    st.info(f"{action} is available only at the live hour ({c.live_head}). You're reviewing "
            f"hour {c.cursor}. Press Back to live to act.")


def log_confirmation_form(fips, state):
    """Log confirmation: for shipments waiting for a hand confirmation."""
    waiting = engine.eligible_for_hand_confirmation(state, fips)
    if not waiting:
        ui.note("No shipment to this county is waiting for a hand confirmation.")
        show_form_msg(f"lc_{fips}")  # e.g. the confirmation just logged
        return
    if not ss.clock.at_live_head:
        not_live_note("Log confirmation")
        return
    labels = {sh["seq"]: f"{engine.quantity_phrase(sh['quantity'], sh['resource'])} from "
                         f"{shapes[sh['from']]}, sent hour {sh['dispatched']} (Unconfirmed)"
              for sh in waiting}
    with st.form(f"log_confirmation_{fips}", clear_on_submit=False, border=False):
        st.selectbox("Shipment", list(labels), index=None, format_func=labels.get,
                     placeholder="Choose the shipment", key=f"lc_ship_{fips}")
        st.text_area("Reason (required)", key=f"lc_reason_{fips}", height=68,
                     placeholder="How was the delivery confirmed?")
        st.form_submit_button("Log confirmation", type="primary",
                              on_click=on_confirm_delivery, args=(fips,))
    show_form_msg(f"lc_{fips}")


def change_status_form(fips, s):
    """Change status: Overall or one lifeline, by hand, until the next report on it."""
    if not ss.clock.at_live_head:
        not_live_note("Change status")
        return
    if s["silent"]:
        ui.note(f"{s['county']} is silent; its status can't be set until contact returns.")
        return
    with st.form(f"change_status_{fips}", clear_on_submit=False, border=False):
        st.selectbox("Overall or lifeline", engine.STATUS_TARGETS, index=None,
                     placeholder="Choose Overall or a lifeline", key=f"cs_target_{fips}")
        st.selectbox("New color", engine.MANUAL_COLORS, index=None,
                     format_func=lambda c: c.capitalize(), placeholder="Choose the new color",
                     key=f"cs_color_{fips}")
        st.text_area("Reason (required)", key=f"cs_reason_{fips}", height=68,
                     placeholder="Why change it? It is recorded in the action log.")
        st.form_submit_button("Change status", type="primary",
                              on_click=on_change_status, args=(fips,))
    st.caption("The county shows a Manual marker. The manual color holds until the next "
               "report on that lifeline: if it agrees, Manual clears; if not, both are shown "
               "as a contradiction and neither is overwritten.")
    show_form_msg(f"cs_{fips}")


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
                + (ui.chip("Manual") + "&nbsp;" if s["manual_marker"] else "")
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
                srcs = s.get("lifeline_sources") or {}
                for ll in engine.LIFELINES:
                    c = s["lifelines"][ll]
                    if c is None:  # AI mode: nothing accepted for this lifeline yet
                        note = (srcs.get(ll) or {}).get("note", "No report yet")
                        body.append([ui.e(ll), '<span class="sk-muted">No report yet</span>',
                                     f'<span class="sk-muted">{ui.e(note)}</span>'])
                        continue
                    if s["silent"]:
                        # Muted: grey text, no colored chip. A silent county never
                        # shows red, yellow or green.
                        cell = (f'<span class="sk-muted">Last known (hour '
                                f'{s["lifelines_as_of"]}): {ui.e(c.capitalize())}<br>'
                                f'<small>{ui.e(engine.LIFELINE_WORDS[ll][c])}</small></span>')
                    else:
                        m = s["manual"].get(ll)
                        detail = engine.LIFELINE_WORDS[ll][c]
                        if m and m["outcome"] != "cleared":
                            detail = f"Manual (hour {m['hour']}, {m['role']})"
                        cell = ui.status_cell(c, c.capitalize(), detail)
                    body.append([ui.e(ll), cell, source_cell(srcs.get(ll), s["silent"])
                                 if s.get("mode") == "ai" else
                                 '<span class="sk-muted">Answer key (no report text in this mode)</span>'])
                ui.table(["Lifeline", "Color", "Source report and quote"], body)
                om = s["manual"].get("Overall")
                if om and om["outcome"] != "cleared" and not s["silent"]:
                    ui.note(f"Overall set by hand to {om['color'].capitalize()} at hour "
                            f"{om['hour']} ({om['role']}).")

            # 3. Resources
            ui.section("Resources" if s["hit"] else "Stock available to send")
            body = []
            for name, unit, _ in engine.RESOURCES:
                r = s["resources"][name]
                if s["hit"]:
                    body.append([f"{ui.e(name)}<br><small class='sk-muted'>{ui.e(unit)}</small>",
                                 need_cell(r), str(r["on_hand"]), str(r["in_transit"])])
                else:
                    body.append([f"{ui.e(name)}<br><small class='sk-muted'>{ui.e(unit)}</small>",
                                 str(r["on_hand"])])
            if s["hit"]:
                ui.table(["Resource", "Need", "On hand", "In transit"], body, num_cols=(1, 2, 3),
                         caption=(("Known need: the latest accepted resource request, minus "
                                   "deliveries confirmed after it (never below 0). "
                                   "No request means need unknown, never 0."
                                   if s.get("mode") == "ai" else
                                   "Need is true need from the answer key"
                                   + (f" as last known at hour {s['lifelines_as_of']}"
                                      if s["silent"] else "")
                                   + ", minus confirmed deliveries (never below 0).")))
            else:
                ui.table(["Resource", "On hand"], body, num_cols=(1,))

            # 4. Contradictions
            ui.section("Contradictions")
            for i, c in enumerate(s["contradictions"]):
                def side(v):
                    if not v.get("color"):
                        return ui.e(str(v.get("value", "")))
                    if s["silent"]:
                        return f'<span class="sk-muted">{ui.e(v["color"].capitalize())}</span>'
                    return ui.status_cell(v["color"], v["color"].capitalize(), str(v.get("value", "")))
                if c.get("kind") == "ai":
                    a, b = c["a"], c["b"]
                    ui.table(
                        [c["target"], "Hour", "Source", "Verified", "Quote"],
                        [[side(v), f"Hour {v['hour']}", ui.e(v["source"]), ui.e(v["verified"]),
                          f"“{ui.e(v['quote'])}”"] for v in (a, b)],
                        caption=f"{c['target']}: two reports disagree. Neither is overwritten; "
                                "the lifeline shows Contradiction until someone resolves it.",
                    )
                    options = {"a": f"Keep {a['value']} (hour {a['hour']}, {a['source']})",
                               "b": f"Keep {b['value']} (hour {b['hour']}, {b['source']})",
                               "both": f"Keep both ({a['value']} and {b['value']})"}
                else:
                    ui.table(
                        [c["target"], "Hour", "Source"],
                        [[side(c["manual"]), f"Hour {c['manual']['hour']}", ui.e(c["manual"]["source"])],
                         [side(c["report"]), f"Hour {c['report']['hour']}", ui.e(c["report"]["source"])]],
                        caption=f"{c['target']}: the manual value and the next report disagree. "
                                "Neither is overwritten.",
                    )
                    options = {"manual": f"Keep the manual value ({c['manual']['color'].capitalize()})",
                               "report": f"Keep the report ({c['report']['color'].capitalize()})",
                               "both": "Keep both (show the more urgent)"}
                resolve_form(fips, i, c, options)
            if not s["contradictions"]:
                ui.note("No open contradictions.")
                # A resolution removes its form; still show its result at the hour it happened.
                for k in [k for k in ss.get("form_msgs", {}) if k.startswith(f"rs_{fips}_")]:
                    show_form_msg(k)

            # 5. Reports about this county, as the AI read them (AI mode)
            if s.get("mode") == "ai" and s["hit"]:
                ui.section("Reports read by AI")
                reads = [(rid, ss.ai_reads[rid]) for rid, r in sorted(
                    sc.reports.items(), key=lambda kv: kv[1]["sim_hour"])
                    if r["fips"] == fips and r["sim_hour"] <= clock.cursor and rid in ss.ai_reads]
                if not reads:
                    ui.note("No report about this county has been read yet.")
                for rid, res in reads:
                    rep_row = sc.reports[rid]
                    head = (f"Hour {rep_row['sim_hour']} · {rep_row['source']} · "
                            f"verified: {rep_row['verified']}")
                    with st.expander(head + ("" if res.status == "ok" else f" · {res.message}")):
                        st.markdown(f"> {rep_row['text']}")
                        if res.status != "ok":
                            st.warning(f"{res.message}. This report changes nothing.")
                            if res.detail:
                                st.caption(f"Reason: {ai.scrub(res.detail)}")
                        for f in res.accepted:
                            st.markdown(f"- **Accepted:** {f.lifeline_or_resource} · {f.metric} · "
                                        f"{f.value} ({f.status_word}) · “{f.quote}”")
                        for raw, why in res.rejected:
                            st.markdown(f"- **Rejected** ({why}): `{raw}`")
                        if res.status == "ok" and not res.accepted and not res.rejected:
                            st.caption("The AI found no fact it could cite in this report.")

            # Shipments to this county, with their delivery status.
            if s["incoming"]:
                ui.section("Shipments to this county")
                ui.table(
                    ["Shipment", "Sent", "Status"],
                    [[ui.e(f"{engine.quantity_phrase(sh['quantity'], sh['resource'])} from "
                           f"{shapes[sh['from']]}"),
                      f"Hour {sh['dispatched']}", ui.e(sh["status"])] for sh in s["incoming"]],
                )

            # 6. Buttons: Direct supplies, Change status, Log confirmation (hit counties)
            if s["hit"]:
                ui.section("Direct supplies")
                direct_supplies_form(fips, state)
                ui.section("Change status")
                change_status_form(fips, s)
                ui.section("Log confirmation")
                log_confirmation_form(fips, state)

# ---- Action log: read-only, newest first, with the only CSV export ---------------
with st.container(border=True):
    ui.eyebrow(f"Action log · up to hour {clock.cursor}")
    rows = engine.log_rows(ss.events, clock.cursor, sc)
    if rows:
        ui.table(list(engine.LOG_COLUMNS),
                 [[ui.e(str(r[c])) for c in engine.LOG_COLUMNS] for r in rows])
    else:
        ui.note("No actions yet. Every action appears here with its role, simulated time "
                "and reason. No one can edit or delete an entry.")
    st.download_button(
        "Export action log (CSV)",
        data=engine.log_csv(ss.events, clock.live_head, sc),
        file_name="skyzr_action_log.csv",
        mime="text/csv",
        icon=":material/download:",
        help="The CSV is the only lasting copy of this tab's run.",
    )

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
