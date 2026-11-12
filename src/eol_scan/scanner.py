"""AWS side: list RDS and Aurora instances, read-only."""
from __future__ import annotations

from datetime import date

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from .core import Finding, evaluate


def enabled_regions(session: boto3.Session) -> list[str]:
    ec2 = session.client("ec2", region_name=session.region_name or "us-east-1")
    resp = ec2.describe_regions(AllRegions=False)
    return sorted(r["RegionName"] for r in resp["Regions"])


def scan_region(session: boto3.Session, region: str, today: date) -> tuple[list[Finding], str | None]:
    """Return findings for one region and an error message if the region could not be read."""
    rds = session.client("rds", region_name=region)
    findings: list[Finding] = []
    try:
        for page in rds.get_paginator("describe_db_instances").paginate():
            for db in page["DBInstances"]:
                findings.append(evaluate(db, region, today))
    except (ClientError, BotoCoreError) as e:
        return findings, f"{region}: {e}"
    return findings, None


def scan(session: boto3.Session, regions: list[str], today: date, progress=None) -> tuple[list[Finding], list[str]]:
    all_findings: list[Finding] = []
    errors: list[str] = []
    for region in regions:
        if progress:
            progress(region)
        found, err = scan_region(session, region, today)
        all_findings.extend(found)
        if err:
            errors.append(err)
    return all_findings, errors
