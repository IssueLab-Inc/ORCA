# Edits: the kinds of fix ORCA can make

Every fix ORCA offers is an edit to the real IFC elements, tried in a transaction, checked by geometry and undone
before anyone sees it. This page is the design of the kinds of fix and how a new one is added. Code:
`server/sightline/edits.py` (the geometry), `agent.py` (trying ideas), `plans.py` (several fixes at once), and
`web/src/fixKinds.ts` (how the page describes them).

## Kinds

| Kind | What it does | Since |
|---|---|---|
| `move` | Moves a straight run (the element and what it is joined to) by a vector | Oct 27 |
| `offset` | Splits a straight segment either side of an obstacle and takes the middle up or down (or sideways), with bends | Oct 27 |
| `trim` | Cuts a slender member's end back to butt another's face | Oct 27 |

## One registry (Oct 29)

Each kind is registered in one place per layer, so a new kind is added by registering it, and a kind nobody
registered is refused instead of being tried as a move (before, anything Muse called by another name was moved by
its `delta_m`):

- **Trying an idea:** `agent.TRIES[kind]` → `(scene, candidate, target, other, clearance, on_trial, others=)` →
  `(Attempt, Option or None)`. `agent.PARAMS[kind]` names the candidate fields that describe it (carried into a
  recommendation, which is never tried).
- **A plan's joint check:** `plans.IN_TRIAL[kind]` applies it inside the plan's trial and says what to check;
  `plans.EXTRA_FILES[kind]` names files it changes beyond its moved elements'.
- **Keeping it:** `plans.KEEP[kind]`, behind `plans.apply`, which the plan, the MCP `apply_fix` and the page's
  `POST /api/scenes/{sid}/fix/apply` all use. That endpoint drops the page's meshes and works out anything that
  depends on the requirements again on the server.
- **Sizing it against the requirements:** `requirements.SIZED` and `change_size` (how far any part goes; a lateral
  offset used to measure 0 mm).
- **The page:** `fixKinds.ts`: the name, the edit in a few words, the clearance line, which pieces to frame, who must
  review it. The newer kinds carry the server's own `edit.summary`, so the page says what Muse was told.

An option of a newer kind carries `edit` (its parameters, a `summary` and a `key` that tells two fixes apart) and
`review` (who must review it before it is built, when geometry alone cannot say it works).

## Ranking

Plain geometry fixes (move, offset, trim, route) rank before a resize (it changes how a service performs), and a
resize before a penetration (another team builds it): `agent.TIERS`. Then comfortable clearance, the smallest change,
the most clearance. A round that verified only a resize or a penetration does not end the search: Muse gets one more
round to find a plain fix.

## Several obstacles

A plan merges pairs that share a movable element into one item (`plans.merge_shared`). The agent now gets those other
obstacles as `Clash.others`: they are placed along the run in the text Muse reads, and a split run's shortened end
pieces are checked against all of them, not only the first (before, an offset could pass while its end still ran
through the second obstacle). Failed attempts also tell Muse where the worst hits are (`Attempt.where`).
