"""The analyses on tiny hand-made traces, where the right answer is known."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import run  # noqa: E402

T0 = datetime(2024, 3, 4, 9, 0, 0)  # a Monday


def make_db(rows: list[dict]):
    """A `queries` table with the prepared schema, from a few rows (defaults for the rest)."""
    con = run.connect()
    con.execute("""
        CREATE TABLE queries (variant VARCHAR, instance_id INTEGER, user_id BIGINT, database_id BIGINT,
            query_id BIGINT, query_type VARCHAR, raw_query_type VARCHAR, cache_source_query_id BIGINT, ts TIMESTAMP, end_ts TIMESTAMP, compile_ms DOUBLE,
            queue_ms BIGINT, exec_ms BIGINT, fp UBIGINT, was_aborted BOOLEAN, was_cached BOOLEAN,
            n_permanent INTEGER, n_external INTEGER, n_system INTEGER, read_ids BIGINT[], write_ids BIGINT[],
            mbytes_scanned DOUBLE, mbytes_spilled DOUBLE, num_joins BIGINT, num_scans BIGINT,
            num_aggregations BIGINT)""")
    for i, r in enumerate(rows):
        ts = T0 + timedelta(seconds=r.get("t", i))
        exec_ms = r.get("ms", 100)
        con.execute(
            "INSERT INTO queries VALUES ('provisioned', 1, 1, 1, ?, ?, ?, NULL, ?, ?, 0, 0, ?, ?, false, ?, 1, ?, ?,"
            " ?, ?, 1, 0, 0, 1, 0)",
            [i, r.get("type", "select"), r.get("type", "select"), ts, ts + timedelta(milliseconds=exec_ms), exec_ms, r.get("fp"),
             r.get("cached", False), r.get("ext", 0), r.get("sys", 0), r.get("reads"), r.get("writes")])
    con.execute("CREATE TABLE dropped AS SELECT 'provisioned' AS variant, 0 AS n")
    return con


def run_file(con, name: str) -> dict:
    return run.analyze(con, [run.SQL / name], out=None)


def test_repetition_rate_matches_the_paper_example():
    # Paper, Section 4.4: q1 three times, q2 twice, q3-q5 once -> 8 queries, 3 repeats -> 37.5 %.
    fps = [1, 1, 1, 2, 2, 3, 4, 5]
    con = make_db([{"fp": f, "t": i * 60} for i, f in enumerate(fps)])
    res = run_file(con, "30_repetition.sql")["repetition_by_cluster"]
    month = res[(res.scope == "all") & (res.window_kind == "month")]
    assert month.repetition.item() == pytest.approx(0.375)


def test_cache_model_classes():
    con = make_db([
        {"fp": 1, "reads": [10]},                       # 0 first run
        {"fp": 1, "reads": [10], "cached": True},       # 1 hit (no write since)
        {"type": "insert", "writes": [10]},             # 2 write to table 10
        {"fp": 1, "reads": [10]},                       # 3 invalidated by the insert
        {"fp": 1, "reads": [10]},                       # 4 hit again (cache repopulated by 3)
        {"fp": 2, "reads": [20], "sys": 1},             # 5 first run
        {"fp": 2, "reads": [20], "sys": 1},             # 6 system table: never cached
        {"fp": 3, "reads": [30], "ms": 5000},           # 7 first run, still running at t=8
        {"fp": 3, "reads": [30]},                       # 8 concurrent: previous result not ready
        {"reads": [10]},                                # 9 no fingerprint
        {"type": "insert", "writes": [99]},             # 10 write to an unrelated table
        {"fp": 1, "reads": [10]},                       # 11 hit: the write was to another table
    ])
    sim = run_file(con, "50_cache.sql")
    classes = con.sql("SELECT query_id, class FROM cache_sim ORDER BY query_id").fetchall()
    assert dict(classes) == {0: "first_run", 1: "hit", 3: "invalidated", 4: "hit", 5: "first_run",
                             6: "system_tables", 7: "first_run", 8: "concurrent", 9: "no_fingerprint", 11: "hit"}
    summary = sim["cache_summary"].iloc[0]
    assert summary.selects == 10
    assert summary.ideal_hit_pct == pytest.approx(30.0)
    assert summary.real_hit_pct == pytest.approx(10.0)
    assert summary.pct_real_hits_that_model_calls_hit == pytest.approx(100.0)


def test_write_committing_during_previous_run_invalidates():
    con = make_db([
        {"fp": 1, "reads": [10], "t": 0, "ms": 10_000},          # runs 0 s - 10 s
        {"type": "update", "writes": [10], "t": 5, "ms": 1000},   # commits at 6 s, during that run
        {"fp": 1, "reads": [10], "t": 20},                       # its result is stale -> invalidated
    ])
    run_file(con, "50_cache.sql")
    assert con.sql("SELECT class FROM cache_sim WHERE query_id = 2").fetchone()[0] == "invalidated"


def test_spikiness_flat_and_single_hour():
    # 24 queries, one per hour on one day: flat over the hours -> 0; one day of the month -> spike on daily.
    con = make_db([{"fp": i, "t": (i - 9) * 3600} for i in range(24)])  # 00:00 to 23:00 on 4 March
    res = run_file(con, "20_workloads.sql")["spikiness"]
    c = res[(res.instance_id == 1) & (res.kind == "all") & (res.month == "2024-03")]
    assert c[c.granularity == "hourly"].spikiness.item() == pytest.approx(0.0)
    assert c[c.granularity == "daily"].spikiness.item() == pytest.approx(2.0)


def test_query_types_shares_sum_to_100():
    con = make_db([{"type": t, "ms": ms} for t, ms in
                   [("select", 100), ("select", 300), ("insert", 600), ("analyze", 0)]])
    qt = run_file(con, "10_queries.sql")["query_types"]
    assert qt.pct_queries.sum() == pytest.approx(100)
    assert qt.pct_runtime.sum() == pytest.approx(100)
    assert qt.set_index("query_type").pct_runtime["insert"] == pytest.approx(60)
