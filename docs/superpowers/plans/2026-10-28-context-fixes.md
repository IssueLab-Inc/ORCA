# Context-aware Fixes Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development task-by-task, fresh context per task, task review after each and whole-branch review at the end.

**Goal:** Propose and atomically accept coordinated context edits resolving one clash.

**Architecture:** A private, revision-pinned IFC scene supports compound trials. A bounded model tool loop inspects geometry and proposes operation sets; server checks decide eligibility. Add dedicated APIs/chat integration and a review panel with whole-proposal acceptance.

**Tech Stack:** Python 3.13/FastAPI/IfcOpenShell, React/TypeScript/Three.js; existing dependencies only.

**Spec:** docs/superpowers/specs/2026-10-28-context-fixes.md

## Global Constraints

- Repository C:/Users/dodzi/source/repos/clashwise-sightline; Windows PowerShell 5.1 (no &&).
- All commits use author and committer Dodzi Agbenorku <50728220+dodzikojo@users.noreply.github.com>. No co-author or session trailers. Never commit or print secrets.
- Never implement on main; controller owns branch switching, pushes and PRs. Workers commit only their assigned files.
- No worker dispatches other agents. Controller schedules independent reviews. Fresh workers read their brief and CLAUDE.md/AGENTS.md.
- Follow TDD: meaningful RED before implementation, focused GREEN, full relevant suite before commit; include command evidence in report. Python .venv exists under server; web/node_modules exists.
- GlobalIds, SI metres, federation coordinates, server-only clearance authority. Preserve old proposal/batch contracts.
- Three groups, six model calls, twelve trials, 120-second budget, three alternatives, 2.5 m initial context; explicit wider search only.
- Unknown design evidence is a review condition; known failed constraints reject. No autonomous acceptance and no partial acceptance of dependent edits.

### Task 1: Edit and verification foundations

**Files:** Modify server/sightline/edits.py, scene.py, verify.py, service.py as needed; create server/sightline/context_eval.py, server/tests/test_context_eval.py and meaningful fixtures/tests in existing geometry test files.

**Produces:**
- `IfcScene.revision: int` starts at zero, advances on every kept Workspace move/offset/trim (including batch routes), not trial edits.
- `IfcScene.snapshot() -> IfcScene`: deep in-memory IFC clone including paths, scales, edited set, current bounds and revision. No disk reload of originals.
- Backward-compatible `edits.apply_offset(..., dz_m, corners=None, *, lateral_m=0.0)`; exactly vertical or lateral, no compound/sloped offsets. Return `Offset.lateral_m` default zero; preserve old callers and vertical tests.
- `context_eval.evaluate_candidate(scene, objective: dict, operations: list[dict], discovered: set[str] | None = None) -> dict` never mutates its input after return, even exceptions. Objective has element_a, element_b plus optional report_id/clash_id. Operations: kind move|offset|trim, element GlobalId, reason (required); move delta_m; offset split_m and delta_m [dx,dy,dz] perpendicular to run (vertical or lateral); trim end and by_m. Reject nonfinite/wrong dimensional values, unknown IDs, duplicate/overlapping move groups and more than three groups. Move groups expand connected_run, with overlap detection and connection preservation checks.
- Result `passed: bool, edits: list, checks: {geometry: {passed, target_resolved, hits, existing_conflicts, min_clearance_m}, integrity: {passed, errors, warnings}}, review_conditions: [{id, message}], files: [int], pieces: [[GlobalId]]`. Hits have element, other, kind, distance_m and available location. Each edit retains operation fields and includes moved:[GlobalId], before:[Mesh], preview:[Mesh], pieces:[GlobalId], label:string. Mesh is {global_id, verts, faces}; before/after are world SI triangles. Failure results expose blockers rather than crashing. Generated trial IDs are only preview IDs.
- `context_eval.commit_candidate(scene, objective, operations, discovered=None) -> dict`: evaluate on private copy, fail with ValueError for nonpassing, then atomically replace scene model state, edited set/bounds and increment live revision once; response includes files, pieces, edits, checks. No partial live mutations if any step fails.

**Verification implementation requirements:** Compare each changed piece against neighbours individually to include intra-edit collisions. Add explicit checking mode/helpers rather than breaking legacy verify behavior. No blanket connected-neighbour exclusion in context checks; allow touching at validated joint pairs but still reject penetrations. Compare baseline pair findings to final findings and report unchanged baseline conflicts; target must resolve. Check original external connections and new chain ports (position, frame/flow compatibility where available), systems/profiles; unknown metadata -> review. Structure -> structural review; services -> performance/access/supports review as relevant. Do not claim engineering adequacy. Keep slender trim gate. For context offsets require real fitting support rather than silent square-corner fallback if it would invalidate checking.

- [ ] RED: tests for lateral external endpoints and SI units; snapshot/trial isolation; single edit blocked, compound passes; three-group bound; connected neighbour overlap; external connection break; unsupported/fabricated/NaN/overlap inputs; structural review; multi-file failed commit rollback and export reload.
- [ ] GREEN: implement interfaces above, run focused tests and full server suite, self-review.
- [ ] Commit assigned changes and report RED/GREEN evidence and exact interfaces.

### Task 2: Bounded planner, APIs and chat

**Files:** Create server/sightline/context_planner.py, domain_packs/context.md, server/tests/test_context_planner.py and test_context_api.py; modify app.py, chat.py, meta_client.py, domain_packs/chat.md and .env.example as needed.

**Consumes:** Task 1 interfaces exactly. No changes to Task 1 interfaces without controller agreement.

**Produces:** `context_planner.build(ws, scene_id, objective, emit=lambda e: None, model=None, ...) -> dict` using ws.model tool-capable chat by default and an optional scripted model for tests. A private snapshot is captured with revision under ws.lock. No model calls under ws.lock. Implement real named model tools inspect_element, inspect_neighbourhood, evaluate_proposal. Initial objective/context automatically inspected; discovery includes near-clash 2.5 m boxes, known connections and geometry hit IDs, not arbitrary entire-model scanning. Pagination avoids silently omitting dense context. Inspection supplies bounds/run/systems/connections/capabilities and measured openings. Validate discovered IDs again after run expansion. Successful candidates are deduplicated and ranked by the spec, at most three retained; proposals stored on Workspace in bounded per-scene memory, canonical objective/operations/discovered set held server-side. Enforce limits even for one response with many tool calls. Remaining-time HTTP timeout is request-local; never mutate shared model client timeout/settings. Recover from tool errors, provide feedback, keep prior passing results on deadline/model failure. Cancellation/disconnect frees work state.

Wire contract (the web task consumes this verbatim):
- POST `/api/scenes/{scene_id}/context/stream`, JSON `{element_a,element_b,report_id?,clash_id?}`. Validate objective and optional report attribution; reserve three proposal units once upfront, owner bypass preserved. Final event `{type:"context_result", proposals: ContextProposal[], message:string, seconds:number, trials:number, model_calls:number}`. Progress `{type:"context_progress", phase:"inspecting"|"thinking"|"checking"|"blocked", message:string}`; failure `{type:"error",detail:string}`. Existing NDJSON headers.
- `ContextProposal`: `{id,scene_revision,objective,title,edits,checks,review_conditions,passed:true}` where evaluate result shape is Task 1. Additional metadata optional.
- POST `/api/scenes/{scene_id}/context/apply`, JSON `{proposal_id,acknowledged_conditions:string[]}`. Only server-stored canonical data accepted, check scene/revision and all condition IDs; stale 409, unknown 404, omitted acknowledgement 422. Recheck+commit under ws.lock; return `{files:number[], pieces:string[][], edits:..., resolved_pairs:[{element_a,element_b}], checks:...}`. Only seed and report pairs actually remeasured clear are resolved. Failed fresh checks 409, no model mutation. Server-stored proposals cannot be reused after revision advances.
- Chat adds `explore_wider_fix(clash_id)` and emits `{type:"context_event",event: ContextEvent}` then final context_result via same event wrapper. Counts three units via propose_allowed_many. Chat cannot accept. Supply clear prompt direction when user asks to move surrounding objects.
- Numeric context knobs in .env.example (defaults above), owner effort carried into workers. Existing routes untouched.

- [ ] RED: scripted model discovers a real blocker then evaluates a passing compound plan; rejects unseen IDs/overlapping closure, respects all budgets, retains best passing candidates on deadline, ranking/dedup, and verifies no live mutation during search.
- [ ] RED: API charges exactly three, owner bypass, streams progress/result, invalid acknowledgements/stale/forged IDs, failed commit rollback, confirmed-only resolved pairs; chat request yields context events without applying.
- [ ] GREEN: implement, run focused/full server tests, self-review, commit and report.

### Task 3: Product integration and runtime

**Files:** Modify web/src/api.ts, App.tsx, index.css; create web/src/ContextPlan.tsx; optional small viewer helpers and README updates.

**Consumes:** Task 2 wire contract verbatim and Task 1 edit preview shape. Keep existing single/batch/triage flows working.

**Produces:** Explore wider fix button for matched selected clashes and manually picked pairs; progress explaining inspection, blocker discovery and complete checks. A context review panel with three alternatives, all edit labels/reasons, geometry/integrity evidence and individual designer-review conditions. Whole proposal before/after/both preview includes moved context elements, not just original clash; reuse existing viewer preview/frame helpers with world meshes. Reuse plan tab with separate context state; do not forge clash pair items for enabling edits. Dragging viewer does not stop search. Chat context events land in same review panel without switching away from chat unnecessarily. Acknowledgement checkboxes for every condition; acceptance disabled until all acknowledged, then sends proposal ID, never raw operations. No partial accept. On success reload all affected IFCs, map source -> generated pieces, mark only resolved_pairs entries fixed; stale/error keeps visible proposal and allows regeneration. Clear stale proposals on scene reload and explain revision conflicts. Existing export downloads all edited files. Product text says geometry/model checks passed with designer review conditions, not fully verified design.

Render `checks.integrity.warnings` as well as review conditions, particularly retained known `legacy_port_frames` conventions; never describe them as unknown or fully conformant. Regenerate a stale proposal for its stored objective, not whichever clash was selected later. Route previews coherently between clash, existing batch plan and context proposal; reset acknowledgement when the alternative changes, and ignore result/accept callbacks belonging to a scene that has since been replaced. The controller will drive the browser using the ignored runtime_smoke.py fixture server; no fake model route is shipped.

- [ ] Verify RED via initial typecheck for new contract usage; implement component wiring; production typecheck/build.
- [ ] Drive local running app through selecting a clash, wider discovery, full context preview, condition acknowledgement, acceptance and IFC export; include a scripted local server model for deterministic geometry proof without shipping a fake-model route.
- [ ] Run complete server suite and web build once final changes settle. Self-review, commit, report runtime evidence and limitations honestly.

## Delivery

Controller creates stacked PRs: foundations -> main; planner -> foundations; product -> planner. Attach all PRs to the chat. Independent task reviewers verify spec and quality, final reviewer checks whole branch. Do not merge or deploy automatically. Durable progress and rulings go in docs/superpowers/context-fixes-progress.md; scratch briefs/reports/review packages under .superpowers/sdd/2026-10-28-context-fixes/.
