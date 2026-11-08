# Track B questions

- Shared hash: local `00_Shared_Contracts_and_Conventions.md` is SHA-256 `788c001924ac4023b24f09f2f90b8faa56366cf805fc78ac9f11aa43f6e3d22f`; the expected value in the integration README could not be cross-checked because that README was not supplied.
- Lawyer review required: confirm the case/statute dates, seed graph predicates, and especially the stockholder prong that accepts either `disinterested_stockholder_approval_obtained` or `mom_approval_obtained`.
- Person A review required for the proposed registry hosts, URL prefixes, and rate limits before production use. All entries remain `terms_verified: false`.
- Person C package dependency: reconcile `contracts_local` and `seed/seed_graph.json` against the published `gba_contracts` v1.0.0 fixtures before integration.
- Track B requirements still depend on external inputs absent from this folder: approved deal/opinion/statute URL plans, SEC user-agent contact email, credentials, source cassettes, and labeled extraction/graph audit gold data.
- GNN training needs a separate dated graph export (audited/high-confidence edges with source IDs and stable citations); never use the illustrative serving seed as training gold.
- GNN evaluation needs lawyer-reviewed gold for `cites`, `addresses`, `applies_to`, treatment, and claim-support relations, including hard in-scope negatives, false-premise cases, and valid controls. Record unreviewed/missing coverage separately from fabricated authorities.
- Opinion-to-elements mapping is a training/evaluation dependency: which opinion propositions or elements count as candidate authorities for A's A4/A5 gap-recovery comparison?
- Research-paper failure sets mentioned in the supplied report/pasted plan (Dahl, PARCEL, LePhantomCite, CG, LexAgentHallu, Charlotin) need availability, jurisdiction fit, redistribution/licence, and ground-truth provenance review before use. Use them as patterns until verified; do not call them Delaware gold labels.
- Evidence claim boundary: we can report measured performance and confidence intervals on a defined, reviewed benchmark and coverage snapshot; no finite benchmark establishes immunity to legal hallucinations.

