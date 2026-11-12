"""Render findings as a terminal table, JSON or a self-contained HTML report."""
from __future__ import annotations

import html
import json
from datetime import date

from .core import Finding

STATUS_LABEL = {
    "standard": "standard support",
    "extended-y1-2": "EXTENDED SUPPORT (yr 1-2)",
    "extended-y3": "EXTENDED SUPPORT (yr 3+)",
    "ended": "support ended",
    "not-covered": "engine not covered",
    "unknown-version": "unknown version",
    "unknown-size": "unknown size",
}


def usd(n: float) -> str:
    return f"${n:,.0f}"


def _relevant(findings: list[Finding], show_all: bool) -> list[Finding]:
    if show_all:
        return findings
    return [f for f in findings if f.monthly_now > 0 or f.next_12_months > 0 or f.status in ("ended", "unknown-size", "unknown-version")]


def to_table(findings: list[Finding], summary: dict, today: date, show_all: bool = False) -> str:
    rows = sorted(_relevant(findings, show_all), key=lambda f: (-f.monthly_now, -f.next_12_months))
    head = ["REGION", "DATABASE", "ENGINE", "VERSION", "CLASS", "vCPU", "STATUS", "NOW/MO", "NEXT 12 MO", "STARTS/ENDS"]
    data = []
    for f in rows:
        when = f.charges_start if f.status == "standard" else (f.rate_doubles if f.status == "extended-y1-2" and f.rate_doubles else f.support_ends)
        data.append([f.region, f.identifier, f.engine, f.version, f.instance_class, str(f.billed_vcpu),
                     STATUS_LABEL.get(f.status, f.status), usd(f.monthly_now), usd(f.next_12_months), when or "-"])
    widths = [max(len(h), *(len(r[i]) for r in data)) if data else len(h) for i, h in enumerate(head)]
    line = lambda cells: "  ".join(c.ljust(w) for c, w in zip(cells, widths))
    out = [
        f"Extended Support scan, {today.isoformat()}",
        "",
        f"  Paying now:        {usd(summary['monthly_now'])} / month",
        f"  Next 12 months:    {usd(summary['next_12_months'])}",
        f"  Until support end: {usd(summary['until_end'])}",
        f"  Databases: {summary['databases_scanned']} scanned, {summary['in_extended_support']} in Extended Support, "
        f"{summary['entering_within_12_months']} entering within 12 months",
        "",
    ]
    if data:
        out += [line(head), line(["-" * w for w in widths])] + [line(r) for r in data]
    else:
        out.append("No databases on versions that cost extra in the next 12 months.")
    out += ["", "Rates are estimates; confirm on the AWS pricing page. Use --all to list every database."]
    return "\n".join(out)


def to_json(findings: list[Finding], summary: dict, today: date, errors: list[str]) -> str:
    return json.dumps({"as_of": today.isoformat(), "summary": summary, "errors": errors,
                       "databases": [f.to_dict() for f in findings]}, indent=2)


def to_html(findings: list[Finding], summary: dict, today: date, errors: list[str], pg: dict | None = None) -> str:
    e = html.escape
    rows = sorted(_relevant(findings, False), key=lambda f: (-f.monthly_now, -f.next_12_months))
    trs = "".join(
        f"<tr><td>{e(f.region)}</td><td><b>{e(f.identifier)}</b></td><td>{e(f.engine)} {e(f.version)}</td>"
        f"<td>{e(f.instance_class)} × {f.nodes}</td><td class='n'>{f.billed_vcpu}</td>"
        f"<td><span class='pill {e(f.status)}'>{e(STATUS_LABEL.get(f.status, f.status))}</span></td>"
        f"<td class='n'>{usd(f.monthly_now)}</td><td class='n'>{usd(f.next_12_months)}</td>"
        f"<td>{e(f.charges_start or '-')}</td><td>{e(f.target or '-')}</td></tr>"
        for f in rows
    ) or "<tr><td colspan='10'>No databases on versions that cost extra in the next 12 months.</td></tr>"
    notes = {}
    for f in rows:
        if f.notes:
            notes.setdefault(f"{f.engine} {f.major} → {f.target}", f.notes)
    notes_html = "".join(
        f"<section class='note'><h3>{e(k)}</h3><ul>{''.join(f'<li>{e(n)}</li>' for n in v)}</ul></section>"
        for k, v in notes.items()
    )
    pg_html = ""
    if pg:
        items = "".join(f"<li class='bad'>{e(b)}</li>" for b in pg.get("blockers", []))
        items += "".join(f"<li>{e(w)}</li>" for w in pg.get("warnings", []))
        exts = ", ".join(f"{x['name']} {x['version']}" for x in pg.get("extensions", []))
        q = "".join(f"<tr><td class='n'>{x['calls']:,}</td><td class='n'>{x['mean_ms']}</td><td><code>{e(x['query'])}</code></td></tr>"
                    for x in pg.get("top_queries", []))
        pg_html = (f"<h2>Database checks (PostgreSQL {e(pg.get('server_version', '?'))})</h2>"
                   f"<ul>{items or '<li>No upgrade blockers found.</li>'}</ul><p><b>Extensions:</b> {e(exts) or 'none'}</p>"
                   + (f"<h3>Queries to test on the new version</h3><table><tr><th>Calls</th><th>Mean ms</th><th>Query</th></tr>{q}</table>" if q else ""))
    err_html = "".join(f"<li>{e(x)}</li>" for x in errors)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Extended Support scan {today.isoformat()}</title><style>
:root{{--bg:#f4f6f6;--card:#fff;--ink:#15201f;--muted:#5b6967;--line:#d9e0df;--accent:#0f6b62;--warn:#9a5b00;--warnbg:#fbefd9;--crit:#a3331f;--critbg:#f8e3de;--ok:#2f7d4f;--okbg:#e4f2e9}}
body{{margin:0;padding:32px max(16px,4vw);background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}}
h1{{margin:0 0 4px;font-size:28px}} h2{{margin:32px 0 10px;font-size:19px}} h3{{margin:0 0 6px;font-size:15px}}
.muted{{color:var(--muted)}} .big{{display:flex;flex-wrap:wrap;gap:16px;margin:20px 0}}
.tile{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 18px;min-width:180px}}
.tile b{{display:block;font:600 28px ui-monospace,Menlo,monospace}} .tile.hot b{{color:var(--crit)}}
.scroll{{overflow-x:auto}} table{{border-collapse:collapse;width:100%;background:var(--card);font-size:14px}}
th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}} th{{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}}
.n{{text-align:right;font-family:ui-monospace,Menlo,monospace;white-space:nowrap}}
.pill{{font-size:12px;font-weight:600;padding:2px 8px;border-radius:99px;white-space:nowrap;background:var(--okbg);color:var(--ok)}}
.pill.extended-y1-2{{background:var(--warnbg);color:var(--warn)}} .pill.extended-y3,.pill.ended{{background:var(--critbg);color:var(--crit)}}
.notes{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}} .note{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 18px}}
.note ul{{margin:0;padding-left:18px}} li.bad{{color:var(--crit);font-weight:600}} code{{font-size:12px}}
</style></head><body>
<h1>Extended Support scan</h1><p class="muted">As of {today.isoformat()} · {summary['databases_scanned']} databases scanned · generated by eol-scan</p>
<div class="big"><div class="tile hot"><span class="muted">Paying now</span><b>{usd(summary['monthly_now'])}/mo</b></div>
<div class="tile"><span class="muted">Next 12 months</span><b>{usd(summary['next_12_months'])}</b></div>
<div class="tile"><span class="muted">Until support ends</span><b>{usd(summary['until_end'])}</b></div></div>
<h2>Databases that cost extra now or within 12 months</h2>
<div class="scroll"><table><tr><th>Region</th><th>Database</th><th>Engine</th><th>Class × nodes</th><th>vCPU</th><th>Status</th><th>Now / mo</th><th>Next 12 mo</th><th>Charges start</th><th>Upgrade to</th></tr>{trs}</table></div>
{('<h2>What to check before upgrading</h2><div class="notes">' + notes_html + '</div>') if notes_html else ''}
{pg_html}
{('<h2>Regions that could not be read</h2><ul>' + err_html + '</ul>') if err_html else ''}
<p class="muted">Costs assume nodes run 24/7 at on-demand Extended Support rates for each region. Rates are estimates; confirm on the AWS pricing page before quoting a number.</p>
</body></html>"""
