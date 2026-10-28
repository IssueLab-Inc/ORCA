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

PR1 pushed through3c4c02a, its4confirmed fixed threads resolved and description updated. Foundations merged forward into planner at e807414 without rewriting history. Fresh Task2 implementer active on nonblocking events/deadline/request allowance isolation. UI brief prepared and queued. Full-stack/frontend/runtime evidence will be recorded after their fixes, not inferred from original suites.

Fresh four-file Northbank regression after the review fixes: all3legacy reference offsets pass; supported strict042duct and061pipe pass separately and together; strict057U-section tray rejects with the expected unsupported-profile reason. Evidence: ignored follow-up workspace `northbank-final-profile-evidence.json`. No configured-model call or live model change was used for this check.

Task2 implementation8a6f0d2 confirms/fixes both inline findings and the shared allowance callback race across all4paid tool paths. Initial focused66/full274server tests passed. Scoped review confirmed those changes but found one introduced Important boundary: final canonical overflow can cancel after chat history was already published. Original worker is fixing this before PR2 publication; no shared-history deletion workaround is allowed because it could erase a newer turn.

Task2 complete through f396e59 after two scoped fix rounds: final message/done/sentinel enqueue, cancellation check and history publication share the session snapshot lock, so cancellation cannot publish and a completed response's immediate follow-up sees the completed exchange. No scene/model calls occur in that final critical section. Normal sentinel consumption differs from cancellation. Final73focused/281fullserver tests passed (full44.01s); scoped rereview2 approved with no Critical/Important findings. Private-copy fault-injection test renamed accurately; outer accept snapshot retained. Review summaries' shared allowance race was confirmed and fixed in addition to both inline findings.

- Ruling: keep event memory bounded at64 and never wait for a client — omit progress under saturation, preserve canonical results/completion by evicting progress, and explicitly cancel with an error if canonical events alone overflow. Cost if wrong: a slow client can miss intermediate visual steps or need a retry; final successful results and shared conversation state remain consistent. No geometry commits are performed by chat search.

Controller browser RED confirms manual preview loss and failed-open unusable scene on original buildKOMhoYeQ with real synthetic IFC/API geometry. Activity timing/header is lost, while fallback attempt rows remain; this narrows the review's activity-table wording. Private QA Docker8002 stopped after reproduction; evidence in ignored `browser-red.md`. Next: publish PR2, merge forward and dispatch fresh UI implementer.
