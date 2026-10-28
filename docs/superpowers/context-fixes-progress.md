# Context fixes program — 2026-10-28

Status: complete. All three slices implemented, task-reviewed, whole-branch-reviewed and pushed as ready stacked PRs. No PR merge or deployment performed.

Spec: docs/superpowers/specs/2026-10-28-context-fixes.md
Plan: docs/superpowers/plans/2026-10-28-context-fixes.md

## Rulings and preflight

- Ruling: reuse the clean current checkout on a new codex branch, with fresh isolated worker contexts — the user authorized branches/PRs and developer guidance prefers a suitable existing checkout; avoid a redundant worktree and duplicate dependencies.
- Ruling: keep evaluation helpers separate from legacy verification behavior — additive APIs must not silently change current proposal semantics.
- Ruling: acceptance publishes an independently checked clone atomically under Workspace.lock — this satisfies all-or-nothing multi-file changes without exposing intermediate live edits.
- Ruling: global user requirement for branch + PR on L work overrides the older CLAUDE.md instruction to commit directly to main.

| Tasks | Shared interface | Check |
|---|---|---|
| 1 | edits/scene/evaluator/tests | SI, old signatures and snapshots explicitly specified; offset vector converted by evaluator |
| 2 | planner/API/chat | One canonical stored proposal; no client raw edits on apply; original API contracts preserved |
| 3 | web | Dedicated context state, resolved_pairs only, context meshes separate from pair highlights |
| 1 -> 2 | evaluate_candidate / commit_candidate / revision / snapshot | Signatures, checks and edit payloads pinned in Task 1 |
| 1 -> 3 | Mesh and edited-piece mapping | Existing world SI Mesh shape and source-to-pieces map used |
| 2 -> 3 | context stream/apply/ChatEvent | Endpoint and event names, acknowledgements and response shapes pinned verbatim |

Next: fresh Task 1 implementer, TDD foundations, independent review, PR 1; then Tasks 2 and 3 sequentially.

## Verification environment

Baseline Windows: 77 passed, 2 PDF failures from missing native libgobject. Web build passes with existing bundle-size warning. Built local ignored Docker image `sightline-context-check:20261028` from frozen server lock and Python 3.13 with native Pango/Harfbuzz. All 4 document tests pass there (2.06 s), confirming the baseline PDF issue is environmental. Full final server checks will run in this container using a read-only bind mount of server source and no pytest cache writes.

## Task 1 checkpoint

Implementation 87d2786 (Dodzi author/committer); full Linux 109 passed. Independent review identified one Important missing-placement integrity bypass; original worker is fixing it before task completion. Controller verified all three Northbank reference offsets individually and together on the four-file federation: three-group result passes with no new hits or integrity errors (9.92 s), retaining five designer-review conditions.

Task 1 complete: fix 6fdccf1 addresses missing-placement bypass with real flow/system/profile mismatch regressions; independent scoped re-review approved. Controller full Linux check after fix: 113 passed in 10.42 s. No critical/important findings remain. Runtime UI smoke remains Task 3.

- Ruling: use a fresh private candidate copy rather than reusing IFC undo history between candidates — measured clone cost is small on Northbank and it makes failed multi-file trials completely isolated; cost if wrong is extra CPU/memory and fewer trials within the time budget, not partially changed live files.

Next: create foundations PR and branch codex/context-fix-planner from its head; dispatch fresh Task 2 implementer.

Additional targeted review found incorrect IFC SOURCE/SINK port-frame convention; correction queued after Task 2 commit, before planner publication. Foundations PR is draft meanwhile.

- Ruling: honor explicit `Pset_SightlineConstraints.KeepFixed` model constraints, including run members, and expose them to planner inspection — the principal fixture must need a surrounding edit, whereas the original open-space fixture has a larger single-duct escape. Any supported unlocked element stays eligible. Cost if wrong is a custom IFC convention needing documentation; no class-based structural ban or new UI lock feature is introduced.

- Ruling: preserve authored external connections with missing flow metadata as explicit frame/flow review conditions; do not let reconnect invent flow on an untouched peer. Fully known SOURCE/SINK and new known-flow joints enforce IFC signed frames, and independent position/system/profile failures still reject. Northbank has unconventional authored external axes with unknown-flow partners; cost if wrong is requiring modeller review of these external conventions rather than claiming verified IFC orientation.

Correction to the preceding diagnostic: Northbank peer flows are known before editing; offset copying/reconnection was clearing one near peer's flow. The prior assumption of originally unknown partners is superseded.

- Ruling: preserve both original peer metadata and narrowly retain an unchanged authored external frame-convention violation as `legacy_port_frames` review evidence plus an integrity warning, requiring acknowledgement. Exact baseline external poses, physical endpoints and profile must be preserved; new/generated or changed/worsened bad frames reject, as do independent position/flow/system/profile violations. This extends the spec's baseline-conflict treatment to legacy external port conventions instead of rejecting all otherwise valid Northbank offsets. Cost if wrong: exported external legacy conventions still need modeller correction; the product must not claim full IFC conformance.

## Foundations final checkpoint

Port/constraint/fixture correction 8adadf1 was cherry-picked as f8743a9 onto foundations. Scoped review found an exception leak for a known physical endpoint gap; fix 3568340 now independently checks both connection owners and prevents that exception. Final scoped review approved with no Critical/Important findings; full foundations Linux suite 173 passed, focused 94 passed. All Northbank reference offsets still pass with disclosed legacy-orientation warnings. The constrained metre/mm fixture proves the duct route needs a surrounding tray relocation under explicit locks/anchors.

Planner commit e24fab4 is preserved on codex/context-fix-planner; next rebase it onto corrected foundations, then fix all three Task 2 findings (inspection keyword, initial pagination, chat cancellation) and integrate constraint inspection/stronger fixture. No UI completion claim yet.

## Planner final checkpoint

Planner rebased ec6b442 onto foundations485361f. Fix1a91469 addresses inspection dispatch, stable long-seed pagination, request-owned disconnect cancellation/backpressure/storage boundaries, explicit constraint capabilities and real constrained fixture acceptance/export. Review found a late cancelled chat turn could erase a newer completed history; fixbeb05d2 uses isolated turn histories and generation/lock-guarded publication. Scoped re-review2 approved with no actionable findings. Full Linux205 passed in29.59s; focused46 passed.

Live configured-model QA on a disposable constrained fixture: first bounded run found no passing result in6 calls/68.7s (correctly inconclusive); second run found the required duct offset+tray relocation in6 calls/2 trials/49.612s. Explicitly acknowledged all6 review conditions; whole-plan acceptance200 with geometry/integrity passed, one confirmed resolved pair, exported30272-byte IFC reloaded with6 duct fittings and tray y0.30..0.40m; replay rejected409. No live user model or existing server was modified. Private QA traces/evidence are under ignored .superpowers; no fake route or API key is shipped.

Next: planner PR2 stacked on PR1, then fresh Task3 UI worker and driven browser acceptance/export with the same constrained fixture.

## Product checkpoint

Foundations PR1: https://github.com/IssueLab-Inc/clashwise-sightline/pull/1. Planner PR2: https://github.com/IssueLab-Inc/clashwise-sightline/pull/2. Both attached, stacked and draft pending the completed program review. Product branch `codex/context-fix-product` implements context state, complete world-mesh preview, all-condition acknowledgement, canonical acceptance, affected IFC reload, confirmed-only report resolution, stale stored-objective regeneration and chat review without forcing a tab switch.

Driven browser proof on the disposable constrained fixture: selected clash -> wider action -> two dependent edits; Before/After/Both show the tray relocation and generated duct detour together. Acceptance stays disabled with zero or one of six acknowledgements; all six enable it. A kept legacy edit advanced the live revision, so acceptance rejected the stale proposal without applying it; regeneration used the original objective and reset acknowledgements. Whole acceptance then reloaded geometry, marked exactly the confirmed report clash fixed, and browser IFC export reloaded with six duct fittings and tray y0.30..0.40m. Final initial bundle `index-B3jnM0-z.js` also completed the Chat -> wider search -> review flow, preserving the transcript when switching tabs. No browser console errors were observed. The fixture server is private QA scaffolding, not a shipped route.

Task review caught obsolete pilot cleanup and late chat callbacks. Fix c629806 adds actual playback cancellation/generation isolation and abortable chat ownership; eight Node regressions and build passed. Scoped review confirmed those fixes and found that retired chat progress could stay active after direct replacement. Original worker is addressing that state transition in fix round 2, with actual App-handler regression coverage. No unreviewed product fixes have been made by the controller. Full server suite remains 205 passed; final frontend and whole-branch gates remain outstanding.

Task3 fix37db0e2 retires only pending progress owned by the cancelled chat tracker, preserving completed proposals and newer work. Scoped review2 approved, no Critical/Important findings. Final fresh controller checks:205 server tests passed in30.00s;12 actual-source frontend regressions passed; production build `index-KOMhoYeQ.js` passed with the existing bundle-size warning. Latest-bundle browser proof also replaced an in-flight chat search with direct work, confirmed wider controls were enabled again, and completed a new wider proposal. The private scripted model lacks the legacy single-proposal method, so that replacement's single action reported its expected QA-stub error rather than exercising a real single proposal; no such stub ships.

Latest-bundle normal flow was reloaded cleanly and completed discovery, full Both preview, six-condition guard, whole acceptance/reload and browser IFC export. Reopened export:30272bytes,6 duct fittings,tray y0.30..0.40m; no browser console errors. Evidence remains in ignored QA files. Native Windows's two original PDF dependency failures were verified separately through the Linux/Pango environment rather than suppressed in product code. Whole-branch review is independent and still pending at this checkpoint.

## Whole-branch review correction

Final reviewer found exactly one Important defect: the inherited profile-size support accepts hollow/open/decorated source profiles, while the bend generator fills a plain rectangle/circle. A real hollow400x300x10mm source cap0.0136m² became solid0.12m² in accepted/exported bends without a profile warning. The final fix wave must reject context offsets outside exact plain rectangle/circle profiles, expose truthful inspection capabilities, preserve whole-run moves and existing legacy edit routes, and verify real IFC rollback plus positive controls. No other Critical/Important finding remained.

Fresh Northbank inventory confirms the tray `LV-TRAY-L02-1` is `IfcUShapeProfileDef`; this new strict context rejection intentionally supersedes prior claims that all three reference offsets preserve profiles. The duct is plain rectangle and cold-water main plain circle. Controller will recheck supported references and explicit tray rejection after the correction; no Northbank-specific bypass is allowed. The stricter unsupported-shape behavior and initial profile limit are now explicit in the spec. Original three-reference legacy API behavior remains unchanged.

Final fix wave: foundationf561898 and plannere672cb5 share `check_offset_profile`, gating exact plain rectangle/circle before mutation and during inspection. Real metre/mm regressions reject hollow rectangle/circle, rounded rectangle and U-section offsets without IFC/revision changes; controls preserve plain offsets and whole-run moves through export/reload. Full server227 passed in36.06s. Scoped final rereview approved, no remaining Critical/Important findings. Web12 regressions and build `index-KOMhoYeQ.js` remain unchanged and passed.

Fresh four-file Northbank checks after the fix: legacy offsets042/057/061 all retain prior behavior; strict context042 and061 pass separately and together with disclosed authored-frame warnings;057 rejects explicitly with `unsupported offset profile: IfcUShapeProfileDef`. This is the final regression result, superseding earlier all-three strict-pass notes.

Restarted final backend, latest web bundle: Chat -> wider discovery -> complete tray+duct Both preview -> six-condition guard -> whole acceptance/reload -> exactly one confirmed report clash fixed -> browser IFC export/reopen all passed. Export30272bytes contains6 duct fittings and trayy0.30..0.40m; browser console errors empty. Original explicit-action, stale409 and stored-objective regeneration proofs remain valid. Actual configured model found this plain-profile arrangement in49.612s; bounded unsuccessful search remains inconclusive. No fake model route ships.

PR3: https://github.com/IssueLab-Inc/clashwise-sightline/pull/3, attached and stacked on PR2. All PRs remain unmerged and undeployed. Native Windows still needs its original native PDF dependencies; all PDF tests passed in frozen-lock Linux/Pango. QA artifacts will be preserved outside the completed SDD scratch directory before cleanup.

## Delivery checkpoint

| Slice | PR | Branch | Final source checkpoint |
|---|---|---|---|
| Foundations | https://github.com/IssueLab-Inc/clashwise-sightline/pull/1 | codex/context-fix-foundations | 26a05a8 |
| Planner/API/chat | https://github.com/IssueLab-Inc/clashwise-sightline/pull/2 | codex/context-fix-planner | f8d7bdc |
| Product integration | https://github.com/IssueLab-Inc/clashwise-sightline/pull/3 | codex/context-fix-product | 9dd32ca, reviewed source identical to e672cb5 plus documentation |

The final foundation-only backport passed189 server tests in30.92s. The complete stack passed227; web12 and build passed. Final task/whole-branch reviews have no open Critical/Important findings. Geometry/profile fixes were backported to their owning slices, then merged forward with no source-tree changes and no force pushes. All author/committer identities and absence of coauthor/session trailers were verified. All PRs are attached to the chat and ready for review in1→2→3 order.

Own QA servers8001/8002 were stopped; unrelated server processes were not changed. Evidence, private reproducible fixture scripts, exported IFCs and review reports are archived under ignored `.superpowers/qa/2026-10-28-context-fixes/`; completed SDD scratch is removed. The working checkout remains on `codex/context-fix-product` for PR feedback. Next action belongs to the user: review the stacked PRs; merging/deployment needs separate authorization.
