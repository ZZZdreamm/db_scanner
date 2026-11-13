# eol-scan

Two things in one repo, both aimed at teams paying AWS RDS/Aurora Extended Support:

- `src/eol_scan/`: a read-only Python CLI that lists RDS and Aurora instances, works out which major versions are past standard support, and estimates the Extended Support charge (now, next 12 months, until support ends). Optional `--pg-dsn` runs read-only upgrade checks inside one PostgreSQL database.
- `site/index.html`: a single-file calculator page deployed to GitHub Pages by `.github/workflows/pages.yml`. `__REPO__` in it is replaced with `owner/name` at deploy time.

## Layout

- `src/eol_scan/data.py`: release calendars, regional rates, vCPU per instance size, upgrade notes. The calculator page has its own copy of the same data in its `<script>`; keep both in sync.
- `src/eol_scan/core.py`: pure logic (version parsing, cost). Unit-tested.
- `src/eol_scan/scanner.py`: boto3 calls (`rds:DescribeDBInstances`, `ec2:DescribeRegions` only).
- `src/eol_scan/pgcheck.py`: in-database checks; every query is tagged `/* eol-scan */` so it is excluded from the top-queries list.
- `src/eol_scan/report.py`: table, JSON and HTML output.
- `tests/`: pytest with moto (mocked AWS). Run `./start.sh test`.

## Rules

- The tool must stay read-only. Never add AWS calls that modify resources.
- Dates come from the AWS release calendars; rates are estimates and must be labelled as such.
- Product direction: the next feature is the paid part, testing query plans and latency on a restored snapshot of the new version.

## Repositories

- This folder is the PUBLIC repo `ZZZdreamm/db_scanner` (remote `origin`); it serves the calculator on GitHub Pages. Nothing private goes here.
- The upgrade labs (the paid part in the making) live in the private repo `ZZZdreamm/db_scanner-private`, checked out at `../db_scanner-lab`. It installs this repo editable, so changes to `eol_scan` belong here.
