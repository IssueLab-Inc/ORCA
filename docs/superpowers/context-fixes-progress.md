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

## Verification environment

Baseline Windows: 77 passed, 2 PDF failures from missing native libgobject. Web build passes with existing bundle-size warning. Built local ignored Docker image `sightline-context-check:20261028` from frozen server lock and Python 3.13 with native Pango/Harfbuzz. All 4 document tests pass there (2.06 s), confirming the baseline PDF issue is environmental. Full final server checks will run in this container using a read-only bind mount of server source and no pytest cache writes.

## Task 1 checkpoint

Implementation 87d2786 (Dodzi author/committer); full Linux 109 passed. Independent review identified one Important missing-placement integrity bypass; original worker is fixing it before task completion. Controller verified all three Northbank reference offsets individually and together on the four-file federation: three-group result passes with no new hits or integrity errors (9.92 s), retaining five designer-review conditions.

Task 1 complete: fix 6fdccf1 addresses missing-placement bypass with real flow/system/profile mismatch regressions; independent scoped re-review approved. Controller full Linux check after fix: 113 passed in 10.42 s. No critical/important findings remain. Runtime UI smoke remains Task 3.

- Ruling: use a fresh private candidate copy rather than reusing IFC undo history between candidates — measured clone cost is small on Northbank and it makes failed multi-file trials completely isolated; cost if wrong is extra CPU/memory and fewer trials within the time budget, not partially changed live files.

Next: create foundations PR and branch codex/context-fix-planner from its head; dispatch fresh Task 2 implementer.
