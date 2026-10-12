-- Section 4.1-4.3 of the paper: how does the load vary over time? (Figures 1-4)
--
-- Load = number of queries (as in the paper). Read = select; write = insert/copy/delete/update/CTAS; all = every query.
-- Spikiness (the paper: "the sum of the root mean square errors between the current and previous day/hour").
-- The paper does not give the normalization; we normalize each series to sum to 1 so clusters of any size are
-- comparable, then sum |x_t - x_(t-1)| (the RMSE of two scalars is their absolute difference):
--   daily:  x_d = share of the month's queries on day d, d = 1..days in month
--   hourly: x_h = share of the month's queries in hour-of-day h, h = 0..23
-- A perfectly flat load scores 0; all load on one day/hour scores 2.

-- name: _cluster_days
CREATE OR REPLACE TEMP TABLE cluster_days AS
WITH grid AS (
    SELECT c.variant, c.instance_id, t.d::DATE AS day
    FROM (SELECT DISTINCT variant, instance_id FROM queries) c,
         range(TIMESTAMP '2024-03-01', TIMESTAMP '2024-05-31', INTERVAL 1 DAY) t(d)
), cnt AS (
    SELECT variant, instance_id, ts::DATE AS day,
           count(*) AS n_all,
           count(*) FILTER (WHERE query_type = 'select') AS n_read,
           count(*) FILTER (WHERE query_type IN ('insert', 'copy', 'delete', 'update', 'ctas')) AS n_write
    FROM queries GROUP BY variant, instance_id, day
)
SELECT g.variant, g.instance_id, g.day, strftime(g.day, '%Y-%m') AS month,
       coalesce(n_all, 0) AS n_all, coalesce(n_read, 0) AS n_read, coalesce(n_write, 0) AS n_write
FROM grid g LEFT JOIN cnt USING (variant, instance_id, day);

-- name: _cluster_hours
CREATE OR REPLACE TEMP TABLE cluster_hours AS
WITH grid AS (
    SELECT c.variant, c.instance_id, m.month, h.hour
    FROM (SELECT DISTINCT variant, instance_id FROM queries) c,
         (VALUES ('2024-03'), ('2024-04'), ('2024-05')) m(month),
         range(24) h(hour)
), cnt AS (
    SELECT variant, instance_id, strftime(ts, '%Y-%m') AS month, hour(ts) AS hour,
           count(*) AS n_all,
           count(*) FILTER (WHERE query_type = 'select') AS n_read,
           count(*) FILTER (WHERE query_type IN ('insert', 'copy', 'delete', 'update', 'ctas')) AS n_write
    FROM queries GROUP BY variant, instance_id, month, hour
)
SELECT g.variant, g.instance_id, g.month, g.hour,
       coalesce(n_all, 0) AS n_all, coalesce(n_read, 0) AS n_read, coalesce(n_write, 0) AS n_write
FROM grid g LEFT JOIN cnt USING (variant, instance_id, month, hour);

-- name: daily_load
-- Every cluster's daily load (instance_id -1 = the whole fleet of that variant), for the figures.
SELECT variant, instance_id, day, n_all, n_read, n_write FROM cluster_days
UNION ALL
SELECT variant, -1, day, sum(n_all), sum(n_read), sum(n_write) FROM cluster_days GROUP BY variant, day
ORDER BY variant, instance_id, day;

-- name: hourly_load
SELECT variant, instance_id, month, hour, n_all, n_read, n_write FROM cluster_hours
UNION ALL
SELECT variant, -1, month, hour, sum(n_all), sum(n_read), sum(n_write) FROM cluster_hours GROUP BY variant, month, hour
ORDER BY variant, instance_id, month, hour;

-- name: spikiness
-- One row per variant, cluster (-1 = fleet), month, granularity (daily/hourly) and load kind (all/read/write).
WITH series AS (
    SELECT variant, instance_id, month, 'daily' AS granularity, epoch(day)::BIGINT AS t, n_all, n_read, n_write
    FROM cluster_days
    UNION ALL
    SELECT variant, -1, month, 'daily', epoch(day)::BIGINT, sum(n_all), sum(n_read), sum(n_write)
    FROM cluster_days GROUP BY variant, month, day
    UNION ALL
    SELECT variant, instance_id, month, 'hourly', hour, n_all, n_read, n_write FROM cluster_hours
    UNION ALL
    SELECT variant, -1, month, 'hourly', hour, sum(n_all), sum(n_read), sum(n_write)
    FROM cluster_hours GROUP BY variant, month, hour
), long AS (
    UNPIVOT series ON n_all AS "all", n_read AS "read", n_write AS "write" INTO NAME kind VALUE n
), shares AS (
    SELECT *, n / sum(n) OVER (PARTITION BY variant, instance_id, month, granularity, kind) AS x
    FROM long
), diffs AS (
    SELECT *, abs(x - lag(x) OVER (PARTITION BY variant, instance_id, month, granularity, kind ORDER BY t)) AS d
    FROM shares
)
SELECT variant, instance_id, month, granularity, kind,
       sum(n)::BIGINT AS queries,
       round(sum(d), 4) AS spikiness
FROM diffs
GROUP BY variant, instance_id, month, granularity, kind
HAVING sum(n) > 0
ORDER BY variant, granularity, kind, month, instance_id;

-- name: daily_queries_distribution
-- Section 4.3: the long tail of the daily number of queries per cluster (active days only).
SELECT variant,
       count(*) AS active_cluster_days,
       quantile_cont(n_all, 0.5)::BIGINT AS p50,
       quantile_cont(n_all, 0.9)::BIGINT AS p90,
       quantile_cont(n_all, 0.99)::BIGINT AS p99,
       max(n_all) AS max,
       round(quantile_cont(n_all, 0.99) / quantile_cont(n_all, 0.5), 1) AS p99_over_p50
FROM cluster_days WHERE n_all > 0 GROUP BY variant ORDER BY variant;

-- name: weekly_pattern
-- Weekend load relative to weekdays, per cluster (1 = no weekly pattern). Full weeks 4 March - 26 May.
SELECT variant, instance_id,
       sum(n_all) AS queries,
       round(avg(n_all) FILTER (WHERE dayofweek(day) IN (0, 6))
             / nullif(avg(n_all) FILTER (WHERE dayofweek(day) NOT IN (0, 6)), 0), 3) AS weekend_over_weekday
FROM cluster_days
WHERE day BETWEEN DATE '2024-03-04' AND DATE '2024-05-26'
GROUP BY variant, instance_id HAVING sum(n_all) > 0
ORDER BY variant, instance_id;
