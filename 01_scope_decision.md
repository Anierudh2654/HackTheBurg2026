# 01 Scope decision (DRAFT for owner and lawyer sign-off)

Status: AI desk-check against official Delaware General Assembly, Delaware Code, and Delaware Supreme Court
sources completed 2026-11-07. This is not a lawyer review or legal advice. Individual graph edges, scope labels,
and case mappings remain draft and must not be treated as legal ground truth.

## Decisions

| # | Decision | Value | Why |
|---|---|---|---|
| S-1 | Jurisdiction | Delaware (`US-DE`) only | Matches Doc 00 default and the registry. One jurisdiction keeps frames testable. Federal law enters only as a reference (SEC Rule 13e-3 is used by the statute to define public going-private transactions). |
| S-2 | Core topic | Controlling-stockholder and going-private transactions: DGCL section 144 as amended by SB 21 (2025), and the common-law review standards it sits beside | This is where amendment, retroactivity carve-outs and group-specific rules all collide, which is exactly what the guards must get right. |
| S-3 | Authority spine | Weinberger (1983) then MFW (2014) then Match Group (2024) then SB 21 (2025-03-25) then Rutledge v. Clearway (2026-02-27); Corwin (2015) as the non-controller contrast case | A single chain with treatment changes at each step, plus one deliberately out-of-scope authority for scope tests. |
| S-4 | Entity types | Delaware stock corporations, public-company focus | Rule 13e-3 and MFW-style votes assume public holders. |
| S-5 | Actor classes | The six values in Doc 00 (`controller`, `control_group`, `independent_director`, `interested_director`, `disinterested_stockholder`, `minority_stockholder`) | Closed vocabulary; no additions. |
| S-6 | Transaction types | The five values in Doc 00 | Closed vocabulary. |
| S-7 | Time window | Authorities from 1983-02-01; matters evaluated as-of dates from 2014 through 2026-11-07 | Covers pre-MFW, MFW, Match, pre-SB 21, post-SB 21 and post-Rutledge regimes. |
| S-8 | Proposed temporal split for the training graph | train: known_from before 2022-01-01; validation: 2022-01-01 to 2024-06-30; test: 2024-07-01 onward | Match Group (2024-04-04) lands in validation; SB 21 and Rutledge land in test, which stresses the amendment cases. Adjust to data volume; keep a purely forward split. |

## Out of scope for v1

DGCL sections 203, 220, 262 (appraisal), 102(b)(7); Revlon/Unocal enhanced scrutiny; LLC, LP and statutory trust acts;
non-Delaware law (Texas, Nevada); Court of Chancery decisions below the Supreme Court except where the owner adds them.

## What changed since the illustrative fixtures (Doc 00 section 13)

1. **Rutledge v. Clearway Energy Group LLC, No. 248, 2025 (Del. Feb. 27, 2026)**: the Delaware Supreme Court answered
   the certified constitutional questions against the challenge: it held the challenged §144 safe-harbor framework did
   not violate the Delaware Constitution and that the retroactive-application provision did not violate the state
   constitution. This does not decide that any particular transaction satisfies a safe harbor. A claim that Rutledge
   struck down SB 21 is a false-premise pattern (benchmark F19).
2. **2026 legislation**: HB 353 was signed 2026-06-10 and takes effect 2026-08-01. The official bill summary says it
   amends §§242, 275, and 312; it does not amend §144. Record it in the wider Title 8 version history, but it is not a
   direct amendment to this narrow §144 scope.
3. **SB 21 details used**: signed and effective 2025-03-25. Section 3 applies the changes to acts and transactions
   before, on, or after enactment, except proceedings commenced in a competent court and completed or pending on or
   before 2025-02-17; the separate §220-demand exception concerns inspection demands made by that date. Under §144(b),
   a non-going-private controller transaction may qualify through the committee route or the disinterested-stockholder
   vote route. Under §144(c), a going-private controller transaction requires both routes. These are eligibility
   conditions, not a conclusion that a specific transaction qualifies. The public-company going-private definition
   references Exchange Act Rule 13e-3. The fixture's `litigation_commenced_on <= 2025-02-17` represents the date part
   of the §144 proceedings exception; F10 must test only that temporal boundary, not assert safe-harbor qualification.

## Decisions I need from you (owner)

1. Confirm S-1 to S-8, or change them.
2. Name the lawyer reviewer (the package marks every label `draft_unreviewed` until that person fills `reviewer` and `reviewed_on`).
3. Contact email for the user agent (needed for any live fetching; EDGAR requires it).
4. Hardware budget for the structural training graph (sets how many Delaware opinions to ingest).
5. Whether to add the pre-amendment section 144 version (needs the 2024 Delaware Code text and its effective date; not drafted because I could not verify the dates).
