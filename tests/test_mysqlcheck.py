from eol_scan.mysqlcheck import fk_on_non_unique_key, implicit_group_by_order, parse_dsn, reserved_hits, target_for
from eol_scan.report import to_html


def test_target_for():
    assert target_for("5.7.44-log") == "8.0"
    assert target_for("8.0.46") == "8.4"
    assert target_for("8.4.13") is None


def test_reserved_hits_by_target():
    names = [("table", "shop.groups"), ("column", "shop.leaderboard.rank"), ("column", "shop.orders.status"),
             ("column", "shop.t.qualify")]
    assert reserved_hits(names, "8.0") == [("table", "shop.groups"), ("column", "shop.leaderboard.rank")]
    assert reserved_hits(names, "8.4") == [("column", "shop.t.qualify")]


def test_fk_on_non_unique_key():
    fks = {("shop", "a", "fk_ok"): ("shop.p", ["id"]),
           ("shop", "b", "fk_partial"): ("shop.p", ["sku"]),
           ("shop", "c", "fk_composite"): ("shop.q", ["x", "y"])}
    unique = {"shop.p": {("id",)}, "shop.q": {("x", "y")}}
    assert fk_on_non_unique_key(fks, unique) == ["shop.b.fk_partial -> shop.p(sku)"]


def test_implicit_group_by_order():
    assert implicit_group_by_order("SELECT `country` , COUNT ( * ) FROM `customers` GROUP BY `country`")
    assert not implicit_group_by_order("SELECT `country` , COUNT ( * ) FROM `customers` GROUP BY `country` ORDER BY `country`")
    assert not implicit_group_by_order("SELECT `id` FROM `orders` WHERE `id` = ?")


def test_parse_dsn():
    assert parse_dsn("mysql://admin:p%40ss@db.example.com:3307/shop") == {
        "host": "db.example.com", "port": 3307, "user": "admin", "password": "p@ss", "database": "shop"}
    assert parse_dsn("mysql://root@localhost")["port"] == 3306


def test_html_shows_mysql_checks():
    my = {"server_version": "5.7.44", "target": "8.0", "blockers": ["Partitioned table shop.t uses MyISAM"],
          "warnings": ["Column shop.l.rank is a reserved word in 8.0"], "top_queries": [
              {"calls": 10, "total_ms": 5.0, "mean_ms": 0.5, "query": "SELECT `rank` FROM `l`"}]}
    from datetime import date
    out = to_html([], {"databases_scanned": 0, "in_extended_support": 0, "entering_within_12_months": 0,
                       "monthly_now": 0, "next_12_months": 0, "until_end": 0}, date(2026, 11, 12), [], None, my)
    assert "MySQL 5.7.44, upgrade to 8.0" in out and "MyISAM" in out and "`rank`" in out
