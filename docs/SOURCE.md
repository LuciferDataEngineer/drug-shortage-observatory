# Source, permissions, and observation contract

## Source and current relevance

Data provided by the U.S. Food and Drug Administration, via
[openFDA Drug Shortages](https://open.fda.gov/apis/drug/drugshortages/).
FDA describes manufacturer reports as the principal input to this dataset and
documents daily updates. The feed includes supply situations marked current,
resolved, and planned discontinuation. A presentation can be available even
while its parent supply situation remains current. These data are for supply
monitoring and portfolio analysis, not medical decisions.

This is a current operations problem: a
[10 November 2026 DEA final order](https://www.govinfo.gov/content/pkg/FR-2026-11-10/pdf/2026-22842.pdf)
adjusted aggregate production quotas for several controlled substances using
FDA shortage information and other supply evidence. That notice motivates
auditable shortage observations; this repository does not estimate the effects
of those quota changes or advise on medication availability.

## Access and reuse

Source documentation and terms were accessed **19 November 2026**. The first
complete local download was acquired at **2026-11-19T01:11:33.374955Z** and reported
an export date of **2026-11-18**.

- [FDA terms](https://open.fda.gov/terms/) provide public-domain/CC0 1.0 reuse
  unless a dataset carries a specific exception; FDA requests attribution. No
  exception was identified in the drug shortage documentation inspected for
  this release. The GMDN restriction concerns device terminology and is not
  used here. Recheck the terms before adapting this project to another dataset.
- [License page](https://open.fda.gov/license/) and
  [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) describe the reuse
  basis. Original project code is MIT-licensed separately.
- [API usage](https://open.fda.gov/apis/drug/drugshortages/how-to-use-the-endpoint/)
  supports credential-free requests. This implementation uses public bulk
  downloads and does not register for a key, create an account, or call a paid
  service. It makes three bounded GET requests per live acquisition.
- The FDA offers the feed without a service-level or accuracy guarantee. FDA
  supplies no signed archive checksum; our digest proves local byte integrity,
  not an independent attestation by FDA.

## Acquisition contract

1. Read the [download manifest](https://api.fda.gov/download.json), specifically
   `results.drug.shortages`.
2. Require one complete partition with matching `total_records` and partition
   `records`. The release observed
   [drug-shortages-0001-of-0001.json.zip](https://download.open.fda.gov/drug/shortages/drug-shortages-0001-of-0001.json.zip).
   Its URL is mutable, so it is never used as an immutable snapshot identifier.
3. Download the ZIP on **every live acquisition**, even if export date, count,
   and declared size match a prior manifest. Those fields cannot identify
   same-day upstream corrections.
4. Read the JSON in memory, without extracting filesystem paths. Check member
   count, member path, expansion size, encrypted-member flag, compression ratio,
   result count, pagination metadata, and `meta.last_updated` against the
   manifest export date.
5. Read the manifest again and require the selected export metadata to match.
   Drift rejects this acquisition without accepting a partial snapshot. A
   later run retries the whole export. A change to multiple partitions requires
   an explicit adapter review; it is never silently truncated to partition one.
6. Store raw bytes in `data/raw/<sha256>.zip`, rechecking any existing file before
   reuse. Write a new acquisition sidecar under `data/manifests/`, including
   export date, archive digest, access timestamp, and a unique observation
   suffix. Identical bytes share raw storage; each acquisition retains its own
   metadata. Same-manifest corrections retain separate raw versions.

The limits are 4 MiB per manifest, 4 MiB compressed archive, 16 MiB expanded JSON,
50,000 records, and a compression ratio of at most 200. Each request has a
15-second socket timeout; a 60-second acquisition deadline is checked between
single buffered reads. A socket read already in progress can run to its timeout.
There are no hidden retries, pagination loops, or unbounded downloads.

`read_snapshot(path)` is the explicit offline replay path. It reopens the
acquisition sidecar and verifies its metadata, safe raw path, byte length,
SHA-256, archive structure, count, and export date before returning rows. It
does not request the current internet feed. Sidecars contain absolute local raw
paths and are intended for this ignored local data directory, not redistribution.
To relocate a cache, preserve the whole directory and adjust the sidecar raw
paths explicitly, then verify with `read_snapshot`.

Source checks cannot detect an upstream change that occurs and reverts between
the two manifest requests, or a correction whose metadata remains identical
during acquisition. The downloaded bytes and digest still record exactly what
was observed. There is no assertion of an atomic FDA-side transaction.

## Grain and measured schema

The bulk export is a **snapshot of source records**, not a transaction/event
history and not a count of unique medicines. Preserve source ordinal within
each snapshot. A National Drug Code identifies a package but is not unique in
this feed. FDA's [field reference](https://open.fda.gov/fields/drugshortages_reference.pdf)
describes the fields; empirical validation of the actual feed remains necessary.

| Field | Observed type | Present / 1,584 | Interpretation |
|---|---|---:|---|
| `package_ndc` | string | 1,584 | Package identifier; preserve hyphens and leading zeros |
| `generic_name` | string | 1,584 | Source display label; not a validated ingredient identifier |
| `company_name` | string | 1,584 | Reporting company label |
| `presentation` | string | 1,584 | Source presentation description |
| `status` | string | 1,584 | Current, Resolved, or To Be Discontinued |
| `availability` | string | 1,116 | Presentation availability; missing is distinct from unavailable |
| `update_type` | string | 1,584 | Reverified, New, or Revised |
| `initial_posting_date` | string | 1,584 | `MM/DD/YYYY`, date-only |
| `update_date` | string | 1,584 | `MM/DD/YYYY`, date-only; does not establish event time |
| `discontinued_date` | string | 409 | Optional `MM/DD/YYYY` |
| `change_date` | string | 63 | Optional `MM/DD/YYYY` |
| `therapeutic_category` | array of strings | 1,584 | Multiple categories per source row; totals can overlap |
| `dosage_form` | string | 1,574 | Optional source label |
| `shortage_reason` | string | 441 | Optional source explanation; not a complete cause census |
| `openfda` | object | 1,428 | Optional harmonization; not required for core metrics |
| `contact_info` | string | 1,584 | Excluded from public outputs and warehouse |
| `related_info` | string | 1,069 | Free text excluded from public outputs and warehouse |
| `resolved_note` | string | 58 | Free text excluded from public outputs and warehouse |
| `related_info_link` | string | 33 | Excluded from public outputs and warehouse |

`product_id` was absent from every observed row despite its presence in the
reference material. The adapter does not invent one. The warehouse owns its
own explicit allowlist and quarantines invalid analytical records; the source
layer preserves byte provenance independently of those decisions.

## Observed source facts

These describe the complete **2026-11-18 export**, observed on 19 November, not
live clinical supply or prevalence. Later runs may differ.

| Observation | Value | Unit / denominator |
|---|---:|---|
| Source records | 1,584 | rows in complete export |
| Current | 1,116 | source rows |
| To Be Discontinued | 409 | source rows |
| Resolved | 59 | source rows |
| Available | 677 | source rows with this exact availability label |
| Unavailable | 284 | source rows with this exact availability label |
| Limited Availability | 154 | source rows with this exact availability label |
| `Unvailable` | 1 | source typo, retained in raw provenance |
| Missing availability | 468 | source rows; not interpreted as unavailable |
| Current generic-name labels | 69 | distinct raw labels among Current rows |
| Repeated package NDC groups | 27 | groups with two source rows each |
| Repeated NDC/company/presentation/status groups | 6 | groups with two source rows each |
| Exact duplicate extra rows | 1 | duplicate beyond first occurrence |
| Download size | 447,839 | ZIP bytes |
| Expanded JSON size | 3,091,010 | JSON bytes |

Archive SHA-256:
`a3f7bc0255643a0912a31ea5a22056147cb9f2df42e168349889423959a2f20c`.

All 1,116 Current rows had an availability field in this particular export.
The 677 Available rows therefore do not contradict the Current classification:
the fields describe different concepts. A source typo may be normalized by an
explicit documented warehouse mapping, with its original value retained for
quality reporting. Snapshot comparison measures observed source-state change;
it does not infer continuous shortage duration or a new clinical event.

## Privacy, fixtures, and recovery

The raw ZIP includes manufacturer contact fields. It remains only in the
ignored `/data/` directory. Do not add raw archives or sidecars to Git, attach
them to releases, or expose them through a frontend. Public evidence consists
of reviewed safe projections, aggregate metrics, digests, counts, and synthetic
fixtures. Fixture builders in `tests/test_source.py` use original synthetic
labels and a fixed ZIP timestamp; they do not copy source contact records.

On timeout, manifest drift, or source-schema change, retry a later complete
acquisition; never treat a partial export as a complete observation. If a local
archive hash or length fails, retain that cache for investigation, move it out
of the active data directory, and reacquire. Historical raw bytes cannot be
recovered from today's mutable FDA URL unless an intact local copy exists.

Run the credential-free deterministic source checks with:

```sh
python3 -m unittest tests.test_source -v
```

Sixteen source integrity tests passed on 19 November 2026. A bounded live
acquisition and verified offline replay both returned all 1,584 declared rows.
The source tests additionally cover unchanged-manifest byte corrections,
repeat acquisition provenance, tampered and truncated caches, count mismatch,
manifest drift, unsafe ZIP paths, expansion limits, untrusted archive hosts,
and response byte budgets. See the repository validation document for the
combined pipeline checks and final release evidence.
