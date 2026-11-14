"""Optional read-only checks inside one PostgreSQL database (needs psycopg)."""
from __future__ import annotations

POLYMORPHIC_CHANGED_IN_14 = ("array_append", "array_prepend", "array_cat", "array_position", "array_positions",
                             "array_remove", "array_replace", "width_bucket")
REG_BLOCKERS = ("regcollation", "regconfig", "regdictionary", "regnamespace",
                "regoper", "regoperator", "regproc", "regprocedure")


def check_postgres(dsn: str, top: int = 20) -> dict:
    try:
        import psycopg
    except ImportError as e:  # pragma: no cover
        raise SystemExit("PostgreSQL checks need psycopg: pip install 'eol-scan[pg]'") from e

    out: dict = {"blockers": [], "warnings": []}
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SET default_transaction_read_only = on")
        cur.execute("SHOW server_version_num")
        num = int(cur.fetchone()[0])
        out["server_version"] = f"{num // 10000}.{num % 10000}"

        cur.execute("/* eol-scan */ SELECT extname, extversion FROM pg_extension ORDER BY extname")
        out["extensions"] = [{"name": n, "version": v} for n, v in cur.fetchall()]

        cur.execute("/* eol-scan */ SELECT slot_name FROM pg_replication_slots WHERE slot_type = 'logical'")
        slots = [r[0] for r in cur.fetchall()]
        out["logical_slots"] = slots
        if slots and num < 170000:
            out["blockers"].append(f"Logical replication slots must be dropped before upgrading: {', '.join(slots)}")

        cur.execute(
            """/* eol-scan */ SELECT n.nspname, c.relname, a.attname, format_type(a.atttypid, NULL)
               FROM pg_attribute a
               JOIN pg_class c ON c.oid = a.attrelid
               JOIN pg_namespace n ON n.oid = c.relnamespace
               WHERE a.attnum > 0 AND NOT a.attisdropped AND c.relkind IN ('r', 'm', 'p')
                 AND n.nspname NOT IN ('pg_catalog', 'information_schema')
                 AND format_type(a.atttypid, NULL) = ANY(%s)""",
            (list(REG_BLOCKERS),),
        )
        for nsp, rel, col, typ in cur.fetchall():
            out["blockers"].append(f"Column {nsp}.{rel}.{col} uses {typ}, which pg_upgrade cannot carry over")

        if num < 140000:
            # 14 changed these to anycompatible; user aggregates/operators built on the old signatures
            # make pg_upgrade --check fail ("incompatible polymorphic functions").
            cur.execute(
                """/* eol-scan */ SELECT 'aggregate ' || a.aggfnoid::regprocedure::text
                   FROM pg_aggregate a JOIN pg_proc p ON p.oid = a.aggfnoid
                   JOIN pg_proc f ON f.oid IN (a.aggtransfn, a.aggfinalfn)
                   WHERE p.pronamespace NOT IN ('pg_catalog'::regnamespace, 'information_schema'::regnamespace)
                     AND f.pronamespace = 'pg_catalog'::regnamespace AND f.proname = ANY(%s)
                   UNION
                   SELECT 'operator ' || o.oid::regoperator::text FROM pg_operator o JOIN pg_proc f ON f.oid = o.oprcode
                   WHERE o.oprnamespace NOT IN ('pg_catalog'::regnamespace, 'information_schema'::regnamespace)
                     AND f.pronamespace = 'pg_catalog'::regnamespace AND f.proname = ANY(%s)""",
                (list(POLYMORPHIC_CHANGED_IN_14), list(POLYMORPHIC_CHANGED_IN_14)),
            )
            for (obj,) in cur.fetchall():
                out["blockers"].append(f"User-defined {obj} is built on a function PostgreSQL 14 changed to anycompatible; "
                                       "pg_upgrade to 14+ refuses to run. Drop it before and recreate it after the upgrade")

        cur.execute("/* eol-scan */ SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements'")
        if cur.fetchone():
            col = "total_exec_time" if num >= 130000 else "total_time"
            mean = "mean_exec_time" if num >= 130000 else "mean_time"
            cur.execute(
                f"""/* eol-scan */ SELECT calls, round({col}::numeric, 1), round({mean}::numeric, 2), left(query, 200)
                    FROM pg_stat_statements
                    WHERE query !~* '^\\s*(begin|commit|rollback|set|show|create|alter|drop|grant|vacuum|analyze)'
                      AND query NOT LIKE '%%eol-scan%%'
                      AND query !~* 'pg_create_logical_replication_slot|pg_stat_statements_reset'
                    ORDER BY {col} DESC LIMIT %s""",
                (top,),
            )
            out["top_queries"] = [
                {"calls": c, "total_ms": float(t), "mean_ms": float(m), "query": q} for c, t, m, q in cur.fetchall()
            ]
        else:
            out["top_queries"] = []
            out["warnings"].append("pg_stat_statements is not installed, so the top queries to test can't be listed")
    return out
