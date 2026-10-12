| § | Claim | Paper | Redset provisioned | Redset serverless | Verdict |
|---|---|---|---|---|---|
| 3.2 | Queries that are selects | 48.9 % | 30.5 % | 30.9 % | not |
| 3.2 | Runtime spent in writes (insert, copy, delete, update, CTAS) | 66.8 % | 65.8 % | 60.8 % | confirmed |
| 3.3 | Runtime spent in CTAS | 16.4 % | 26.5 % | 3.6 % | partial |
| 3.4 | Queries under 100 ms | 62.0 % | 62.4 % | 40.1 % | confirmed |
| 3.4 | Runtime in queries over 1 h | 15.9 % | 12.7 % | 30.8 % | confirmed |
| 4.3 | Runtime tail: p99.9 / median | 2,030x | 7,483x | 7,066x | confirmed |
| 3.4 | Scans per executed query | 2.03 | 1.31 | 0.74 | partial |
| 3.4 | Joins per executed query | 0.53 | 0.52 | 0.56 | confirmed |
| 4.1 | Fleet daily spikiness (March) | 0.12 | 0.11 | 0.15 | confirmed |
| 4.2 | Fleet hourly spikiness (March) | 0.09 | 0.11 | 0.13 | confirmed |
| 4.1 | Clusters at most as spiky as the paper's C2 (daily, 0.28) | 75.0 % | 50.0 % | 12.5 % | partial |
| 4.4 | Repeated queries in the median cluster (month) | 80.0 % | 79.0 % | 54.5 % | confirmed |
| 4.4 | Fingerprints of long queries (10 min-10 h) that repeat, median cluster | - | 82.0 % | 87.3 % | confirmed |
| 4.4 | Same, for queries under 10 ms | - | 32.4 % | 49.7 % | confirmed |
| 4.4 | Median gap between repeats of a select, median cluster | 100 s | 42 s | 35 s | confirmed |
| 4.4 | Median gap between repeats, median repeating query | - | 599 s | 278 s | n/a |
| 4.4 | Longest median repeat gap of a cluster | 12.0 d | 1.0 d | 2.7 d | not |
| 4.6 | Selects that repeat a previous select | 80.0 % | 92.9 % | 92.9 % | confirmed |
| 4.6 | Selects answered by the real result cache | 20.0 % | 33.6 % | 14.8 % | partial |
| 4.6 | Repeating selects that still miss the cache | 60.0 % | 63.9 % | 84.1 % | confirmed |
| 4.6 | ↳ of those misses: reads system tables | 14.0 % | 12.4 % | 51.2 % | partial |
| 4.6 | ↳ of those misses: reads external tables | 4.0 % | 3.3 % | 3.7 % | confirmed |
| 4.6 | ↳ of those misses: a table was written since | 54.0 % | 24.8 % | 5.9 % | partial |
| 3.3 | CTAS statements run once in a week | 66.0 % | 70.8 % | 66.3 % | confirmed |
| 3.3 | CTAS tables read by exactly one query | 80.0 % | 8.1 % | 13.3 % | not |
| 3.3 | Queries reading a CTAS-created table | 40.0 % | 17.6 % | 2.8 % | not |
| 4.5 | Distinct table sets in a busy cluster-month (10 sampled) | 23.5 | 5,884 | - | not |
| 5.2 | Tables with inserts and no deletes the same day | 80.0 % | 76.9 % | 79.1 % | confirmed |
| 5.2 | Tables with deletes and no inserts the same day | 30.0 % | 19.5 % | 1.4 % | partial |
| 3.4 | Runtime spread, p90 / median (TPC-H 22 queries in DuckDB SF 10: 3.6x) | - | 38x | 51x | confirmed |

verdict
confirmed    17
partial       7
not           5
n/a           1
TpchSpread = 3.60
TpcdsSpread = 5.05
TpchScans = 3.77
TpchJoins = 3.45
TpcdsScans = 7.42
TpcdsJoins = 6.78
QueriesProv = 433107731.00
QueriesServ = 8244381.00
CachedRestoredProv = 96.23
IdealHitProv = 63.13
IdealHitServ = 38.62
RealHitProv = 33.57
RealHitServ = 14.81
IdealSavedProv = 25.06
IdealSavedServ = 17.57
RealSavedProv = 8.35
RealSavedServ = 1.25
ModelExplainsProv = 97.45
ModelExplainsServ = 99.14
AllTableSetsMean = 97636.60
TtlTenMinHitProv = 56.34
TtlTenMinSavedProv = 14.91
TtlOneHourHitProv = 59.81
TtlOneHourSavedProv = 19.75
TtlTenMinHitServ = 27.01
TtlTenMinSavedServ = 11.89
TtlOneHourHitServ = 32.93
TtlOneHourSavedServ = 16.15
