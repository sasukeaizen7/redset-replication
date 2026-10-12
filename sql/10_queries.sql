-- Section 3 of the paper: how do the queries differ? (Tables 2, 3, 4, 6, plus data coverage)
-- Runtime = execution_duration_ms, the paper's "query runtime". Shares are within each variant.

-- name: coverage
SELECT q.variant,
       count(*) AS queries,
       count(DISTINCT instance_id) AS clusters,
       count(DISTINCT (instance_id, user_id)) AS users,
       min(ts)::DATE AS first_day,
       max(ts)::DATE AS last_day,
       round(100 * count(fp) / count(*), 2) AS pct_with_fingerprint,
       round(100 * count(read_ids) / count(*), 2) AS pct_with_read_tables,
       round(100 * count(write_ids) / count(*), 2) AS pct_with_write_tables,
       round(100 * count(num_scans) / count(*), 2) AS pct_with_plan_stats,
       round(100 * avg(was_cached::INT), 2) AS pct_cached,
       round(100 * count(*) FILTER (WHERE was_cached AND query_type <> 'other')
             / nullif(count(*) FILTER (WHERE was_cached), 0), 2) AS pct_cached_restored_as_select,
       round(100 * avg(was_aborted::INT), 2) AS pct_aborted,
       any_value(d.n) AS dropped_outside_period
FROM queries q JOIN dropped d USING (variant)
GROUP BY ALL ORDER BY variant;

-- name: query_types
-- The paper's Table 2 groups: RO = select, RW = insert/copy/delete/update/CTAS, Sys = maintenance + other.
-- Redset adds `unload` (export a select's result to S3): it reads, so it is grouped with RO, shown separately.
SELECT variant,
       CASE WHEN query_type IN ('select', 'unload') THEN 'RO'
            WHEN query_type IN ('insert', 'copy', 'delete', 'update', 'ctas') THEN 'RW'
            ELSE 'Sys' END AS grp,
       CASE query_type WHEN 'analyze' THEN 'maintenance (analyze)'
                       WHEN 'vacuum' THEN 'maintenance (vacuum)'
                       ELSE query_type END AS query_type,
       count(*) AS queries,
       round(100 * count(*) / sum(count(*)) OVER (PARTITION BY variant), 2) AS pct_queries,
       round(100 * sum(exec_ms) / sum(sum(exec_ms)) OVER (PARTITION BY variant), 2) AS pct_runtime,
       round(median(exec_ms) / 1000, 3) AS median_runtime_s,
       round(avg(exec_ms) / 1000, 3) AS mean_runtime_s
FROM queries
GROUP BY variant, queries.query_type
ORDER BY variant, grp, queries DESC;

-- name: runtime_buckets
-- Table 3: share of queries and of total runtime per runtime bucket.
WITH b AS (
    SELECT variant, exec_ms,
           CASE WHEN exec_ms <= 10 THEN 1 WHEN exec_ms <= 100 THEN 2 WHEN exec_ms <= 1000 THEN 3
                WHEN exec_ms <= 10000 THEN 4 WHEN exec_ms <= 60000 THEN 5 WHEN exec_ms <= 600000 THEN 6
                WHEN exec_ms <= 3600000 THEN 7 WHEN exec_ms < 36000000 THEN 8 ELSE 9 END AS bucket
    FROM queries
)
SELECT variant, bucket,
       ['(0s, 10ms]', '(10ms, 100ms]', '(100ms, 1s]', '(1s, 10s]', '(10s, 1min]', '(1min, 10min]',
        '(10min, 1h]', '(1h, 10h]', '>= 10h'][bucket] AS runtime_bucket,
       count(*) AS queries,
       round(100 * count(*) / sum(count(*)) OVER (PARTITION BY variant), 4) AS pct_queries,
       round(100 * sum(exec_ms) / sum(sum(exec_ms)) OVER (PARTITION BY variant), 2) AS pct_runtime
FROM b GROUP BY variant, bucket ORDER BY variant, bucket;

-- name: runtime_percentiles
-- Table 6 (runtime row; Redset has no memory column). Also for select statements only.
SELECT variant, scope,
       round(quantile_cont(exec_ms, 0.5) / 1000, 3) AS p50_s,
       round(quantile_cont(exec_ms, 0.9) / 1000, 3) AS p90_s,
       round(quantile_cont(exec_ms, 0.99) / 1000, 3) AS p99_s,
       round(quantile_cont(exec_ms, 0.999) / 1000, 3) AS p999_s,
       round(max(exec_ms) / 1000, 1) AS max_s,
       round(quantile_cont(exec_ms, 0.999) / nullif(quantile_cont(exec_ms, 0.5), 0), 0) AS p999_over_p50,
       round(quantile_cont(mbytes_scanned, 0.5), 1) AS p50_mb_scanned,
       round(quantile_cont(mbytes_scanned, 0.999), 1) AS p999_mb_scanned
FROM (SELECT variant, 'all' AS scope, exec_ms, mbytes_scanned FROM queries
      UNION ALL
      SELECT variant, 'select', exec_ms, mbytes_scanned FROM queries WHERE query_type = 'select')
GROUP BY ALL ORDER BY variant, scope;

-- name: runtime_share_top
-- "Less than 0.1 % of queries run longer than 1 h, they take up ~25 % of all resources."
SELECT variant,
       round(100 * avg((exec_ms > 3600000)::INT), 4) AS pct_queries_over_1h,
       round(100 * sum(exec_ms) FILTER (WHERE exec_ms > 3600000) / sum(exec_ms), 2) AS pct_runtime_over_1h,
       round(100 * avg((exec_ms <= 100)::INT), 2) AS pct_queries_under_100ms,
       round(100 * avg((exec_ms <= 60000)::INT), 2) AS pct_queries_under_1min,
       round(100 * sum(exec_ms) FILTER (WHERE exec_ms <= 60000) / sum(exec_ms), 2) AS pct_runtime_under_1min
FROM queries GROUP BY ALL ORDER BY variant;

-- name: plan_operators
-- Table 4: average plan operators per query, by runtime bucket. Redset has scans, joins and aggregations
-- (the paper also has sorts, windows, ...). Only executed queries: a result-cache hit runs no plan.
SELECT variant, scope,
       CASE WHEN exec_ms < 1000 THEN '(0s, 1s)' WHEN exec_ms < 60000 THEN '[1s, 60s)' ELSE '[60s, inf)' END
           AS runtime_bucket,
       count(*) AS queries,
       round(avg(num_scans), 2) AS scans,
       round(avg(num_joins), 2) AS joins,
       round(avg(num_aggregations), 2) AS aggregations
FROM (SELECT *, 'all' AS scope FROM queries UNION ALL
      SELECT *, 'select' FROM queries WHERE query_type = 'select')
WHERE num_scans IS NOT NULL AND NOT was_cached
GROUP BY GROUPING SETS ((variant, scope, runtime_bucket), (variant, scope))
ORDER BY variant, scope, runtime_bucket NULLS LAST;

-- name: joins_distribution
-- Long tail of query complexity: number of joins per select statement.
SELECT variant,
       CASE WHEN num_joins >= 10 THEN '10+' ELSE num_joins::VARCHAR END AS joins,
       count(*) AS queries,
       round(100 * count(*) / sum(count(*)) OVER (PARTITION BY variant), 3) AS pct
FROM queries WHERE query_type = 'select' AND num_joins IS NOT NULL AND NOT was_cached
GROUP BY variant, joins ORDER BY variant, min(num_joins);

-- name: external_system_tables
-- Share of queries touching external (S3) and system tables, by query type.
SELECT variant, query_type,
       count(*) AS queries,
       round(100 * avg((n_external > 0)::INT), 2) AS pct_external,
       round(100 * avg((n_system > 0)::INT), 2) AS pct_system
FROM queries GROUP BY GROUPING SETS ((variant, query_type), (variant))
ORDER BY variant, query_type NULLS FIRST;

-- name: by_month
-- Stability check: the headline query mix for each month.
SELECT variant, strftime(ts, '%Y-%m') AS month,
       count(*) AS queries,
       round(100 * avg((query_type = 'select')::INT), 2) AS pct_select,
       round(100 * avg((query_type IN ('insert', 'copy', 'delete', 'update', 'ctas'))::INT), 2) AS pct_rw,
       round(100 * sum(exec_ms) FILTER (WHERE query_type IN ('insert', 'copy', 'delete', 'update', 'ctas'))
             / sum(exec_ms), 2) AS pct_runtime_rw,
       round(100 * avg(was_cached::INT), 2) AS pct_cached
FROM queries GROUP BY ALL ORDER BY variant, month;
