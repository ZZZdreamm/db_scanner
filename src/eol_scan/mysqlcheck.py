"""Optional read-only checks inside one MySQL server before a major upgrade (needs PyMySQL).

Covers the RDS paths 5.7 -> 8.0 (also Aurora MySQL 2 -> 3) and 8.0 -> 8.4.
"""
from __future__ import annotations

import re
from urllib.parse import unquote, urlparse

from .data import MYSQL_NEW_RESERVED

SYSTEM_SCHEMAS = ("mysql", "information_schema", "performance_schema", "sys")
_SYS = "('mysql', 'information_schema', 'performance_schema', 'sys')"


def target_for(version: str) -> str | None:
    """The next RDS major version: 5.7 -> 8.0, 8.0 -> 8.4."""
    if version.startswith("5.7"):
        return "8.0"
    if version.startswith("8.0"):
        return "8.4"
    return None


def reserved_hits(names: list[tuple[str, str]], target: str) -> list[tuple[str, str]]:
    """(kind, qualified name) pairs whose last part becomes a reserved word in the target version."""
    words = MYSQL_NEW_RESERVED.get(target, set())
    return [(kind, name) for kind, name in names if name.rsplit(".", 1)[-1].upper() in words]


def fk_on_non_unique_key(fks: dict, unique_keys: dict) -> list[str]:
    """Foreign keys whose referenced columns are not exactly a PRIMARY/UNIQUE key (refused by 8.4 by default)."""
    out = []
    for (schema, table, name), (ref, cols) in sorted(fks.items()):
        if tuple(cols) not in unique_keys.get(ref, set()):
            out.append(f"{schema}.{table}.{name} -> {ref}({', '.join(cols)})")
    return out


def implicit_group_by_order(digest: str) -> bool:
    """A GROUP BY with no ORDER BY: 5.7 sorted the result, 8.0 does not."""
    d = re.sub(r"\s+", " ", digest.upper())
    return " GROUP BY " in d and " ORDER BY " not in d and not d.startswith(("INSERT", "UPDATE", "DELETE"))


def parse_dsn(dsn: str) -> dict:
    """mysql://user:password@host:3306/db -> PyMySQL connect() arguments."""
    u = urlparse(dsn)
    if u.scheme not in ("mysql", ""):
        raise SystemExit("--mysql-dsn must look like mysql://user:password@host:3306/dbname")
    args = {"host": u.hostname or "127.0.0.1", "port": u.port or 3306, "user": unquote(u.username or "root"),
            "password": unquote(u.password or "")}
    if u.path.strip("/"):
        args["database"] = u.path.strip("/")
    return args


def check_mysql(dsn: str, top: int = 20) -> dict:
    try:
        import pymysql
    except ImportError as e:  # pragma: no cover
        raise SystemExit("MySQL checks need PyMySQL: pip install 'eol-scan[mysql]'") from e

    out: dict = {"engine": "MySQL", "blockers": [], "warnings": [], "extensions": []}
    conn = pymysql.connect(**parse_dsn(dsn), connect_timeout=10, autocommit=True)
    try:
        cur = conn.cursor()
        cur.execute("SET SESSION TRANSACTION READ ONLY")

        def q(sql: str, *args):
            cur.execute("/* eol-scan */ " + sql, args or None)
            return cur.fetchall()

        version = q("SELECT VERSION()")[0][0]
        out["server_version"] = version
        target = target_for(version)
        out["target"] = target
        if not target:
            out["warnings"].append(f"No upgrade checks for MySQL {version}.")
            return out
        words = MYSQL_NEW_RESERVED[target]

        # 1. Identifiers that become reserved words.
        names = [("table", f"{s}.{t}") for s, t in q(f"SELECT TABLE_SCHEMA, TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA NOT IN {_SYS}")]
        names += [("column", f"{s}.{t}.{c}") for s, t, c in q(f"SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA NOT IN {_SYS}")]
        names += [("routine", f"{s}.{r}") for s, r in q(f"SELECT ROUTINE_SCHEMA, ROUTINE_NAME FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA NOT IN {_SYS}")]
        hits = reserved_hits(names, target)
        for kind, name in hits:
            out["warnings"].append(f"{kind.capitalize()} {name} is a reserved word in {target}: "
                                   f"every query must quote it as `{name.rsplit('.', 1)[-1]}`, unquoted SQL fails")

        # 2. Partitioned tables not on InnoDB: MySQL 8.0 has no generic partitioning.
        for s, t, eng in q(f"SELECT TABLE_SCHEMA, TABLE_NAME, ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA NOT IN {_SYS} "
                           "AND CREATE_OPTIONS LIKE '%%partitioned%%' AND ENGINE <> 'InnoDB'"):
            if target == "8.0":
                out["blockers"].append(f"Partitioned table {s}.{t} uses {eng}; 8.0 supports partitioning on InnoDB only")

        # 3. utf8mb3 columns.
        n_utf8 = q(f"SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA NOT IN {_SYS} AND CHARACTER_SET_NAME IN ('utf8', 'utf8mb3')")[0][0]
        if n_utf8:
            out["warnings"].append(f"{n_utf8} columns use utf8mb3 (alias utf8), deprecated; new tables default to utf8mb4")

        # 4. Zero dates as defaults fail under the 8.0 default sql_mode (NO_ZERO_DATE, strict).
        for s, t, c in q(f"SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA NOT IN {_SYS} "
                         "AND COLUMN_DEFAULT LIKE '0000-00-00%%'"):
            out["warnings"].append(f"Column {s}.{t}.{c} defaults to a zero date; ALTER TABLE fails under the strict default sql_mode")

        # 5. Foreign keys on non-unique or partial keys: 8.4 refuses new ones (restrict_fk_on_non_standard_key).
        if target == "8.4":
            fks: dict = {}
            for s, t, name, col, rs, rt in q(
                    f"SELECT TABLE_SCHEMA, TABLE_NAME, CONSTRAINT_NAME, REFERENCED_COLUMN_NAME, REFERENCED_TABLE_SCHEMA, REFERENCED_TABLE_NAME "
                    f"FROM information_schema.KEY_COLUMN_USAGE WHERE REFERENCED_TABLE_NAME IS NOT NULL AND TABLE_SCHEMA NOT IN {_SYS} "
                    "ORDER BY TABLE_SCHEMA, TABLE_NAME, CONSTRAINT_NAME, ORDINAL_POSITION"):
                fks.setdefault((s, t, name), (f"{rs}.{rt}", []))[1].append(col)
            uniq: dict = {}
            for s, t, idx, col in q(f"SELECT TABLE_SCHEMA, TABLE_NAME, INDEX_NAME, COLUMN_NAME FROM information_schema.STATISTICS "
                                    f"WHERE NON_UNIQUE = 0 AND SUB_PART IS NULL AND TABLE_SCHEMA NOT IN {_SYS} "
                                    "ORDER BY TABLE_SCHEMA, TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX"):
                uniq.setdefault(f"{s}.{t}", {}).setdefault(idx, []).append(col)
            unique_keys = {ref: {tuple(c) for c in idx.values()} for ref, idx in uniq.items()}
            for fk in fk_on_non_unique_key(fks, unique_keys):
                out["warnings"].append(f"Foreign key {fk} does not reference a whole PRIMARY/UNIQUE key; 8.4 refuses such keys by default")

        # 6. Accounts on mysql_native_password: deprecated in 8.0, disabled by default in community 8.4.
        try:
            native = [f"'{u}'@'{h}'" for u, h in q("SELECT User, Host FROM mysql.user WHERE plugin = 'mysql_native_password' "
                                                   "AND User NOT IN ('mysql.sys', 'mysql.session', 'mysql.infoschema', 'rdsadmin')")]
        except pymysql.MySQLError:
            native = None
            out["warnings"].append("Could not read mysql.user to check authentication plugins")
        if native:
            msg = f"{len(native)} accounts use mysql_native_password ({', '.join(native[:5])}{', ...' if len(native) > 5 else ''})"
            if target == "8.4":
                out["warnings"].append(msg + "; 8.4 disables this plugin by default, so these logins fail unless it is enabled. "
                                       "Move them to caching_sha2_password and check client drivers")
            else:
                out["warnings"].append(msg + "; deprecated in 8.0 (default becomes caching_sha2_password)")

        # 7. Top queries from performance_schema (statement digests).
        try:
            rows = q("SELECT COUNT_STAR, ROUND(SUM_TIMER_WAIT / 1e9, 1), ROUND(AVG_TIMER_WAIT / 1e9, 2), LEFT(DIGEST_TEXT, 300) "
                     "FROM performance_schema.events_statements_summary_by_digest "
                     f"WHERE DIGEST_TEXT IS NOT NULL AND (SCHEMA_NAME IS NULL OR SCHEMA_NAME NOT IN {_SYS}) "
                     "AND DIGEST_TEXT NOT REGEXP '^(SET|SHOW|SELECT @@|SELECT VERSION|COMMIT|ROLLBACK|BEGIN|START TRANSACTION)' "
                     "AND DIGEST_TEXT NOT LIKE '%%information_schema%%' AND DIGEST_TEXT NOT LIKE '%%performance_schema%%' "
                     "ORDER BY SUM_TIMER_WAIT DESC LIMIT %s", top)
            out["top_queries"] = [{"calls": int(c), "total_ms": float(t), "mean_ms": float(m), "query": d} for c, t, m, d in rows]
        except pymysql.MySQLError:
            out["top_queries"] = []
            out["warnings"].append("performance_schema is off or not readable, so the top queries to test can't be listed")

        for qq in out["top_queries"]:
            used = sorted({w for w in re.findall(r"`([A-Za-z_]+)`", qq["query"]) if w.upper() in words})
            if used:
                out["warnings"].append(f"A top query uses identifiers reserved in {target} ({', '.join(used)}); "
                                       f"make sure the application quotes them: {qq['query'][:120]}")
            if target == "8.0" and implicit_group_by_order(qq["query"]):
                out["warnings"].append("A top query has GROUP BY without ORDER BY; 5.7 returned it sorted, 8.0 does not: "
                                       + qq["query"][:120])
    finally:
        conn.close()
    return out
