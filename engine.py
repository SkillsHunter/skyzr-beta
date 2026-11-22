"""SKYZR engine: the rules as pure functions. No Streamlit import, ever.

Data loading, the startup checks (plan v2 §3 item 7), and from Phase 1 the
answer-key rules. `state_at(cursor, events)` is the only thing that computes
state. The playback clock (live head and review cursor) is here too, as pure
functions, so it can be tested without a browser.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent / "data"

# Scenario CSVs that carry a county. answer_key.csv is loaded here for the
# startup checks and answer-key mode only; ai.py must never read it.
SCENARIO_CSVS = ("answer_key.csv", "feeds.csv", "reports.csv", "stock.csv")

EXPECTED_COUNTIES = 100
FIPS_LEN = 5
NC_STATE_FIPS = "37"


def load_geojson(data_dir: Path = DATA_DIR) -> dict:
    with open(Path(data_dir) / "nc_counties.geojson", encoding="utf-8") as f:
        return json.load(f)


def load_csv(name: str, data_dir: Path = DATA_DIR) -> pd.DataFrame:
    """Read a scenario CSV with FIPS kept as text so leading digits survive."""
    return pd.read_csv(Path(data_dir) / name, dtype={"fips": str})


def load_scenario_csvs(data_dir: Path = DATA_DIR) -> dict[str, pd.DataFrame]:
    return {name: load_csv(name, data_dir) for name in SCENARIO_CSVS}


def county_shapes(geojson: dict) -> dict[str, str]:
    """FIPS -> county name, from the GeoJSON feature ids and NAME property."""
    return {
        feature.get("id"): feature.get("properties", {}).get("NAME")
        for feature in geojson.get("features", [])
    }


def _is_fips_text(value) -> bool:
    return (
        isinstance(value, str)
        and len(value) == FIPS_LEN
        and value.isdigit()
        and value.startswith(NC_STATE_FIPS)
    )


def startup_checks(geojson: dict, tables: dict[str, pd.DataFrame]) -> list[str]:
    """Return a list of problems. An empty list means every check passed.

    Checks (plan v2 §3 item 7):
    1. The map has exactly 100 features.
    2. Those features carry 100 unique FIPS codes, each a 5-character text string.
    3. Every county in every scenario CSV matches a shape (FIPS and name).
    4. FIPS codes in the CSVs are text, 5 characters, not numbers.
    """
    problems: list[str] = []
    features = geojson.get("features", [])

    # 1. 100 features
    if len(features) != EXPECTED_COUNTIES:
        problems.append(
            f"Map has {len(features)} features; expected {EXPECTED_COUNTIES}."
        )

    # 2. 100 unique FIPS codes, as text
    ids = [feature.get("id") for feature in features]
    bad_ids = [i for i in ids if not _is_fips_text(i)]
    if bad_ids:
        problems.append(
            f"Map has {len(bad_ids)} feature ids that are not 5-character NC FIPS "
            f"text, e.g. {bad_ids[:3]!r}."
        )
    if len(set(ids)) != EXPECTED_COUNTIES:
        problems.append(
            f"Map has {len(set(ids))} unique FIPS codes; expected {EXPECTED_COUNTIES}."
        )

    shapes = county_shapes(geojson)

    for name, df in tables.items():
        # 4. FIPS read as text
        if "fips" not in df.columns:
            problems.append(f"{name} has no 'fips' column.")
            continue
        not_text = [v for v in df["fips"].tolist() if not _is_fips_text(v)]
        if not_text:
            problems.append(
                f"{name}: {len(not_text)} FIPS values are not 5-character text, "
                f"e.g. {not_text[:3]!r}."
            )
            continue

        # 3. Every county matches a shape, by FIPS and by name
        pairs = df[["fips", "county"]].drop_duplicates()
        for fips, county in pairs.itertuples(index=False):
            if fips not in shapes:
                problems.append(f"{name}: FIPS {fips} ({county}) has no map shape.")
            elif shapes[fips] != county:
                problems.append(
                    f"{name}: FIPS {fips} is '{county}' in the CSV but "
                    f"'{shapes[fips]}' on the map."
                )

    return problems


# ===========================================================================
# Phase 1: answer-key mode
# ===========================================================================

FIRST_HOUR = 0
LAST_HOUR = 72
SILENCE_HOURS = 12  # Proposal: no contact for 12 simulated hours -> purple

LIFELINES = ("Power", "Communications", "Roads", "Water", "Health and Medical")
_LIFELINE_COLUMN = {
    "Power": "power",
    "Communications": "communications",
    "Roads": "roads",
    "Water": "water",
    "Health and Medical": "health",
}

# (display name, unit, CSV suffix) for the 9 resources.
RESOURCES = (
    ("Water", "tankers", "water_tankers"),
    ("Generators", "units", "generators"),
    ("Utility crews", "crews", "utility_crews"),
    ("Search-and-rescue teams", "teams", "sar_teams"),
    ("Food", "pallets of meals", "food_pallets"),
    ("Shelter", "cots and shelter kits", "shelter_cots_kits"),
    ("Medical teams", "teams", "medical_teams"),
    ("Hygiene items", "kits", "hygiene_kits"),
    ("Sanitation", "portable toilet and handwashing units", "sanitation_units"),
)

RED, YELLOW, GREEN, PURPLE, GREY = "red", "yellow", "green", "purple", "grey"
_URGENCY = {GREEN: 0, YELLOW: 1, RED: 2}

# Words shown with every color, so color never carries meaning alone.
STATUS_WORD = {
    RED: "Urgent need",
    YELLOW: "Moderate need",
    GREEN: "Needs met or minimal",
    PURPLE: "Silent: no contact",
    GREY: "Not hit",
}
# What each lifeline color means (design doc thresholds).
LIFELINE_WORDS = {
    "Power": {GREEN: "Under 10% of customers out", YELLOW: "10 to 49% of customers out",
              RED: "50% or more of customers out"},
    "Communications": {GREEN: "Under 10% of cell sites out", YELLOW: "10 to 39% of cell sites out",
                       RED: "40% or more of cell sites out"},
    "Roads": {GREEN: "Open", YELLOW: "Some primary routes closed",
              RED: "No open route to the county seat"},
    "Water": {GREEN: "Normal", YELLOW: "Boil-water notice", RED: "A system out of service"},
    "Health and Medical": {GREEN: "Normal", YELLOW: "A hospital on generator or diverting",
                           RED: "A hospital closed or evacuating"},
}
LEGEND = (
    (RED, "Red", "Urgent need"),
    (YELLOW, "Yellow", "Moderate need"),
    (GREEN, "Green", "Hit, needs met or minimal"),
    (PURPLE, "Purple", "In the storm, no reports"),
    (GREY, "Grey", "Not hit; may hold stock"),
)


def most_urgent(colors) -> str:
    """The overall color: the most urgent of the given lifeline colors."""
    return max(colors, key=lambda c: _URGENCY[c])


@dataclass(frozen=True)
class Scenario:
    """Everything state_at needs, indexed once. Built from the CSVs."""

    names: dict  # fips -> county name, all 100
    hit: frozenset  # fips of the 29 counties in the storm path
    lifelines: dict  # (fips, hour) -> {lifeline: color}
    true_need: dict  # (fips, hour) -> {resource: int}
    stock: dict  # fips -> {resource: int} at hour 0
    contacts: dict  # fips -> sorted contact hours (reports + feeds, Fix 1)
    report_hours: dict  # fips -> sorted report hours
    feeds: dict = field(default_factory=dict)  # fips -> [(hour, power % out, cell % out)]
    reports: dict = field(default_factory=dict)  # report_id -> report row (dict)


def build_scenario(geojson: dict, tables: dict) -> Scenario:
    ak = tables["answer_key.csv"]
    feeds = tables["feeds.csv"]
    reports = tables["reports.csv"]
    stock = tables["stock.csv"]

    hit = frozenset(stock.loc[stock["hit_or_grey"] == "hit", "fips"])

    lifelines, true_need = {}, {}
    for row in ak.to_dict("records"):
        key = (row["fips"], int(row["hour"]))
        lifelines[key] = {ll: row[col] for ll, col in _LIFELINE_COLUMN.items()}
        true_need[key] = {
            name: int(row[f"true_need_{suffix}"]) for name, _, suffix in RESOURCES
        }

    stock_map = {
        row["fips"]: {name: int(row[f"on_hand_{suffix}"]) for name, _, suffix in RESOURCES}
        for row in stock.to_dict("records")
    }

    report_hours = {f: [] for f in hit}
    for f, h in zip(reports["fips"], reports["sim_hour"]):
        report_hours[f].append(int(h))
    contacts = {f: set(hs) for f, hs in report_hours.items()}
    for f, h in zip(feeds["fips"], feeds["hour"]):
        contacts[f].add(int(h))
    feed_map = {f: [] for f in hit}
    for row in feeds.to_dict("records"):
        feed_map[row["fips"]].append(
            (int(row["hour"]), float(row["power_pct_out"]), float(row["cell_pct_out"])))
    report_map = {}
    for row in reports.to_dict("records"):
        row = dict(row)
        row["sim_hour"] = int(row["sim_hour"])
        report_map[str(row["report_id"])] = row

    return Scenario(
        names=county_shapes(geojson),
        hit=hit,
        lifelines=lifelines,
        true_need=true_need,
        stock=stock_map,
        contacts={f: sorted(hs) for f, hs in contacts.items()},
        report_hours={f: sorted(hs) for f, hs in report_hours.items()},
        feeds={f: sorted(v) for f, v in feed_map.items()},
        reports=report_map,
    )


@lru_cache(maxsize=1)
def default_scenario() -> Scenario:
    return build_scenario(load_geojson(), load_scenario_csvs())


def _last_at_or_before(hours: list, cursor: int):
    last = None
    for h in hours:
        if h > cursor:
            break
        last = h
    return last


def state_at(cursor: int, events=(), scenario: Scenario | None = None,
             ai_reads: dict | None = None) -> dict:
    """Every county's state at simulated hour `cursor`, from the data and events.

    This is the only function that computes state. `events` is the action log
    (a tuple of DirectSupplies entries); it is replayed up to `cursor`.

    Returns {fips: dict} with: county, hit, color, status_word, lifelines,
    lifelines_as_of, hours_since_contact, last_contact_hour, last_report_hour,
    resources {name: {need, on_hand, in_transit}}, incoming (shipments).

    ai_reads=None is answer-key mode. In AI mode it is {report_id: ReadResult}
    for the reports read so far: Roads, Water and Health and Medical come from
    accepted facts, Power and Communications from feeds.csv, and known need
    from resource requests (Fix 4). The silence rule is the same in both modes.
    """
    sc = scenario or default_scenario()
    cursor = int(cursor)
    if not FIRST_HOUR <= cursor <= LAST_HOUR:
        raise ValueError(f"cursor {cursor} is outside hours {FIRST_HOUR} to {LAST_HOUR}")

    out = {}
    for fips, name in sc.names.items():
        on_hand = dict(sc.stock[fips])
        if fips not in sc.hit:
            out[fips] = {
                "county": name,
                "hit": False,
                "color": GREY,
                "status_word": STATUS_WORD[GREY],
                "lifelines": None,
                "lifelines_as_of": None,
                "hours_since_contact": None,
                "last_contact_hour": None,
                "last_report_hour": None,
                "resources": {
                    r: {"need": None, "on_hand": on_hand[r], "in_transit": 0}
                    for r, _, _ in RESOURCES
                },
                "incoming": [],
                "silent": False,
                "manual": {},
                "manual_marker": False,
                "contradictions": [],
            }
            continue

        last_contact = _last_at_or_before(sc.contacts[fips], cursor)
        since = None if last_contact is None else cursor - last_contact
        silent = since is None or since >= SILENCE_HOURS

        # While silent, nothing new arrives: show what was known at last contact.
        as_of = cursor if not silent else last_contact
        ai_view = None
        if ai_reads is not None:
            ai_view = ai_county_view(sc, fips, as_of, ai_reads, events, cursor)
            lifelines = ai_view["lifelines"] if as_of is not None else None
            need = ai_view["need"]
        else:
            lifelines = sc.lifelines[(fips, as_of)] if as_of is not None else None
            need = sc.true_need[(fips, as_of)] if as_of is not None else {}

        known = [c for c in (lifelines or {}).values() if c]
        color = PURPLE if silent else (most_urgent(known) if known else YELLOW)
        out[fips] = {
            "county": name,
            "hit": True,
            "color": color,
            "status_word": STATUS_WORD[color],
            "lifelines": dict(lifelines) if lifelines else None,
            "lifelines_as_of": as_of,
            "hours_since_contact": since,
            "last_contact_hour": last_contact,
            "last_report_hour": _last_at_or_before(sc.report_hours[fips], cursor),
            "resources": {
                r: {"need": need.get(r), "on_hand": on_hand[r], "in_transit": 0}
                for r, _, _ in RESOURCES
            },
            "incoming": [],
            "silent": silent,
            "manual": {},
            "manual_marker": False,
            "contradictions": [],
        }
        if ai_view is not None:
            s = out[fips]
            s["mode"] = "ai"
            s["lifeline_sources"] = ai_view["sources"]
            s["contradictions"] = list(ai_view["contradictions"])
            s["no_status_yet"] = not known
            for r in s["resources"]:
                s["resources"][r]["need_since"] = ai_view["need_since"].get(r)
                s["resources"][r]["request"] = ai_view["requests"].get(r)

    # Replay the action log up to the cursor: shipments, confirmations and
    # manual status changes. A confirmation moves stock and lowers need; it
    # never changes a lifeline or county color.
    apply_events(out, cursor, events, sc)
    return out


def silent_at(sc: Scenario, fips: str, hour: int) -> bool:
    """True if a hit county has had no contact for SILENCE_HOURS or more."""
    if fips not in sc.hit:
        return False
    last = _last_at_or_before(sc.contacts[fips], hour)
    return last is None or hour - last >= SILENCE_HOURS


def overlay_color(county_state: dict, overlay: str) -> str:
    """Map color for one county under an overlay. Grey and purple never change."""
    color = county_state["color"]
    if overlay == "Overall" or color in (GREY, PURPLE):
        return color
    # AI mode: a lifeline with no accepted report yet has no color of its own.
    return county_state["lifelines"][overlay] or GREY


# ---- Clock: live head and review cursor (plan v2 Fix 2) --------------------

@dataclass(frozen=True)
class Clock:
    live_head: int = FIRST_HOUR  # latest hour played; only play advances it
    cursor: int = FIRST_HOUR  # hour on screen; never past the live head
    playing: bool = False

    @property
    def at_live_head(self) -> bool:
        return self.cursor == self.live_head

    @property
    def finished(self) -> bool:
        return self.live_head >= LAST_HOUR


def play(clock: Clock) -> Clock:
    """Play snaps the cursor back to the live head."""
    if clock.finished:
        return replace(clock, cursor=clock.live_head, playing=False)
    return replace(clock, cursor=clock.live_head, playing=True)


def pause(clock: Clock) -> Clock:
    return replace(clock, playing=False)


def tick(clock: Clock) -> Clock:
    """One simulated hour of playback. A cursor at the live head moves with it;
    a cursor held back for review stays where it is. Stops at the last hour."""
    if not clock.playing or clock.finished:
        return replace(clock, playing=False)
    head = clock.live_head + 1
    cursor = head if clock.at_live_head else clock.cursor
    return Clock(live_head=head, cursor=cursor, playing=head < LAST_HOUR)


def move_cursor(clock: Clock, hour: int) -> Clock:
    """The slider moves only the cursor, and never past the live head."""
    return replace(clock, cursor=max(FIRST_HOUR, min(int(hour), clock.live_head)))


def reset(_clock: Clock | None = None) -> Clock:
    return Clock()


# ===========================================================================
# Phase 2A: Direct supplies and the action log (engine only)
# ===========================================================================

TRANSIT_HOURS = 6  # Proposal: transit time
TRANSIT_HOURS_ROADS_RED = 12  # ... or 12 if the receiver's Roads lifeline is red
RESOURCE_NAMES = tuple(name for name, _, _ in RESOURCES)


class ActionRefused(ValueError):
    """An action the rules don't allow. Nothing is logged and nothing changes."""


@dataclass(frozen=True)
class DirectSupplies:
    """One logged Direct supplies action. Frozen: no entry can be edited."""

    seq: int  # position in the log, from 1
    hour: int  # simulated hour of dispatch (the live head)
    role: str
    from_fips: str
    to_fips: str
    resource: str
    quantity: int
    reason: str
    transit_hours: int  # fixed at dispatch: 6, or 12 if receiver Roads was red

    @property
    def arrives(self) -> int:
        return self.hour + self.transit_hours

    action = "Directed supplies"


def direct_supplies(
    events: tuple,
    clock: Clock,
    from_fips: str,
    to_fips: str,
    resource: str,
    quantity: int,
    role: str,
    reason: str,
    scenario: Scenario | None = None,
) -> tuple:
    """Return a new log with one Direct supplies entry appended, or raise
    ActionRefused. The log is a tuple, so the old one is never changed."""
    sc = scenario or default_scenario()
    events = tuple(events)

    if not clock.at_live_head:
        raise ActionRefused(
            f"Actions are allowed only at the live hour ({clock.live_head}); "
            f"the view is at hour {clock.cursor}."
        )
    if not isinstance(role, str) or not role.strip():
        raise ActionRefused("A role is required.")
    if not isinstance(reason, str) or not reason.strip():
        raise ActionRefused("A reason is required.")
    if resource not in RESOURCE_NAMES:
        raise ActionRefused(f"Unknown resource: {resource!r}.")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise ActionRefused("Quantity must be a whole number greater than zero.")
    if from_fips not in sc.names or to_fips not in sc.names:
        raise ActionRefused("Unknown county.")
    if from_fips == to_fips:
        raise ActionRefused("A county can't send supplies to itself.")
    if to_fips not in sc.hit:
        raise ActionRefused("Supplies are directed to counties in the storm path.")

    now = state_at(clock.live_head, events, sc)
    on_hand = now[from_fips]["resources"][resource]["on_hand"]
    if quantity > on_hand:
        raise ActionRefused(
            f"{now[from_fips]['county']} has {on_hand} {resource} on hand; "
            f"can't send {quantity}."
        )

    receiver_roads = (now[to_fips]["lifelines"] or {}).get("Roads")
    transit = TRANSIT_HOURS_ROADS_RED if receiver_roads == RED else TRANSIT_HOURS

    entry = DirectSupplies(
        seq=len(events) + 1,
        hour=clock.live_head,
        role=role.strip(),
        from_fips=from_fips,
        to_fips=to_fips,
        resource=resource,
        quantity=quantity,
        reason=reason.strip(),
        transit_hours=transit,
    )
    return events + (entry,)


@dataclass(frozen=True)
class ConfirmDelivery:
    """A delivery confirmed by hand (Log confirmation). Frozen like every entry."""

    seq: int
    hour: int
    role: str
    shipment_seq: int  # the DirectSupplies entry it confirms
    reason: str

    action = "Confirmed delivery"


@dataclass(frozen=True)
class ChangeStatus:
    """A manual status (Change status). Holds until the next report on it."""

    seq: int
    hour: int
    role: str
    fips: str
    target: str  # "Overall" or one lifeline
    color: str  # red, yellow or green
    reason: str

    action = "Changed status"


STATUS_TARGETS = ("Overall",) + LIFELINES
MANUAL_COLORS = (RED, YELLOW, GREEN)


@dataclass(frozen=True)
class ResolveContradiction:
    """A person resolved a contradiction (keep one value, or keep both)."""

    seq: int
    hour: int
    role: str
    fips: str
    target: str  # lifeline, resource or "Overall"
    kind: str  # "manual" (manual change vs report) or "ai" (two reports)
    key: str  # which pair: contradiction_key(...) for "ai"; the target for "manual"
    choice: str  # "manual" / "report" / "both" (manual); "a" / "b" / "both" (ai)
    reason: str
    detail: str = ""

    action = "Resolved contradiction"


def is_action(entry, kind) -> bool:
    """Match a log entry to its kind by its action name, not its class object,
    so entries made before a code reload (a session keeps its log) still count."""
    return getattr(entry, "action", None) == kind.action


def shipment_outcome(ev: DirectSupplies, cursor: int, events, sc: Scenario):
    """(status, delivered_hour or None, by_hand) for one shipment at `cursor`.

    Answer-key mode: at the arrival hour a fictional confirmation arrives and
    is accepted, unless the receiver is silent then. A silent receiver's
    shipment is "Unconfirmed" until someone logs a confirmation by hand."""
    if cursor < ev.arrives:
        return "In transit", None, False
    if not silent_at(sc, ev.to_fips, ev.arrives):
        return f"Delivered (hour {ev.arrives})", ev.arrives, False
    hand = next((c for c in events if is_action(c, ConfirmDelivery)
                 and c.shipment_seq == ev.seq and c.hour <= cursor), None)
    if hand:
        return f"Delivered (hour {hand.hour}, by hand)", hand.hour, True
    return "Unconfirmed", None, False


def _ak_value(sc: Scenario, fips: str, target: str, hour: int) -> str:
    lifelines = sc.lifelines[(fips, hour)]
    return most_urgent(lifelines.values()) if target == "Overall" else lifelines[target]


def next_report_on(sc: Scenario, fips: str, target: str, after: int, cursor: int):
    """The next "report" on a lifeline (or Overall) after hour `after`, up to
    `cursor`: reports.csv names no lifeline, so it is the next hour the answer
    key's value changes, counting only hours the county is in contact.
    Returns (hour, value) or None."""
    prev = _ak_value(sc, fips, target, after)
    for h in range(after + 1, cursor + 1):
        if silent_at(sc, fips, h):
            continue
        v = _ak_value(sc, fips, target, h)
        if v != prev:
            return h, v
    return None


def manual_outcome(cs: ChangeStatus, cursor: int, sc: Scenario, ai_sources=None):
    """("holding" | "cleared" | "contradiction", (hour, value) or None).
    In AI mode (ai_sources given) the next report is the first accepted fact on
    that lifeline after the manual change; Overall is not matched in AI mode."""
    if ai_sources is not None:
        src = ai_sources.get(cs.target) or {}
        if src.get("kind") == "report" and src["hour"] > cs.hour and src.get("color"):
            nxt = (src["hour"], src["color"])
        else:
            nxt = None
    else:
        nxt = next_report_on(sc, cs.fips, cs.target, cs.hour, cursor)
    if nxt is None:
        return "holding", None
    return ("cleared" if nxt[1] == cs.color else "contradiction"), nxt


def apply_events(out: dict, cursor: int, events, sc: Scenario) -> None:
    """Replay the log up to `cursor` onto state_at's output (in place)."""
    events = tuple(events)
    delivered = {}  # (fips, resource) -> [(hour confirmed, quantity)] up to cursor
    latest_manual = {}  # (fips, target) -> latest ChangeStatus
    resolved_manual = {}  # (fips, target) -> ResolveContradiction for it
    for ev in events:
        if ev.hour > cursor:
            continue
        if is_action(ev, DirectSupplies):
            out[ev.from_fips]["resources"][ev.resource]["on_hand"] -= ev.quantity
            status, when, by_hand = shipment_outcome(ev, cursor, events, sc)
            to = out[ev.to_fips]
            if when is None:
                to["resources"][ev.resource]["in_transit"] += ev.quantity
            else:
                to["resources"][ev.resource]["on_hand"] += ev.quantity
                delivered.setdefault((ev.to_fips, ev.resource), []).append((when, ev.quantity))
            to["incoming"].append({
                "seq": ev.seq, "from": ev.from_fips, "resource": ev.resource,
                "quantity": ev.quantity, "dispatched": ev.hour, "arrives": ev.arrives,
                "status": status, "delivered_hour": when, "by_hand": by_hand,
            })
        elif is_action(ev, ChangeStatus):
            latest_manual[(ev.fips, ev.target)] = ev
            resolved_manual.pop((ev.fips, ev.target), None)  # a new manual status starts over
        elif is_action(ev, ResolveContradiction) and ev.kind == "manual":
            resolved_manual[(ev.fips, ev.target)] = ev

    # A confirmed delivery lowers known need (never below 0). Colors untouched.
    for (fips, resource), batches in delivered.items():
        r = out[fips]["resources"][resource]
        if r["need"] is not None:
            since = r.get("need_since")  # AI mode: only deliveries after the request
            qty = sum(q for h, q in batches if since is None or h >= since)
            r["need"] = max(0, r["need"] - qty)

    # Manual statuses hold until the next report on that lifeline.
    for (fips, target), cs in latest_manual.items():
        s = out[fips]
        outcome, report = manual_outcome(cs, cursor, sc, s.get("lifeline_sources"))
        res = resolved_manual.get((fips, target))
        if outcome == "contradiction" and res is not None:
            outcome = {"manual": "kept manual", "report": "cleared",
                       "both": "kept both"}[res.choice]
        s["manual"][target] = {
            "color": cs.color, "hour": cs.hour, "role": cs.role, "reason": cs.reason,
            "outcome": outcome, "report": report,
        }
        if outcome == "contradiction":
            s["contradictions"].append({
                "kind": "manual",
                "target": target,
                "manual": {"color": cs.color, "hour": cs.hour,
                           "source": f"Manual change ({cs.role})"},
                "report": {"color": report[1], "hour": report[0],
                           "source": "Answer key (scenario report)"},
            })

    for s in out.values():
        if not s["hit"] or s["silent"] or not s["manual"]:
            continue  # purple overrides everything while silent
        active = {t: m for t, m in s["manual"].items() if m["outcome"] != "cleared"}
        for t, m in active.items():  # kept both: show the more urgent of the two
            if m["outcome"] == "kept both" and m["report"]:
                m = dict(m, color=most_urgent([m["color"], m["report"][1]]))
                active[t] = m
        if not active:
            continue
        s["manual_marker"] = True
        for t, m in active.items():  # overwrite nothing: the manual value stays shown
            if t != "Overall":
                s["lifelines"][t] = m["color"]
        if "Overall" in active:
            s["color"] = active["Overall"]["color"]
        else:
            s["color"] = most_urgent([c for c in s["lifelines"].values() if c] or [YELLOW])
        s["status_word"] = STATUS_WORD[s["color"]]


def _require(clock: Clock, role, reason) -> None:
    if not clock.at_live_head:
        raise ActionRefused(
            f"Actions are allowed only at the live hour ({clock.live_head}); "
            f"the view is at hour {clock.cursor}."
        )
    if not isinstance(role, str) or not role.strip():
        raise ActionRefused("A role is required.")
    if not isinstance(reason, str) or not reason.strip():
        raise ActionRefused("A reason is required.")


def confirm_delivery(events, clock: Clock, shipment_seq: int, role: str, reason: str,
                     scenario: Scenario | None = None) -> tuple:
    """Log a delivery confirmation by hand for an Unconfirmed shipment."""
    sc = scenario or default_scenario()
    events = tuple(events)
    _require(clock, role, reason)
    ship = next((e for e in events if is_action(e, DirectSupplies)
                 and e.seq == shipment_seq), None)
    if ship is None or ship.hour > clock.live_head:
        raise ActionRefused("That shipment isn't in the log.")
    status, _, _ = shipment_outcome(ship, clock.live_head, events, sc)
    if status != "Unconfirmed":
        raise ActionRefused(f"That shipment is {status.lower()}; only an Unconfirmed "
                            "shipment can be confirmed by hand.")
    return events + (ConfirmDelivery(len(events) + 1, clock.live_head, role.strip(),
                                     shipment_seq, reason.strip()),)


def change_status(events, clock: Clock, fips: str, target: str, color: str, role: str,
                  reason: str, scenario: Scenario | None = None) -> tuple:
    """Set Overall or one lifeline by hand. Refused on a silent county."""
    sc = scenario or default_scenario()
    events = tuple(events)
    _require(clock, role, reason)
    if fips not in sc.names:
        raise ActionRefused("Unknown county.")
    if fips not in sc.hit:
        raise ActionRefused(f"{sc.names[fips]} is not in the storm path; "
                            "it has no status to change.")
    if silent_at(sc, fips, clock.live_head):
        raise ActionRefused(f"{sc.names[fips]} is silent; its status can't be set "
                            "until contact returns.")
    if target not in STATUS_TARGETS:
        raise ActionRefused(f"Unknown lifeline: {target!r}.")
    if color not in MANUAL_COLORS:
        raise ActionRefused("The new color must be red, yellow or green.")
    return events + (ChangeStatus(len(events) + 1, clock.live_head, role.strip(), fips,
                                  target, color, reason.strip()),)


ROLES = ("Situation analyst", "Logistics", "Operations chief", "Other")  # Proposal
LOG_COLUMNS = ("Simulated time", "Role", "Action", "Details", "Reason", "Status")

# How a quantity reads in the log, e.g. "2 water tankers".
DETAIL_NOUN = {
    "Water": "water tankers",
    "Generators": "generators",
    "Utility crews": "utility crews",
    "Search-and-rescue teams": "search-and-rescue teams",
    "Food": "pallets of meals",
    "Shelter": "cots and shelter kits",
    "Medical teams": "medical teams",
    "Hygiene items": "hygiene kits",
    "Sanitation": "portable toilet and handwashing units",
}
# The same for a quantity of exactly 1, e.g. "1 water tanker".
DETAIL_NOUN_ONE = {
    "Water": "water tanker",
    "Generators": "generator",
    "Utility crews": "utility crew",
    "Search-and-rescue teams": "search-and-rescue team",
    "Food": "pallet of meals",
    "Shelter": "cot or shelter kit",
    "Medical teams": "medical team",
    "Hygiene items": "hygiene kit",
    "Sanitation": "portable toilet and handwashing unit",
}
# Units (plural from RESOURCES, singular here) for stock labels: "1 tanker on hand".
UNIT_ONE = {
    "Water": "tanker",
    "Generators": "unit",
    "Utility crews": "crew",
    "Search-and-rescue teams": "team",
    "Food": "pallet of meals",
    "Shelter": "cot or shelter kit",
    "Medical teams": "team",
    "Hygiene items": "kit",
    "Sanitation": "portable toilet and handwashing unit",
}


def quantity_phrase(quantity: int, resource: str) -> str:
    """'1 water tanker', '2 water tankers'."""
    noun = DETAIL_NOUN_ONE[resource] if quantity == 1 else DETAIL_NOUN[resource]
    return f"{quantity} {noun}"


def unit_phrase(quantity: int, resource: str) -> str:
    """'1 tanker', '0 tankers', '8 tankers'."""
    unit = UNIT_ONE[resource] if quantity == 1 else dict(
        (n, u) for n, u, _ in RESOURCES)[resource]
    return f"{quantity} {unit}"


def shipment_phrase(ev: DirectSupplies, sc: Scenario) -> str:
    """'4 water tankers, Wake to Robeson'."""
    return (f"{quantity_phrase(ev.quantity, ev.resource)}, "
            f"{sc.names[ev.from_fips]} to {sc.names[ev.to_fips]}")


def _manual_status_text(cs: ChangeStatus, cursor: int, sc: Scenario) -> str:
    outcome, report = manual_outcome(cs, cursor, sc)
    if outcome == "holding":
        return "Manual"
    if outcome == "cleared":
        return f"Cleared (hour {report[0]}): next report agreed"
    return f"Contradiction (hour {report[0]})"


def log_rows(events, cursor: int, scenario: Scenario | None = None) -> list[dict]:
    """The action log as read-only rows, newest first, for entries made at or
    before `cursor` (the log replayed up to the hour on screen, Fix 2)."""
    sc = scenario or default_scenario()
    events = tuple(events)
    by_seq = {e.seq: e for e in events}
    rows = []
    for ev in reversed(events):
        if ev.hour > cursor:
            continue
        if is_action(ev, DirectSupplies):
            details = shipment_phrase(ev, sc)
            status = shipment_outcome(ev, cursor, events, sc)[0]
        elif is_action(ev, ConfirmDelivery):
            ship = by_seq[ev.shipment_seq]
            details = f"{shipment_phrase(ship, sc)} (sent hour {ship.hour})"
            status = "Delivered"
        elif is_action(ev, ResolveContradiction):
            details = f"{sc.names[ev.fips]} {ev.target}: {ev.detail}"
            status = "Resolved"
        else:  # ChangeStatus
            details = f"{sc.names[ev.fips]} {ev.target}: set to {ev.color.capitalize()}"
            status = _manual_status_text(ev, cursor, sc)
        rows.append({
            "Simulated time": f"Hour {ev.hour}",
            "Role": ev.role,
            "Action": ev.action,
            "Details": details,
            "Reason": ev.reason,
            "Status": status,
        })
    return rows


def log_csv(events, cursor: int, scenario: Scenario | None = None) -> str:
    """The CSV export: the same six columns as the log panel."""
    import csv
    import io

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=LOG_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(log_rows(events, cursor, scenario))
    return buf.getvalue()


def sender_options(state: dict, resource: str, receiver_fips: str) -> list[tuple]:
    """Every other county as (fips, name, on_hand of `resource`), in
    ALPHABETICAL order by name only. Never sorted by stock, distance or gap,
    and nothing is marked as suggested."""
    return sorted(
        (
            (f, s["county"], s["resources"][resource]["on_hand"])
            for f, s in state.items()
            if f != receiver_fips
        ),
        key=lambda t: t[1],
    )


def sender_label(state: dict, fips: str, resource: str) -> str:
    """'Wake · 8 water tankers on hand'. A silent county stays listed, marked
    with the hour its information dates from."""
    s = state[fips]
    label = (f"{s['county']} · {quantity_phrase(s['resources'][resource]['on_hand'], resource)}"
             " on hand")
    if s.get("silent"):
        label += f" (last known, hour {s['lifelines_as_of']})"
    return label


def eligible_for_hand_confirmation(state: dict, fips: str) -> list[dict]:
    """Shipments to this county waiting for a hand confirmation."""
    return [sh for sh in state[fips]["incoming"] if sh["status"] == "Unconfirmed"]


def reset_run() -> tuple[Clock, tuple]:
    """Reset: hour 0 and an empty log. Clears every test-mode action."""
    return Clock(), ()


# ---- Direct supplies form handler (Confirm is always clickable) ------------

MISSING_MESSAGES = {
    "role": "Choose your role at the top of the page first: every action is stamped with one.",
    "resource": "Choose a resource first.",
    "quantity": "Type a quantity first.",
    "sender": "Choose the sending county first.",
    "reason": "Type a reason first: every action needs one.",
    "shipment": "Choose the shipment first.",
    "target": "Choose Overall or a lifeline first.",
    "color": "Choose the new color first.",
    "choice": "Choose which value to keep first.",
}


def _missing(**fields) -> list[str]:
    out = []
    for name, value in fields.items():
        if value is None or (isinstance(value, str) and not value.strip()):
            out.append(name)
    return out


def _refused(prefix: str, missing: list[str]) -> str:
    return prefix + " " + " ".join(MISSING_MESSAGES[m] for m in missing)


def submit_confirm_delivery(events, clock: Clock, shipment_seq, role, reason,
                            scenario: Scenario | None = None):
    """One click on the Log confirmation form. Returns (events, message, logged)."""
    sc = scenario or default_scenario()
    events = tuple(events)
    missing = _missing(role=role, shipment=shipment_seq, reason=reason)
    if missing:
        return events, _refused("Not logged.", missing), False
    try:
        new = confirm_delivery(events, clock, int(shipment_seq), role, reason, sc)
    except ActionRefused as err:
        return events, f"Not logged: {err}", False
    ship = next(e for e in new if e.seq == new[-1].shipment_seq)
    return new, f"Logged: delivery confirmed, {shipment_phrase(ship, sc)}.", True


def submit_change_status(events, clock: Clock, fips: str, target, color, role, reason,
                         scenario: Scenario | None = None):
    """One click on the Change status form. Returns (events, message, logged)."""
    sc = scenario or default_scenario()
    events = tuple(events)
    missing = _missing(role=role, target=target, color=color, reason=reason)
    if missing:
        return events, _refused("Not changed.", missing), False
    try:
        new = change_status(events, clock, fips, target, color, role, reason, sc)
    except ActionRefused as err:
        return events, f"Not changed: {err}", False
    e = new[-1]
    return new, (f"Logged: {sc.names[fips]} {e.target} set to {e.color.capitalize()} "
                 "(Manual until the next report on it)."), True


def missing_fields(role, resource, quantity, from_fips, reason) -> list[str]:
    """Which required fields of the Direct supplies form are empty, in form order."""
    missing = []
    if not (isinstance(role, str) and role.strip()):
        missing.append("role")
    if not resource:
        missing.append("resource")
    if quantity is None or quantity == "":
        missing.append("quantity")
    if not from_fips:
        missing.append("sender")
    if not (isinstance(reason, str) and reason.strip()):
        missing.append("reason")
    return missing


def submit_direct_supplies(events, clock: Clock, to_fips: str, role, resource, quantity,
                           from_fips, reason, scenario: Scenario | None = None):
    """What one click on Confirm does. Returns (events, message, logged).

    If anything is missing or the rules refuse the send, the log comes back
    unchanged and the message says why. Nothing is ever guessed or filled in."""
    sc = scenario or default_scenario()
    events = tuple(events)
    missing = missing_fields(role, resource, quantity, from_fips, reason)
    if missing:
        return events, "Not sent. " + " ".join(MISSING_MESSAGES[m] for m in missing), False
    if isinstance(quantity, float) and quantity.is_integer():
        quantity = int(quantity)
    try:
        new = direct_supplies(events, clock, from_fips, to_fips, resource, quantity,
                              role, reason, sc)
    except ActionRefused as err:
        return events, f"Not sent: {err}", False
    e = new[-1]
    return new, (f"Logged: {quantity_phrase(e.quantity, e.resource)}, "
                 f"{sc.names[e.from_fips]} to {sc.names[e.to_fips]}. In transit."), True


# ===========================================================================
# Phase 3: AI mode (facts from ai.py; code decides every color)
# ===========================================================================

AI_LIFELINES = ("Roads", "Water", "Health and Medical")  # read from reports
FEED_LIFELINES = ("Power", "Communications")  # read from feeds.csv by code
NEED_UNKNOWN = "No request received, need unknown"

# Status word -> color, from the design doc thresholds (data/README.md vocabulary).
FACT_COLOR = {
    "Roads": {"Open": GREEN, "Partly closed": YELLOW, "No route": RED},
    "Water": {"Normal": GREEN, "Boil notice": YELLOW, "Out": RED},
    "Health and Medical": {"Normal": GREEN, "On generator": YELLOW,
                           "Evacuating": RED, "Closed": RED},
}


def power_color(pct: float) -> str:
    return GREEN if pct < 10 else YELLOW if pct < 50 else RED


def comms_color(pct: float) -> str:
    return GREEN if pct < 10 else YELLOW if pct < 40 else RED


def fact_color(f) -> str | None:
    """The lifeline color a fact stands for, or None if its words don't map."""
    if f.lifeline_or_resource == "Water" and f.metric == "Systems out of service":
        # Gold review rule: a count of 0 means no system is out. It is Normal
        # (green) whatever status word comes back, and never red or yellow.
        try:
            return RED if float(f.value) > 0 else GREEN
        except (TypeError, ValueError):
            return FACT_COLOR["Water"].get(f.status_word)
    return FACT_COLOR.get(f.lifeline_or_resource, {}).get(f.status_word)


def _county_key(name) -> str:
    n = str(name).strip().lower()
    return n[:-len(" county")] if n.endswith(" county") else n


def contradiction_key(target: str, a, b) -> str:
    return f"{target}|{a.source}|{a.sim_hour}|{b.source}|{b.sim_hour}"


def _fact_info(f, report_id: str) -> dict:
    return {"kind": "report", "source": f.source, "hour": f.sim_hour, "quote": f.quote,
            "verified": f.verified, "value": f.value, "status_word": f.status_word,
            "report_id": report_id, "color": fact_color(f)}


def ai_facts_for(sc: Scenario, fips: str, hour: int, ai_reads: dict) -> list:
    """(fact, report_id) for accepted facts about this county from reports read
    and dated at or before `hour`. The county comes from the AI's own answer."""
    name = _county_key(sc.names[fips])
    out = []
    for rid, res in ai_reads.items():
        rep = sc.reports.get(rid)
        if rep is None or rep["sim_hour"] > hour or getattr(res, "status", "") != "ok":
            continue
        for f in res.accepted:
            if _county_key(f.county) == name:
                out.append((f, rid))
    return sorted(out, key=lambda x: x[0].sim_hour)


def _resolutions(events, fips: str, cursor: int) -> dict:
    """key -> ResolveContradiction (kind "ai") made at or before the cursor."""
    return {ev.key: ev for ev in events
            if is_action(ev, ResolveContradiction) and ev.kind == "ai"
            and ev.fips == fips and ev.hour <= cursor}


def ai_county_view(sc: Scenario, fips: str, hour, ai_reads: dict, events=(), cursor=None):
    """AI-mode lifelines, sources, contradictions and known need for one county
    as of `hour` (the last contact hour while silent)."""
    import ai as ai_mod  # supersede and the contradiction rule, as built in Phase 3 prep

    cursor = hour if cursor is None else cursor
    lifelines, sources, contradictions = {}, {}, []
    need, need_since, requests = {}, {}, {}
    if hour is None:
        return {"lifelines": None, "sources": {}, "contradictions": [], "need": {},
                "need_since": {}, "requests": {}}

    # Power and Communications: the latest feed reading (code, not AI).
    feed = None
    for row in sc.feeds.get(fips, ()):
        if row[0] > hour:
            break
        feed = row
    for ll in FEED_LIFELINES:
        if feed is None:
            lifelines[ll] = None
            sources[ll] = {"kind": "none", "note": "No feed reading yet"}
            continue
        pct = feed[1] if ll == "Power" else feed[2]
        lifelines[ll] = power_color(pct) if ll == "Power" else comms_color(pct)
        what = "customers out" if ll == "Power" else "cell sites out"
        sources[ll] = {"kind": "feed", "hour": feed[0], "color": lifelines[ll],
                       "note": f"Feed reading (code, not AI): {pct:g}% {what}, hour {feed[0]}"}

    facts = ai_facts_for(sc, fips, hour, ai_reads)
    rid_of = {id(f): rid for f, rid in facts}
    resolved = _resolutions(events, fips, cursor)

    def topic_facts(target, requests=False):
        fs = [f for f, _ in facts if f.lifeline_or_resource == target
              and (f.metric == "Requested") == requests]
        current, _ = ai_mod.supersede(tuple(fs))
        dropped = set()
        both = []
        open_pairs = []
        for a, b in ai_mod.find_contradictions(current):
            key = contradiction_key(target, a, b)
            res = resolved.get(key)
            newest = max(f.sim_hour for f in current)
            if res is None:
                if newest <= max(a.sim_hour, b.sim_hour):  # nothing newer settles it
                    open_pairs.append((key, a, b))
            elif res.choice == "a":
                dropped.add(id(b))
            elif res.choice == "b":
                dropped.add(id(a))
            else:
                both.append((a, b))
        kept = [f for f in current if id(f) not in dropped]
        return kept, open_pairs, both

    for ll in AI_LIFELINES:
        kept, open_pairs, both = topic_facts(ll)
        applied = None
        skipped_note = ""
        for f in sorted(kept, key=lambda f: f.sim_hour, reverse=True):
            c = fact_color(f)
            if c is None:
                continue
            if c == GREEN and f.verified != "Yes":
                # SKYZR will not let an unverified report turn a county green.
                skipped_note = (f"An unverified report at hour {f.sim_hour} says this is back "
                                "to normal; unverified reports can't turn a lifeline green.")
                continue
            applied = f
            break
        if open_pairs:
            key, a, b = open_pairs[-1]
            colors = [c for c in (fact_color(a), fact_color(b)) if c]
            lifelines[ll] = most_urgent(colors) if colors else None
            sources[ll] = {"kind": "contradiction", "key": key, "color": lifelines[ll],
                           "note": "Contradiction: two sources disagree. Resolve to choose."}
            for k, x, y in open_pairs:
                contradictions.append({
                    "kind": "ai", "target": ll, "key": k,
                    "a": _fact_info(x, rid_of.get(id(x), "")),
                    "b": _fact_info(y, rid_of.get(id(y), "")),
                })
        elif applied is not None:
            lifelines[ll] = fact_color(applied)
            sources[ll] = _fact_info(applied, rid_of.get(id(applied), ""))
            pair = next(((a, b) for a, b in both if applied in (a, b)), None)
            if pair:
                lifelines[ll] = most_urgent([fact_color(pair[0]), fact_color(pair[1])])
                sources[ll]["both"] = [_fact_info(x, rid_of.get(id(x), "")) for x in pair]
            if skipped_note:
                sources[ll]["note"] = skipped_note
        else:
            lifelines[ll] = None
            sources[ll] = {"kind": "none", "note": skipped_note or "No report yet"}

    for r, _, _ in RESOURCES:
        kept, open_pairs, both = topic_facts(r, requests=True)
        reqs = [f for f in kept if ai_mod._number(f.value) is not None]
        if not reqs:
            need[r] = None
            continue
        latest = max(reqs, key=lambda f: f.sim_hour)
        if open_pairs:
            _, a, b = open_pairs[-1]
            vals = sorted(int(ai_mod._number(x.value)) for x in (a, b))
            need[r] = vals[1]  # the larger, shown as a range in the panel
            need_since[r] = max(a.sim_hour, b.sim_hour)
            requests[r] = {"range": vals, "contradiction": True}
            for k, x, y in open_pairs:
                contradictions.append({
                    "kind": "ai", "target": r, "key": k,
                    "a": _fact_info(x, rid_of.get(id(x), "")),
                    "b": _fact_info(y, rid_of.get(id(y), "")),
                })
            continue
        need[r] = int(ai_mod._number(latest.value))
        need_since[r] = latest.sim_hour
        requests[r] = _fact_info(latest, rid_of.get(id(latest), ""))
        pair = next(((a, b) for a, b in both if latest in (a, b)), None)
        if pair:
            vals = sorted(int(ai_mod._number(x.value)) for x in pair)
            need[r] = vals[1]
            requests[r]["range"] = vals

    return {"lifelines": lifelines, "sources": sources, "contradictions": contradictions,
            "need": need, "need_since": need_since, "requests": requests}


def resolve_contradiction(events, clock: Clock, fips: str, target: str, kind: str, key: str,
                          choice: str, role: str, reason: str, sc: Scenario | None = None,
                          detail: str = "") -> tuple:
    """Log a resolution. Live hour only; role and reason required."""
    sc = sc or default_scenario()
    _require(clock, role, reason)
    allowed = ("manual", "report", "both") if kind == "manual" else ("a", "b", "both")
    if choice not in allowed:
        raise ActionRefused("Choose which value to keep.")
    entry = ResolveContradiction(
        seq=len(events) + 1, hour=clock.live_head, role=role, fips=fips, target=target,
        kind=kind, key=key, choice=choice, reason=str(reason).strip(), detail=detail)
    return tuple(events) + (entry,)


def submit_resolve(events, clock: Clock, fips, target, kind, key, choice, role, reason,
                   sc: Scenario | None = None, detail: str = ""):
    """The Resolve form's one-click handler: (events, message, logged)."""
    missing = _missing(role=role, choice=choice, reason=reason)
    if missing:
        return events, _refused("Not resolved.", missing), False
    try:
        events = resolve_contradiction(events, clock, fips, target, kind, key, choice,
                                       role, reason, sc, detail)
    except ActionRefused as e:
        return events, f"Not resolved. {e}", False
    return events, f"Resolved: {detail}. Logged as Resolved contradiction.", True


FACT_CSV_COLUMNS = ("report_id",) + (
    "county", "lifeline_or_resource", "metric", "value", "status_word",
    "source", "sim_hour", "quote", "verified")


def accepted_facts_csv(ai_reads: dict) -> str:
    """Every accepted fact (report_id plus the nine fields), for the AI-vs-gold check."""
    import csv
    import io

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(FACT_CSV_COLUMNS)
    for rid in sorted(ai_reads):
        res = ai_reads[rid]
        for f in getattr(res, "accepted", ()):
            w.writerow([rid, f.county, f.lifeline_or_resource, f.metric, f.value,
                        f.status_word, f.source, f.sim_hour, f.quote, f.verified])
    return buf.getvalue()
