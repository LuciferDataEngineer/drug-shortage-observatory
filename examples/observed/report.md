# FDA shortage snapshot analysis

**Coverage: Observed FDA bulk snapshot at the recorded export date; a source listing census, not patient-level or clinical evidence.**

FDA bulk export **2026-11-18**, acquired 2026-11-19T01:16:16.374551Z.

Recorded source: `https://download.open.fda.gov/drug/shortages/drug-shortages-0001-of-0001.json.zip`.

Accepted 1,584 of 1,584 source listing rows. Quarantined 0.

Generic labels, company labels and listing rows have separate denominators. FDA advises against using openFDA for medical-care decisions.

Snapshot ID `3999b7e65a288a14c2bc627334263da07e80e323ee2ad26d12fb065b7ccf9b40`. Archive SHA-256 `a3f7bc0255643a0912a31ea5a22056147cb9f2df42e168349889423959a2f20c`.

## Listing status

| status | listing_rows | generic_labels | company_labels |
| --- | --- | --- | --- |
| Current | 1116 | 69 | 89 |
| Resolved | 59 | 6 | 17 |
| To Be Discontinued | 409 | 158 | 55 |


## Status and reported availability

| status | availability | availability_reported | listing_rows | generic_labels |
| --- | --- | --- | --- | --- |
| Current | Available | 1 | 677 | 59 |
| Current | Limited Availability | 1 | 154 | 38 |
| Current | Unavailable | 1 | 284 | 58 |
| Current | Unvailable | 1 | 1 | 1 |
| Resolved | Not reported | 0 | 59 | 6 |
| To Be Discontinued | Not reported | 0 | 409 | 158 |


## Age of the source update at the export date

| status | update_age | listing_rows |
| --- | --- | --- |
| Current | 0-7 days | 185 |
| Current | 31-90 days | 186 |
| Current | 8-30 days | 696 |
| Current | 91+ days | 49 |
| Resolved | 31-90 days | 17 |
| Resolved | 8-30 days | 40 |
| Resolved | 91+ days | 2 |
| To Be Discontinued | 0-7 days | 9 |
| To Be Discontinued | 31-90 days | 47 |
| To Be Discontinued | 8-30 days | 42 |
| To Be Discontinued | 91+ days | 311 |


## Therapeutic categories among Current listings

| category | current_listing_rows | current_generic_labels |
| --- | --- | --- |
| Anesthesia | 359 | 10 |
| Pediatric | 227 | 16 |
| Psychiatry | 220 | 6 |
| Gastroenterology | 134 | 10 |
| Analgesia/Addiction | 126 | 10 |
| Endocrinology/Metabolism | 110 | 9 |
| Other | 104 | 9 |
| Neurology | 88 | 7 |
| Oncology | 84 | 8 |
| Cardiovascular | 81 | 9 |
| Rheumatology | 58 | 4 |
| Anti-Infective | 45 | 7 |
| Pulmonary/Allergy | 35 | 3 |
| Hematology | 31 | 3 |
| Ophthalmology | 21 | 3 |
| Dermatology | 19 | 1 |
| Total Parenteral Nutrition | 15 | 1 |
| Renal | 10 | 1 |
| Medical Imaging | 3 | 1 |


## Source quality and duplicate counts

| metric | value |
| --- | --- |
| raw_rows | 1584 |
| accepted_rows | 1584 |
| quarantined_rows | 0 |
| repeated_natural_key_groups | 17 |
| extra_rows_at_repeated_natural_keys | 17 |
| exact_raw_duplicate_extra_rows | 1 |
| projected_duplicate_extra_rows | 1 |
| generic_labels_with_multiple_statuses | 7 |
| unknown_availability_rows | 1 |
| missing_dosage_form_rows | 10 |
| missing_shortage_reason_rows | 1143 |


Generic labels may have listings in multiple statuses. A listing marked Current can report Available for an individual presentation. Category memberships overlap. Update age measures source metadata freshness and does not estimate shortage duration.

The first collected export provides one observed time point. Future local observations support record multiset comparisons. Disappearance from an export is recorded as an observation change.

[FDA dataset overview](https://open.fda.gov/apis/drug/drugshortages/) · [Reuse terms](https://open.fda.gov/license/)
