from datetime import date

import boto3
import pytest
from moto import mock_aws

from eol_scan.cli import main
from eol_scan.core import evaluate, major_version, summarize, vcpu_for_class
from eol_scan.scanner import scan

TODAY = date(2026, 11, 12)


def test_major_version():
    assert major_version("postgres", "14.10") == "14"
    assert major_version("aurora-postgresql", "13.12") == "13"
    assert major_version("postgres", "9.6.24") == "9.6"
    assert major_version("mysql", "8.0.35") == "8.0"
    assert major_version("mysql", "5.7.44-rds.20240408") == "5.7"
    assert major_version("aurora-mysql", "8.0.mysql_aurora.3.05.2") == "3"
    assert major_version("aurora-mysql", "5.7.mysql_aurora.2.11.2") == "2"


def test_vcpu_for_class():
    assert vcpu_for_class("db.r6g.4xlarge") == 16
    assert vcpu_for_class("db.t3.medium") == 2
    assert vcpu_for_class("db.m5.xlarge") == 4
    assert vcpu_for_class("db.serverless") is None


def test_mysql80_frankfurt_is_paying_now():
    f = evaluate({"DBInstanceIdentifier": "crm", "Engine": "mysql", "EngineVersion": "8.0.40",
                  "DBInstanceClass": "db.r6g.2xlarge", "MultiAZ": False}, "eu-central-1", TODAY)
    assert f.status == "extended-y1-2"
    assert f.monthly_now == pytest.approx(8 * 0.122 * 730)
    assert f.next_12_months == pytest.approx(8 * 0.122 * 24 * 365)


def test_pg14_multi_az_counts_standby_and_starts_in_march():
    f = evaluate({"DBInstanceIdentifier": "orders", "Engine": "postgres", "EngineVersion": "14.12",
                  "DBInstanceClass": "db.r6g.4xlarge", "MultiAZ": True}, "us-east-1", TODAY)
    assert f.nodes == 2 and f.billed_vcpu == 32
    assert f.status == "standard" and f.monthly_now == 0
    days = (date(2027, 11, 12) - date(2027, 3, 1)).days
    assert f.next_12_months == pytest.approx(32 * 0.10 * 24 * days)


def test_year3_rate_doubles():
    f = evaluate({"DBInstanceIdentifier": "old", "Engine": "mysql", "EngineVersion": "5.7.44",
                  "DBInstanceClass": "db.m5.large", "MultiAZ": False}, "us-east-1", TODAY)
    assert f.status == "extended-y3"
    assert f.monthly_now == pytest.approx(2 * 0.20 * 730)


def test_supported_and_other_engines():
    f = evaluate({"DBInstanceIdentifier": "new", "Engine": "postgres", "EngineVersion": "17.4",
                  "DBInstanceClass": "db.r6g.large"}, "us-east-1", TODAY)
    assert f.status == "standard" and f.next_12_months == 0
    g = evaluate({"DBInstanceIdentifier": "ms", "Engine": "sqlserver-se", "EngineVersion": "15.00",
                  "DBInstanceClass": "db.m5.xlarge"}, "us-east-1", TODAY)
    assert g.status == "not-covered"


@mock_aws
def test_scan_with_mocked_aws(tmp_path, capsys):
    session = boto3.Session(region_name="eu-central-1")
    rds = session.client("rds")
    rds.create_db_instance(DBInstanceIdentifier="crm", Engine="mysql", EngineVersion="8.0.40",
                           DBInstanceClass="db.r6g.2xlarge", AllocatedStorage=20,
                           MasterUsername="admin", MasterUserPassword="password123")
    rds.create_db_instance(DBInstanceIdentifier="orders", Engine="postgres", EngineVersion="14.12",
                           DBInstanceClass="db.r6g.4xlarge", AllocatedStorage=20, MultiAZ=True,
                           MasterUsername="admin", MasterUserPassword="password123")
    rds.create_db_instance(DBInstanceIdentifier="fresh", Engine="postgres", EngineVersion="17.4",
                           DBInstanceClass="db.t3.medium", AllocatedStorage=20,
                           MasterUsername="admin", MasterUserPassword="password123")
    findings, errors = scan(session, ["eu-central-1"], TODAY)
    assert not errors
    by_id = {f.identifier: f for f in findings}
    assert set(by_id) == {"crm", "orders", "fresh"}
    s = summarize(findings)
    assert s["in_extended_support"] == 1
    assert s["entering_within_12_months"] == 1
    assert s["monthly_now"] == pytest.approx(8 * 0.122 * 730, rel=1e-6)

    out = tmp_path / "report.html"
    assert main(["--regions", "eu-central-1", "--as-of", "2026-11-12", "--format", "html", "-o", str(out)]) == 0
    html = out.read_text()
    assert "crm" in html and "orders" in html and "fresh" not in html

    assert main(["--regions", "eu-central-1", "--as-of", "2026-11-12"]) == 0
    table = capsys.readouterr().out
    assert "Paying now" in table and "$712 / month" in table
