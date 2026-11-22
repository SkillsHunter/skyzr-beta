"""SKYZR engine: the rules as pure functions. No Streamlit import, ever.

Phase 0 holds only data loading and the startup checks (plan v2 §3 item 7).
`state_at(cursor, events)` arrives in Phase 1 and will be the only thing that
computes state.
"""

from __future__ import annotations

import json
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
