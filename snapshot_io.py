"""AI readings snapshot file (Phase 3F): reading and writing data/ai_readings.json.

ai.py holds the rules (export, shape check, quote check) and never reads files;
this module does the file work around them. It reads only reports.csv and the
snapshot, never answer_key.csv.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path

import ai

DATA_DIR = Path(__file__).parent / "data"
SNAPSHOT_PATH = DATA_DIR / "ai_readings.json"
REPORTS_PATH = DATA_DIR / "reports.csv"


def reports_sha256(path: Path = REPORTS_PATH) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def reports_by_id(path: Path = REPORTS_PATH) -> dict:
    """report_id -> {sim_hour, source, verified, text, ...} from reports.csv."""
    text = Path(path).read_text(encoding="utf-8")
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        row = dict(row)
        row["sim_hour"] = int(row["sim_hour"])
        out[str(row["report_id"])] = row
    return out


def export_snapshot(namespace: str, cache: ai.SharedCache | None = None) -> dict:
    return ai.export_snapshot(reports_by_id(), reports_sha256(), namespace, cache)


def export_snapshot_json(namespace: str, cache: ai.SharedCache | None = None) -> str:
    return json.dumps(export_snapshot(namespace, cache), ensure_ascii=False, indent=1)


def load_snapshot(path=SNAPSHOT_PATH, namespace: str = ai.GEMINI_CACHE_NAME,
                  cache: ai.SharedCache | None = None) -> ai.LoadResult:
    """No file: nothing loaded, no error. Bad JSON: nothing loaded, reason recorded."""
    path = Path(path)
    if not path.exists():
        return ai.LoadResult(error="no snapshot file")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        return ai.LoadResult(error=f"could not read the snapshot ({type(err).__name__})")
    return ai.load_snapshot_data(data, reports_by_id(), namespace, reports_sha256(), cache)
