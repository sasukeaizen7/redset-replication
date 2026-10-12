Spent the last few weeks re-checking a VLDB 2024 paper from Amazon on 441 million real queries, on my laptop, to learn how real cloud data warehouses are actually used.

The paper is called "Why TPC Is Not Enough". Its argument: the benchmarks everyone uses to compare databases (TPC-H, TPC-DS) look nothing like what companies really run on Amazon Redshift. Real workloads are full of writes, the same queries come back again and again, and a handful of huge queries eat most of the time.

The authors computed their numbers on internal Amazon data nobody else can see. But they also released a public dataset, Redset: three months of query logs from 400 clusters. So I asked a simple question: do their conclusions still hold on the data anyone can download?

I rebuilt every metric I could as SQL in DuckDB, ran it on the full 441M rows, and compared 29 claims side by side.

The data had a few surprises, and they mattered more than the model or the code.

First one: the result cache looked completely unused. 0% of select queries served from cache, which made no sense. It turned out that cache hits are logged as "other", with no query fingerprint and no tables, just a pointer to the original query. Once I linked them back, a third of all select queries reappeared and the real cache hit rate went from 0% to 34%.

Second one was sneakier: every CREATE TABLE AS SELECT gets a brand-new table id, even when it recreates "the same" table every night. So anything that tracks tables by id quietly counts thousands of tables that are really one. I had to follow the query's fingerprint instead.

There were engineering lessons too. Updating 46 million rows in place ran for over an hour and I killed it. Rewriting it as a small fixed table plus a view took 7 minutes. Another query filled 92 GB of temp files and crashed before I redesigned it.

The result: 17 claims confirmed, 7 partially, 5 not.
- Writes take two thirds of the runtime, like in the paper.
- 79% of queries repeat in a typical cluster (paper: 80%).
- The long tail is even longer than reported.
- But the query mix, how CTAS tables are used, and the number of distinct table sets look quite different on the public data.

Then I added one thing the paper doesn't measure. I replayed every query against a perfect result cache: same query seen before, and no write to its tables since. It would answer 63% of selects instead of 34%, and save 3x more compute. The model agrees with 97% of the cache hits Redshift really made, which is how I know it's not fooling itself.

My favorite finding: the cache hits are cheap queries repeated within seconds, but the savings come from expensive queries repeated hours apart. A short timeout keeps almost all the hits and loses 40% of the savings.

Full write-up (7 pages, with the methodology, all the plots and every place I disagree with the paper) attached below. The code is on GitHub. Thanks to the authors for releasing the data, it's rare and it's what made this possible.

#DataEngineering #Databases #DuckDB #SQL #Research
