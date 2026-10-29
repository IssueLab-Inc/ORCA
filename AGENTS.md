# ORCA working guide

Read `CLAUDE.md` for the product, geometry, environment, and secret-handling rules.

- All commits use author and committer `Dodzi Agbenorku <50728220+dodzikojo@users.noreply.github.com>`. No co-author or session trailers.
- Large work uses a branch per slice named for its kind (`feature/…`, `fix/…`, `docs/…`; no tool prefixes such as `codex/` or `claude/`) and a PR; do not implement on main or merge without authorization.
- New specs and plans go in `docs/` (e.g. `docs/requirements.md`), never `docs/superpowers/`; no superpowers skills (owner decision, Oct 29).
- Earlier program (history): `docs/superpowers/specs/2026-10-28-context-fixes.md`, implementation plan `docs/superpowers/plans/2026-10-28-context-fixes.md`, durable progress `docs/superpowers/context-fixes-progress.md`.
- Python: `server/.venv/Scripts/python.exe`; tests from `server` with `..` paths adjusted. `uv run pytest -q` is also supported. Web: `npm run build` in `web`.
- Preserve IFC federation coordinates and SI metres. Only server geometry supplies clearance numbers. API keys and `.env` contents never enter git or tool output.
- Verify tests and the running product before claiming completion. Keep unrelated changes intact.
