# Context fixes program — 2026-10-28

Status: approved design saved; implementation starting on codex/context-fix-foundations.

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
