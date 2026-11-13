"""Pure logic: version parsing, vCPU lookup and Extended Support cost."""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta

from .data import (CALENDAR, DEFAULT_RATE, ENDED, RATES, SIZE_VCPU, SMALL_VCPU_NON_BURSTABLE, SMALL_VCPU_T2,
                   TARGET, UPGRADE_NOTES)

ES_DISABLED = "open-source-rds-extended-support-disabled"

HOURS_PER_MONTH = 730


def major_version(engine: str, version: str) -> str | None:
    """Map an RDS engine version string to the key used in the release calendar."""
    if not version:
        return None
    if engine == "aurora-mysql":
        if version.startswith("8.4"):
            return "8.4"
        m = re.search(r"mysql_aurora\.(\d+)", version)
        if m:
            return m.group(1)
        if version.startswith("5.6"):
            return "1"
        if version.startswith("5.7"):
            return "2"
        if version.startswith("8.0"):
            return "3"
        return None
    if engine in ("postgres", "aurora-postgresql"):
        m = re.match(r"(\d+)(?:\.(\d+))?", version)
        if not m:
            return None
        return m.group(1) if int(m.group(1)) >= 10 else f"{m.group(1)}.{m.group(2)}"
    if engine == "mysql":
        m = re.match(r"(\d+\.\d+)", version)
        return m.group(1) if m else None
    return None


def vcpu_for_class(instance_class: str) -> int | None:
    """db.r6g.4xlarge -> 16. Returns None for serverless or unknown classes."""
    if not instance_class or instance_class == "db.serverless":
        return None
    parts = instance_class.split(".")
    if len(parts) != 3:  # e.g. db.r5.large.tpc2.mem2x (Optimize CPU) or db.r7i.metal-48xl
        return None
    _, family, size = parts
    if family.startswith("t2") and size in SMALL_VCPU_T2:
        return SMALL_VCPU_T2[size]
    if not family.startswith("t") and size in SMALL_VCPU_NON_BURSTABLE:
        return SMALL_VCPU_NON_BURSTABLE[size]
    return SIZE_VCPU.get(size)


def _d(s: str) -> date:
    return date.fromisoformat(s)


def rate_on(day: date, cal: dict, region: str) -> float | None:
    """USD per vCPU-hour on a given day; 0 before Extended Support, None after it ends."""
    r1, r3 = RATES.get(region, DEFAULT_RATE)
    if day < _d(cal["y1"]):
        return 0.0
    if day > _d(cal["end"]):
        return None
    if cal.get("y3") and day >= _d(cal["y3"]):
        return r3
    return r1


@dataclass
class Finding:
    region: str
    identifier: str
    engine: str
    version: str
    major: str | None
    instance_class: str
    vcpu_per_node: int | None
    nodes: int
    billed_vcpu: int
    status: str            # standard | extended-y1-2 | extended-y3 | ended | es-disabled | not-covered
                           # | unknown-version | unknown-size | serverless
    monthly_now: float = 0.0
    next_12_months: float = 0.0
    until_end: float = 0.0
    charges_start: str | None = None
    rate_doubles: str | None = None
    support_ends: str | None = None
    target: str | None = None
    lifecycle: str | None = None
    cluster: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def notes_key(engine: str, major: str) -> str:
    if engine in ("postgres", "aurora-postgresql"):
        try:
            return "pg-old" if float(major) <= 14 else "pg-new"
        except ValueError:
            return "pg-old"
    if major in ("5.7", "2", "1"):
        return "mysql57"
    return "mysql80"


def evaluate(db: dict, region: str, today: date) -> Finding:
    """Turn one DescribeDBInstances entry into a Finding."""
    engine = db.get("Engine", "")
    version = db.get("EngineVersion", "")
    klass = db.get("DBInstanceClass", "")
    major = major_version(engine, version) if engine in CALENDAR else None
    vcpu = vcpu_for_class(klass)
    aurora = engine.startswith("aurora")
    # A Multi-AZ (instance) deployment bills its hidden standby too. Aurora readers
    # and RDS read replicas show up as their own instances, so they are counted there.
    nodes = 2 if (db.get("MultiAZ") and not aurora and not db.get("DBClusterIdentifier")) else 1
    f = Finding(
        region=region, identifier=db.get("DBInstanceIdentifier", "?"), engine=engine, version=version,
        major=major, instance_class=klass, vcpu_per_node=vcpu, nodes=nodes,
        billed_vcpu=(vcpu or 0) * nodes, status="standard",
        lifecycle=db.get("EngineLifecycleSupport"), cluster=db.get("DBClusterIdentifier"),
    )
    if engine not in CALENDAR:
        f.status = "not-covered"
        return f
    cal = CALENDAR[engine].get(major or "")
    if cal is None:
        f.status = "ended" if major in ENDED.get(engine, ()) else "unknown-version"
        return f
    if cal["y1"] is None:  # standard support, Extended Support dates not announced yet
        return f
    f.charges_start, f.rate_doubles, f.support_ends = cal["y1"], cal.get("y3"), cal["end"]
    f.target = TARGET.get(engine)
    f.notes = UPGRADE_NOTES[notes_key(engine, major)]
    if f.lifecycle == ES_DISABLED:
        # Opted out of Extended Support: never billed, AWS upgrades it at the end of standard support.
        f.status = "es-disabled"
        return f
    if vcpu is None:
        f.status = "serverless" if klass == "db.serverless" else "unknown-size"
    now_rate = rate_on(today, cal, region)
    if now_rate is None:
        f.status = "ended"
        return f
    if f.status not in ("unknown-size", "serverless"):
        if now_rate == 0:
            f.status = "standard"
        elif cal.get("y3") and today >= _d(cal["y3"]):
            f.status = "extended-y3"
        else:
            f.status = "extended-y1-2"
    v = f.billed_vcpu
    f.monthly_now = v * (now_rate or 0) * HOURS_PER_MONTH
    end = _d(cal["end"])
    day = today
    while day <= end:
        r = rate_on(day, cal, region) or 0.0
        cost = v * r * 24
        f.until_end += cost
        if day < today + timedelta(days=365):
            f.next_12_months += cost
        day += timedelta(days=1)
    return f


def summarize(findings: list[Finding]) -> dict:
    paying = [f for f in findings if f.monthly_now > 0]
    upcoming = [f for f in findings if f.status == "standard" and f.next_12_months > 0]
    return {
        "databases_scanned": len(findings),
        "in_extended_support": len(paying),
        "entering_within_12_months": len(upcoming),
        "monthly_now": round(sum(f.monthly_now for f in findings), 2),
        "next_12_months": round(sum(f.next_12_months for f in findings), 2),
        "until_end": round(sum(f.until_end for f in findings), 2),
    }
