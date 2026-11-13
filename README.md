# eol-scan

Find the Amazon RDS and Aurora databases you pay **Extended Support** for, see what they will cost over the next 12 months, and get a checklist of what to fix before upgrading.

AWS charges Extended Support per vCPU-hour on every node (primary, read replicas, Multi-AZ standbys) of a major version past its end of standard support. The rate doubles in year three. `eol-scan` reads your fleet, read-only, and adds it up.

```
$ eol-scan --all-regions

Extended Support scan, 2026-11-12

  Paying now:        $1,069 / month
  Next 12 months:    $36,811
  Until support end: $191,368
  Databases: 4 scanned, 2 in Extended Support, 1 entering within 12 months

REGION        DATABASE  ENGINE    VERSION  CLASS           vCPU  STATUS                     NOW/MO  NEXT 12 MO  STARTS/ENDS
eu-central-1  crm       mysql     8.0.40   db.r6g.2xlarge  8     EXTENDED SUPPORT (yr 1-2)  $712    $8,550      2028-08-01
eu-central-1  billing   postgres  13.15    db.m6g.xlarge   4     EXTENDED SUPPORT (yr 1-2)  $356    $4,275      2028-03-01
eu-central-1  orders    postgres  14.12    db.r6g.4xlarge  32    standard support           $0      $23,986     2027-03-01
```

## Quick start

```
./start.sh            # install, test, scan your AWS account, publish the calculator
./start.sh scan       # only the scan
./start.sh deploy     # create the GitHub repo and deploy site/ to GitHub Pages
./start.sh preview    # open the calculator locally on http://localhost:8000
```

The repository also contains `site/`, a one-page Extended Support calculator that needs no AWS access. It is deployed to GitHub Pages by `.github/workflows/pages.yml` on every push to `main` that changes `site/`.

## Install

```
pip install .            # from this folder
pip install '.[pg]'      # also enables the in-database PostgreSQL checks
pip install '.[mysql]'   # also enables the in-database MySQL checks
```

## Use

```
eol-scan                                   # the region of your default AWS profile
eol-scan --profile prod --all-regions      # every enabled region of an account
eol-scan --regions eu-central-1,eu-west-1 --format html -o report.html
eol-scan --format json                     # for scripts and dashboards
eol-scan --as-of 2027-03-01                # what-if: the bill on a future date
eol-scan --all                             # list every database, not only the costly ones
```

### In-database checks (PostgreSQL)

```
eol-scan --pg-dsn "host=mydb.xxxx.eu-central-1.rds.amazonaws.com dbname=app user=readonly" --format html -o report.html
```

The session is set to read-only. It reports:

- logical replication slots that must be dropped before upgrading from versions below 17,
- columns using `reg*` types that `pg_upgrade` cannot carry over,
- installed extensions and their versions,
- the 20 queries with the highest total time from `pg_stat_statements`, as the list to test on the new version.

### In-database checks (MySQL)

```
eol-scan --mysql-dsn "mysql://readonly:password@mydb.xxxx.eu-central-1.rds.amazonaws.com:3306/app" --format html -o report.html
```

The session is set to read-only. For the next major version (5.7 → 8.0, 8.0 → 8.4) it reports:

- tables, columns and routines named after words that become reserved (`rank`, `groups`, `rows`, `system`, `qualify`, …),
- partitioned tables not on InnoDB, which stop 8.0 from starting,
- utf8mb3 columns and zero-date defaults,
- foreign keys that do not reference a whole PRIMARY/UNIQUE key (8.4 refuses new ones),
- accounts on `mysql_native_password`, disabled by default in community 8.4,
- the 20 statements with the highest total time from `performance_schema`, flagging `GROUP BY` without `ORDER BY` (5.7 sorted it, 8.0 does not).

## Permissions

Read-only. The minimum IAM policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": ["rds:DescribeDBInstances", "ec2:DescribeRegions"], "Resource": "*" }
  ]
}
```

Nothing is sent anywhere. The tool only calls the AWS API with your credentials and prints a report.

## What it covers

| Engine | Versions in the calendar |
| --- | --- |
| RDS for PostgreSQL, Aurora PostgreSQL | 11 to 18 |
| RDS for MySQL | 5.7, 8.0, 8.4 |
| Aurora MySQL | version 2 (5.7), version 3 (8.0), 8.4-compatible (standard support until April 2032, Extended Support dates not announced) |


SQL Server, Oracle, Db2, MariaDB, RDS Custom, DocumentDB and Neptune have no RDS Extended Support charge and are listed as `engine not covered`. Aurora Serverless v2 instances are flagged but not priced (billed per ACU-hour). Databases created with Extended Support disabled (`open-source-rds-extended-support-disabled`) are shown as such and cost nothing: AWS upgrades them at the end of standard support.

## Accuracy

- Dates come from the AWS release calendars for each engine.
- Regional rates come from a published summary of the AWS price list and may have changed. Confirm on the AWS pricing page for your engine before you quote a number.
- vCPUs are derived from the instance size (`large` = 2, `xlarge` = 4, `2xlarge` = 8, …, with the 1-vCPU exceptions `db.t2.micro/small` and Graviton `.medium`). The tests check this against every class AWS offers for PostgreSQL, MySQL, MariaDB and Aurora (EC2 vCPU counts, November 2026). Optimize CPU classes show as `unknown size`.
- Costs assume nodes run 24/7 at on-demand Extended Support rates.

## Develop

```
pip install -e '.[test]'
pytest
```

Tests run against a mocked AWS (moto), no account needed.
