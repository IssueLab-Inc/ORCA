# Escalating to Muse Wonder

**Status (Oct 29):** built (below: "What was built" and "E0 results"). The design that follows is the plan it was built
from; where the two differ, "What was built" says what the code does.

When Muse Spark's propose → verify loop ends with no verified fix, the clash gets a second, longer try: Muse Wonder
(`muse-wonder-1.0`), with everything ORCA learned on the first try and every registered kind of edit. It runs
through the same geometry check: nothing reaches the user unverified, and the headline stays verified model edits.

## What we know (checked Oct 29)

- `muse-wonder-1.0` is on our key (`/v1/models`). Preview, $4 / $20 per million input / output tokens, 1M context, no
  contributor tier (every call is billed). Takes text and images.
- Strict `json_schema` works on chat completions and on Responses, and Responses streams reasoning summaries
  (`reasoning: {summary: "auto"}`). So `MetaChatModel(model="muse-wonder-1.0")` works as it is: `complete_json`
  and `complete_json_reasoning` need no change.
- A small question: 9.3 s on Responses (effort low, 225 reasoning tokens), 5.1 s on chat completions.
- Reasoning tokens count against `max_completion_tokens`: a 20-token cap came back with `content: null`. Never set a
  tight cap.
- Wonder on real clashes Spark can't fix: E0, below.

## When it runs

- **Button** (default, owner decision Oct 29): NoFix ("No edit passed the geometry check") gets **Ask Muse Wonder**,
  with one line on what it does ("A larger Meta model takes a second, longer look, with everything ORCA tried. About a
  minute.").
- **After a successful run too** (owner decision Oct 29): under the options, a quieter **Look for a better fix with
  Muse Wonder**. Wonder then gets Spark's options as well as its failures and is asked to beat them (a plain fix where
  Spark found only a resize or a penetration, more clearance, a smaller change). Its options join Spark's in one
  ranked list, each with its model chip; nothing Spark verified is dropped.
- Owner setting `escalation`: `off` / `button` / `auto` (settings.py, For me and For everyone; env
  `SIGHTLINE_ESCALATION`, default `button`). `auto` escalates once when Spark ends with no verified option (never
  after a successful run: that stays a choice).
- Not offered: for a requirements recommendation (nothing may be edited: `_recommend`); for a clash that is not a
  clash.
- Plans: a Fix-together item that failed (`plans.failure_summary`) gets the same button; never automatic in a plan
  (the cost multiplies).

## What Wonder reads that Spark didn't

The same system pack (`construction.md`, plus the requirements' guidance) and `domain_packs/escalation.md`. The user
text is `_describe` plus:

1. **Spark's run:** its understanding and advice, every attempt with its reason, what it hit (`hit_ids` by name and
   class) and where (`Attempt.where`). The server keeps the last result per scene and pair (`Workspace`), so the
   browser doesn't resend it.
2. **A wider neighbourhood:** every element within 5 m of the pair (class, name, system, storey, box, ports) and the
   free height along the run (soffit to the next element below).
3. **Passages in every blocker,** not only the clash's obstacle (`edits.passages` for each element it hit).
4. **The requirements,** as Spark gets them: who may move, clearance, largest move, who reviews.
5. **The kinds of edit, from the registry:** every `agent.TRIES` kind with its `PARAMS`, written from the registry so
   Wonder is never offered a kind that isn't there. After the Advanced edits: reroute, resize, penetration.
6. **Compound fixes (new):** one candidate may change several elements (move the return-air main 150 mm *and* offset
   the duct), tried in one trial and checked together, the way `plans.verify_together` checks a plan. This needs a
   compound kind in the registry (an ask of the edits work, below).
7. **Pictures:** A/B/C, as Spark had. Later: one view per main blocker.

The brief is capped at about 60k tokens: the 1M context means no trimming is needed for quality, but each token is
billed.

## The loop

`agent.resolve(model=wonder, max_rounds=2, …)`: the same kinds, refusals, ranking (`agent.TIERS`) and trials streamed
to the pilot. Events and options carry `model`, so the activity table, the pilot's status line and the option say
"Muse Wonder". As today, a round with only a resize or a penetration gets one more round to find a plain fix.

A penetration, or any option with `review`, shows **Needs approval by structure** (or services): the geometry is
verified, it is never applied before that team says yes, and the PDF and BCF assign it to them.

If Wonder fails too, NoFix shows its advice ("What decides it") and "Muse Wonder also tried n ideas"; **Flag for the
model's author** carries both runs.

## Model plumbing

- `META_ESCALATION_MODEL` (default `muse-wonder-1.0`) and a role `"escalation"` in `MetaChatModel.effort`, so the
  owner's Spark effort doesn't carry over to Wonder. Default effort `medium`; the owner can change it (Wonder takes
  minimal to max; `max` does not select Wonder Full).
- **Usage:** read `usage` from both endpoints (Responses: the `response.completed` event), add it up per run, and
  return tokens and an estimated cost with the result. The owner sees it in the activity footer; evals record it.
  Nothing records usage today.
- Calls time out at 240 s (Wonder reasons longer than Spark).

## Caps

- `SIGHTLINE_ESCALATE_PER_HOUR` per visitor (default 3) and `SIGHTLINE_ESCALATE_PER_DAY` for everyone (default 30);
  an escalation also takes one proposal. The owner has no caps; MCP links charge the link's creator.
- A spend guard: `SIGHTLINE_WONDER_MAX_USD_DAY` (built as one budget for every Muse Wonder call, Show it built's
  judges included), from the recorded usage, stops escalations for the day.

## UI

- NoFix: the button and its line. While it runs: the live reasoning notes, the pilot and the activity table, as for
  Spark; status "Muse Wonder is thinking".
- Options: a small "Muse Wonder" chip; "Needs approval by …" for reviewed kinds.
- Phones: when NoFix shows, the peek line's next step is Ask Muse Wonder.
- Chat: `propose_fixes(escalate=true)`. MCP: `escalate_fix` (a job, like propose).
- Tour: not in the main tour (live cost and time); a recorded run later, if it earns a step.

## E0: is it the model or the brief?

Run this before building anything.

- **Set:** (a) every real clash in the Northbank and cell runs where Spark's proposal has no verified option (sweep
  once, list in `evals/escalation.csv`); (b) the Advanced edits work's cases that need a reroute, resize or
  penetration; (c) known failures such as the cell's C5 HMI (the clearance check counts the floor contact).
- **Arms:** Spark again (control), Spark with the escalation brief, Wonder with the escalation brief. The same round
  limit for each.
- **Measure:** verified or not, time to the first verified option, rounds, tokens, cost. The answer key (3/3 at Rev04
  heights) must not change.
- **Also:** on clashes Spark does fix, does Wonder find a better one (plain where Spark's was a resize or a
  penetration, more clearance, a smaller change), and how often? That sizes the "better fix" link.
- **Decide:** ship the Wonder button if Wonder with the brief verifies clearly more than Spark with the brief (at
  least two more cases, or cases where Spark with the brief verified none). If the brief alone closes the gap, give
  the brief to Spark first and keep Wonder for what is left.
- Rows go in `evals/results.csv` (append-only).

## Plan (after the Advanced IFC edits land)

Branch `feature/wonder-escalation`, one PR.

1. E0 (`evals/escalation.py`); write the numbers and the decision here.
2. Server: `escalation.py` (the brief), `Workspace` keeps the last result per pair, `propose/stream` takes
   `escalate: true`, usage and the `"escalation"` role in `meta_client`, caps, the setting. Tests with a scripted
   model: the kind list comes from the registry; refused when Spark found an option; caps and spend guard; usage adds
   up; after a successful run Spark's options are kept and ranked with Wonder's; a reviewed kind is never applied
   without approval.
3. The compound kind, if the edits work didn't add it.
4. Web: the NoFix button, the "Look for a better fix" link under the options, model chip, needs-approval chip,
   activity labels, phone peek. If App's imports change, add
   them to both stub lists (`web/tests/app-host.mjs`, `app-replacement.test.mjs`).
5. Chat and MCP tools.
6. Runtime check: one escalation end to end in the browser on Northbank and on the cell, the PDF page showing the
   option and its reviewer; then on Modal.
7. CLAUDE.md entry. Landing and README only with measured numbers.

## Asks of the Advanced IFC edits work

- `PARAMS` for each kind, clear enough to write Wonder's kind list from.
- A compound candidate (several edits, one trial), or a note that it is out of scope.
- Preview meshes for a penetration (the girder drawn with its new opening): Show it built needs them too
  (`docs/show-it-built.md`).
- Bends that follow the segment's profile. `edits._bend_mesh` sweeps a closed rectangle (or circle) for every bend, so
  an offset cable tray (`IfcUShapeProfileDef`, Northbank's 300 × 100 mm, 4 mm walls) gets closed box bends between
  open channels; the same would hold for C, I and L profiles. Sweep the profile's own outline. Show it built's pictures
  draw the tray open all the way and a prompt line didn't change that (`docs/show-it-built.md`), so this is what makes
  picture and model agree.
- Test cases that need each new kind, for E0.

## What was built (Oct 29)

- **Model:** `meta_client.escalation_model()` (`META_ESCALATION_MODEL`, default `muse-wonder-1.0`, 240 s timeout, role
  `"escalation"`, default effort medium). `escalation_info()` tells the page the model, its label and the mode.
  `MetaChatModel.usage` counts every call's tokens (chat completions' `usage`; Responses' final event, however it
  ended: completed, incomplete or failed); `PRICES` is by id prefix, so any Wonder version is billed. A run's usage is
  the difference over that run (`Usage.snapshot`), reported only for a model billed per token (Muse Spark's one client
  is shared by every visitor).
- **Budget:** `spend.py`, one day's limit for every Muse Wonder call (`SIGHTLINE_WONDER_MAX_USD_DAY`, default $25;
  in memory, UTC day). A request claims its estimate when it is let through (`spend.claim`, $1 a second try:
  `escalation.ESTIMATE_USD`; checked and held in one step) and the second try takes the claim over while it runs
  (`spend.held`), so tries started together cannot all pass on a nearly spent day. The owner is exempt from the
  limit, not from the count.
- **Setting:** `settings.escalation()` off / button / auto (`SIGHTLINE_ESCALATION`, default button) and
  `escalation_effort`, for me and for everyone in the owner menu.
- **The brief:** `escalation.brief` = the first try (understanding, advice, each idea with why it failed and what it
  hit by name, the fixes it verified), the elements it ran into most with the openings and room past each
  (`blockers`), every element within 5 m (`neighbourhood`: class, name, level, box, whether a combined fix may move it,
  whether it is joined to A or B), and the kinds of fix from the registry. Prompt: `domain_packs/escalation.md`.
- **The combined kind** (`agent._try_combined`, registered in `TRIES`/`PARAMS`/`IN_TRIAL`/`KEEP`/`SIZED`): 1 to 3
  steps (move, offset, route), each on its own element, one on A or B, tried in one trial and checked together
  (`check_combined`: each step's elements against everything, a split run's shortened ends against A, B and the other
  steps). Never structure (`agent.stays`: the fixed classes by inheritance, IFC2X3's `IfcWallStandardCase` included,
  and piles), nothing but services besides A and B, and a moved run must hold neither; the requirements apply to
  every element a step moves. Ranks after a single element's fix (`TIERS` 0.5) and ends the search. Kept all or
  nothing (`edits.kept_files`), with each split run's pieces returned on its own (`groups`). A plan checks it the same
  way (`plans._in_trial_combined` returns its own check).
- **The second try:** `Workspace.escalate`: reads the last try at the pair (`last_try`, kept per scene and pair, 200
  at most, dropped with its scene), but only while it still holds: once an edit was kept in the scene or the
  requirements changed, its options were verified against a model or rules that are gone, so the second try starts
  without it. Two rounds on Wonder; the result's options are both tries' in one ranked list, each with its `model`,
  and its attempts both tries'. A first try that a plan made (a Fix-together item) is remembered too. Refused where
  nothing may be edited (409, before any cap is taken). `propose` with `auto`: a second try at once when nothing
  verified, if the caller's caps allow; if it fails, the first try's result comes back with a note.
- **API:** `POST /propose` and `/propose/stream` with `escalate: true` (events: `escalating` with the model and the
  first try's ideas, then the second try's events, each with `model`); `GET /api/models` has `escalation`. Caps:
  `SIGHTLINE_ESCALATE_PER_HOUR` / `_PER_DAY`, plus one proposal, both taken or neither
  (`ProposeLimit.take_all`).
- **Page:** NoFix's **Ask Muse Wonder**; under verified options **Look for a better fix with Muse Wonder**; a failed
  Fix-together item's **Ask Muse Wonder** (it reads the plan's try at that pair); model chips on options and
  ideas; the pilot names the model and numbers the second try's ideas after the first's; the owner sees tokens and
  cost. A second try that fails or is refused puts the first try's options back.
- **Chat and MCP:** `propose_fixes(escalate=true)`; chat suggests it when there is no fix, or only a resize or an
  opening, and no recommendation. The `escalating` event carries the first try (understanding, ideas, verified
  options), so a page that did not watch it keeps those options if the second try fails. A plan whose model changed
  since it was checked (a failed item's second try was kept) cannot be accepted until it is built again.
- **Tests:** `tests/test_escalation.py` (combined fixes, guards, atomic keep, the second try, staleness, caps, budget,
  usage, chat, API) and `tests/test_plans.py` (a combined fix in a plan; a plan item remembered).

## E0 results (Oct 29, `evals/escalation.py`, `evals/runs/2026-10-29-escalation/`)

21 real clashes (Northbank's answer key and B1, the cell's planted C1-C8), one Muse Spark proposal each: 6 with no
verified fix, 2 fixed only with an opening (C7, C8), 1 lost to a Meta 500 in the sweep. On the 6, three arms of two
rounds each:

| Case | Spark again | Spark + brief | Wonder + brief | Wonder s / $ |
|---|---|---|---|---|
| Cell C4 robot reach × post N3 | no fix | no fix | move post 300 mm and lift 180 mm | 113 / 0.26 |
| Cell C4 × post N4 | no fix | move post 400 mm onto plinth | move post 400 mm and lift 120 mm | 112 / 0.19 |
| Cell C4 × base plate N3 | no fix | move base 1250 mm | move base 500 mm, lift 200 mm | 143 / 0.35 |
| Cell C4 × base plate N4 | no fix | move base 350 mm onto plinth | move base 500 mm, lift 150 mm | 117 / 0.30 |
| Cell C5 HMI × panel space | no fix | no fix | no fix | 124 / 0.33 |
| Northbank B1 pad footing × lift pit wall | no fix | no fix | move the pad footing 1.30 m west | 45 / 0.12 |
| **Verified** | **0 of 6** | **3 of 6** | **5 of 6** | 19 min, **$2.01** in all |

- **Decision:** ship it as built (the button; auto for the owner to try). Wonder with the brief verified two more
  than Spark with it, the rule set above.
- **The brief is most of the gain on Spark:** 0 → 3 of 6. Next: give it to Spark's own second round (free on the
  contributor tier) and keep Wonder for what is left.
- **Read the C4 fixes with care.** Four of Wonder's five lift a fence post or base plate 120-200 mm off its slab:
  the move check counted the post's embedment in the slab as a clash once the post moved (as the C5 HMI's floor
  contact), so lifting dodged it. Geometrically verified, not buildable as drawn. Fixed in the check (Oct 30,
  `docs/edits.md` "A move keeps what it stands on"): a post slid along its slab keeps its anchors' contact, and a
  lift off it is refused.
- **B1 moves a pad footing:** verified, but structure; `review` should say so (follow-up: the same "structure
  review" chip a penetration in structure gets).
- **Better fix** on C7 and C8 (openings): Wonder found no plain fix either. Northbank's answer key stays 3/3 first
  try at Rev04 heights on Spark.

## Open questions

1. Cap defaults and the daily spend limit: 3 an hour per visitor, 30 a day, $25 a day for now.

Decided (Oct 29): a button by default; also offered after a successful run, to look for a better fix.
