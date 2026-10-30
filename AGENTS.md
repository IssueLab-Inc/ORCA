# ORCA working guide

Read `CLAUDE.md` for the product, geometry, environment, and secret-handling rules.

- All commits use author and committer `Dodzi Agbenorku <50728220+dodzikojo@users.noreply.github.com>`. No co-author or session trailers.
- Large work uses a branch per slice named for its kind (`feature/…`, `fix/…`, `docs/…`; no tool prefixes such as `codex/` or `claude/`) and a PR; do not implement on main or merge without authorization.
- New specs and plans go in `docs/` (e.g. `docs/requirements.md`), never `docs/superpowers/`; no superpowers skills (owner decision, Oct 29).
- Earlier program (history): `docs/superpowers/specs/2026-10-28-context-fixes.md`, implementation plan `docs/superpowers/plans/2026-10-28-context-fixes.md`, durable progress `docs/superpowers/context-fixes-progress.md`.
- Python: `server/.venv/Scripts/python.exe`; tests from `server` with `..` paths adjusted. `uv run pytest -q` is also supported. Web: `npm run build` in `web`.
- Preserve IFC federation coordinates and SI metres. Only server geometry supplies clearance numbers. API keys and `.env` contents never enter git or tool output.
- Verify tests and the running product before claiming completion. Keep unrelated changes intact.

## Keep the architecture docs current

`docs/architecture/` maps the whole application (start at its `README.md`). Every agent keeps it true:

- A core change updates the matching doc **in the same PR**: a new, renamed or removed module, route, stream event, fix kind, model or prompt, env var, cap or budget, stored state or id, deploy step, test harness, user-facing flow, or owner decision. The table "Keeping these docs current" in `docs/architecture/README.md` says which doc each change touches; each doc ends with "When to update this doc".
- Re-checked a doc against the code? Update its "Checked against code" date and commit. Found one wrong? Fix it, even if your change didn't cause it.
- Notable work gets a short dated entry at the end of `docs/architecture/22-build-log.md`, not in `CLAUDE.md`.
- `server/tests/test_docs_map.py` fails when a server module, prompt, web source file, route, MCP tool or env var is missing from the map, or a link in it is broken. Add the doc line; never loosen the test.
- Feature designs still go in `docs/<feature>.md`; the map links to them rather than copying them.
