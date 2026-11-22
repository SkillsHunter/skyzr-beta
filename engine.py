"""SKYZR engine: the rules as pure functions. No Streamlit import, ever.

Data loading, the startup checks (plan v2 §3 item 7), and from Phase 1 the
answer-key rules. `state_at(cursor, events)` is the only thing that computes
state. The playback clock (live head and review cursor) is here too, as pure
functions, so it can be tested without a browser.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
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

    return Scenario(
        names=county_shapes(geojson),
        hit=hit,
        lifelines=lifelines,
        true_need=true_need,
        stock=stock_map,
        contacts={f: sorted(hs) for f, hs in contacts.items()},
        report_hours={f: sorted(hs) for f, hs in report_hours.items()},
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


def state_at(cursor: int, events=(), scenario: Scenario | None = None) -> dict:
    """Every county's state at simulated hour `cursor`, from the data and events.

    This is the only function that computes state. `events` is the action log
    (a tuple of DirectSupplies entries); it is replayed up to `cursor`.

    Returns {fips: dict} with: county, hit, color, status_word, lifelines,
    lifelines_as_of, hours_since_contact, last_contact_hour, last_report_hour,
    resources {name: {need, on_hand, in_transit}}, incoming (shipments).
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
            }
            continue

        last_contact = _last_at_or_before(sc.contacts[fips], cursor)
        since = None if last_contact is None else cursor - last_contact
        silent = since is None or since >= SILENCE_HOURS

        # While silent, nothing new arrives: show what was known at last contact.
        as_of = cursor if not silent else last_contact
        lifelines = sc.lifelines[(fips, as_of)] if as_of is not None else None
        need = sc.true_need[(fips, as_of)] if as_of is not None else {}

        color = PURPLE if silent else most_urgent(lifelines.values())
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
        }

    # Replay the action log. Dispatch moves stock only: need and color above
    # come from the answer key and are never touched by a shipment.
    apply_events(out, cursor, events)
    return out


def overlay_color(county_state: dict, overlay: str) -> str:
    """Map color for one county under an overlay. Grey and purple never change."""
    color = county_state["color"]
    if overlay == "Overall" or color in (GREY, PURPLE):
        return color
    return county_state["lifelines"][overlay]


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


def shipment_status(entry: DirectSupplies, cursor: int) -> str:
    """Delivery confirmation waits for the team (Sunday 9:00), so a shipment
    past its transit time is 'Arrived, not confirmed', still counted in transit."""
    return "In transit" if cursor < entry.arrives else "Arrived, not confirmed"


def apply_events(out: dict, cursor: int, events) -> None:
    """Replay the log up to `cursor` onto state_at's output (in place)."""
    for ev in events:
        if not isinstance(ev, DirectSupplies) or ev.hour > cursor:
            continue
        out[ev.from_fips]["resources"][ev.resource]["on_hand"] -= ev.quantity
        out[ev.to_fips]["resources"][ev.resource]["in_transit"] += ev.quantity
        out[ev.to_fips]["incoming"].append(
            {
                "seq": ev.seq,
                "from": ev.from_fips,
                "resource": ev.resource,
                "quantity": ev.quantity,
                "dispatched": ev.hour,
                "arrives": ev.arrives,
                "status": shipment_status(ev, cursor),
            }
        )


def log_rows(events, cursor: int, scenario: Scenario | None = None) -> list[dict]:
    """The action log as read-only rows, newest first (design doc fields)."""
    sc = scenario or default_scenario()
    rows = []
    for ev in reversed(tuple(events)):
        rows.append(
            {
                "Simulated time": f"Hour {ev.hour}",
                "Role": ev.role,
                "Action": ev.action,
                "Details": f"{ev.quantity} {ev.resource}, "
                f"{sc.names[ev.from_fips]} to {sc.names[ev.to_fips]}",
                "Reason": ev.reason,
                "Status": shipment_status(ev, cursor) if ev.hour <= cursor else "Not yet sent",
            }
        )
    return rows


def reset_run() -> tuple[Clock, tuple]:
    """Reset: hour 0 and an empty log. Clears every test-mode action."""
    return Clock(), ()
