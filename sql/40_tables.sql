-- Sections 3.3 (CTAS), 4.5 (common table sets) and 5.2 (table change) of the paper, from table ids.
-- Table ids are per cluster: a table is (variant, instance_id, table_id).
-- Inserts = insert + copy (both add rows); deletes = delete; CTAS (re)creates its target table.

-- name: _reads
CREATE OR REPLACE TEMP TABLE reads AS
SELECT variant, instance_id, query_id, ts, query_type, unnest(read_ids) AS table_id
FROM queries WHERE read_ids IS NOT NULL;

-- name: _writes
CREATE OR REPLACE TEMP TABLE writes AS
SELECT variant, instance_id, query_id, ts, end_ts, query_type, unnest(write_ids) AS table_id
FROM queries WHERE write_ids IS NOT NULL;

-- name: _ctas
-- Every CTAS creation. In Redset a CTAS always gets a fresh table id (25.36 M creations, 25.34 M distinct ids in
-- the provisioned trace), so the reads of a table id are exactly the reads of that one creation.
CREATE OR REPLACE TEMP TABLE ctas AS
SELECT variant, instance_id, table_id, query_id, ts, end_ts FROM writes WHERE query_type = 'ctas';

-- name: ctas_recreation
-- "~66 % of CTAS tables are created only once within the span of a week". Fresh ids make the table id useless
-- here, so the same CTAS statement (same fingerprint) re-run stands for re-creating the same table.
WITH weekly AS (
    SELECT variant, instance_id, fp, date_trunc('week', ts) AS week, count(*) AS creations
    FROM queries
    WHERE query_type = 'ctas' AND fp IS NOT NULL
      AND date_trunc('week', ts) BETWEEN DATE '2024-03-04' AND DATE '2024-05-20'
    GROUP BY ALL
)
SELECT variant,
       CASE WHEN creations = 1 THEN '1' WHEN creations <= 7 THEN '2-7' WHEN creations <= 168 THEN '8-168'
            ELSE '>168' END AS creations_per_week,
       count(*) AS statement_weeks,
       round(100 * count(*) / sum(count(*)) OVER (PARTITION BY variant), 2) AS pct
FROM weekly GROUP BY variant, creations_per_week ORDER BY variant, min(creations);

-- name: ctas_usage
-- "~80 % of CTAS tables are only used by one query": distinct queries reading each created table.
WITH uses AS (
    SELECT c.variant, count(DISTINCT r.query_id) AS readers
    FROM ctas c LEFT JOIN reads r
      ON r.variant = c.variant AND r.instance_id = c.instance_id AND r.table_id = c.table_id AND r.query_id <> c.query_id
    GROUP BY c.variant, c.instance_id, c.table_id
)
SELECT variant,
       CASE WHEN readers = 0 THEN '0' WHEN readers = 1 THEN '1' WHEN readers <= 5 THEN '2-5' ELSE '>5' END AS readers,
       count(*) AS creations,
       round(100 * count(*) / sum(count(*)) OVER (PARTITION BY variant), 2) AS pct
FROM uses GROUP BY variant, 2 ORDER BY variant, min(uses.readers);

-- name: ctas_reach
-- "Roughly 40 % of queries overall utilize [CTAS tables]": share of queries reading a table that some CTAS created.
WITH targets AS (SELECT DISTINCT variant, instance_id, table_id FROM ctas),
q AS (SELECT DISTINCT r.variant, r.instance_id, r.query_id FROM reads r SEMI JOIN targets USING (variant, instance_id, table_id))
SELECT t.variant, t.queries, count(q.query_id) AS queries_reading_ctas_tables,
       round(100 * count(q.query_id) / t.queries, 2) AS pct
FROM (SELECT variant, count(*) AS queries FROM queries GROUP BY variant) t
LEFT JOIN q USING (variant)
GROUP BY t.variant, t.queries ORDER BY t.variant;

-- name: table_sets
-- Section 4.5: distinct sets of tables read together, per cluster and month, and how many of the most frequent
-- sets cover 90 % of the queries. Scope 'all' uses every cluster. Staging/temporary tables get a fresh id on
-- every run, which inflates the count; scope 'long-lived' keeps only tables read on at least 2 different days
-- of the month. That one needs one row per (query, table), so like the paper it uses 10 random clusters with
-- more than 50,000 queries in the month (fixed seed); 'all' is also given for those 10 clusters.
WITH sets AS (
    SELECT variant, instance_id, strftime(ts, '%Y-%m') AS month, list_sort(list_distinct(read_ids)) AS tables,
           count(*) AS cnt
    FROM queries WHERE read_ids IS NOT NULL
    GROUP BY ALL
), picked AS (
    SELECT variant, instance_id, month FROM (
        SELECT variant, instance_id, month, sum(cnt) AS n FROM sets GROUP BY ALL HAVING sum(cnt) > 50000
    ) USING SAMPLE reservoir(10 ROWS) REPEATABLE (42)
), rm AS (
    SELECT r.*, strftime(r.ts, '%Y-%m') AS month FROM reads r
    SEMI JOIN picked p ON r.variant = p.variant AND r.instance_id = p.instance_id
                       AND strftime(r.ts, '%Y-%m') = p.month
), long_lived AS (
    SELECT variant, instance_id, month, table_id FROM rm
    GROUP BY ALL HAVING count(DISTINCT ts::DATE) >= 2
), ll_sets AS (
    SELECT variant, instance_id, month, tables, count(*) AS cnt FROM (
        SELECT variant, instance_id, month, query_id, list_sort(list_distinct(list(table_id))) AS tables
        FROM rm SEMI JOIN long_lived USING (variant, instance_id, month, table_id)
        GROUP BY variant, instance_id, month, query_id
    ) GROUP BY ALL
), scoped AS (
    SELECT *, 'all' AS scope, false AS sampled FROM sets
    UNION ALL
    SELECT s.*, 'all', true FROM sets s SEMI JOIN picked USING (variant, instance_id, month)
    UNION ALL
    SELECT *, 'long-lived', true FROM ll_sets
), ranked AS (
    SELECT *, sum(cnt) OVER (PARTITION BY variant, instance_id, month, scope, sampled ORDER BY cnt DESC, tables
                             ROWS UNBOUNDED PRECEDING) AS running,
              sum(cnt) OVER (PARTITION BY variant, instance_id, month, scope, sampled) AS total
    FROM scoped
)
SELECT variant, instance_id, month, scope, sampled,
       any_value(total)::BIGINT AS queries,
       count(*) AS distinct_sets,
       count(*) FILTER (WHERE running - cnt < 0.9 * total) AS sets_for_90pct
FROM ranked GROUP BY variant, instance_id, month, scope, sampled
ORDER BY variant, sampled, instance_id, month, scope;

-- name: table_changes
-- Table 9 (approximation): of the tables a cluster touched in a month, which ones received inserts or deletes.
-- Redset has no row counts, so "stable / growing / shrinking" cannot be told apart; we split by write kind.
WITH touched AS (
    SELECT variant, instance_id, strftime(ts, '%Y-%m') AS month, table_id FROM reads
    UNION
    SELECT variant, instance_id, strftime(ts, '%Y-%m'), table_id FROM writes
), changed AS (
    SELECT variant, instance_id, strftime(ts, '%Y-%m') AS month, table_id,
           bool_or(query_type IN ('insert', 'copy')) AS ins,
           bool_or(query_type = 'delete') AS del,
           bool_or(query_type = 'update') AS upd,
           bool_or(query_type = 'ctas') AS created
    FROM writes GROUP BY ALL
)
SELECT t.variant,
       CASE WHEN c.table_id IS NULL OR NOT (c.ins OR c.del OR c.upd OR c.created) THEN 'no insert/delete/update'
            WHEN c.created THEN 'created by CTAS'
            WHEN c.ins AND c.del THEN 'inserts and deletes'
            WHEN c.ins THEN 'inserts only'
            WHEN c.del THEN 'deletes only'
            ELSE 'updates only' END AS change,
       count(*) AS table_months,
       round(100 * count(*) / sum(count(*)) OVER (PARTITION BY t.variant), 2) AS pct
FROM touched t LEFT JOIN changed c USING (variant, instance_id, month, table_id)
GROUP BY t.variant, change ORDER BY t.variant, table_months DESC;

-- name: daily_inserts_deletes
-- "~80 % of tables receiving inserts did not receive deletes the same day, ~30 % of tables receiving deletes
-- did not receive inserts the same day."
WITH d AS (
    SELECT variant, instance_id, table_id, ts::DATE AS day,
           bool_or(query_type IN ('insert', 'copy')) AS ins,
           bool_or(query_type = 'delete') AS del
    FROM writes GROUP BY ALL
)
SELECT variant,
       count(*) FILTER (WHERE ins) AS table_days_with_inserts,
       round(100 * count(*) FILTER (WHERE ins AND NOT del) / count(*) FILTER (WHERE ins), 2) AS pct_inserts_without_deletes,
       count(*) FILTER (WHERE del) AS table_days_with_deletes,
       round(100 * count(*) FILTER (WHERE del AND NOT ins) / count(*) FILTER (WHERE del), 2) AS pct_deletes_without_inserts
FROM d GROUP BY variant ORDER BY variant;
