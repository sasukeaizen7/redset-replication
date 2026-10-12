-- Section 4.4 of the paper: repeating queries (Figures 5b, 6 and 7).
--
-- Redset has no query text: `feature_fingerprint` (a hash of query features) stands in for "the same query".
-- The README warns it overestimates repetition: two queries with different literals can share a fingerprint,
-- so it sits between the paper's "query" (exact text) and "query template" (literals removed) metrics.
-- Repetition rate of a set of queries = (queries - distinct fingerprints) / queries (paper's example: 3/8).
-- Queries without a fingerprint are left out.

-- name: _daily_fp
CREATE OR REPLACE TEMP TABLE daily_fp AS
SELECT variant, instance_id, ts::DATE AS day, fp,
       bool_or(query_type = 'select') AS is_select,
       count(*) AS cnt
FROM queries WHERE fp IS NOT NULL
GROUP BY variant, instance_id, day, fp;

-- name: _rep_windows
-- One row per cluster, window (calendar month, full week Mon-Sun, weekday, weekend day) and scope (all/select).
CREATE OR REPLACE TEMP TABLE rep_windows AS
WITH windows AS (
    SELECT variant, instance_id, 'month' AS window_kind, strftime(day, '%Y-%m') AS window_id, fp, is_select, cnt
    FROM daily_fp
    UNION ALL
    SELECT variant, instance_id, 'week', strftime(date_trunc('week', day), '%Y-%m-%d'), fp, is_select, cnt
    FROM daily_fp WHERE date_trunc('week', day) BETWEEN DATE '2024-03-04' AND DATE '2024-05-20'
    UNION ALL
    SELECT variant, instance_id, CASE WHEN dayofweek(day) IN (0, 6) THEN 'day_weekend' ELSE 'day_weekday' END,
           day::VARCHAR, fp, is_select, cnt
    FROM daily_fp
), per_fp AS (
    SELECT variant, instance_id, window_kind, window_id, fp, bool_or(is_select) AS is_select, sum(cnt) AS cnt
    FROM windows GROUP BY variant, instance_id, window_kind, window_id, fp
), scoped AS (
    SELECT *, 'all' AS scope FROM per_fp
    UNION ALL
    SELECT *, 'select' FROM per_fp WHERE is_select
)
SELECT variant, instance_id, scope, window_kind, window_id,
       sum(cnt)::BIGINT AS queries,
       count(*) AS distinct_fp,
       1 - count(*) / sum(cnt) AS repetition
FROM scoped
GROUP BY variant, instance_id, scope, window_kind, window_id;

-- name: repetition_windows
SELECT * REPLACE (round(repetition, 5) AS repetition) FROM rep_windows
ORDER BY variant, instance_id, scope, window_kind, window_id;

-- name: repetition_by_cluster
-- Figure 5b: one value per cluster and window kind = the median over that cluster's windows.
SELECT variant, instance_id, scope, window_kind,
       count(*) AS windows,
       sum(queries) AS queries,
       round(median(repetition), 5) AS repetition
FROM rep_windows GROUP BY variant, instance_id, scope, window_kind
ORDER BY variant, scope, window_kind, repetition DESC;

-- name: repetition_by_runtime
-- Figure 6: per cluster and month, fingerprints are put in a bucket by their maximum runtime;
-- repetition rate of the queries in each bucket.
WITH fps AS (
    SELECT variant, instance_id, strftime(ts, '%Y-%m') AS month, fp, count(*) AS cnt, max(exec_ms) AS max_ms
    FROM queries WHERE fp IS NOT NULL
    GROUP BY variant, instance_id, month, fp
), b AS (
    SELECT *, CASE WHEN max_ms < 10 THEN 1 WHEN max_ms < 100 THEN 2 WHEN max_ms < 1000 THEN 3
                   WHEN max_ms < 10000 THEN 4 WHEN max_ms < 60000 THEN 5 WHEN max_ms < 600000 THEN 6
                   WHEN max_ms < 3600000 THEN 7 WHEN max_ms < 36000000 THEN 8 ELSE 9 END AS bucket
    FROM fps
)
SELECT variant, instance_id, month, bucket,
       ['<10ms', '<100ms', '<1s', '<10s', '<1min', '<10min', '<1h', '<10h', '>=10h'][bucket] AS runtime_bucket,
       sum(cnt)::BIGINT AS queries,
       round(1 - count(*) / sum(cnt), 5) AS repetition
FROM b GROUP BY variant, instance_id, month, bucket
ORDER BY variant, month, bucket, instance_id;

-- name: _select_gaps
-- Figure 7: time between consecutive select statements of a cluster, and between repeats of the same select.
CREATE OR REPLACE TEMP TABLE select_gaps AS
SELECT variant, instance_id, fp,
       epoch(ts - lag(ts) OVER (PARTITION BY variant, instance_id ORDER BY ts)) * 1000 AS gap_any_ms,
       CASE WHEN fp IS NOT NULL
            THEN epoch(ts - lag(ts) OVER (PARTITION BY variant, instance_id, fp ORDER BY ts)) * 1000 END AS gap_repeat_ms
FROM queries WHERE query_type = 'select';

-- name: downtime_by_cluster
SELECT variant, instance_id,
       count(gap_any_ms) AS select_gaps,
       round(median(gap_any_ms), 1) AS median_gap_any_ms,
       count(gap_repeat_ms) AS repeat_gaps,
       round(median(gap_repeat_ms), 1) AS median_gap_repeat_ms
FROM select_gaps GROUP BY variant, instance_id ORDER BY variant, instance_id;

-- name: downtime_percentiles
-- Percentile curves (1 %..99 %): of each cluster's median gap between any selects, and of each repeating
-- select fingerprint's median gap between its repeats.
WITH per_fp AS (
    SELECT variant, median(gap_repeat_ms) AS m FROM select_gaps WHERE gap_repeat_ms IS NOT NULL
    GROUP BY variant, instance_id, fp
), per_cluster AS (
    SELECT variant, median(gap_any_ms) AS m FROM select_gaps GROUP BY variant, instance_id
)
SELECT series, variant, unnest(range(1, 100)) / 100 AS q, unnest(qs) AS ms
FROM (
    SELECT 'repeat (per fingerprint)' AS series, variant, quantile_cont(m, [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.11, 0.12, 0.13, 0.14, 0.15, 0.16, 0.17, 0.18, 0.19, 0.20, 0.21, 0.22, 0.23, 0.24, 0.25, 0.26, 0.27, 0.28, 0.29, 0.30, 0.31, 0.32, 0.33, 0.34, 0.35, 0.36, 0.37, 0.38, 0.39, 0.40, 0.41, 0.42, 0.43, 0.44, 0.45, 0.46, 0.47, 0.48, 0.49, 0.50, 0.51, 0.52, 0.53, 0.54, 0.55, 0.56, 0.57, 0.58, 0.59, 0.60, 0.61, 0.62, 0.63, 0.64, 0.65, 0.66, 0.67, 0.68, 0.69, 0.70, 0.71, 0.72, 0.73, 0.74, 0.75, 0.76, 0.77, 0.78, 0.79, 0.80, 0.81, 0.82, 0.83, 0.84, 0.85, 0.86, 0.87, 0.88, 0.89, 0.90, 0.91, 0.92, 0.93, 0.94, 0.95, 0.96, 0.97, 0.98, 0.99]) AS qs FROM per_fp GROUP BY variant
    UNION ALL
    SELECT 'any select (per cluster)', variant, quantile_cont(m, [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.11, 0.12, 0.13, 0.14, 0.15, 0.16, 0.17, 0.18, 0.19, 0.20, 0.21, 0.22, 0.23, 0.24, 0.25, 0.26, 0.27, 0.28, 0.29, 0.30, 0.31, 0.32, 0.33, 0.34, 0.35, 0.36, 0.37, 0.38, 0.39, 0.40, 0.41, 0.42, 0.43, 0.44, 0.45, 0.46, 0.47, 0.48, 0.49, 0.50, 0.51, 0.52, 0.53, 0.54, 0.55, 0.56, 0.57, 0.58, 0.59, 0.60, 0.61, 0.62, 0.63, 0.64, 0.65, 0.66, 0.67, 0.68, 0.69, 0.70, 0.71, 0.72, 0.73, 0.74, 0.75, 0.76, 0.77, 0.78, 0.79, 0.80, 0.81, 0.82, 0.83, 0.84, 0.85, 0.86, 0.87, 0.88, 0.89, 0.90, 0.91, 0.92, 0.93, 0.94, 0.95, 0.96, 0.97, 0.98, 0.99]) FROM per_cluster GROUP BY variant
)
ORDER BY series, variant, q;
