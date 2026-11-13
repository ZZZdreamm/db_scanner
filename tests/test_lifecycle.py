"""data.py's calendar against AWS's own lifecycle API (DescribeDBMajorEngineVersions).

The API gives the Extended Support period. Charges started later than that period for a few
versions (AWS announced a grace month), and those are listed here with the source of the date.
Refresh the fixture: aws rds describe-db-major-engine-versions --region eu-central-1 (free).
"""
import json
from pathlib import Path

import pytest

from eol_scan.data import CALENDAR

API = json.loads((Path(__file__).parent / "data" / "aws_lifecycle.json").read_text())["lifecycles"]
ES = "open-source-rds-extended-support"
# data.py names Aurora MySQL by Aurora major; the API by MySQL major.
API_MAJOR = {("aurora-mysql", "2"): "5.7", ("aurora-mysql", "3"): "8.0"}
# Charges began a month after the Extended Support period did (AWS announcements).
CHARGES_START_LATER = {
    ("postgres", "11"): "2024-04-01",
    ("aurora-postgresql", "11"): "2024-04-01",
    ("aurora-mysql", "2"): "2024-12-01",
}
# In data.py ahead of the API: dates assumed from the RDS release calendar. Re-check on refresh.
NOT_IN_API_YET = {("aurora-postgresql", "18")}

CASES = [(e, v) for e, vs in CALENDAR.items() for v, c in vs.items() if c["y1"]]


def api_period(engine, major):
    m = API_MAJOR.get((engine, major), major)
    for x in API:
        if x["engine"] == engine and x["major"] == m and ES in x["support"]:
            return tuple(x["support"][ES])
    return None


@pytest.mark.parametrize("engine,major", CASES)
def test_calendar_matches_aws_lifecycle(engine, major):
    cal = CALENDAR[engine][major]
    period = api_period(engine, major)
    if period is None:
        assert (engine, major) in NOT_IN_API_YET, f"{engine} {major} has no Extended Support dates in the AWS API"
        return
    start, end = period
    assert cal["end"] == end
    assert cal["y1"] == CHARGES_START_LATER.get((engine, major), start)


def test_every_api_extended_support_version_is_in_the_calendar():
    known = {(e, API_MAJOR.get((e, v), v)) for e, v in CASES}
    missing = [(x["engine"], x["major"]) for x in API if ES in x["support"] and (x["engine"], x["major"]) not in known]
    assert not missing
