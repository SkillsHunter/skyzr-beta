"""Phase 0: the app's startup checks (plan v2 §3 item 7), run without Streamlit."""

import copy
import sys

import pytest

import engine


@pytest.fixture(scope="module")
def geojson():
    return engine.load_geojson()


@pytest.fixture(scope="module")
def tables():
    return engine.load_scenario_csvs()


@pytest.mark.parametrize("module", ["engine", "ai"])
def test_module_does_not_import_streamlit(module):
    """Checked in a fresh interpreter: other test files (the app form test)
    import Streamlit into this process, so sys.modules here can't tell."""
    import subprocess
    from pathlib import Path

    code = f"import sys, {module}; print('streamlit' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=Path(__file__).parent.parent, check=True)
    assert out.stdout.strip() == "False"


def test_map_has_100_features(geojson):
    assert len(geojson["features"]) == 100


def test_map_has_100_unique_fips_as_text(geojson):
    ids = [f["id"] for f in geojson["features"]]
    assert len(set(ids)) == 100
    assert all(isinstance(i, str) and len(i) == 5 and i.isdigit() for i in ids)


@pytest.mark.parametrize("name", engine.SCENARIO_CSVS)
def test_csv_fips_read_as_text(tables, name):
    values = tables[name]["fips"].tolist()
    assert values, f"{name} is empty"
    assert all(isinstance(v, str) and len(v) == 5 and v.isdigit() for v in values)


@pytest.mark.parametrize("name", engine.SCENARIO_CSVS)
def test_every_csv_county_matches_a_shape(geojson, tables, name):
    shapes = engine.county_shapes(geojson)
    pairs = tables[name][["fips", "county"]].drop_duplicates()
    for fips, county in pairs.itertuples(index=False):
        assert fips in shapes, f"{name}: {fips} ({county}) has no shape"
        assert shapes[fips] == county, f"{name}: {fips} is {county} vs {shapes[fips]}"


def test_stock_covers_all_100_counties(geojson, tables):
    assert set(tables["stock.csv"]["fips"]) == set(engine.county_shapes(geojson))


def test_startup_checks_pass_on_real_data(geojson, tables):
    assert engine.startup_checks(geojson, tables) == []


# The checks must be able to fail, or they prove nothing.

def test_check_catches_missing_feature(geojson, tables):
    broken = copy.deepcopy(geojson)
    broken["features"].pop()
    problems = engine.startup_checks(broken, tables)
    assert any("99 features" in p for p in problems)


def test_check_catches_duplicate_fips(geojson, tables):
    broken = copy.deepcopy(geojson)
    broken["features"][1]["id"] = broken["features"][0]["id"]
    problems = engine.startup_checks(broken, tables)
    assert any("unique FIPS" in p for p in problems)


def test_check_catches_numeric_fips(geojson, tables):
    broken = {k: v.copy() for k, v in tables.items()}
    broken["stock.csv"]["fips"] = broken["stock.csv"]["fips"].astype(int)
    problems = engine.startup_checks(geojson, broken)
    assert any("stock.csv" in p and "not 5-character text" in p for p in problems)


def test_check_catches_unmatched_county(geojson, tables):
    broken = {k: v.copy() for k, v in tables.items()}
    df = broken["reports.csv"]
    df.loc[df.index[0], "county"] = "Atlantis"
    problems = engine.startup_checks(geojson, broken)
    assert any("Atlantis" in p for p in problems)
