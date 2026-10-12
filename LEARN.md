# LEARN: how this replication works, and how to defend it

This file explains the choices behind the code, the traps found in the data, and what to say about them in an interview. The results are in [README.md](README.md).

## 1. What kind of study this is

The paper (van Renen et al., *Why TPC Is Not Enough*, PVLDB 17(11), 2024) computes its numbers on **internal Redshift telemetry**: provisioned clusters, mostly one month (November 2023), with columns the public never sees (query text, filters, memory, table statistics). Next to the paper, Amazon published **Redset**: 200 provisioned and 200 serverless clusters, 1 March to 30 May 2024, with 24 columns per query.

So this is not a re-run of the paper's code on the paper's data. It is a **conceptual replication**: the same metrics, recomputed on a *different sample* of the same system. The question is "do the paper's conclusions survive on the data anyone can download?" There are three possible outcomes for each claim:

- **confirmed**: same direction, similar size;
- **partially confirmed**: same direction, very different size (or only measurable through a proxy);
- **not confirmed**: the public data says otherwise.

In an interview: *"I reproduced the paper's analyses on the public dataset the authors released with it. Some claims hold, some do not, and I can explain each difference from how the dataset was built."*

## 2. The pipeline

```
data/*.parquet (17.7 GB)  --00_prepare.sql-->  data/redset_full.duckdb (one typed `queries` table, 441 M rows)
                          --10..50_*.sql----->  results/<name>.csv  (one CSV per `-- name:` query)
                          --src/figures.py--->  figures/*.png
src/tpc.py: TPC-H / TPC-DS in DuckDB -> results/tpc_*.csv
```

- **DuckDB, not Spark.** 441 M rows fit one laptop: DuckDB is columnar, vectorized, and spills to disk when a sort or join does not fit in memory (`memory_limit = 20GB`, `temp_directory = data/tmp`). Building the database takes about 15 minutes; it is read many times afterwards.
- **One typed table instead of reading Parquet every time.** The fingerprint (a 64-character hex string) is hashed to a 64-bit integer, and the comma-separated table ids are parsed into integer lists. With ~4×10⁸ fingerprints, the chance that two different fingerprints of the *same cluster* collide on 64 bits is negligible (birthday bound ≈ n²/2⁶⁵ ≈ 10⁻³ over the whole trace, and comparisons are always within one cluster).
- **SQL files with `-- name:` markers** (the same contract as the SQL portfolio): each query's result is a CSV, so every number can be traced to a file and a query. A name starting with `_` is a setup step (a temporary table) and is not saved.
- **Develop on the 1 % sample, conclude on the full data** (`python src/run.py --sample`). Careful: a uniform 1 % sample of *queries* destroys everything that depends on sequences (repetition, cache, CTAS reuse). The sample is only for checking that the SQL runs.

## 3. Traps found in the data (the best interview stories)

1. **Result-cache hits are hidden in `other`.** In Redset, a select answered by the result cache is logged as `query_type = 'other'`, with no fingerprint, no tables and ~0 ms, plus a `cache_source_query_id` pointing at the select that produced the result (a select in 99.8 % of cases). Left as is, the selects are undercounted and the real cache hit rate among selects looks like **0 %**. `00_prepare.sql` restores them as selects with their source's fingerprint and tables (the original type is kept in `raw_query_type`). This changes the query mix, the repetition rates and the cache analysis.
2. **The trace ends on 30 May, not 31 May.** The last rows arrive seconds after midnight on 31 May. Keeping 31 May would add an almost empty day and fake a drop in the load (and in the daily spikiness). The period is 1 March to 30 May.
3. **Every CTAS creates a new table id.** In the provisioned trace there are 25.36 M CTAS creations and 25.34 M distinct target ids. "How often is the same table re-created?" cannot be answered with ids. The replication uses the CTAS statement's fingerprint instead (same statement re-run = same logical table). Conversely, this makes "who reads this CTAS table" exact: the readers of an id are the readers of that one creation.
4. **Staging tables inflate "distinct table sets".** The same fresh-id effect applies to every temporary or staging table, so a cluster can show thousands of distinct table sets. The replication reports both "all tables" and "long-lived tables only" (read on at least 2 different days of the month).
5. **The fingerprint is not the query text.** Redset's README says the fingerprint *overestimates* repetition. It sits between the paper's "query" (exact text) and "query template" (literals removed) metrics. Filters cannot be measured at all.

## 4. Metric by metric

| Metric | Definition used here | Why |
|---|---|---|
| Runtime | `execution_duration_ms` | the paper's "query runtime"; compile and queue time are excluded, as in Table 3 |
| Query type groups | RO = select (+ unload, shown separately), RW = insert/copy/delete/update/CTAS, Sys = analyze/vacuum/other | the paper's Table 2 groups; Redset has `unload`, the paper does not |
| Spikiness | series normalized to sum to 1, then Σ\|x_t − x_(t−1)\| over the days of a month (daily) or the 24 hours of the day (hourly) | the paper says "sum of RMSE between current and previous day" without a normalization; for two scalars the RMSE is the absolute difference. Check: the whole provisioned fleet gives 0.11 daily and 0.11 hourly (March), the paper's fleet gives 0.12 and 0.09, so the reading is right |
| Repetition | (queries − distinct fingerprints) / queries, per cluster and window, then the median over windows | the paper's definition and its worked example (3/8 = 37.5 %, a unit test) |
| Repetition by runtime | each fingerprint goes to the bucket of its longest runtime | as in the paper (Figure 6), so all repeats of a query land in one bucket |
| Downtime | median gap between consecutive selects (per cluster) and between repeats of one select (per fingerprint) | the paper's Figure 7 |

## 5. The extension: an ideal result cache

The paper says the real cache hit rate is ~20 %, that ~80 % of queries repeat, and lists why repeats miss. Redset allows the counterfactual: **replay every select of every cluster and decide whether a perfect cache could have answered it.**

Rules (in `sql/50_cache.sql`, tested in `tests/test_sql.py`):

1. same fingerprint seen before on the cluster, otherwise `first_run` (a compulsory miss);
2. no system or external tables (Redshift never caches them);
3. the previous run had finished when this one arrived, otherwise `concurrent`;
4. no write to any table it reads **committed since the previous run started**, otherwise `invalidated`. "Started", not "finished": a write that commits while the previous run is still executing makes its result stale (snapshot isolation).

The "last write to any of my tables before I arrived" is one **ASOF join** (each read table × the write log, matched on the latest commit before arrival), then a max per query. This replaces a per-query scan of the write log, which would be quadratic.

Two design points to defend:

- **Hit chains.** If the previous run was itself a hit, the cache entry dates from an earlier execution. Rule 4 still holds, because that hit already required no write since the entry's run; by induction, "no write since the previous run started" is the same as "no write since the entry was filled".
- **Saved runtime.** A real cache hit reports ~0 ms, so the cost of a query is the median runtime of its fingerprint when it really ran.

**Validation.** Real cache hits (`was_cached`) should almost all be classified `hit` by the model. If they were not, the model would be wrong, for example missing a way the real cache shares results. The share is in `results/cache_summary.csv` (`pct_real_hits_that_model_calls_hit`).

Then the policies: an **idle timeout** (an entry is dropped when its query has not been seen for T) turns the unlimited cache into a curve of hits and saved runtime against T.

## 6. Engineering lessons from the full run

- **Never UPDATE 46 M rows in place.** Restoring the cache hits with an `UPDATE` (and then with a join over the whole table) spilled for over an hour. Fixing only the cached rows in their own table, and defining `queries` as a view (`untouched rows UNION ALL fixed rows`), took 7 minutes.
- **One row per (query, table) is a billion rows.** The table-set analysis filled 92 GB of temporary files. The fix follows the paper: compute the expensive variant on 10 sampled busy clusters (fixed seed), and the cheap one (sets straight from the id lists) on all clusters.
- **Develop on the 1 % sample, but do not trust its numbers.** The SQL and the charts were built on the sample in seconds; repetition, cache and CTAS results only make sense on the full trace.
- **A laptop that sleeps pauses DuckDB.** Long runs need the machine kept awake.

## 7. Limits to state up front

- Redset is a **biased sample**: clusters were picked to cover all levels of "busyness", not uniformly. Fleet-wide shares are shares *of this sample*.
- Different period (March to May 2024 vs November 2023) and, for serverless, a different product.
- No query text, filters, memory, data types or table statistics: Section 5 of the paper (data skew, types, formats) is out of reach.
- The TPC side runs in DuckDB at SF 10 on a laptop, not Redshift at SF 3000. Only the *shape* of the runtime distribution and the plan operators per query are compared, not absolute times.

## 8. Two-minute pitch

> "I took a VLDB 2024 paper from Amazon that argues TPC benchmarks no longer match real cloud warehouse workloads, and replicated it on Redset, the 441-million-query trace they published with it. I built the pipeline in DuckDB on my laptop, wrote each metric as a tested SQL query, and compared every claim: 17 of 29 claims hold, including the importance of writes, the long tails and the 80 % repetition rate, but the query mix, CTAS usage and table sets are clearly different on the public data. I found three data traps, including cache hits logged as 'other', which made the cache look unused. Then I extended the paper with a result-cache simulation: an ASOF join finds the last write before each query, and a perfect cache would answer 63 % of selects instead of 34 %, saving three times more runtime. The model agrees with 97 % of the real cache hits, which is how I know it is right."
