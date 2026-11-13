"""The calculator page keeps its own copy of the calendars and rates; keep it in sync with data.py."""
import re
from pathlib import Path

from eol_scan.data import CALENDAR, RATES

SITE = (Path(__file__).resolve().parents[1] / "site" / "index.html").read_text(encoding="utf-8")

ENGINE_MAP = {"rds-pg": "postgres", "aurora-pg": "aurora-postgresql", "rds-mysql": "mysql", "aurora-mysql": "aurora-mysql"}


def _site_versions(key):
    block = re.search(r'"%s":\s*\{.*?versions:\s*\{(.*?)\}\}' % key, SITE, re.S).group(1)
    out = {}
    for ver, y1, y3, end in re.findall(
        r'"([^"]+)":\s*\{\s*y1:\s*"([\d-]+)",\s*y3:\s*(?:"([\d-]+)"|null),\s*end:\s*"([\d-]+)"', block
    ):
        out[ver.split(" ")[0]] = {"y1": y1, "y3": y3 or None, "end": end}
    return out


def test_calendars_match():
    for site_key, engine in ENGINE_MAP.items():
        # Versions whose Extended Support dates AWS has not announced have nothing to calculate.
        dated = {v: c for v, c in CALENDAR[engine].items() if c["y1"]}
        assert _site_versions(site_key) == dated, site_key


def test_postgres_18_on_page():
    assert "18" in _site_versions("rds-pg")
    assert "18" in _site_versions("aurora-pg")


def test_region_rates_match():
    rows = re.findall(r'\["([a-z0-9-]+)",\s*"[^"]+",\s*([\d.]+),\s*([\d.]+)\]', SITE)
    assert rows
    for region, r1, r3 in rows:
        assert RATES[region] == (float(r1), float(r3)), region
