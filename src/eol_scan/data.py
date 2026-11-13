"""Release calendars and Extended Support rates.

Dates: AWS release calendars for RDS for PostgreSQL, Aurora PostgreSQL,
RDS for MySQL and Aurora MySQL (checked 2026-11-12).
Rates: USD per vCPU-hour for provisioned instances, years 1-2 and year 3+,
from Vantage's summary of the AWS price list (Feb 2025). eu-central-1 checked
against the official AWS Price List (AmazonRDS offer, published 2026-11-12):
0.122 / 0.244 for RDS PostgreSQL, RDS MySQL, Aurora PostgreSQL and Aurora MySQL.
Other regions are unverified estimates; confirm on the AWS pricing page before
quoting a number.
"""

# y1: Extended Support year-1 pricing starts, y3: year-3 pricing starts
# (None = never), end: Extended Support ends, target: suggested upgrade.
PG = {
    "11": {"y1": "2024-04-01", "y3": "2026-04-01", "end": "2027-03-31"},
    "12": {"y1": "2025-03-01", "y3": "2027-03-01", "end": "2028-02-29"},
    "13": {"y1": "2026-03-01", "y3": "2028-03-01", "end": "2029-02-28"},
    "14": {"y1": "2027-03-01", "y3": "2029-03-01", "end": "2030-02-28"},
    "15": {"y1": "2028-03-01", "y3": "2030-03-01", "end": "2031-02-28"},
    "16": {"y1": "2029-03-01", "y3": "2031-03-01", "end": "2032-02-29"},
    "17": {"y1": "2030-03-01", "y3": "2032-03-01", "end": "2033-02-28"},
    "18": {"y1": "2031-03-01", "y3": "2033-03-01", "end": "2034-02-28"},
}

CALENDAR = {
    "postgres": PG,
    "aurora-postgresql": PG,
    "mysql": {
        "5.7": {"y1": "2024-03-01", "y3": "2026-03-01", "end": "2029-06-30"},
        "8.0": {"y1": "2026-08-01", "y3": "2028-08-01", "end": "2029-07-31"},
        "8.4": {"y1": "2029-08-01", "y3": "2031-08-01", "end": "2032-07-31"},
    },
    "aurora-mysql": {
        "2": {"y1": "2024-12-01", "y3": "2026-12-01", "end": "2029-06-30"},
        "3": {"y1": "2028-05-01", "y3": None, "end": "2029-07-31"},
        # Standard support until April 2032; Extended Support dates "to be determined" by AWS.
        "8.4": {"y1": None, "y3": None, "end": None},
    },
}

TARGET = {
    "postgres": "17 or 18",
    "aurora-postgresql": "17",
    "mysql": "8.4",
    "aurora-mysql": "3 (MySQL 8.0), later 8.4-compatible",
}

# region: (years 1-2 rate, year 3+ rate) in USD per vCPU-hour
RATES = {
    "us-east-1": (0.100, 0.200),
    "us-east-2": (0.100, 0.200),
    "us-west-2": (0.100, 0.200),
    "us-west-1": (0.100, 0.200),
    "ca-central-1": (0.108, 0.216),
    "eu-central-1": (0.122, 0.244),
    "eu-west-1": (0.112, 0.224),
    "eu-west-2": (0.118, 0.235),
    "eu-west-3": (0.118, 0.235),
    "eu-south-1": (0.118, 0.235),
    "eu-south-2": (0.112, 0.224),
    "eu-north-1": (0.103, 0.206),
    "eu-central-2": (0.134, 0.269),
    "ap-south-1": (0.114, 0.228),
    "ap-southeast-1": (0.120, 0.240),
    "ap-southeast-2": (0.120, 0.240),
    "ap-northeast-1": (0.120, 0.240),
    "sa-east-1": (0.210, 0.419),
}
DEFAULT_RATE = (0.100, 0.200)

# Major versions older than the calendar: support has ended, AWS upgraded them.
ENDED = {
    "postgres": {"9.3", "9.4", "9.5", "9.6", "10"},
    "aurora-postgresql": {"9.6", "10"},
    "mysql": {"5.5", "5.6"},
    "aurora-mysql": {"1"},
}

# Instance size suffix -> vCPU. Covers the standard db.* families.
SIZE_VCPU = {
    "micro": 2, "small": 2, "medium": 2, "large": 2,
    "xlarge": 4, "2xlarge": 8, "4xlarge": 16, "8xlarge": 32,
    "12xlarge": 48, "16xlarge": 64, "24xlarge": 96, "32xlarge": 128, "48xlarge": 192,
}
# Small sizes that break the pattern (checked against EC2 DescribeInstanceTypes):
# burstable t2 has 1 vCPU up to small, Graviton .medium of m/c/r families has 1.
SMALL_VCPU_T2 = {"micro": 1, "small": 1, "medium": 2}
SMALL_VCPU_NON_BURSTABLE = {"medium": 1}

UPGRADE_NOTES = {
    "pg-old": [
        "Before PostgreSQL 18 a major upgrade drops planner statistics: run ANALYZE on every database right after.",
        "Update extensions (PostGIS, pg_repack, ...) to versions the target supports; the RDS precheck fails otherwise.",
        "Drop logical replication slots before upgrading from versions below 17.",
        "PostgreSQL 14 made scram-sha-256 the default password encryption; check old client drivers.",
        "PostgreSQL 15 removed CREATE on the public schema for all users in new databases.",
        "Compare your top queries on a restored snapshot of the new version before switching.",
    ],
    "pg-new": [
        "Update extensions to versions the target supports before starting.",
        "Run ANALYZE after the upgrade unless the target is 18 or later.",
        "Compare your top queries on a restored snapshot of the new version before switching.",
    ],
    "mysql57": [
        "New reserved words in 8.0 (RANK, GROUPS, LEAD, ...) break unquoted identifiers.",
        "GROUP BY no longer sorts implicitly: add ORDER BY where order matters.",
        "Query cache is removed.",
        "Default character set becomes utf8mb4 with a new collation.",
        "Renamed variables, e.g. tx_isolation -> transaction_isolation.",
        "Compare your top queries on a restored snapshot before switching.",
    ],
    "mysql80": [
        "mysql_native_password is deprecated and not enabled by default in 8.4; default_authentication_plugin is gone.",
        "SHOW MASTER STATUS and CHANGE MASTER are removed; use BINARY LOG / REPLICATION SOURCE syntax.",
        "Several InnoDB defaults changed (adaptive hash index is now off).",
        "Foreign keys on non-unique or partial keys are rejected by default.",
        "Compare your top queries on a restored snapshot before switching.",
    ],
}

# Words that become reserved in the target MySQL version, so unquoted identifiers with these
# names stop parsing. Taken from INFORMATION_SCHEMA.KEYWORDS (RESERVED = 1) on 8.0.46 and 8.4.13,
# keeping only words that 5.7.44 (resp. 8.0.46) still accepts as a column name (checked 2026-11-12).
MYSQL_NEW_RESERVED = {
    "8.0": {"CUBE", "CUME_DIST", "DENSE_RANK", "EMPTY", "EXCEPT", "FIRST_VALUE", "FUNCTION", "GROUPING", "GROUPS",
            "INTERSECT", "JSON_TABLE", "LAG", "LAST_VALUE", "LATERAL", "LEAD", "NTH_VALUE", "NTILE", "OF", "OVER",
            "PERCENT_RANK", "RANK", "RECURSIVE", "ROW", "ROWS", "ROW_NUMBER", "SYSTEM", "WINDOW"},
    "8.4": {"QUALIFY", "TABLESAMPLE"},
}
