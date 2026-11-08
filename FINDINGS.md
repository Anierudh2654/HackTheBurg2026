# Findings (research read 2026-11-07; demo only, AI-checked, not legal review)

## A. CourtListener bulk data
- Terms page: https://wiki.free.law/c/courtlistener/help/api/bulk-data/bulk-legal-data
- One-line terms: FLP says the bulk files are "free of known copyright restrictions" (Public Domain Mark). Snapshots regenerated quarterly (end of Mar/Jun/Sep/Dec); files are PostgreSQL COPY CSVs with a header row; tables are exported separately so some rows may reference rows missing from another file.
- Redistribution: no restriction stated on that page. (FLP's separate website content licence, CC BY-ND, is about their site text, not the bulk files.) The API has separate, tighter rate limits; this plan does not use the API.
- Citation map header (from FLP docs): `id, depth, cited_opinion_id, citing_opinion_id`.
- File names, sizes, hashes, other headers and row counts: NOT obtained. My sandbox has no network and the bulk-info page blocks automated readers. `fetch_and_hash.py bulk --list` prints the real names/sizes; `bulk` records hashes, headers and row counts into the manifest.
- Size warning: the opinions file (needed to map opinion id to cluster id) is the largest file. `--skip-opinions` is the cheap demo shortcut (assumes opinion id = cluster id).
- Filter note: Delaware court is on the dockets table, not clusters. The script chains courts > dockets > clusters > citations > citation map.

## B. Primary texts
| Item | Finding |
|---|---|
| Match Group, 315 A.3d 446 (Del. 2024), No. 368, 2022 | Official PDF: https://courts.delaware.gov/Opinions/Download.aspx?id=362250 (decided Apr. 4, 2024) |
| Weinberger, 457 A.2d 701 (Del. 1983) | No official courts.delaware.gov copy found. Non-official options: CourtListener https://www.courtlistener.com/opinion/1954871/weinberger-v-uop-inc/ (ID from Wikipedia, unverified), Justia, Harvard CAP. **Manual**: save one, then `python fetch_and_hash.py hash <file>` and answer official = n. |
| SB 21 as enacted | Senate Substitute 1 for SB 21, signed 3/25/25, 85 Del. Laws c. 6, effective 3/25/25. Bill page https://legis.delaware.gov/BillDetail/141930 ; session-law PDF fileAttachmentId=647918 (linked from that page). Script saves it. |
| SB 21 section 3 | Per the official bill synopsis (paraphrase, not the enacted text): Sections 1-2 take effect on enactment, apply to acts and transactions before, on or after enactment, but do not apply to or affect an action or proceeding commenced that is completed or pending, or a books-and-records demand made, on or before **Feb. 17, 2025**. Verbatim section text comes from the saved PDF. The scope doc's "on or before" boundary matches the synopsis. |
| 144(b), (c), (e) text | In the saved session-law PDF/HTML. I did not copy or reconstruct it. |
| 2026 HB 353 | Signed 6/10/26; 85 Del. Laws c. 279. It amends §§ 242, 275 and 312 of Title 8 (dissolution, class-vote opt-out, nonstock revival). **It does not amend § 144** in anything I read. Effective Aug. 1, 2026 for Sections 1 and 3; Section 2A/2 are conditional on another bill (HB 400), which I did not read. Impact on this project: none for § 144 as-of dates. |

## Manual to-do list
1. Set `GBA_CONTACT_EMAIL`, run `python fetch_and_hash.py texts`.
2. Weinberger: download by hand, then `python fetch_and_hash.py hash <file>`.
3. `python fetch_and_hash.py bulk --list`, then `bulk` (or `bulk --skip-opinions`). Leave it running.
4. Open each official PDF and fill `pinpoint` / `source_passage` in 04 and 05 (fields exist, currently empty).
5. Skim the site Terms pages for courts.delaware.gov and legis.delaware.gov; the script respects robots.txt but I could not read their terms.

## Package changes
- 04 labels (69), 05 mapping (29), 06 benchmark (32): reviewer = "Claude (AI, demo-only single reviewer)", status `ai_checked_demo`. Added `source_id`, `pinpoint`, `evidence_date`, `evidence_status`.
- `evidence_status = passage_pending_fetch` where a primary source is located (Match, SB 21); `no_primary_source_located` otherwise (e.g. Weinberger, MFW, Corwin, Rutledge). 
- "ai_checked_demo" means labels were reviewed for consistency, not that passages were verified.
- Splits unchanged (train 10, val 10, test 12); validator passes.
