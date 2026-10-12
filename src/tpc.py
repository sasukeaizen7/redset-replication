"""The TPC side of the comparison: TPC-H and TPC-DS generated and run in DuckDB.

    python src/tpc.py              # scale factor 10 (as in results/)
    python src/tpc.py --sf 1       # quicker

The paper ran both benchmarks at SF 3000 on a 10-node Redshift cluster; here they run at SF 10 on one laptop,
so absolute runtimes are not comparable. What carries over is the shape: how narrow the runtime spread is,
and the plan operators per query. The query mix follows the specifications (refresh functions included), as
in the paper's Table 2.

Writes results/tpc_runtimes.csv (one row per query: median of 3 timed runs after a warm-up, plan operators),
results/tpc_runtime_buckets.csv and results/tpc_query_mix.csv.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"

# Plan operator names in DuckDB, grouped like Redset's num_scans / num_joins / num_aggregations.
SCANS = {"SEQ_SCAN", "TABLE_SCAN", "READ_PARQUET", "COLUMN_DATA_SCAN"}
JOINS = {"HASH_JOIN", "NESTED_LOOP_JOIN", "PIECEWISE_MERGE_JOIN", "CROSS_PRODUCT", "IE_JOIN", "LEFT_DELIM_JOIN",
         "RIGHT_DELIM_JOIN", "DELIM_JOIN", "BLOCKWISE_NL_JOIN", "POSITIONAL_JOIN", "ASOF_JOIN"}
AGGS = {"HASH_GROUP_BY", "PERFECT_HASH_GROUP_BY", "UNGROUPED_AGGREGATE", "SIMPLE_AGGREGATE", "STREAMING_WINDOW",
        "PARTITIONED_AGGREGATE"}

# Statements per run in the specifications (the paper's Section 3.2): the queries plus the refresh functions.
MIX = {
    "TPC-H": {"select": 22, "copy": 3, "insert": 2, "delete": 2},
    "TPC-DS": {"select": 99, "copy": 12, "insert": 7, "delete": 7},
}
BUCKETS = [(10, "(0s, 10ms]"), (100, "(10ms, 100ms]"), (1000, "(100ms, 1s]"), (10_000, "(1s, 10s]"),
           (60_000, "(10s, 1min]"), (600_000, "(1min, 10min]"), (3_600_000, "(10min, 1h]"),
           (36_000_000, "(1h, 10h]"), (float("inf"), ">= 10h")]


def operators(con: duckdb.DuckDBPyConnection, query: str) -> dict[str, int]:
    plan = json.loads(con.sql("EXPLAIN (FORMAT JSON) " + query).fetchall()[0][1])
    counts = {"scans": 0, "joins": 0, "aggregations": 0}

    def walk(node: dict) -> None:
        name = node.get("name", "").strip().upper().replace(" ", "_")
        counts["scans"] += name in SCANS
        counts["joins"] += name in JOINS
        counts["aggregations"] += name in AGGS
        for child in node.get("children", []):
            walk(child)

    for root in plan:
        walk(root)
    return counts


def bench(name: str, generate: str, queries_fn: str, sf: float, runs: int = 3) -> list[dict]:
    db = ROOT / "data" / f"{name.lower().replace('-', '')}_sf{sf:g}.duckdb"
    con = duckdb.connect(str(db))
    if not con.sql("SELECT count(*) FROM information_schema.tables").fetchone()[0]:
        start = time.perf_counter()
        print(f"{name}: generating SF {sf:g} ...", flush=True)
        con.execute(f"CALL {generate}(sf = {sf})")
        print(f"  generated in {time.perf_counter() - start:.0f}s", flush=True)
    rows = []
    for nr, query in con.sql(f"SELECT * FROM {queries_fn}()").fetchall():
        con.sql(query).fetchall()  # warm-up
        times = []
        for _ in range(runs):
            start = time.perf_counter()
            con.sql(query).fetchall()
            times.append((time.perf_counter() - start) * 1000)
        rows.append({"benchmark": name, "query": nr, "ms": round(statistics.median(times), 1),
                     **operators(con, query)})
        print(f"  {name} q{nr}: {rows[-1]['ms']:.0f} ms", flush=True)
    con.close()
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sf", type=float, default=10)
    args = parser.parse_args()
    RESULTS.mkdir(exist_ok=True)

    rows = bench("TPC-H", "dbgen", "tpch_queries", args.sf) + bench("TPC-DS", "dsdgen", "tpcds_queries", args.sf)
    df = pd.DataFrame(rows).assign(sf=args.sf)
    df.to_csv(RESULTS / "tpc_runtimes.csv", index=False)

    df["runtime_bucket"] = df.ms.map(lambda ms: next(label for limit, label in BUCKETS if ms <= limit))
    buckets = (df.groupby(["benchmark", "runtime_bucket"], sort=False)
                 .agg(queries=("ms", "size"), runtime_ms=("ms", "sum")).reset_index())
    buckets["pct_queries"] = (100 * buckets.queries / buckets.groupby("benchmark").queries.transform("sum")).round(2)
    buckets["pct_runtime"] = (100 * buckets.runtime_ms / buckets.groupby("benchmark").runtime_ms.transform("sum")).round(2)
    order = {label: i for i, (_, label) in enumerate(BUCKETS)}
    buckets = buckets.sort_values(["benchmark", "runtime_bucket"], key=lambda s: s.map(order) if s.name == "runtime_bucket" else s)
    buckets.drop(columns="runtime_ms").to_csv(RESULTS / "tpc_runtime_buckets.csv", index=False)

    mix = pd.DataFrame([{"benchmark": b, "query_type": t, "statements": n} for b, m in MIX.items() for t, n in m.items()])
    mix["pct_queries"] = (100 * mix.statements / mix.groupby("benchmark").statements.transform("sum")).round(2)
    mix.to_csv(RESULTS / "tpc_query_mix.csv", index=False)
    print(df.groupby("benchmark")[["ms", "scans", "joins", "aggregations"]].describe().T.round(1))


if __name__ == "__main__":
    main()
