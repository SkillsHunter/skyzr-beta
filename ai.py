"""SKYZR AI intake: the plain-code parts around the model (Phase 3 prep).

The model only proposes facts. Code decides what is accepted:
- the quote check (plan v2 Fix 5) rejects any fact whose quote isn't in its
  own report word for word;
- the contradiction rule (design doc p. 9) flags conflicting accepted facts;
- a failed or timed-out call changes nothing ("AI unavailable");
- calls are cached by report-text hash and capped per session.

Rules (CLAUDE.md): the API key comes only from st.secrets. This module never
reads answer_key.csv and never passes any of it to the model. Each call gets
one report's sim_hour, source, verified and text, and nothing else.

No Streamlit import here, so everything is testable without a browser or a key.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import re
import threading
from dataclasses import dataclass, field

# ---- Messages and limits ----------------------------------------------------------

AI_UNAVAILABLE = "AI unavailable: report not processed"
CALL_LIMIT_MESSAGE = "AI call limit reached"
MAX_CALLS_PER_SESSION = 80  # plan v2 §2: at most 80 AI calls per session
CALL_TIMEOUT_SECONDS = 30.0

# ---- Contradiction rule (design doc p. 9) ----------------------------------------

CONTRADICTION_WINDOW_HOURS = 6  # "within 6 simulated hours"
CONTRADICTION_RELATIVE_DIFF = 0.20  # "differ by more than 20%"
# DECISIONS.md: the design doc says "lifeline and metric"; resource requests can
# conflict too. The team can switch this off with one constant.
CONTRADICTIONS_COVER_RESOURCE_REQUESTS = True

RESOURCE_NAMES = (
    "Water", "Generators", "Utility crews", "Search-and-rescue teams", "Food",
    "Shelter", "Medical teams", "Hygiene items", "Sanitation",
)

# ---- The fact schema: design doc p. 9, field for field ----------------------------

FACT_FIELDS = (
    "county",                # County
    "lifeline_or_resource",  # Lifeline or resource
    "metric",                # Metric (of "Metric and value")
    "value",                 # Value  (of "Metric and value")
    "status_word",           # Status word
    "source",                # Source
    "sim_hour",              # Simulated time
    "quote",                 # Exact quote
    "verified",              # Verified? "Yes" (official) / "No" (social or unofficial)
)

# The only report fields the model ever sees.
PAYLOAD_FIELDS = ("sim_hour", "source", "verified", "text")


@dataclass(frozen=True)
class Fact:
    county: str
    lifeline_or_resource: str
    metric: str
    value: object  # a number, or a status phrase such as "Boil-water notice"
    status_word: str
    source: str
    sim_hour: int
    quote: str
    verified: str  # "Yes" or "No"


@dataclass(frozen=True)
class ReadResult:
    report_id: str
    status: str  # "ok", "unavailable" or "limit"
    message: str
    report_text: str  # the raw report always stays available to show
    accepted: tuple = ()  # Fact, ...
    rejected: tuple = ()  # (raw fact dict, reason), ...
    from_cache: bool = False


# ---- Quote check (plan v2 Fix 5) ---------------------------------------------------

_QUOTE_MARKS = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"',
})


def normalize(text: str) -> str:
    """Curly quote marks become straight; any run of whitespace becomes one
    space; ends are trimmed. Nothing else changes (case is kept)."""
    return re.sub(r"\s+", " ", str(text).translate(_QUOTE_MARKS)).strip()


def quote_in_report(quote: str, report_text: str) -> bool:
    """True if the quote appears word for word in the report, after normalizing.
    It must start and end on word boundaries, so "ree systems" doesn't match
    inside "three systems"."""
    q = normalize(quote)
    if not q:
        return False
    pattern = r"(?<!\w)" + re.escape(q) + r"(?!\w)"
    return re.search(pattern, normalize(report_text)) is not None


# ---- Reading one report --------------------------------------------------------------

def payload_for(report: dict) -> dict:
    """Exactly sim_hour, source, verified and text. Never county, fips, the
    report id, or anything from the answer key."""
    return {k: report[k] for k in PAYLOAD_FIELDS}


def _verified_word(flag) -> str:
    return "Yes" if str(flag).strip().lower() == "yes" else "No"


def _check_fact(raw, report: dict):
    """Return (Fact, None) if accepted, or (None, reason) if rejected.

    Source, simulated time and verified come from the report itself, not from
    the model: they are given, not extracted (DECISIONS.md)."""
    if not isinstance(raw, dict):
        return None, "not a fact object"
    missing = [f for f in ("county", "lifeline_or_resource", "metric", "value",
                           "status_word", "quote") if raw.get(f) in (None, "")]
    if missing:
        return None, f"missing field(s): {', '.join(missing)}"
    if not quote_in_report(raw["quote"], report["text"]):
        return None, "quote not found word for word in the report"
    return Fact(
        county=str(raw["county"]).strip(),
        lifeline_or_resource=str(raw["lifeline_or_resource"]).strip(),
        metric=str(raw["metric"]).strip(),
        value=raw["value"],
        status_word=str(raw["status_word"]).strip(),
        source=str(report["source"]),
        sim_hour=int(report["sim_hour"]),
        quote=str(raw["quote"]),
        verified=_verified_word(report["verified"]),
    ), None


def check_facts(raw_facts, report: dict) -> tuple[tuple, tuple]:
    accepted, rejected = [], []
    for raw in raw_facts or ():
        fact, reason = _check_fact(raw, report)
        if fact:
            accepted.append(fact)
        else:
            rejected.append((raw, reason))
    return tuple(accepted), tuple(rejected)


def _call(client, payload, timeout):
    """Call the client with a hard timeout. Any failure raises."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.extract, payload)
        return future.result(timeout=timeout)


def read_report(report: dict, client, timeout: float | None = None) -> ReadResult:
    """One report through the model and the quote check. If the client raises
    or times out, nothing is accepted and the raw report stays visible."""
    rid = str(report.get("report_id", ""))
    try:
        raw = _call(client, payload_for(report), timeout or CALL_TIMEOUT_SECONDS)
    except Exception:  # noqa: BLE001 - any failure means "not processed", never a guess
        return ReadResult(rid, "unavailable", AI_UNAVAILABLE, report["text"])
    accepted, rejected = check_facts(raw, report)
    return ReadResult(rid, "ok", "", report["text"], accepted, rejected)


# ---- Session: cache and call cap -----------------------------------------------------

def text_hash(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


class SharedCache:
    """Server-wide cache of raw model output, shared by every tab (Phase 3).

    Keyed by (client name, text hash), so a fake client's answers are never
    served to the real one. Only successful calls are stored. It lives for as
    long as the server process (a code reload or restart empties it)."""

    def __init__(self):
        self._data = {}
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            return self._data.get(key)

    def put(self, key, raw):
        with self._lock:
            self._data[key] = raw

    def clear(self):
        with self._lock:
            self._data.clear()

    def __len__(self):
        return len(self._data)


SHARED_CACHE = SharedCache()


@dataclass
class Intake:
    """One browser tab's AI intake: its call cap. The cache is server-wide
    (SHARED_CACHE); a cache hit costs no call and doesn't count to the cap."""

    client: object
    max_calls: int = MAX_CALLS_PER_SESSION
    calls_made: int = 0
    cache: SharedCache = field(default_factory=lambda: SHARED_CACHE)

    def cache_key(self, report: dict):
        return (getattr(self.client, "cache_name", type(self.client).__name__),
                text_hash(report["text"]))

    def cached(self, report: dict) -> bool:
        return self.cache.get(self.cache_key(report)) is not None

    def read(self, report: dict) -> ReadResult:
        rid = str(report.get("report_id", ""))
        key = self.cache_key(report)
        raw = self.cache.get(key)
        if raw is not None:  # no second call for the same text, in any tab
            accepted, rejected = check_facts(raw, report)
            return ReadResult(rid, "ok", "", report["text"], accepted, rejected, True)
        if self.calls_made >= self.max_calls:
            return ReadResult(rid, "limit", CALL_LIMIT_MESSAGE, report["text"])
        self.calls_made += 1
        try:
            raw = _call(self.client, payload_for(report), CALL_TIMEOUT_SECONDS)
            if not isinstance(raw, (list, tuple)):
                raise ValueError("model output is not a list of facts")
        except Exception:  # noqa: BLE001
            return ReadResult(rid, "unavailable", AI_UNAVAILABLE, report["text"])
        self.cache.put(key, list(raw))  # only successful calls are cached
        accepted, rejected = check_facts(raw, report)
        return ReadResult(rid, "ok", "", report["text"], accepted, rejected)


# ---- Contradictions (design doc p. 9) ------------------------------------------------

def _number(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except ValueError:
        return None


def relative_difference(a: float, b: float) -> float:
    """The one formula for "differ by more than 20%":
    |a - b| / max(|a|, |b|), and 0 when both are 0."""
    larger = max(abs(a), abs(b))
    return 0.0 if larger == 0 else abs(a - b) / larger


def values_differ(a, b) -> bool:
    x, y = _number(a), _number(b)
    if x is None or y is None:
        return False  # non-numeric values are compared through the status word
    return relative_difference(x, y) > CONTRADICTION_RELATIVE_DIFF


def is_resource_request(f: Fact) -> bool:
    return f.lifeline_or_resource in RESOURCE_NAMES or f.metric == "Requested"


def _topic(f: Fact):
    return (f.county, f.lifeline_or_resource, f.metric)


def supersede(facts) -> tuple[tuple, tuple]:
    """A later fact from the same source on the same county, lifeline or
    resource, and metric replaces the earlier one instead of conflicting.
    Returns (current facts, replaced facts). Ties keep the later in the list."""
    latest = {}
    order = []
    for i, f in enumerate(facts):
        k = _topic(f) + (f.source,)
        if k not in latest or f.sim_hour >= latest[k][1].sim_hour:
            latest[k] = (i, f)
        order.append((i, f))
    keep = {i for i, _ in latest.values()}
    current = tuple(f for i, f in order if i in keep)
    replaced = tuple(f for i, f in order if i not in keep)
    return current, replaced


def conflicts(a: Fact, b: Fact) -> bool:
    if _topic(a) != _topic(b) or a.source == b.source:
        return False
    if not CONTRADICTIONS_COVER_RESOURCE_REQUESTS and (
            is_resource_request(a) or is_resource_request(b)):
        return False
    if abs(a.sim_hour - b.sim_hour) > CONTRADICTION_WINDOW_HOURS:
        return False
    return a.status_word != b.status_word or values_differ(a.value, b.value)


def find_contradictions(facts) -> list[tuple]:
    """Pairs of accepted facts that conflict, after same-source replacement."""
    current, _ = supersede(tuple(facts))
    return [
        (a, b)
        for i, a in enumerate(current)
        for b in current[i + 1:]
        if conflicts(a, b)
    ]


# ---- The real client (Phase 3) -------------------------------------------------------

MODEL_ID = "claude-haiku-5-5"
MAX_OUTPUT_TOKENS = 800
TOOL_NAME = "record_facts"

LIFELINE_VOCAB = ("Roads", "Water", "Health and Medical")
METRIC_VOCAB = ("Route status", "Systems out of service", "System status",
                "Hospital status", "Requested")
STATUS_VOCAB = ("Open", "Partly closed", "No route", "Out", "Normal", "Boil notice",
                "On generator", "Evacuating", "Closed", "Requested")

SYSTEM_PROMPT = """You read one field report from a fictional hurricane exercise in North Carolina and record facts with the record_facts tool.

Extract only these kinds of fact:
- Roads: metric "Route status"; status_word Open, Partly closed or No route; value "Open", "Some primary routes closed" or "No open route to county seat".
- Water: metric "Systems out of service" with status_word "Out" and the number of systems out as value whenever a count is stated or clear ("the water system" = 1); otherwise metric "System status" with status_word Normal, Boil notice or Out and value "Normal", "Boil-water notice" or "System out of service".
- Health and Medical: metric "Hospital status"; status_word Normal, On generator, Evacuating or Closed; value "Normal", "Hospital on generator or diverting" or "Hospital closed or evacuating".
- Resource requests: lifeline_or_resource one of Water, Generators, Utility crews, Search-and-rescue teams, Food, Shelter, Medical teams, Hygiene items, Sanitation; metric "Requested"; status_word "Requested"; value the number requested, as a number.

Rules:
- quote: copy the words from the report that support the fact, exactly as written, word for word. Never paraphrase or fix spelling.
- county: the North Carolina county the report is about, as named or clearly implied in the source or text, without the word "County".
- Never guess. If a fact is uncertain, leave it out. Returning no facts is fine.
- Do not record power or communications; they come from other feeds.
- Use only the words listed above for lifeline_or_resource, metric and status_word."""

FACT_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "county": {"type": "string"},
                    "lifeline_or_resource": {
                        "type": "string", "enum": list(LIFELINE_VOCAB + RESOURCE_NAMES)},
                    "metric": {"type": "string", "enum": list(METRIC_VOCAB)},
                    "value": {"type": ["string", "number"]},
                    "status_word": {"type": "string", "enum": list(STATUS_VOCAB)},
                    "quote": {"type": "string"},
                },
                "required": ["county", "lifeline_or_resource", "metric", "value",
                             "status_word", "quote"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["facts"],
    "additionalProperties": False,
}


def user_message(payload: dict) -> str:
    """The model sees exactly payload_for(report), as JSON, and nothing else."""
    return json.dumps(payload, ensure_ascii=False, default=str)


def tool_definition() -> dict:
    return {
        "name": TOOL_NAME,
        "description": "Record the facts found in the report (an empty list if none).",
        "input_schema": FACT_SCHEMA,
        "strict": True,
    }


class ClaudeClient:
    """The real client. The API key comes only from st.secrets and is never
    logged. extract() receives payload_for(report) and nothing else."""

    cache_name = MODEL_ID

    def __init__(self, api_key: str | None = None):
        if api_key is None:
            import streamlit as st  # only here: ai.py stays importable without Streamlit
            api_key = st.secrets["ANTHROPIC_API_KEY"]
        import anthropic
        self._client = anthropic.Anthropic(
            api_key=api_key, timeout=CALL_TIMEOUT_SECONDS, max_retries=1)

    def request(self, payload: dict) -> dict:
        """The exact request sent (no key in it), so tests can check it."""
        return {
            "model": MODEL_ID,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "system": SYSTEM_PROMPT,
            # Haiku 5.5 thinks by default; thinking off is allowed at its default
            # effort, and a forced tool call needs it off.
            "thinking": {"type": "disabled"},
            "tools": [tool_definition()],
            "tool_choice": {"type": "tool", "name": TOOL_NAME},
            "messages": [{"role": "user", "content": user_message(payload)}],
        }

    def extract(self, payload: dict):
        response = self._client.messages.create(**self.request(payload))
        if response.stop_reason not in ("tool_use", "end_turn"):
            raise RuntimeError(f"stopped: {response.stop_reason}")  # max_tokens, refusal: not processed
        for block in response.content:
            if block.type == "tool_use" and block.name == TOOL_NAME:
                facts = block.input.get("facts")
                if not isinstance(facts, list):
                    raise ValueError("no facts list")
                return facts
        raise ValueError("no tool call in the response")


class UnavailableClient:
    """Stands in when there is no key or the client can't start: every call
    fails, so every report shows "AI unavailable" and changes nothing."""

    cache_name = "unavailable"

    def __init__(self, why: str = ""):
        self.why = why

    def extract(self, payload: dict):
        raise RuntimeError(self.why or "AI unavailable")


class ScriptedClient:
    """A test double: answers from a table {report text: [raw facts]}; any
    other text gets no facts. `fail=True` makes every call raise. Records
    every payload it receives, so tests can check what the model is sent."""

    cache_name = "scripted"

    def __init__(self, table: dict | None = None, fail: bool = False):
        self.table = {normalize(k): v for k, v in (table or {}).items()}
        self.fail = fail
        self.payloads = []

    def extract(self, payload: dict):
        self.payloads.append(dict(payload))
        if self.fail:
            raise RuntimeError("scripted failure")
        return [dict(f) for f in self.table.get(normalize(payload["text"]), [])]
