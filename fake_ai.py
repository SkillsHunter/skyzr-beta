"""TEST DOUBLE ONLY: scripted AI answers for localhost checks and tests.

Used only when the environment variable SKYZR_FAKE_AI is set (never on the
deployed app). Written by hand from the public report texts in
data/reports.csv; it is not the answer key and not the hidden scoring key.
SKYZR_FAKE_AI=fail makes every call fail ("AI unavailable").
"""

import ai
import engine


def _f(county, what, metric, value, status, quote):
    return {"county": county, "lifeline_or_resource": what, "metric": metric,
            "value": value, "status_word": status, "quote": quote}


BY_ID = {
    "R01": [_f("New Hanover", "Roads", "Route status", "No open route to county seat",
               "No route", "there is no open route into Wilmington, the county seat")],
    "R03": [_f("New Hanover", "Water", "System status", "Boil-water notice", "Boil notice",
               "A boil-water notice is in effect for all customers")],
    # An invented quote: the quote check must reject it (Fix 5).
    "R04": [_f("New Hanover", "Health and Medical", "Hospital status",
               "Hospital closed or evacuating", "Closed", "the hospital has closed its doors")],
    "R10": [_f("New Hanover", "Generators", "Requested", 7, "Requested", "seven generators"),
            _f("New Hanover", "Water", "Requested", 1, "Requested", "one water tanker")],
    "R13": [_f("Robeson", "Water", "Systems out of service", 3, "Out",
               "three municipal water systems are offline"),
            _f("Robeson", "Health and Medical", "Hospital status",
               "Hospital on generator or diverting", "On generator",
               "a hospital in Lumberton is on generator")],
    "R16": [_f("Robeson", "Water", "Requested", 4, "Requested", "four water tankers"),
            _f("Robeson", "Sanitation", "Requested", 16, "Requested",
               "roughly sixteen portable toilet and handwashing units")],
    "R22": [_f("Scotland", "Water", "Systems out of service", 1, "Out",
               "Laurinburg's water system is out of service"),
            _f("Scotland", "Roads", "Route status", "Open", "Open", "Roads are open")],
    "R23": [_f("Moore", "Water", "Systems out of service", 2, "Out",
               "Two water systems are out of service")],
    "R26": [_f("Moore", "Water", "Systems out of service", 5, "Out",
               "five water systems out of service")],
    # Unverified social post: must never turn Scotland's water green.
    "R39": [_f("Scotland", "Water", "System status", "Normal", "Normal",
               "water is back everywhere in scotland county")],
    "R44": [_f("Robeson", "Water", "System status", "Boil-water notice", "Boil notice",
               "a boil-water notice remains in effect")],
}


def scripted_table() -> dict:
    reports = engine.default_scenario().reports
    return {reports[rid]["text"]: facts for rid, facts in BY_ID.items()}


def client(fail: bool = False) -> ai.ScriptedClient:
    return ai.ScriptedClient(scripted_table(), fail=fail)
