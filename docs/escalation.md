# Escalating to Muse Wonder (draft plan)

**Status (Oct 29):** draft, not built. Waits on the Advanced IFC edits (`docs/edits.md` on `feature/fix-kinds`, then
reroute, resize and penetration), which give Wonder the edits it needs: an opening in structure, a reroute, a resize.

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
- **Not yet tried: Wonder on a real clash Spark can't fix.** That is step 1 (E0).

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
- A spend guard: `SIGHTLINE_ESCALATE_MAX_USD_DAY`, from the recorded usage, stops escalations for the day.

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

## Open questions

1. Cap defaults and the daily spend limit.

Decided (Oct 29): a button by default; also offered after a successful run, to look for a better fix.
