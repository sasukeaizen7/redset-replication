"""results/*.csv -> figures/*.png. Paper values come from src/paper.py.

    python src/figures.py            # from results/
    python src/figures.py --sample   # from results_sample/ into figures_sample/
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import charts  # noqa: E402
import paper  # noqa: E402
from charts import GRID, INK_2, MUTED, PALETTE, plt, save  # noqa: E402
from matplotlib.ticker import FuncFormatter, PercentFormatter  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SRC_REDSET = "Redset (Amazon, CC BY-NC 4.0), 1 Mar - 30 May 2024; paper: van Renen et al., PVLDB 17(11), 2024"
PAPER_C, PROV_C, SERV_C, TPC_C = MUTED, PALETTE[0], PALETTE[1], PALETTE[2]
MONTH = "2024-03"
PCT = PercentFormatter(decimals=0)


def pct_axis(ax, axis="x"):
    (ax.xaxis if axis == "x" else ax.yaxis).set_major_formatter(PCT)


def legend_top(ax, ncol=4):
    """Legend in one row just above the plot (inside the layout, so it never meets the source line)."""
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.02), ncol=ncol, fontsize=9, borderaxespad=0,
              handletextpad=0.4, columnspacing=1.4)


def query_types(r, out):
    qt = r["query_types"].copy()
    qt["t"] = qt.query_type.str.replace(r"maintenance.*", "maintenance", regex=True)
    qt = qt.groupby(["variant", "t"])[["pct_queries", "pct_runtime"]].sum()
    order = ["select", "insert", "copy", "delete", "update", "ctas", "maintenance", "other", "unload"]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.6), sharey=True)
    y = np.arange(len(order))[::-1]
    for ax, col, k, title in ((axes[0], "pct_queries", 0, "Share of queries"),
                             (axes[1], "pct_runtime", 1, "Share of total runtime")):
        pv = [paper.QUERY_TYPES[t][k] if t in paper.QUERY_TYPES else np.nan for t in order]
        ax.scatter(pv, y, s=70, facecolors="none", edgecolors=PAPER_C, linewidths=1.6, label="Paper (fleet, Nov 2023)", zorder=3)
        for variant, c, lab in (("provisioned", PROV_C, "Redset provisioned"), ("serverless", SERV_C, "Redset serverless")):
            vals = [qt[col].get((variant, t), 0) for t in order]
            ax.scatter(vals, y, s=46, color=c, label=lab, zorder=4)
        ax.set_yticks(y, order)
        ax.set_xlim(0, None)
        pct_axis(ax)
        ax.grid(axis="y", visible=False)
        ax.set_xlabel(title)
    axes[0].set_title("Writes take a bigger share in Redset than in the paper")
    axes[0].tick_params(axis="y", length=0)
    legend_top(axes[0], 3)
    save(fig, out / "query_types.png", SRC_REDSET,
         "Table 2 of the paper vs the public trace. Result-cache hits counted as selects; maintenance = analyze + vacuum")


def runtime_buckets(r, out):
    rb = r["runtime_buckets"].set_index(["variant", "runtime_bucket"])
    tpc = r.get("tpc_runtime_buckets")
    labels = paper.RUNTIME_BUCKETS
    series = [("Paper (fleet)", PAPER_C, paper.RUNTIME_PCT_QUERIES["fleet"], paper.RUNTIME_PCT_RUNTIME["fleet"])]
    for variant, c in (("provisioned", PROV_C), ("serverless", SERV_C)):
        series.append((f"Redset {variant}", c,
                       [rb.pct_queries.get((variant, b), 0) for b in labels],
                       [rb.pct_runtime.get((variant, b), 0) for b in labels]))
    if tpc is not None:
        t = tpc[tpc.benchmark == "TPC-H"].set_index("runtime_bucket")
        series.append(("TPC-H in DuckDB (SF 10)", TPC_C, [t.pct_queries.get(b, 0) for b in labels],
                       [t.pct_runtime.get(b, 0) for b in labels]))
    fig, axes = plt.subplots(2, 1, figsize=(10, 6.4), sharex=True)
    x = np.arange(len(labels))
    w = 0.8 / len(series)
    for ax, k, ylab in ((axes[0], 2, "% of queries"), (axes[1], 3, "% of total runtime")):
        for i, s in enumerate(series):
            ax.bar(x + (i - (len(series) - 1) / 2) * w, s[k], width=w * 0.9, color=s[1], label=s[0])
        ax.set_ylabel(ylab)
        pct_axis(ax, "y")
        ax.grid(axis="x", visible=False)
    axes[1].set_xticks(x, labels, rotation=0, fontsize=8.5)
    axes[0].set_title("Most queries are short, most runtime is in a few long ones")
    legend_top(axes[0], 4)
    save(fig, out / "runtime_buckets.png", SRC_REDSET + "; TPC-H run by this project",
         "Table 3 of the paper: queries and runtime per execution-time bucket")


def spikiness(r, out):
    s = r["spikiness"]
    s = s[(s.month == MONTH) & (s.kind == "all") & (s.instance_id != -1)]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), sharey=True)
    for ax, gran, ref in ((axes[0], "daily", paper.CLAIMS["spikiness_daily"]),
                          (axes[1], "hourly", paper.CLAIMS["spikiness_hourly"])):
        for variant, c in (("provisioned", PROV_C), ("serverless", SERV_C)):
            v = np.sort(s[(s.granularity == gran) & (s.variant == variant)].spikiness.to_numpy())
            ax.plot(np.linspace(0, 100, len(v)), v, color=c, label=f"Redset {variant}")
        merged = {}  # values closer than 0.03 share one label (daily C2 0.28 and C3 0.29)
        for name, val in sorted(ref.items(), key=lambda kv: kv[1]):
            near = next((v for v in merged if abs(v - val) < 0.03), None)
            if near is None:
                merged[val] = name
            else:
                merged[near] += f"/{name}"
        for val, name in merged.items():
            ax.axhline(val, color=GRID, linewidth=1, zorder=0)
            ax.annotate(f"paper {name} {val}", xy=(1, val), xycoords=("axes fraction", "data"), xytext=(-4, 2),
                        textcoords="offset points", ha="right", fontsize=8, color=MUTED)
        ax.set_xlabel("Percentile of clusters")
        ax.xaxis.set_major_formatter(PercentFormatter(decimals=0))
        ax.set_xlim(0, 100)
        ax.set_ylim(0, 2.05)
        ax.text(0.02, 0.97, gran.capitalize(), transform=ax.transAxes, fontsize=11, fontweight="bold", va="top", color=INK_2)
    axes[0].set_ylabel("Spikiness (0 = flat, 2 = one burst)")
    axes[0].set_title("Single clusters are much spikier than the fleet")
    legend_top(axes[0], 2)
    save(fig, out / "spikiness.png", SRC_REDSET,
         f"Figures 2 and 4 of the paper: per-cluster spikiness, {MONTH}, all queries; gray lines = the paper's values")


def load_examples(r, out):
    s = r["spikiness"]
    d = r["daily_load"].assign(day=lambda x: pd.to_datetime(x.day))
    d = d[(d.variant == "provisioned") & (d.day.dt.strftime("%Y-%m") == MONTH)]
    cand = s[(s.variant == "provisioned") & (s.month == MONTH) & (s.granularity == "daily") & (s.kind == "all")
             & (s.instance_id != -1) & (s.queries >= 10_000)].sort_values("spikiness")
    picks = [("Fleet", -1)] + [(f"p{int(q * 100)} cluster", int(cand.iloc[int(q * (len(cand) - 1))].instance_id))
                               for q in (0.1, 0.5, 0.9)]
    fig, axes = plt.subplots(2, 2, figsize=(10, 5.6))
    for ax, (name, inst) in zip(axes.flat, picks):
        x = d[d.instance_id == inst].sort_values("day")
        sp = s[(s.variant == "provisioned") & (s.month == MONTH) & (s.granularity == "daily") & (s.kind == "all")
               & (s.instance_id == inst)].spikiness.item()
        other = x.n_all - x.n_read - x.n_write
        ax.bar(x.day, x.n_read, color=PROV_C, width=0.75, label="Read (select)")
        ax.bar(x.day, x.n_write, bottom=x.n_read, color=SERV_C, width=0.75, label="Write")
        ax.bar(x.day, other, bottom=x.n_read + x.n_write, color=GRID, width=0.75, label="Other")
        ax.text(0.01, 0.97, f"{name} (spikiness {sp:.2f})", transform=ax.transAxes, fontsize=10, color=INK_2,
                va="top")
        ax.set_ylim(0, x.n_all.max() * 1.22)
        ax.yaxis.set_major_formatter(charts.THOUSANDS)
        ax.set_xlim(x.day.min() - pd.Timedelta(hours=14), x.day.max() + pd.Timedelta(hours=14))
        ax.xaxis.set_major_locator(plt.matplotlib.dates.DayLocator(bymonthday=[1, 8, 15, 22, 29]))
        ax.xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter("%d %b"))
        ax.grid(axis="x", visible=False)
    axes[0, 0].set_title("Daily load: the fleet is flat, single clusters are not")
    legend_top(axes[0, 0], 3)
    save(fig, out / "load_examples.png", SRC_REDSET,
         f"Figure 1 of the paper, redone: queries per day in {MONTH}, fleet and clusters at the 10th/50th/90th spikiness percentile")


def repetition(r, out):
    rc = r["repetition_by_cluster"]
    rc = rc[rc.scope == "all"]
    kinds = [("month", "Month"), ("week", "Week"), ("day_weekday", "Day (weekday)"), ("day_weekend", "Day (weekend)")]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), sharey=True)
    for ax, variant in zip(axes, ("provisioned", "serverless")):
        for (k, lab), c in zip(kinds, PALETTE):
            v = np.sort(rc[(rc.variant == variant) & (rc.window_kind == k)].repetition.to_numpy())[::-1]
            ax.plot(np.linspace(0, 100, len(v)), 100 * v, color=c, label=lab)
        ax.scatter([50], [paper.CLAIMS["repetition_median_cluster"]], s=70, facecolors="none", edgecolors=INK_2,
                   linewidths=1.6, zorder=5, label="Paper: 80 % on half the clusters")
        ax.text(0.98, 0.97, f"Redset {variant}", transform=ax.transAxes, ha="right", va="top", fontsize=11,
                fontweight="bold", color=INK_2)
        ax.set_xlabel("Percentile of clusters")
        ax.xaxis.set_major_formatter(PercentFormatter(decimals=0))
        ax.set_xlim(0, 100)
        ax.set_ylim(0, 102)
        pct_axis(ax, "y")
    axes[0].set_ylabel("Repeated queries")
    axes[0].set_title("Queries repeat, by the same fingerprint")
    legend_top(axes[0], 3)
    save(fig, out / "repetition.png", SRC_REDSET,
         "Figure 5b of the paper: share of queries whose fingerprint was already seen in the window, per cluster")


def repetition_by_runtime(r, out):
    rr = r["repetition_by_runtime"]
    rr = rr[(rr.variant == "provisioned") & (rr.month == MONTH) & (rr.queries >= 10)]
    labels = ["<10ms", "<100ms", "<1s", "<10s", "<1min", "<10min", "<1h", "<10h", ">=10h"]
    data = [100 * rr[rr.runtime_bucket == b].repetition.to_numpy() for b in labels]
    keep = [i for i, v in enumerate(data) if len(v)]
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.boxplot([data[i] for i in keep], positions=range(len(keep)), widths=0.5, showfliers=False,
               medianprops={"color": PROV_C, "linewidth": 2}, boxprops={"color": MUTED},
               whiskerprops={"color": MUTED}, capprops={"color": MUTED})
    for j, i in enumerate(keep):
        ax.text(j, 103, f"n={len(data[i])}", ha="center", fontsize=8, color=MUTED)
    ax.set_xticks(range(len(keep)), [labels[i] for i in keep])
    ax.set_ylim(0, 108)
    pct_axis(ax, "y")
    ax.set_ylabel("Repeated queries per cluster")
    ax.set_xlabel("Bucket of the fingerprint's longest runtime")
    ax.grid(axis="x", visible=False)
    ax.set_title("Long-running queries repeat too")
    save(fig, out / "repetition_by_runtime.png", SRC_REDSET,
         f"Figure 6 of the paper: Redset provisioned, {MONTH}, clusters with at least 10 queries in the bucket")


def downtime(r, out):
    dp = r["downtime_percentiles"]
    fig, ax = plt.subplots(figsize=(10, 4.4))
    for (series, ls) in (("repeat (per fingerprint)", "-"), ("any select (per cluster)", "--")):
        for variant, c in (("provisioned", PROV_C), ("serverless", SERV_C)):
            x = dp[(dp.series == series) & (dp.variant == variant)]
            ax.plot(100 * x.q, x.ms / 1000, color=c, linestyle=ls, label=f"{variant}: {series}")
    ax.axhline(paper.CLAIMS["median_repeat_gap_s"], color=GRID, linewidth=1, zorder=0)
    ax.annotate("paper: median repeat gap < 100 s for most repeating queries", xy=(1, 100),
                xycoords=("axes fraction", "data"), xytext=(-4, 3), textcoords="offset points", ha="right",
                fontsize=8, color=MUTED)
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: {1: "1 s", 60: "1 min", 3600: "1 h", 86400: "1 day"}.get(v, f"{v:g} s")))
    ax.set_yticks([0.01, 1, 60, 3600, 86400])
    ax.set_xlabel("Percentile")
    ax.xaxis.set_major_formatter(PercentFormatter(decimals=0))
    ax.set_ylabel("Median time between")
    ax.set_title("Repeats come back after minutes to hours")
    legend_top(ax, 2)
    save(fig, out / "downtime.png", SRC_REDSET,
         "Figure 7 of the paper: median gap between consecutive selects of a cluster, and between repeats of one select")


def cache(r, out):
    cc = r["cache_classes"].groupby(["variant", "class"]).pct_selects.sum().unstack(0).fillna(0)
    order = ["hit", "invalidated", "concurrent", "system_tables", "external_tables", "first_run", "no_fingerprint"]
    names = {"hit": "Ideal hit", "invalidated": "Table written since", "concurrent": "Previous run unfinished",
             "system_tables": "Reads system tables", "external_tables": "Reads external tables",
             "first_run": "First run", "no_fingerprint": "No fingerprint"}
    colors = [PALETTE[0], PALETTE[1], PALETTE[3], PALETTE[4], PALETTE[6], GRID, "#ecebe6"]
    ttl = r["cache_ttl"]
    summ = r["cache_summary"].set_index("variant")
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), gridspec_kw={"width_ratios": [1.1, 1]})
    ax = axes[0]
    variants = ["provisioned", "serverless"]
    left = np.zeros(len(variants))
    for k, c in zip(order, colors):
        vals = np.array([cc.get(v, pd.Series()).get(k, 0) for v in variants])
        ax.barh(variants, vals, left=left, color=c, height=0.55, label=names[k], edgecolor=charts.SURFACE, linewidth=1)
        left += vals
    for i, v in enumerate(variants):
        ax.text(101, i, f"real cache: {summ.real_hit_pct[v]:.1f} %", va="center", fontsize=9, color=INK_2)
    ax.set_xlim(0, 125)
    ax.set_xticks([0, 25, 50, 75, 100])
    pct_axis(ax)
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", length=0)
    ax.set_xlabel("Share of select statements")
    ax.legend(loc="upper center", bbox_to_anchor=(0.45, -0.18), ncol=3, fontsize=8.5)
    ax.set_title("An ideal result cache would answer far more selects")
    ax = axes[1]
    for variant, c in (("provisioned", PROV_C), ("serverless", SERV_C)):
        x = ttl[ttl.variant == variant]
        ax.plot(range(len(x)), x.hit_pct, color=c, marker="o", markersize=5, label=f"{variant}: hits")
        ax.plot(range(len(x)), x.saved_runtime_pct, color=c, marker="o", markersize=5, linestyle="--",
                label=f"{variant}: runtime saved")
    ax.set_xticks(range(len(x)), x.ttl_label, rotation=30, fontsize=8.5)
    ax.set_ylim(0, None)
    pct_axis(ax, "y")
    ax.set_xlabel("Idle timeout (entry dropped when its query is unseen this long)")
    ax.set_ylabel("Share of selects / of select runtime")
    legend_top(ax, 2)
    ax.grid(axis="x", visible=False)
    save(fig, out / "cache.png", SRC_REDSET + "; simulation by this project",
         "Replay of every select per cluster: unlimited cache, table-level invalidation (extension of Section 4.6)")


def headline(r, out):
    """The paper's claims next to the public trace (provisioned), for the report and the LinkedIn post."""
    qt = r["query_types"].set_index(["variant", "query_type"])
    top = r["runtime_share_top"].set_index("variant")
    cs = r["cache_summary"].set_index("variant")
    rc = r["repetition_by_cluster"]
    rep = rc[(rc.scope == "all") & (rc.window_kind == "month") & (rc.variant == "provisioned")].repetition.median() * 100
    rw = ["insert", "copy", "delete", "update", "ctas"]
    rows = [
        ("Queries that are selects", paper.QUERY_TYPES["select"][0], qt.pct_queries.get(("provisioned", "select"))),
        ("Runtime spent in writes", sum(paper.QUERY_TYPES[t][1] for t in rw),
         sum(qt.pct_runtime.get(("provisioned", t), 0) for t in rw)),
        ("Runtime spent in CTAS", paper.QUERY_TYPES["ctas"][1], qt.pct_runtime.get(("provisioned", "ctas"))),
        ("Runtime in queries over 1 h", sum(paper.RUNTIME_PCT_RUNTIME["fleet"][7:]), top.pct_runtime_over_1h["provisioned"]),
        ("Repeated queries, median cluster", paper.CLAIMS["repetition_median_cluster"], rep),
        ("Selects answered by the result cache", paper.CLAIMS["cache_hit_rate"], cs.real_hit_pct["provisioned"]),
    ]
    fig, ax = plt.subplots(figsize=(10, 3.8))
    for i, (lab, p, v) in enumerate(rows[::-1]):
        ax.plot([p, v], [i, i], color=GRID, linewidth=3, solid_capstyle="round", zorder=1)
        ax.scatter([p], [i], s=70, facecolors="none", edgecolors=PAPER_C, linewidths=1.6, zorder=2,
                   label="Paper (internal fleet, Nov 2023)" if i == 0 else None)
        ax.scatter([v], [i], s=55, color=PROV_C, zorder=3, label="Public Redset, provisioned (Mar-May 2024)" if i == 0 else None)
        ax.annotate(f"{v:.0f} %", xy=(v, i), xytext=(0, 9), textcoords="offset points", ha="center", fontsize=8.5, color=INK_2)
    ax.set_yticks(range(len(rows)), [r[0] for r in rows[::-1]])
    ax.set_xlim(0, 100)
    pct_axis(ax)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="y", visible=False)
    ax.set_title("Replicating 'Why TPC Is Not Enough' on the public trace")
    legend_top(ax, 2)
    save(fig, out / "headline.png", SRC_REDSET, "Same metric, paper's number (circle) vs this replication (dot)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true")
    args = parser.parse_args()
    src = ROOT / ("results_sample" if args.sample else "results")
    out = ROOT / ("figures_sample" if args.sample else "figures")
    r = {p.stem: pd.read_csv(p) for p in src.glob("*.csv")}
    if (ROOT / "results" / "tpc_runtime_buckets.csv").exists():
        r.setdefault("tpc_runtime_buckets", pd.read_csv(ROOT / "results" / "tpc_runtime_buckets.csv"))
    charts.style()
    for fn in (headline, query_types, runtime_buckets, spikiness, load_examples, repetition, repetition_by_runtime,
               downtime, cache):
        fn(r, out)


if __name__ == "__main__":
    main()
