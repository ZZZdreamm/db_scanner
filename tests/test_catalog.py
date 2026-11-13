"""Every engine version and instance class AWS offers today must be understood by eol-scan."""
import json
from datetime import date
from pathlib import Path

import pytest

from eol_scan.core import evaluate, major_version, vcpu_for_class
from eol_scan.data import CALENDAR

CATALOG = json.loads((Path(__file__).parent / "data" / "aws_catalog.json").read_text())
TODAY = date(2026, 11, 12)
COVERED = set(CALENDAR)


@pytest.mark.parametrize("engine,version", CATALOG["engine_versions"])
def test_every_engine_version_has_a_known_status(engine, version):
    f = evaluate({"Engine": engine, "EngineVersion": version, "DBInstanceClass": "db.r6g.large"}, "eu-central-1", TODAY)
    if engine in COVERED:
        assert f.status in ("standard", "extended-y1-2", "extended-y3", "ended"), (engine, version, f.major)
    else:
        # SQL Server, Oracle, Db2, MariaDB, RDS Custom, DocumentDB, Neptune: no RDS Extended Support charges.
        assert f.status == "not-covered" and f.monthly_now == 0


@pytest.mark.parametrize("klass,vcpu", sorted(CATALOG["instance_classes"].items()))
def test_every_orderable_class_has_the_ec2_vcpu_count(klass, vcpu):
    assert vcpu_for_class(klass) == vcpu


def test_catalog_covers_all_covered_engines():
    engines = {e for e, _ in CATALOG["engine_versions"]}
    assert COVERED <= engines
    assert len(CATALOG["instance_classes"]) > 200


def test_aurora_mysql_84_is_standard_until_dates_are_announced():
    assert major_version("aurora-mysql", "8.4.mysql_aurora.8.4.10") == "8.4"
    f = evaluate({"Engine": "aurora-mysql", "EngineVersion": "8.4.mysql_aurora.8.4.10",
                  "DBInstanceClass": "db.r7g.xlarge"}, "eu-central-1", TODAY)
    assert f.status == "standard" and f.next_12_months == 0 and f.until_end == 0


@pytest.mark.parametrize("engine,version", [("postgres", "9.4.26"), ("postgres", "9.5.25"), ("mysql", "5.5.62"),
                                            ("aurora-mysql", "5.6.10a")])
def test_versions_older_than_the_calendar_have_ended(engine, version):
    f = evaluate({"Engine": engine, "EngineVersion": version, "DBInstanceClass": "db.m5.large"}, "eu-central-1", TODAY)
    assert f.status == "ended" and f.monthly_now == 0


def test_small_classes_that_break_the_size_pattern():
    assert vcpu_for_class("db.t2.micro") == 1
    assert vcpu_for_class("db.t2.small") == 1
    assert vcpu_for_class("db.t3.small") == 2
    assert vcpu_for_class("db.t4g.medium") == 2
    assert vcpu_for_class("db.c6gd.medium") == 1
    assert vcpu_for_class("db.r5.large.tpc2.mem2x") is None
