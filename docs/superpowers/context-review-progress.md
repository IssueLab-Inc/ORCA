# Context-fix PR review follow-up — 2026-10-28

Status: active. Original feature implementation is complete; user requested fetching, reviewing and addressing confirmed feedback on PRs1/2/3. Origin fetched; no external branch changes. Existing author/committer identity and no-trailer rules remain binding. No PR merge, deployment or external reply message is authorized.

Plan: docs/superpowers/plans/2026-10-28-context-review-fixes.md. Scratch ledger/review source/report packages: .superpowers/sdd/2026-10-28-context-review-fixes/. The prior policy-blocked scratch cleanup is not retried.

| PR | Inline review IDs | Follow-up |
|---|---|---|
|1 foundations|4399890403,4399891399,4399892172,4399892683|Reproduce small-bend clearance, single port handling, axis noise, hollow SAT; fix confirmed cases with real IFC tests|
|2 planner/API/chat|4399898191,4399898971|Nonblocking bounded stream publication; retain fully checked late trial. Also confirm/fix shared per-request allowance callback from review summary|
|3 product|4399903598,4399904451,4399905166,4399905855,4399906368,4399906835|Manual effect preview/activity, stale pending work after accept, document evidence, actual stream abort, objective attribution, failed scene load recovery|

Preliminary review decisions: never take the suggested blanket same-chain exclusion, which contradicts explicit intra-run collision checking. A narrow generated-bend clearance allowance must retain hard-penetration checks. Meaningful along-run delta rejection already exists; test tolerance behavior rather than claim it was absent. The outer acceptance snapshot protects subsequent acknowledgement/report-pair failures and is not removed as a speculative optimization. Review summaries explicitly retract active Discard as an abort path; completed Discard is distinct.

Fresh sequential workers implement each owning slice with independent scoped reviews, then verified changes merge forward without history rewriting. Only confirmed/fixed threads resolve after tests and push. Root owns driven product smoke and final verification. No review replies are posted without a direct request.

Task1 complete: b3faefa fixes all4primary findings with35real IFC regressions;224 full foundation tests passed36.86s and111 related native tests passed39.34s. Independent scoped review approved, no Critical/Important findings. Known meaningful along-run rejection remains unchanged; negligible residue now matches the actual reported edit. Guide main-branch conflict reconciled.

- Ruling: waive required clearance only between the two generated pieces immediately flanking one physically validated bend, while still checking their hard intersections — these pieces form one joint footprint rather than two independently spaced services. Cost if wrong: a near-contact within that single bend footprint may be allowed; unrelated same-run and external clearance, and all penetration checks, remain active and regression-tested. Whole-chain exclusions are forbidden.

Next: push/resolve PR1's4confirmed fixed threads, merge foundations forward, fresh Task2 worker for nonblocking events/deadline/request allowance isolation. UI brief prepared and queued. Full-stack/frontend/runtime evidence will be recorded after their fixes, not inferred from original suites.
