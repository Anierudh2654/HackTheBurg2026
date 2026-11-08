# 07 Data permissions and licences (DRAFT: not legal advice; nothing here is a clearance)

Method: the drafter read search-result snippets on 2026-11-07. A human must read each primary terms page. Where I
could not see a primary terms page, the row says "not verified".

| Corpus / dataset | What I saw | Status | What a human must do |
|---|---|---|---|
| SEC EDGAR filings | SEC page: max request rate 10 req/s; declare a user agent with contact details; no botnets or automated crawling outside policy; JSON APIs on data.sec.gov | Access rules seen; reuse of filings is public disclosure data | Read the SEC's current policy page; set the user agent with a real email; keep to explicit URLs |
| Delaware Code (delcode.delaware.gov) | Site disclaimer (no warranty); index says code is current to acts enacted 2026-01-30; older copies mention LexisNexis editorial staff; a 2014 public-records letter shows past disagreement about Delaware reuse policy | **Reuse terms not verified** | Read the site's current terms. Ingest statutory text only. Exclude annotations and headnotes. The government-edicts principle (Georgia v. Public.Resource.Org, 2020) is the usual basis for treating statutory text as free to use, but applying it to Delaware's site is a lawyer question |
| Delaware session laws and bills (legis.delaware.gov) | Chapter and bill pages carry act text and effectiveness sections | Terms not verified | Read the terms; fetch only needed acts |
| Delaware Courts opinions (courts.delaware.gov) | Official site with an "Opinions & Orders" section and a Terms of Use link | **Terms and robots not verified** | Read Terms of Use and robots.txt before building the adapter |
| CourtListener API | FLP announced on 2026-05-07 that API access comes with membership and defaults were reduced; third-party summary gives 5/min, 50/hr, 125/day for new accounts | Rate limits changed; **my earlier 5,000/day figure was out of date** | Read FLP's allowed-usage policy and current limits; consider a membership or contacting FLP for research use |
| CourtListener bulk data | Citation graph exported quarterly; parentheticals available in bulk | Terms not verified. FLP's website content is CC BY-ND, which is about their site content, not necessarily the opinions or bulk files | Read the bulk-data terms; record what you may redistribute |
| Harvard Caselaw Access Project | Harvard LIL (2024): original access limits expired and data can be released without restriction | Statement from the data owner; confirm current terms and distribution URL | Confirm before use; coverage is historical (digitised reporters) |
| MAUD, CUAD, ACORD (Atticus Project) | Atticus says its datasets are free and open under CC BY 4.0; MAUD paper also states CC BY 4 | Seen on the owner's pages | Keep the attribution |
| LegalBench | Dataset card says tasks carry different licences | Per-task | Check each task's licence before use |
| Dahl et al. "Large Legal Fictions" data | Your report says it is on Harvard Dataverse and Hugging Face | Availability and licence **not verified** | Check both pages |
| LePhantomCite, PARCEL, LexAgentHallu | Described in your report only | Availability and licence **not verified** | Check each paper's artifact page |
| Charlotin AI Hallucination Cases database | Crowd-sourced; counts reported as 1,200 to 1,600 depending on date; records detections only | Terms **not verified** | Ask or read terms before copying records; link rather than copy if unsure |
| Law-firm client alerts (Sidley, Gibson Dunn, DLA Piper, Benesch, etc.) | Used by the drafter to cross-check dates | Copyrighted commentary | Do not ingest as ground truth or redistribute; the propositions in this package are paraphrased in my own words |
| Westlaw-style identifiers (e.g. "2026 WL ...") | Seen in a secondary source | Proprietary identifiers | Prefer reporter and docket citations; the package does not use WL cites as canonical |

## Rules the package follows

1. No text from any source is copied into the graph; propositions are short paraphrases.
2. `terms_verified` stays false everywhere (R9).
3. `source_ids` and spans are empty until real documents are registered by hash.
4. Secondary-source URLs appear only as `secondary_hints` for date cross-checks.
