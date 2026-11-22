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
import logging
import re
import threading
from collections import Counter
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
    detail: str = ""  # why a call failed (class, HTTP code, API message); never the key


# ---- Failure reasons (Phase 3C) ----------------------------------------------------------

log = logging.getLogger("skyzr.ai")
_KEY_PATTERN = re.compile(r"AIza[0-9A-Za-z_-]+")
REASON_MAX_CHARS = 300


def scrub(text) -> str:
    """Remove anything that looks like a Google API key."""
    return _KEY_PATTERN.sub("[key removed]", str(text))


def failure_reason(err) -> str:
    """A short, safe reason: exception class, HTTP status code if any, and the
    API's own message cut to 300 characters. The key pattern is removed."""
    parts = [type(err).__name__]
    code = getattr(err, "code", None)
    if isinstance(code, int):
        parts.append(str(code))
    message = getattr(err, "message", None) or str(err)
    head = " ".join(parts)
    return scrub(f"{head}: {scrub(message)[:REASON_MAX_CHARS]}" if message else head)


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
        except Exception as err:  # noqa: BLE001
            reason = failure_reason(err)
            log.warning("AI call failed for %s: %s", rid, reason)  # server log is owner-only
            return ReadResult(rid, "unavailable", AI_UNAVAILABLE, report["text"], detail=reason)
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

# Phase 3B: Google Gemini (Gemini API, Google AI Studio free tier).
# The SDK's own Gemini API examples (google-genai 3.6.1) use this model id.
# An optional GEMINI_MODEL entry in Streamlit Secrets overrides it.
GEMINI_MODEL = "gemini-3.8-flash"
MODEL_ID = GEMINI_MODEL  # what the app shows; GeminiClient.model is what it calls
MAX_OUTPUT_TOKENS = 800
RATE_LIMIT_RETRIES = 2  # HTTP 429: wait and retry at most twice, within the 30 s budget
RATE_LIMIT_WAIT_SECONDS = 4.0  # first wait; doubled for the second
PREPARE_SECONDS_PER_CALL = 7.0  # Prepare pacing: about 8 calls a minute, under free-tier limits
GEMINI_THINKING_MODES = ("minimal", "off")  # Secrets GEMINI_THINKING; "off" sends no thinking config
GEMINI_SCHEMA_MODES = ("full", "loose")  # Secrets GEMINI_SCHEMA; "loose" sends no response schema
PREPARE_FAIL_FAST = 3  # Prepare stops if its first 3 calls all fail with the same reason

LIFELINE_VOCAB = ("Roads", "Water", "Health and Medical")
METRIC_VOCAB = ("Route status", "Systems out of service", "System status",
                "Hospital status", "Requested")
STATUS_VOCAB = ("Open", "Partly closed", "No route", "Out", "Normal", "Boil notice",
                "On generator", "Evacuating", "Closed", "Requested")

SYSTEM_PROMPT = """You read one field report from a fictional hurricane exercise in North Carolina and return its facts as JSON: {"facts": [...]}.

Extract only these kinds of fact:
- Roads: metric "Route status"; status_word Open, Partly closed or No route; value "Open", "Some primary routes closed" or "No open route to county seat".
- Water: metric "Systems out of service" with the number of systems out as value whenever a count is stated or clear ("the water system" = 1), and status_word "Out". A count of 0 means no system is out: its status_word is "Normal", never "Out" (e.g. "All three water systems are back in service" = Systems out of service, 0, Normal). Otherwise metric "System status" with status_word Normal, Boil notice or Out and value "Normal", "Boil-water notice" or "System out of service".
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
                    "value": {"anyOf": [{"type": "string"}, {"type": "number"}]},
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


def check_response_shape(data) -> list:
    """The parsed JSON must fit FACT_SCHEMA exactly (same fields, same enums).
    Anything else raises, so the report shows "AI unavailable" (never a guess)."""
    if not isinstance(data, dict) or set(data) != {"facts"} or not isinstance(data["facts"], list):
        raise ValueError("response is not {facts: [...]}")
    props = FACT_SCHEMA["properties"]["facts"]["items"]["properties"]
    fields = set(props)
    for f in data["facts"]:
        if not isinstance(f, dict) or set(f) != fields:
            raise ValueError("a fact has missing or extra fields")
        for name, spec in props.items():
            v = f[name]
            if "enum" in spec and v not in spec["enum"]:
                raise ValueError(f"{name} is outside the fixed vocabulary")
            if name == "value":
                if isinstance(v, bool) or not isinstance(v, (str, int, float)):
                    raise ValueError("value is not a string or number")
            elif not isinstance(v, str):
                raise ValueError(f"{name} is not a string")
    return data["facts"]


def _is_rate_limit(err) -> bool:
    return getattr(err, "code", None) == 429


class GeminiClient:
    """The real client (Phase 3B: Google Gemini). The API key comes only from
    st.secrets["GEMINI_API_KEY"], read here, and is never printed or logged.
    extract() receives payload_for(report) and nothing else."""

    prepare_seconds_per_call = PREPARE_SECONDS_PER_CALL

    def __init__(self, api_key: str | None = None, model: str | None = None,
                 sdk_client=None, sleep=None, thinking: str | None = None,
                 schema: str | None = None):
        if api_key is None or model is None or thinking is None or schema is None:
            import streamlit as st  # only here: ai.py stays importable without Streamlit

            def secret(name, default):
                try:
                    return st.secrets.get(name) or default
                except Exception:  # noqa: BLE001 - no secrets file: the default
                    return default

            if api_key is None:
                api_key = st.secrets["GEMINI_API_KEY"]
            model = model or secret("GEMINI_MODEL", GEMINI_MODEL)
            thinking = thinking or secret("GEMINI_THINKING", "minimal")
            schema = schema or secret("GEMINI_SCHEMA", "full")
        thinking, schema = str(thinking).strip().lower(), str(schema).strip().lower()
        if thinking not in GEMINI_THINKING_MODES or schema not in GEMINI_SCHEMA_MODES:
            raise ValueError("GEMINI_THINKING must be minimal or off; GEMINI_SCHEMA full or loose")
        self.model, self.thinking, self.schema = model, thinking, schema
        self.cache_name = f"gemini:{model}"
        if sdk_client is None:
            from google import genai
            from google.genai import types
            sdk_client = genai.Client(
                api_key=api_key,
                # The SDK's own retries are off: 429s are retried below, inside the budget.
                http_options=types.HttpOptions(
                    timeout=int(CALL_TIMEOUT_SECONDS * 1000),
                    retry_options=types.HttpRetryOptions(attempts=1)),
            )
        self._client = sdk_client
        self._sleep = sleep or __import__("time").sleep

    def config(self, timeout_s: float) -> dict:
        """The generation settings (no key in them), so tests can check them."""
        cfg = {
            "system_instruction": SYSTEM_PROMPT,
            "temperature": 0,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "response_mime_type": "application/json",
            "http_options": {"timeout": max(1000, int(timeout_s * 1000))},
        }
        if getattr(self, "schema", "full") == "full":
            cfg["response_json_schema"] = FACT_SCHEMA  # "loose": the parser alone checks shape
        if getattr(self, "thinking", "minimal") == "minimal":
            cfg["thinking_config"] = {"thinking_level": "MINIMAL"}  # keep the call fast
        return cfg

    def extract(self, payload: dict):
        import time

        deadline = time.monotonic() + CALL_TIMEOUT_SECONDS
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 1:
                raise TimeoutError("30 s budget used up")
            try:
                response = self._client.models.generate_content(
                    model=self.model,
                    contents=user_message(payload),
                    config=self.config(remaining),
                )
                break
            except Exception as err:  # noqa: BLE001
                if not _is_rate_limit(err) or attempt == RATE_LIMIT_RETRIES:
                    raise
                wait = RATE_LIMIT_WAIT_SECONDS * (2 ** attempt)
                if time.monotonic() + wait >= deadline - 1:
                    raise
                self._sleep(wait)
        text = getattr(response, "text", None)
        if not text:
            raise ValueError("empty response")
        return check_response_shape(json.loads(text))


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
        # A failing double has its own cache space, so cached answers don't hide the failure.
        self.cache_name = "scripted-fail" if fail else "scripted"

    def extract(self, payload: dict):
        self.payloads.append(dict(payload))
        if self.fail:
            raise RuntimeError("scripted failure")
        return [dict(f) for f in self.table.get(normalize(payload["text"]), [])]


# ---- Prepare AI reading (Phase 3C: reasons and fail fast) -------------------------------

@dataclass
class PrepareResult:
    results: list
    stopped_early: bool = False
    reasons: Counter = field(default_factory=Counter)

    @property
    def ok(self) -> int:
        return sum(1 for r in self.results if r.status == "ok")


def prepare(intake: Intake, reports, pace: float = 0.0, sleep=None, monotonic=None,
            on_progress=None) -> PrepareResult:
    """Read every report once to fill the server cache. Cached reports are
    skipped (no call). Real calls are paced `pace` seconds apart. If the first
    PREPARE_FAIL_FAST calls all fail with the same reason, stop there."""
    import time

    sleep = sleep or time.sleep
    monotonic = monotonic or time.monotonic
    out = PrepareResult([])
    calls, last_call = [], None
    reports = list(reports)
    for i, r in enumerate(reports, 1):
        cached = intake.cached(r)
        if not cached and pace and last_call is not None:
            wait = pace - (monotonic() - last_call)
            if wait > 0:
                sleep(wait)
        if not cached:
            last_call = monotonic()
        res = intake.read(r)
        out.results.append(res)
        if res.status != "ok":
            out.reasons[res.detail or res.message] += 1
        if not cached:
            calls.append(res)
        if on_progress:
            on_progress(i, len(reports))
        first = calls[:PREPARE_FAIL_FAST]
        if (len(calls) == PREPARE_FAIL_FAST and all(c.status != "ok" for c in first)
                and len({c.detail or c.message for c in first}) == 1):
            out.stopped_early = True
            break
    return out


def prepare_summary(res: PrepareResult, total: int) -> str:
    """One line per distinct failure reason, with counts."""
    lines = [f"Prepared: {res.ok} of {total} reports read and cached."]
    if res.stopped_early:
        reason = next(iter(res.reasons))
        lines.append(f"Stopped early: the first {PREPARE_FAIL_FAST} calls all failed with the "
                     f"same reason: {reason}. Fix the setting (for example GEMINI_MODEL, "
                     "GEMINI_THINKING or GEMINI_SCHEMA in Secrets) and press Prepare again.")
    for reason, n in res.reasons.most_common():
        lines.append(f"{n} × {reason}")
    return scrub("\n".join(lines))
