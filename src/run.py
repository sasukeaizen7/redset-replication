"""Run the replication: build a DuckDB database from the Redset Parquet files, then every analysis in sql/.

    python src/run.py                      # full dataset (441 M queries), results in results/
    python src/run.py --sample             # 1 % samples, results in results_sample/ (for development)
    python src/run.py --only 30            # only the sql/ files whose name starts with 30
    python src/run.py --rebuild            # rebuild the database even if it exists

Each analysis file holds queries separated by `-- name: <id>` markers; the result of each one is saved to
results/<id>.csv. A name starting with `_` is a setup step (e.g. a temporary table): run, not saved.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SQL = ROOT / "sql"
NAME_RE = re.compile(r"^--\s*name:\s*([\w-]+)\s*$", re.MULTILINE)

DATASETS = {
    "full": {"provisioned": DATA / "provisioned" / "full.parquet",
             "serverless": DATA / "serverless" / "full.parquet"},
    "sample": {"provisioned": DATA / "provisioned" / "sample_0.01.parquet",
               "serverless": DATA / "serverless" / "sample_0.01.parquet"},
}


def connect(path: Path | str = ":memory:") -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(path))
    if path != ":memory:":
        (DATA / "tmp").mkdir(exist_ok=True)
        con.execute(f"SET temp_directory = '{(DATA / 'tmp').as_posix()}'")
        con.execute("SET memory_limit = '20GB'")
    return con


def split_named(text: str) -> list[tuple[str, str]]:
    """Split an analysis file into (name, query) pairs on `-- name:` markers."""
    parts = NAME_RE.split(text)
    pairs = []
    for i in range(1, len(parts), 2):
        query = parts[i + 1].strip().rstrip(";").strip()
        if query:
            pairs.append((parts[i], query))
    return pairs


def build(con: duckdb.DuckDBPyConnection, dataset: str) -> None:
    sql = (SQL / "00_prepare.sql").read_text(encoding="utf-8")
    for variant, path in DATASETS[dataset].items():
        sql = sql.replace("{" + variant + "}", path.as_posix())
    con.execute(sql)


def analyze(con: duckdb.DuckDBPyConnection, files: list[Path], out: Path | None) -> dict[str, pd.DataFrame]:
    """Run every named query of the given files; save results to out/<name>.csv when out is set."""
    results = {}
    for f in files:
        for name, query in split_named(f.read_text(encoding="utf-8")):
            start = time.perf_counter()
            if name.startswith("_"):
                con.execute(query)
            else:
                results[name] = df = con.sql(query).df()
                if out is not None:
                    df.to_csv(out / f"{name}.csv", index=False)
            print(f"  {f.stem}/{name}: {time.perf_counter() - start:.1f}s", flush=True)
    return results


def analysis_files(only: str | None = None) -> list[Path]:
    files = sorted(p for p in SQL.glob("*.sql") if not p.name.startswith("00_"))
    return [p for p in files if only is None or p.name.startswith(only)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true", help="use the 1 %% samples")
    parser.add_argument("--only", help="run only the sql/ files whose name starts with this")
    parser.add_argument("--rebuild", action="store_true", help="rebuild the database from Parquet")
    args = parser.parse_args()

    dataset = "sample" if args.sample else "full"
    db = DATA / f"redset_{dataset}.duckdb"
    out = ROOT / ("results_sample" if args.sample else "results")
    out.mkdir(exist_ok=True)

    fresh = args.rebuild or not db.exists()
    if fresh:
        db.unlink(missing_ok=True)
        db.with_suffix(".duckdb.wal").unlink(missing_ok=True)
    con = connect(db)
    if fresh:
        start = time.perf_counter()
        print(f"building {db.name} from Parquet ...", flush=True)
        build(con, dataset)
        print(f"  built in {time.perf_counter() - start:.0f}s", flush=True)
    analyze(con, analysis_files(args.only), out)


if __name__ == "__main__":
    sys.exit(main())
