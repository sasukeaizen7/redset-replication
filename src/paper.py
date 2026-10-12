"""The paper's published numbers (van Renen et al., PVLDB 17(11), 2024), copied from its tables and text.

These are the values the replication compares against; each one cites where it comes from in the paper.
The paper's fleet numbers come from internal telemetry of provisioned Redshift clusters (one month, Nov. 2023),
not from the public Redset release.
"""

# Table 2: % of queries and % of total runtime per query type (Fleet, TPC-H, TPC-DS).
QUERY_TYPES = {
    #               fleet n, fleet rt, TPC-H n, TPC-H rt, TPC-DS n, TPC-DS rt
    "select":      (48.9, 28.6, 75.9, 91.6, 79.2, 86.7),
    "insert":      (19.5, 7.3, 6.9, 0.4, 5.6, 0.5),
    "copy":        (7.4, 38.3, 10.0, 1.1, 9.6, 10.8),
    "delete":      (6.6, 2.6, 6.9, 7.0, 5.6, 2.0),
    "update":      (3.8, 2.2, 0.0, 0.0, 0.0, 0.0),
    "ctas":        (1.9, 16.4, 0.0, 0.0, 0.0, 0.0),
    "maintenance": (8.2, 3.3, 0.0, 0.0, 0.0, 0.0),
    "other":       (3.7, 1.3, 0.0, 0.0, 0.0, 0.0),
}

# Table 3: % of queries and % of runtime per runtime bucket.
RUNTIME_BUCKETS = ["(0s, 10ms]", "(10ms, 100ms]", "(100ms, 1s]", "(1s, 10s]", "(10s, 1min]", "(1min, 10min]",
                   "(10min, 1h]", "(1h, 10h]", ">= 10h"]
RUNTIME_PCT_QUERIES = {
    "fleet": [13.7, 48.3, 24.9, 9.9, 2.2, 0.86, 0.08, 0.008, 0.00009],
    "TPC-H": [0, 0, 0, 27, 55, 8, 0, 0, 0],
    "TPC-DS": [0, 0, 22, 59, 13, 5, 0, 0, 0],
}
RUNTIME_PCT_RUNTIME = {
    "fleet": [0.01, 0.4, 2.3, 7.3, 13.3, 35.7, 25.2, 14.3, 1.6],
    "TPC-H": [0, 0, 0, 3, 30, 66, 0, 0, 0],
    "TPC-DS": [0, 0, 2, 19, 25, 55, 0, 0, 0],
}

# Table 4: average plan operators per query (joins = hash + merge + nested-loop joins).
PLAN_OPERATORS = {
    #              scans, joins, aggregations
    "(0s, 1s)":   (1.63, 0.38, 0.52),
    "[1s, 60s)":  (4.15, 1.35, 0.50),
    "[60s, inf)": (6.51, 2.28, 0.72),
    "total":      (2.03, 0.53, 0.52),
    "TPC-H":      (4.00, 2.54, 1.15),
    "TPC-DS":     (9.17, 5.58, 2.11),
}

# Table 6: runtime percentiles in seconds.
RUNTIME_PERCENTILES_S = {"p50": 0.1, "p90": 1.8, "p99": 26.1, "p99.9": 203.0}

CLAIMS = {
    # Section 3.4 / Table 3
    "pct_queries_over_1h": 0.1,          # "less than 0.1 % of queries run longer than 1 h"
    "pct_runtime_over_1h": 25,           # "... they take up ~25 % of all resources"
    # Section 3.3
    "ctas_created_once_per_week": 66,    # "most tables (~66 %) are created only once within ... a week"
    "ctas_single_reader": 80,            # "~80 % of CTAS tables are only used by one query each"
    "ctas_reach": 40,                    # "roughly ~40 % of queries overall utilize them"
    # Section 4.1 / 4.2: spikiness of the aggregated fleet and of the three example clusters
    "spikiness_daily": {"All": 0.12, "C1": 0.03, "C2": 0.28, "C3": 0.29},
    "spikiness_hourly": {"All": 0.09, "C1": 0.25, "C2": 0.51, "C3": 0.81},
    "daily_share_below_c2": 75,          # "most clusters (75 %) ... are more stable than C2/C3"
    # Section 4.4
    "repetition_median_cluster": 80,     # "in 50 % of database clusters 80 % of queries are ... repetitions"
    "median_repeat_gap_s": 100,          # "for more than 50 % of repeating queries, the median time ... under 100 s"
    "max_cluster_median_gap_days": 12,   # "the longest median time between repeats on a cluster ... below 12 days"
    # Section 4.5
    "table_sets_mean": 23.5,             # 10 clusters with > 50,000 queries: 23.5 distinct table sets (max 108)
    "table_sets_max": 108,
    # Section 4.6
    "cache_hit_rate": 20,                # "overall the cache has a hit rate of ~20 %"
    "repeating_queries": 80,             # "only ~80 % of queries do repeat"
    "cache_miss_of_repeating": 60,       # "of the repeating queries, ~60 % are cache misses"
    "miss_system_tables": 14,            # misses of repeating queries: ~14 % access system tables
    "miss_external_tables": 4,           # ~4 % read an external table
    "miss_concurrent": 2,                # ~2 % another query's result was concurrently being cached
    "miss_writes": 54,                   # ~30 % concurrent transaction updated a table + ~24 % write after read
    # Section 5.2
    "tables_unchanged": 86.6,            # Table 9: no insert/delete
    "inserts_without_deletes": 80,       # Fig. 8 text: ~80 % of tables receiving inserts ... no deletes same day
    "deletes_without_inserts": 30,       # ~30 % of tables receiving deletes ... no inserts same day
}
