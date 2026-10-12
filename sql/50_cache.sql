-- Extension: how much could a result cache save? (builds on Section 4.6 of the paper)
--
-- Replay of every select statement, per cluster, in arrival order. An ideal result cache (unlimited size,
-- exact table-level invalidation) answers a select from its cache when:
--   1. the same select (same fingerprint) ran before on the cluster,
--   2. it reads no system or external table (Redshift never caches those: catalog data, S3 files),
--   3. the previous run had finished when this one arrives (otherwise its result is not there yet),
--   4. no write (insert, copy, delete, update, CTAS, ...) to a table it reads committed since the previous
--      run started (a write committing during the previous run makes that result stale too).
-- Each select gets the first class it fails, in this order:
--   no_fingerprint, first_run (compulsory miss), system_tables, external_tables, concurrent, invalidated, hit.
-- Redset's own `was_cached` (Redshift's real result cache) is kept alongside, to validate the model:
-- real hits should almost all be ideal hits.
-- Saved runtime is measured with each fingerprint's median runtime when it really ran (was_cached = false),
-- because a cached query reports ~0 ms.

-- name: _sel
CREATE OR REPLACE TEMP TABLE sel AS
SELECT variant, instance_id, query_id, ts, end_ts, exec_ms, fp, was_cached, read_ids,
       coalesce(n_system, 0) > 0 AS uses_system, coalesce(n_external, 0) > 0 AS uses_external,
       CASE WHEN fp IS NOT NULL THEN lag(ts) OVER w END AS prev_ts,
       CASE WHEN fp IS NOT NULL THEN lag(end_ts) OVER w END AS prev_end
FROM queries
WHERE query_type = 'select'
WINDOW w AS (PARTITION BY variant, instance_id, fp ORDER BY ts, query_id);

-- name: _table_writes
CREATE OR REPLACE TEMP TABLE table_writes AS
SELECT variant, instance_id, unnest(write_ids) AS table_id, end_ts AS committed
FROM queries WHERE write_ids IS NOT NULL AND NOT coalesce(was_aborted, false);

-- name: _last_write
-- For each repeated select: the last commit, before it arrives, of a write to any table it reads.
CREATE OR REPLACE TEMP TABLE last_write AS
WITH r AS (
    SELECT variant, instance_id, query_id, ts, unnest(read_ids) AS table_id
    FROM sel WHERE prev_ts IS NOT NULL AND read_ids IS NOT NULL
)
SELECT r.variant, r.instance_id, r.query_id, max(w.committed) AS last_commit
FROM r ASOF LEFT JOIN table_writes w
  ON r.variant = w.variant AND r.instance_id = w.instance_id AND r.table_id = w.table_id AND r.ts >= w.committed
GROUP BY r.variant, r.instance_id, r.query_id;

-- name: _cache_sim
CREATE OR REPLACE TEMP TABLE cache_sim AS
WITH cost AS (
    SELECT variant, instance_id, fp, median(exec_ms) AS fp_ms
    FROM sel WHERE fp IS NOT NULL AND NOT was_cached GROUP BY ALL
)
SELECT s.variant, s.instance_id, s.query_id, s.ts, s.was_cached,
       CASE WHEN s.fp IS NULL THEN 'no_fingerprint'
            WHEN s.prev_ts IS NULL THEN 'first_run'
            WHEN s.uses_system THEN 'system_tables'
            WHEN s.uses_external THEN 'external_tables'
            WHEN s.prev_end > s.ts THEN 'concurrent'
            WHEN lw.last_commit >= s.prev_ts THEN 'invalidated'
            ELSE 'hit' END AS class,
       epoch(s.ts - s.prev_ts) AS since_prev_s,
       coalesce(CASE WHEN s.was_cached THEN c.fp_ms END, s.exec_ms, 0) AS cost_ms
FROM sel s
LEFT JOIN last_write lw USING (variant, instance_id, query_id)
LEFT JOIN cost c USING (variant, instance_id, fp);

-- name: cache_classes
SELECT variant, class, was_cached,
       count(*) AS selects,
       round(100 * count(*) / sum(count(*)) OVER (PARTITION BY variant), 3) AS pct_selects,
       round(100 * sum(cost_ms) / sum(sum(cost_ms)) OVER (PARTITION BY variant), 3) AS pct_runtime
FROM cache_sim GROUP BY variant, class, was_cached
ORDER BY variant, class, was_cached;

-- name: cache_summary
-- Real cache vs ideal cache; and how well the model explains the real hits.
SELECT variant,
       count(*) AS selects,
       round(100 * avg(was_cached::INT), 2) AS real_hit_pct,
       round(100 * avg((class = 'hit')::INT), 2) AS ideal_hit_pct,
       round(100 * sum(cost_ms) FILTER (WHERE was_cached) / sum(cost_ms), 2) AS real_saved_runtime_pct,
       round(100 * sum(cost_ms) FILTER (WHERE class = 'hit') / sum(cost_ms), 2) AS ideal_saved_runtime_pct,
       round(100 * count(*) FILTER (WHERE was_cached AND class = 'hit') / count(*) FILTER (WHERE was_cached), 2)
           AS pct_real_hits_that_model_calls_hit,
       round(100 * count(*) FILTER (WHERE was_cached AND class = 'hit') / count(*) FILTER (WHERE class = 'hit'), 2)
           AS pct_ideal_hits_really_cached,
       round(100 * avg((class NOT IN ('no_fingerprint', 'first_run'))::INT), 2) AS repeating_pct
FROM cache_sim GROUP BY variant ORDER BY variant;

-- name: cache_ttl
-- Idle-timeout policy: an entry is dropped when its query has not been seen for `ttl`.
-- Hits that survive each timeout, as a share of all selects and of all select runtime.
WITH t(ttl_label, ttl_s) AS (
    VALUES ('1 s', 1), ('10 s', 10), ('1 min', 60), ('10 min', 600), ('1 h', 3600), ('6 h', 21600),
           ('1 day', 86400), ('1 week', 604800), ('unlimited', 1e12)
), totals AS (
    SELECT variant, count(*) AS n, sum(cost_ms) AS ms FROM cache_sim GROUP BY variant
)
SELECT c.variant, t.ttl_label, t.ttl_s,
       count(*) AS hits,
       round(100 * count(*) / any_value(totals.n), 2) AS hit_pct,
       round(100 * sum(c.cost_ms) / any_value(totals.ms), 2) AS saved_runtime_pct
FROM cache_sim c JOIN totals USING (variant), t
WHERE c.class = 'hit' AND c.since_prev_s <= t.ttl_s
GROUP BY c.variant, t.ttl_label, t.ttl_s ORDER BY c.variant, t.ttl_s;

-- name: cache_by_cluster
SELECT variant, instance_id,
       count(*) AS selects,
       round(100 * avg(was_cached::INT), 2) AS real_hit_pct,
       round(100 * avg((class = 'hit')::INT), 2) AS ideal_hit_pct,
       round(100 * sum(cost_ms) FILTER (WHERE class = 'hit') / nullif(sum(cost_ms), 0), 2) AS ideal_saved_runtime_pct
FROM cache_sim GROUP BY variant, instance_id ORDER BY variant, instance_id;
