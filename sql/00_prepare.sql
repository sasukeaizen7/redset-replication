-- One table for both Redset variants, typed for the analyses.
-- {provisioned} and {serverless} are replaced by the Parquet paths (full dataset or 1 % samples).
--
-- Choices (explained in LEARN.md):
--   * keep 1 March to 30 May 2024: the trace ends at midnight on 31 May (a few rows arrive seconds before 1 March or after the end);
--   * fingerprint hashed to a 64-bit integer: the analyses only compare fingerprints for equality,
--     and an integer is ~8x cheaper than the 64-char hex string over 441 M rows;
--   * end_ts = arrival + compile + queue + execution: when a query's result (or its write) becomes visible;
--   * table ids parsed from "12,57" strings into integer lists;
--   * result-cache hits: Redset logs them as query_type 'other' with no fingerprint and no tables, plus a
--     cache_source_query_id pointing at the select that produced the result (a select in 99.8 % of cases).
--     They are restored as selects with their source's fingerprint and tables (raw_query_type keeps 'other').

SET preserve_insertion_order = false;

CREATE OR REPLACE TABLE queries_raw AS
WITH raw AS (
    SELECT 'provisioned' AS variant, * FROM read_parquet('{provisioned}')
    UNION ALL BY NAME
    SELECT 'serverless' AS variant, * FROM read_parquet('{serverless}')
)
SELECT
    variant,
    instance_id,
    user_id,
    database_id,
    query_id,
    query_type,
    query_type AS raw_query_type,
    cache_source_query_id,
    arrival_timestamp AS ts,
    arrival_timestamp + to_microseconds(round(1000 * (coalesce(compile_duration_ms, 0)
                                                     + coalesce(queue_duration_ms, 0)
                                                     + coalesce(execution_duration_ms, 0)))::BIGINT) AS end_ts,
    compile_duration_ms AS compile_ms,
    queue_duration_ms AS queue_ms,
    execution_duration_ms AS exec_ms,
    CASE WHEN feature_fingerprint IS NOT NULL THEN hash(feature_fingerprint) END AS fp,
    was_aborted,
    was_cached,
    num_permanent_tables_accessed::INTEGER AS n_permanent,
    num_external_tables_accessed::INTEGER AS n_external,
    num_system_tables_accessed::INTEGER AS n_system,
    CASE WHEN nullif(read_table_ids, '') IS NOT NULL
         THEN list_transform(string_split(read_table_ids, ','), x -> x::BIGINT) END AS read_ids,
    CASE WHEN nullif(write_table_ids, '') IS NOT NULL
         THEN list_transform(string_split(write_table_ids, ','), x -> x::BIGINT) END AS write_ids,
    mbytes_scanned,
    mbytes_spilled,
    num_joins,
    num_scans,
    num_aggregations
FROM raw
WHERE arrival_timestamp >= TIMESTAMP '2024-03-01' AND arrival_timestamp < TIMESTAMP '2024-05-31';

-- Restore cache hits. Only the ~46 M cached rows change, so they are fixed in a table of their own and
-- `queries` is a view over the untouched rows plus the fixed ones: no rewrite of the 441 M-row table
-- (an UPDATE, or a join over the whole table, took over an hour).
CREATE OR REPLACE TABLE cache_hits AS
SELECT q.* REPLACE (
           coalesce(s.query_type, q.query_type) AS query_type,
           coalesce(q.fp, s.fp) AS fp,
           coalesce(q.read_ids, s.read_ids) AS read_ids,
           coalesce(q.n_permanent, s.n_permanent) AS n_permanent,
           coalesce(q.n_external, s.n_external) AS n_external,
           coalesce(q.n_system, s.n_system) AS n_system)
FROM (SELECT * FROM queries_raw WHERE was_cached) q
LEFT JOIN (SELECT variant, instance_id, query_id, query_type, fp, read_ids, n_permanent, n_external, n_system
           FROM queries_raw WHERE NOT was_cached) s
  ON q.variant = s.variant AND q.instance_id = s.instance_id AND q.cache_source_query_id = s.query_id;

CREATE OR REPLACE VIEW queries AS
SELECT * FROM queries_raw WHERE NOT was_cached
UNION ALL
SELECT * FROM cache_hits;

-- Clusters: provisioned size (number of nodes) when known.
CREATE OR REPLACE TABLE clusters AS
SELECT 'provisioned' AS variant, instance_id, max(cluster_size) AS cluster_size
FROM read_parquet('{provisioned}') GROUP BY ALL
UNION ALL
SELECT 'serverless', instance_id, NULL FROM read_parquet('{serverless}') GROUP BY ALL;

-- Rows dropped by the date filter, for the data-coverage table.
CREATE OR REPLACE TABLE dropped AS
SELECT 'provisioned' AS variant, count(*) AS n FROM read_parquet('{provisioned}')
WHERE NOT (arrival_timestamp >= TIMESTAMP '2024-03-01' AND arrival_timestamp < TIMESTAMP '2024-05-31')
UNION ALL
SELECT 'serverless', count(*) FROM read_parquet('{serverless}')
WHERE NOT (arrival_timestamp >= TIMESTAMP '2024-03-01' AND arrival_timestamp < TIMESTAMP '2024-05-31');
