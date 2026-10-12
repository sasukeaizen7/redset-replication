"""The replication scorecard: each of the paper's claims, its value in the paper, and its value on Redset.

    python src/claims.py     # results/*.csv -> results/claims.csv, report/claims.tex, report/numbers.tex

Every Redset number comes from results/ (never typed by hand); the paper's numbers come from src/paper.py.
The verdict is a judgment, written next to each claim with its reason:
  confirmed   same direction, similar size
  partial     same direction, clearly different size (or measured through a proxy)
  not         the public trace says otherwise
  n/a         not comparable (the metric cannot be rebuilt from Redset)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paper  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"
RW = ["insert", "copy", "delete", "update", "ctas"]


def load() -> dict[str, pd.DataFrame]:
    return {p.stem: pd.read_csv(p) for p in RES.glob("*.csv")}


def per_variant(fn):
    return {v: fn(v) for v in ("provisioned", "serverless")}


def build(r: dict[str, pd.DataFrame]) -> tuple[list[dict], dict[str, float]]:
    qt = r["query_types"].set_index(["variant", "query_type"])
    rb = r["runtime_buckets"].set_index(["variant", "runtime_bucket"])
    rp = r["runtime_percentiles"].set_index(["variant", "scope"])
    top = r["runtime_share_top"].set_index("variant")
    po = r["plan_operators"]
    po = po[(po.scope == "all") & po.runtime_bucket.isna()].set_index("variant")
    sp = r["spikiness"]
    sp_c = sp[(sp.instance_id != -1) & (sp.month == "2024-03") & (sp.kind == "all")]
    sp_f = sp[(sp.instance_id == -1) & (sp.month == "2024-03") & (sp.kind == "all")].set_index(["variant", "granularity"])
    rc = r["repetition_by_cluster"]
    rep = rc[(rc.scope == "all") & (rc.window_kind == "month")]
    cs = r["cache_summary"].set_index("variant")
    cc = r["cache_classes"].groupby(["variant", "class"]).pct_selects.sum()
    dt = r["downtime_by_cluster"]
    dp = r["downtime_percentiles"]
    ctr = r["ctas_recreation"].set_index(["variant", "creations_per_week"])
    ctu = r["ctas_usage"].set_index(["variant", "readers"])
    ctx = r["ctas_reach"].set_index("variant")
    ts = r["table_sets"]
    did = r["daily_inserts_deletes"].set_index("variant")
    rbr = r["repetition_by_runtime"]

    def misses(v):  # real misses among repeating selects, in % of selects
        return cs.repeating_pct[v] - cs.real_hit_pct[v]

    ll = ts[ts.sampled & (ts.scope == "long-lived")]
    al = ts[ts.sampled & (ts.scope == "all")]
    long_runs = rbr[(rbr.month == "2024-03") & (rbr.queries >= 10) & rbr.runtime_bucket.isin(["<10min", "<1h", "<10h"])]
    short_runs = rbr[(rbr.month == "2024-03") & (rbr.queries >= 10) & (rbr.runtime_bucket == "<10ms")]

    C = []

    def add(section, claim, paper_value, values, unit, verdict, why):
        C.append({"section": section, "claim": claim, "paper": paper_value,
                  "provisioned": values.get("provisioned"), "serverless": values.get("serverless"),
                  "unit": unit, "verdict": verdict, "why": why})

    add("3.2", "Queries that are selects", paper.QUERY_TYPES["select"][0],
        per_variant(lambda v: qt.pct_queries[(v, "select")]), "%", "not",
        "fewer selects than in the paper: writes dominate the query count even more")
    add("3.2", "Runtime spent in writes (insert, copy, delete, update, CTAS)", sum(paper.QUERY_TYPES[t][1] for t in RW),
        per_variant(lambda v: sum(qt.pct_runtime.get((v, t), 0) for t in RW)), "%", "confirmed",
        "about two thirds of the runtime goes to writes, as in the paper")
    add("3.3", "Runtime spent in CTAS", paper.QUERY_TYPES["ctas"][1],
        per_variant(lambda v: qt.pct_runtime[(v, "ctas")]), "%", "partial",
        "provisioned: even larger; serverless: small")
    add("3.4", "Queries under 100 ms", sum(paper.RUNTIME_PCT_QUERIES["fleet"][:2]),
        per_variant(lambda v: rb.pct_queries[(v, "(0s, 10ms]")] + rb.pct_queries[(v, "(10ms, 100ms]")]), "%",
        "confirmed", "provisioned matches; serverless queries are slower")
    add("3.4", "Runtime in queries over 1 h", sum(paper.RUNTIME_PCT_RUNTIME["fleet"][7:]),
        per_variant(lambda v: top.pct_runtime_over_1h[v]), "%", "confirmed",
        "a tiny share of queries (< 0.05 %) takes a large share of runtime (the paper's text says ~25 %, its Table 3 15.9 %)")
    add("4.3", "Runtime tail: p99.9 / median", paper.RUNTIME_PERCENTILES_S["p99.9"] / paper.RUNTIME_PERCENTILES_S["p50"],
        per_variant(lambda v: rp.p999_over_p50[(v, "all")]), "x", "confirmed", "an even longer tail")
    add("3.4", "Scans per executed query", paper.PLAN_OPERATORS["total"][0],
        per_variant(lambda v: po.scans[v]), "", "partial", "fewer scans per query; joins per query match (next row)")
    add("3.4", "Joins per executed query", paper.PLAN_OPERATORS["total"][1],
        per_variant(lambda v: po.joins[v]), "", "confirmed", "")
    add("4.1", "Fleet daily spikiness (March)", paper.CLAIMS["spikiness_daily"]["All"],
        per_variant(lambda v: sp_f.spikiness[(v, "daily")]), "", "confirmed",
        "the aggregated fleet is stable from day to day")
    add("4.2", "Fleet hourly spikiness (March)", paper.CLAIMS["spikiness_hourly"]["All"],
        per_variant(lambda v: sp_f.spikiness[(v, "hourly")]), "", "confirmed", "")
    add("4.1", "Clusters at most as spiky as the paper's C2 (daily, 0.28)", paper.CLAIMS["daily_share_below_c2"],
        per_variant(lambda v: 100 * (sp_c[(sp_c.variant == v) & (sp_c.granularity == "daily")].spikiness <= 0.28).mean()),
        "%", "partial", "single clusters are spikier than in the paper; serverless far more")
    add("4.4", "Repeated queries in the median cluster (month)", paper.CLAIMS["repetition_median_cluster"],
        per_variant(lambda v: 100 * rep[rep.variant == v].repetition.median()), "%", "confirmed",
        "provisioned matches (fingerprint proxy); serverless repeats less")
    add("4.4", "Fingerprints of long queries (10 min-10 h) that repeat, median cluster", None,
        per_variant(lambda v: 100 * long_runs[long_runs.variant == v].repetition.median()), "%", "confirmed",
        "long-running queries repeat (the paper: 'almost always'); very short ones much less (next row)")
    add("4.4", "Same, for queries under 10 ms", None,
        per_variant(lambda v: 100 * short_runs[short_runs.variant == v].repetition.median()), "%", "confirmed", "")
    add("4.4", "Median gap between repeats of a select, median cluster", paper.CLAIMS["median_repeat_gap_s"],
        per_variant(lambda v: dt[dt.variant == v].median_gap_repeat_ms.median() / 1000), "s", "confirmed",
        "under 100 s per cluster; per individual query the median gap is minutes (next row)")
    add("4.4", "Median gap between repeats, median repeating query", None,
        per_variant(lambda v: dp[(dp.series == "repeat (per fingerprint)") & (dp.variant == v) & (dp.q == 0.5)].ms.item() / 1000),
        "s", "n/a", "the paper's sentence can be read per cluster or per query")
    add("4.4", "Longest median repeat gap of a cluster", paper.CLAIMS["max_cluster_median_gap_days"],
        per_variant(lambda v: dt[dt.variant == v].median_gap_repeat_ms.max() / 86_400_000), "days", "not",
        "1-3 days instead of 12")
    add("4.6", "Selects that repeat a previous select", paper.CLAIMS["repeating_queries"],
        per_variant(lambda v: cs.repeating_pct[v]), "%", "confirmed",
        "more repetition, as expected from a fingerprint (it overestimates)")
    add("4.6", "Selects answered by the real result cache", paper.CLAIMS["cache_hit_rate"],
        per_variant(lambda v: cs.real_hit_pct[v]), "%", "partial",
        "the paper does not give the denominator; over all queries Redset gives 10.6 % / 4.6 %")
    add("4.6", "Repeating selects that still miss the cache", paper.CLAIMS["cache_miss_of_repeating"],
        per_variant(lambda v: 100 * misses(v) / cs.repeating_pct[v]), "%", "confirmed", "")
    add("4.6", "  of those misses: reads system tables", paper.CLAIMS["miss_system_tables"],
        per_variant(lambda v: 100 * cc[(v, "system_tables")] / misses(v)), "%", "partial", "serverless: far more")
    add("4.6", "  of those misses: reads external tables", paper.CLAIMS["miss_external_tables"],
        per_variant(lambda v: 100 * cc[(v, "external_tables")] / misses(v)), "%", "confirmed", "")
    add("4.6", "  of those misses: a table was written since", paper.CLAIMS["miss_writes"],
        per_variant(lambda v: 100 * cc[(v, "invalidated")] / misses(v)), "%", "partial",
        "fewer write invalidations; the rest are ideal hits the real cache missed (see the extension)")
    add("3.3", "CTAS statements run once in a week", paper.CLAIMS["ctas_created_once_per_week"],
        per_variant(lambda v: ctr.pct[(v, "1")]), "%", "confirmed", "same CTAS fingerprint = same table (ids are fresh)")
    add("3.3", "CTAS tables read by exactly one query", paper.CLAIMS["ctas_single_reader"],
        per_variant(lambda v: ctu.pct[(v, "1")]), "%", "not", "most are read by 2-5 queries, a quarter (provisioned) by none")
    add("3.3", "Queries reading a CTAS-created table", paper.CLAIMS["ctas_reach"],
        per_variant(lambda v: ctx.pct[v]), "%", "not", "")
    add("4.5", "Distinct table sets in a busy cluster-month (10 sampled)", paper.CLAIMS["table_sets_mean"],
        {"provisioned": ll.distinct_sets.mean()}, "count", "not",
        "thousands even after dropping short-lived tables (all tables: tens of thousands)")
    add("5.2", "Tables with inserts and no deletes the same day", paper.CLAIMS["inserts_without_deletes"],
        per_variant(lambda v: did.pct_inserts_without_deletes[v]), "%", "confirmed", "")
    add("5.2", "Tables with deletes and no inserts the same day", paper.CLAIMS["deletes_without_inserts"],
        per_variant(lambda v: did.pct_deletes_without_inserts[v]), "%", "partial", "deletes mostly come with inserts")

    tpc = r["tpc_runtimes"]
    spread = lambda x: x.quantile(0.9) / x.median()  # noqa: E731
    add("3.4", "Runtime spread, p90 / median (TPC-H 22 queries in DuckDB SF 10: "
        f"{spread(tpc[tpc.benchmark == 'TPC-H'].ms):.1f}x)", None,
        per_variant(lambda v: rp.p90_s[(v, "all")] / rp.p50_s[(v, "all")]), "x", "confirmed",
        "real workloads spread over orders of magnitude, TPC queries do not")

    numbers = {
        "TpchSpread": spread(tpc[tpc.benchmark == "TPC-H"].ms),
        "TpcdsSpread": spread(tpc[tpc.benchmark == "TPC-DS"].ms),
        "TpchScans": tpc[tpc.benchmark == "TPC-H"].scans.mean(),
        "TpchJoins": tpc[tpc.benchmark == "TPC-H"].joins.mean(),
        "TpcdsScans": tpc[tpc.benchmark == "TPC-DS"].scans.mean(),
        "TpcdsJoins": tpc[tpc.benchmark == "TPC-DS"].joins.mean(),
        "QueriesProv": r["coverage"].set_index("variant").queries["provisioned"],
        "QueriesServ": r["coverage"].set_index("variant").queries["serverless"],
        "CachedRestoredProv": r["coverage"].set_index("variant").pct_cached_restored_as_select["provisioned"],
        "IdealHitProv": cs.ideal_hit_pct["provisioned"], "IdealHitServ": cs.ideal_hit_pct["serverless"],
        "RealHitProv": cs.real_hit_pct["provisioned"], "RealHitServ": cs.real_hit_pct["serverless"],
        "IdealSavedProv": cs.ideal_saved_runtime_pct["provisioned"], "IdealSavedServ": cs.ideal_saved_runtime_pct["serverless"],
        "RealSavedProv": cs.real_saved_runtime_pct["provisioned"], "RealSavedServ": cs.real_saved_runtime_pct["serverless"],
        "ModelExplainsProv": cs.pct_real_hits_that_model_calls_hit["provisioned"],
        "ModelExplainsServ": cs.pct_real_hits_that_model_calls_hit["serverless"],
        "AllTableSetsMean": al.distinct_sets.mean(),
    }
    ttl = r["cache_ttl"].set_index(["variant", "ttl_label"])
    for v, tag in (("provisioned", "Prov"), ("serverless", "Serv")):
        for lab, key in (("10 min", "TenMin"), ("1 h", "OneHour")):
            numbers[f"Ttl{key}Hit{tag}"] = ttl.hit_pct[(v, lab)]
            numbers[f"Ttl{key}Saved{tag}"] = ttl.saved_runtime_pct[(v, lab)]
    return C, numbers


def fmt(x, unit) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "-"
    if unit == "x":
        return f"{x:,.0f}x"
    if unit == "%":
        return f"{x:.1f} %"
    if unit == "s":
        return f"{x:,.0f} s"
    if unit == "days":
        return f"{x:.1f} d"
    if unit == "count":
        return f"{x:,.1f}" if x < 100 else f"{x:,.0f}"
    return f"{x:.2f}"


def tex_escape(s: str) -> str:
    return s.replace("%", r"\%").replace("&", r"\&").replace("_", r"\_").replace("~", r"$\sim$").replace("<", r"$<$")


def main() -> None:
    claims, numbers = build(load())
    df = pd.DataFrame(claims)
    df.to_csv(RES / "claims.csv", index=False)

    out = ROOT / "report"
    out.mkdir(exist_ok=True)
    mark = {"confirmed": r"\textcolor{ok}{confirmed}", "partial": r"\textcolor{part}{partial}",
            "not": r"\textcolor{no}{not confirmed}", "n/a": "n/a"}
    lines = []
    for c in claims:
        claim = (r"\quad " if c["claim"].startswith("  ") else "") + tex_escape(c["claim"].strip())
        lines.append(" & ".join([c["section"], claim,
                                 tex_escape(fmt(c["paper"], c["unit"])), tex_escape(fmt(c["provisioned"], c["unit"])),
                                 tex_escape(fmt(c["serverless"], c["unit"])), mark[c["verdict"]]]) + r" \\")
    (out / "claims.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "numbers.tex").write_text(
        "\n".join(rf"\newcommand{{\{k}}}{{{v:,.0f}}}" if v > 1000 else rf"\newcommand{{\{k}}}{{{v:.1f}}}"
                  for k, v in numbers.items()) + "\n", encoding="utf-8")

    print("| § | Claim | Paper | Redset provisioned | Redset serverless | Verdict |")
    print("|---|---|---|---|---|---|")
    for c in claims:
        print(f"| {c['section']} | {'↳ ' if c['claim'].startswith('  ') else ''}{c['claim'].strip()} | {fmt(c['paper'], c['unit'])} | "
              f"{fmt(c['provisioned'], c['unit'])} | {fmt(c['serverless'], c['unit'])} | {c['verdict']} |")
    print()
    print(df.verdict.value_counts().to_string())
    for k, v in numbers.items():
        print(f"{k} = {v:.2f}")


if __name__ == "__main__":
    main()
