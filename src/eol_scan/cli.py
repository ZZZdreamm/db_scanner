"""eol-scan: find RDS and Aurora databases that cost extra in Extended Support."""
from __future__ import annotations

import argparse
import sys
from datetime import date

from . import __version__
from .core import summarize
from .report import to_html, to_json, to_table


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="eol-scan", description=__doc__)
    p.add_argument("--profile", help="AWS profile to use")
    p.add_argument("--regions", help="comma-separated regions (default: the profile's region)")
    p.add_argument("--all-regions", action="store_true", help="scan every region enabled in the account")
    p.add_argument("--format", choices=["table", "json", "html"], default="table")
    p.add_argument("-o", "--output", help="write the report to this file instead of stdout")
    p.add_argument("--all", action="store_true", help="list every database, not only the ones that cost extra")
    p.add_argument("--as-of", help="evaluate as if today were YYYY-MM-DD (what-if)")
    p.add_argument("--pg-dsn", help="also run read-only upgrade checks inside this PostgreSQL database")
    p.add_argument("--mysql-dsn", help="also run read-only upgrade checks inside this MySQL server, "
                                       "e.g. mysql://user:password@host:3306/dbname")
    p.add_argument("--version", action="version", version=f"eol-scan {__version__}")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    import boto3
    from .scanner import enabled_regions, scan

    today = date.fromisoformat(args.as_of) if args.as_of else date.today()
    session = boto3.Session(profile_name=args.profile) if args.profile else boto3.Session()
    if args.all_regions:
        regions = enabled_regions(session)
    elif args.regions:
        regions = [r.strip() for r in args.regions.split(",") if r.strip()]
    else:
        regions = [session.region_name or "us-east-1"]

    def progress(region):
        print(f"scanning {region} ...", file=sys.stderr)

    findings, errors = scan(session, regions, today, progress=progress)
    summary = summarize(findings)

    pg = None
    if args.pg_dsn:
        from .pgcheck import check_postgres
        pg = check_postgres(args.pg_dsn)
    my = None
    if args.mysql_dsn:
        from .mysqlcheck import check_mysql
        my = check_mysql(args.mysql_dsn)

    if args.format == "json":
        text = to_json(findings, summary, today, errors)
        if pg:
            import json
            d = json.loads(text); d["postgres_checks"] = pg; text = json.dumps(d, indent=2)
        if my:
            import json
            d = json.loads(text); d["mysql_checks"] = my; text = json.dumps(d, indent=2)
    elif args.format == "html":
        text = to_html(findings, summary, today, errors, pg, my)
    else:
        text = to_table(findings, summary, today, show_all=args.all)
        for title, chk in (("PostgreSQL", pg), ("MySQL", my)):
            if not chk:
                continue
            target = f", upgrade to {chk['target']}" if chk.get("target") else ""
            text += f"\n\n{title} checks ({chk.get('server_version', '?')}{target}):\n"
            for b in chk["blockers"]:
                text += f"  BLOCKER  {b}\n"
            for w in chk["warnings"]:
                text += f"  note     {w}\n"
            if not chk["blockers"]:
                text += "  No upgrade blockers found.\n"
            for q in chk.get("top_queries", [])[:10]:
                text += f"  {q['calls']:>10,} calls  {q['mean_ms']:>9} ms  {q['query'][:90]}\n"
        for err in errors:
            text += f"\nwarning: could not read {err}"

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"report written to {args.output}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
