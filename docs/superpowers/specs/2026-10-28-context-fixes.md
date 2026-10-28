# Context-aware fix proposals — agreed specification

Approved by Dodzi on 2026-10-28. Build Explore wider fix for a selected clash, also available through chat. The agent searches arrangements of at most three independently edited elements/runs, including surrounding elements outside the original pair. Any supported element is eligible; structural edits are not forbidden, but service-only arrangements rank first and structural implications require designer review.

## Search

Use a dedicated tool-driven planner. Inspect the objective pair and a 2.5 m local neighbourhood, returning real GlobalIds, bounds, run shape, systems, ports/connections, supported operations and measured openings. The model can inspect discovered elements, inspect blockers found by geometry, and evaluate complete arrangements. Undiscovered IDs cannot be edited. Every edit has a reason explaining how it enables the objective or another edit.

Evaluate complete candidates: edits need not pass separately. Expand through actual geometry blockers. Bound each job to three edit groups, six model calls, twelve geometry trials, approximately 120 seconds, and three returned alternatives. Connected run translations are one group, independently edited fittings/neighbours are separate groups, generated offset pieces belong to their source edit. Reject duplicate/overlapping edits. Rank service-only before structural, then fewer review conditions, groups, fittings, displacement, and finally larger clearance. On exhaustion return passing candidates or remaining blockers; never claim no solution exists.

## Edits and whole-proposal checks

Use an isolated IFC snapshot pinned to a scene revision; trial changes never affect the live scene. Reuse reversible transactions in the private scene. Apply all operations before checking the final arrangement; operation order is not a construction sequence.

Check objective resolution, all changed/new geometry against unchanged and changed geometry (including pieces inside one run), baseline conflicts versus new/worsened conflicts, connection relationships and physical endpoint alignment, new port orientations, system membership and supported profile compatibility. Legitimate joint contact is pair-specific; never blanket-ignore all connected neighbours. Preserve/report unchanged baseline conflicts, but reject known new/worsened collisions and broken constraints. Unsupported shapes and operations fail with reasons. Missing evidence becomes explicit review conditions, not a verification pass. Structural adequacy, hydraulic performance, missing connectivity metadata and maintenance/access implications are designer-review conditions where relevant.

Extend local offsets to vertical OR lateral detours on supported horizontal straight service segments, preserving external endpoints, profile/system metadata and fitting chains. Compound 3D detours and sloped runs are out of scope. Preserve slender-member trim restrictions and old API behavior. Do not introduce destructive structural edits beyond existing supported primitives.

Context offsets initially support exact plain `IfcRectangleProfileDef` and `IfcCircleProfileDef` profiles. Hollow, rounded, open-section and other decorated profiles are unsupported because the current bend generator does not preserve their material topology. Reject these offsets with a specific reason and omit the offset capability during inspection; whole-run moves remain eligible. This includes Northbank's U-section tray reference, whose prior context-offset pass is superseded by the stricter profile check. Existing legacy edit routes retain their behavior.

## Product and acceptance

Dedicated context-proposal stream and acceptance endpoints; existing proposal/batch APIs remain compatible. Return server IDs, revision, objective, edits with reasons/dependencies, before/after geometry, checks and review conditions. Stream inspection/discovery/check progress using existing uncompressed NDJSON headers. Reuse before/after/both previews; show every edit and its reason. Keep the original clash objective separate from enabling edits. Chat can request a wider fix but cannot accept it.

Accept only a whole server-stored proposal, with acknowledgement of all review conditions. Reject stale scene revisions, recheck under the workspace lock, and publish all changes atomically or leave every model untouched. Advance revisions for all existing kept edit routes too. Reload changed files, associate generated pieces with their source, and mark only report clashes confirmed resolved by geometry. Proposal state is in memory like scenes; restart requires regeneration. Charge three existing proposal allowance units before starting; respect owner no-caps and reasoning settings. Algorithm limits still apply to owners.

## Acceptance and delivery

The principal fixture is unsolvable by editing the original pair alone but solved by relocating surrounding geometry; prove both one-blocker and three-group chains. Cover lateral endpoints/fittings/ports, candidates failing alone/passing together, cross-file conflicts, internal self-collisions, broken connections, structural review conditions, known violations, unsupported shapes, fabricated IDs, overlaps, budgets, rollback, stale acceptance, failed multi-file application, metre/mm files and export reloads. Run full server tests, production web build, and a driven runtime smoke through discovery, review, accept and IFC export; Northbank is regression data, synthetic fixtures prove the new capability.

Use fresh implementer contexts and independent task reviews. Three stacked branch/PR slices: foundations; bounded planner/API/chat; product integration. No merges without authorization. All commits author and committer Dodzi Agbenorku, GitHub noreply, without attribution trailers.

## Execution rulings — 2026-10-28

Controller decisions and costs are recorded in context-fixes-progress.md. Explicit model property `Pset_SightlineConstraints.KeepFixed` is a known constraint, not a class ban; use it to make the principal anchored/corridor fixture require a context edit. Per-candidate private copies replace shared undo-history reuse for stronger rollback isolation at a measured extra copy cost.

For authored EXTERNAL port frames only, an exact unchanged baseline convention defect may remain as `legacy_port_frames` review evidence plus an integrity warning. Preserve both peers' original metadata, endpoint positions and profile. This is an explicit exception to rejecting preexisting known frame defects, aligned with reporting unchanged baseline geometry conflicts; it does not establish IFC conformance. New/generated or changed/worsened bad frames reject, and independent position/flow/system/profile failures still reject. Missing metadata remains distinct from a known retained legacy defect. Show these warnings and require acknowledgement before acceptance.
