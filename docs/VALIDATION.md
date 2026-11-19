# Validation record — 19 November 2026

This is a local Python/SQLite data-analysis project. The observed export is **2026-11-18**; acquisition and validation took place **2026-11-19**. No cloud, clinical, distributed-load or continuous-monitoring validation is claimed.

## Deterministic suite

Executed on macOS with **Python 3.14.7**:

```sh
python3 -W error::ResourceWarning -m unittest discover -s tests -v
```

**40 tests passed**: 16 source adapter, 10 warehouse, 11 report, and 3 CLI tests. The captured output is [examples/test-results.txt](../examples/test-results.txt).

Coverage includes complete-export checks, undeclared growth and partition drift, archive bounds, truncated/tampered caches, manifest changes, corrected bytes under unchanged metadata, repeat-acquisition provenance, transactional rollback, concurrent identical loads, older-export backfills, multiset history, duplicate conservation, quarantine, category overlap, recency boundaries, explicit missing availability, concurrent reader consistency, report atomicity and competing writers. End-to-end tests run the fictional demo and CLI from an unrelated working directory. Synthetic and custom-source reports are checked for truthful labels.

The GitHub workflow targets Python **3.12 and 3.14** on Linux. Its badge and Actions run are the source of truth for remote execution; this local record does not imply that a cloud data platform was deployed.

## Bounded public-source smoke

Executed:

```sh
python3 validate_live.py --data-dir data --output examples/observed
```

At **2026-11-19T01:16:16.374551Z**, the source adapter acquired the complete FDA archive between matching pre/post manifest reads. The live numerical/replay validation finished at **2026-11-19T01:16:16.535592Z**. Its aggregate-only evidence is preserved as [live-acquisition.json](../examples/observed/live-acquisition.json).

After improving synthetic-source labeling, the report was regenerated from that same digest-verified local acquisition, with no further network calls. The final offline validation finished at **2026-11-19T01:18:01.849075Z** and is recorded in [validation.json](../examples/observed/validation.json). Its runtime command is reproducible with the acquisition sidecar retained in your own local data directory:

```sh
python3 validate_live.py --manifest path/to/acquisition-sidecar.json --data-dir data --output data/replay-review
```

The live run made three bounded public GET requests. Limits: 4 MiB each manifest/archive response, 16 MiB expanded JSON, one complete partition, 50,000 records. A 60-second acquisition deadline is checked between reads, with up to a 15-second active socket-read timeout. No credentials or metered APIs were used.

| Check | Actual result |
|---|---|
| FDA export date | 2026-11-18 |
| Declared / downloaded / accepted rows | 1,584 / 1,584 / 1,584 |
| Quarantined rows | 0 |
| Archive bytes | 447,839 |
| Independent aggregate reconciliation | All 5 SQL tables, 50 aggregate rows matched Python tuple/set/count calculations |
| Current rows / generic labels | 1,116 / 69 |
| Current rows reporting Available | 677 |
| Raw exact duplicate extra rows | 1, preserved |
| Repeated natural-key groups | 17, preserved |
| Unknown availability spelling | 1 (`Unvailable`), preserved and flagged |
| Replay after closing/reopening DB | Analysis and every table count unchanged |
| SQLite integrity | `ok` |
| Foreign-key violations | 0 |

Archive SHA-256:

```text
a3f7bc0255643a0912a31ea5a22056147cb9f2df42e168349889423959a2f20c
```

Snapshot ID:

```text
3999b7e65a288a14c2bc627334263da07e80e323ee2ad26d12fb065b7ccf9b40
```

The oracle in `validate_live.py` independently computes grouping, distinct sets, date buckets, category membership and duplicate tuples from raw dictionaries. It does not call the warehouse projection or reuse the SQL. It fails when any aggregate differs, if a live row is quarantined, or if a reopened replay changes state. Direct `monitor.py ingest` was also executed twice against the same acquisition: first load accepted 1,584 rows; second returned `idempotent=true` with the same totals.

`examples/observed/summary.json`, five CSVs and Markdown are the final aggregate output. They contain no contact records, local raw paths or secrets. The original ZIP and acquisition sidecars are intentionally not published. The original live export cannot be redownloaded by hash from FDA's mutable URL; full offline recreation of that historical source requires the preserved private local cache. The aggregate calculations and synthetic fixture tests remain inspectable and reproducible from the repository.

## Synthetic history scenario

Executed by the test suite and `python3 demo.py --work-dir data/demo`:

| Stage | Raw | Accepted | Quarantined |
|---|---:|---:|---:|
| Fictional before export | 6 | 5 | 1 |
| Fictional after export | 5 | 5 | 0 |

Comparison: **2 added, 2 removed, 3 unchanged projected records**. One changed presentation contributes a removal and addition; a removed row has no inferred clinical meaning. Reports and their JSON explicitly label this coverage SYNTHETIC. These numbers are not real observations.

## Limits of the evidence

- One observed real FDA export supports a cross-sectional analysis. It establishes no shortage trend, duration, patient risk or effect of policy changes.
- Raw byte hashes establish local integrity; FDA has not independently signed these hashes.
- The source may be stale or revised. A typo and duplicate records remain visible rather than being silently corrected.
- Concurrency and crash/error cases are small deterministic local tests, not a throughput benchmark or distributed recovery SLA.
- No paid subscription, Azure resource, deployment, hosted scheduler, clinical decision support, production security assessment or load test was used.
