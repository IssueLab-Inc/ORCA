# ORCA Workings: watching the agent work

Workings draws a run as it happens: what Muse proposes, what ORCA checks and what it decides, as lanes of steps
joined by the paths between them. It lives in the Activity panel, beside today's table (Steps), so people can see
the work behind each result: every idea, every geometry check, every retry and why.

It is new work, written for ORCA during the event. No code from other products. A clickable mockup was reviewed on
Oct 30 (recorded #042 and girder runs, illustrative triage and Show it built); this plan builds what it showed.

## Decisions (owner, Oct 30)

- **The name is Workings.**
- **It lives in the Activity panel**, as a second view beside Steps (`W` switches). It goes wherever the panel goes:
  the bottom bar, floating over the model, or a window of its own on a second screen (`docs/panels.md`).
- **It can be switched off completely.** Off, the Activity panel is Steps alone, as today.

To settle before slice 1 (recommendations in bold):

- The Activity panel's default view: **Steps** (the tour and the golden path read as today; the video pops Workings
  out), or Workings.
- When Workings opens in the bottom bar: **the bar grows to about 360 px and goes back on Steps**, or the person
  drags it.
- Phones and tablets: **Steps only** (they keep their layouts, `docs/mobile.md`), or Workings in the sheet.

## What it shows

Lanes are who does the work: you (or an agent linked over MCP, or the chat), Muse (Spark, Spark Open, Wonder,
Image) and ORCA (rules, edits, geometry checks). Steps sit in columns in the order they happen, so nothing jumps as
events land. A step that hasn't happened yet but could (Accept, Look for a better fix) is drawn dashed.

| Run | Steps | Built from | Slice |
|---|---|---|---|
| Proposal | the brief, each round (Muse's reasoning summaries, its understanding), each idea, each geometry check (in place, verified with its clearance, or what it hit), the stop rule, the ranking, the options | `thinking`, `reasoning`, `ideas`, `checking`, `trial`, `attempt`, `note`, `result` | 1 |
| Second try | a Muse Wonder branch that starts from the first try's attempts | `escalating`, then as above | 1 |
| Fix together, root cause | the cause, one row per item with its ideas and checks side by side (Muse thinks for all at once; the checks take turns), the plan checked as a whole | `thinking`, `root_cause`, `plan_items`, `item`, `checking_plan`, `plan` | 2 |
| Triage | settled by rule (by basis), alike groups, the open model's calls at once with their reasoning, open-model facts winning, the verdict counts | `start`, `clash` (`source`, `basis`, `alike_of`), `reasoning`, `audit`, `done` | 2 |
| Show it built | each round's restyles, the pixel gate's numbers, each judge's verdict, the retry and what it was told, the picture kept | `drawing`, `gate`, `judging`, `judged`, `retry`, `result` | 2 |
| Detection | each test, its candidate pairs and clashes, the diff | `phase`, `start`, `test`, `test_done`, `done` | 2 |
| Chat and MCP | who started a run (a label in slices 1 and 2); later a chat turn as the parent of the runs its tools start | `tool`, `tool_result`, wrapped events | 1 (label), later |

**It shows only what the streams say.** Times are measured from the events; numbers are the server's; Muse's words
are its own reasoning summaries and answers. It never writes "thoughts" of its own (the rule in `CLAUDE.md`:
numbers people see are measured).

**It costs nothing and changes nothing.** It reads events the page already receives: no new requests, no model
calls, no effect on how a run goes. Switched off or hidden behind Steps, it is not drawn; the run is still logged
(a few kilobytes), so opening it mid-run shows the run so far.

## Using it

- **Follow** keeps the newest step in view. A drag, a scroll or a zoom hands the view over; Follow takes it back (the
  pilot's own rule in the 3D viewer).
- **Zoom:** far out, each step shows its title; close in, its reasoning, numbers and hits. **Fit** shows the whole
  run. A **minimap** shows where you are.
- **The timeline** under the canvas shows the run's model calls, checks and (for a proposal) the viewer's playback.
  Dragging it replays a finished run from its events.
- **With the 3D viewer:** "In view" marks the step the pilot is showing (it trails the stream on purpose, to keep
  each trial readable). Later: hover or tap a check to see that trial in the viewer.
- **Runs:** the latest run is shown; a picker holds the last few (a proposal, the triage still going, a plan).
- **Events** labels each step with the event behind it, for reviewers.

## How it fits the panels (`docs/panels.md`)

- **Drawn in the Activity slot.** Workings is a component inside `slots.activity`, so floating, popping out,
  collapsing or Put it back only moves it. Nothing remounts: zoom, Follow and the chosen run survive a move.
- **Size.** The bottom bar's default (120 px) suits Steps, not a graph. `DockHandle` gains a call that makes the
  Activity panel's bar at least a given height (dockview's edge group size; check its API in slice 1), used when
  Workings opens there; `EDGE_SIZE.bottom` may need a higher maximum. Floating and pop-out windows keep the size the
  person gives them.
- **Pop-out windows.** Animation frames, the resize observer and pointer capture come from the slot's own window
  (`el.ownerDocument.defaultView`): the main window's frames stop when it is hidden behind. `App`'s keys already
  listen in pop-out windows (`W` and `F` join them); tooltips take that window's `doc`.
- **Floating over the model.** The canvas pans by transform and never scrolls, so the WebGL hole found on Oct 30
  should not come back; a browser check confirms it.
- **Classic layout.** The footer grows when Workings is chosen and shrinks back on Steps.
- **The tour** gathers panels home as now. It has no Workings step in slice 1.

## How it works

| Part | What it does |
|---|---|
| `web/src/runlog.ts` (pure, tested) | The runs this page watched: `start(kind, { origin, title })` returns a run; `add(event)` stamps it with the time; `end(result or error)`. Keeps the last 12 runs; subscribers re-draw (`useSyncExternalStore`). |
| Hooks in `App.tsx` | One line in each tracker that already gathers a run's events: `trackAgent` (a click, the chat, an MCP agent and the tour's replays all pass through it), `trackPlan`, `runTriage`, the built job, `onDetectEvent`. Each passes its origin: `you`, `chat`, `agent`, `replay`. |
| `web/src/workings.ts` (pure, tested) | A run's events to a graph: lanes, columns, steps (actor, title, status, start and end, body), edges (sequence, path not taken, feedback), timeline bars. One builder per run kind. |
| `web/src/Workings.tsx` | Draws the graph: steps as HTML on a pan-and-zoom layer, edges in SVG, lane labels, Follow, zoom and Fit, Events, the minimap, the timeline with scrub, the run picker. Ported from the mockup. |
| `Activity.tsx` and the Activity panel | Steps and Workings switch, and the off switch. Kept in this browser as `sightline.workings` (on or off, last view). |
| `pilot.ts` | `PilotStatus` gains the step it shows, for "In view". |

**No new dependency.** A node-graph library (React Flow) was weighed: the layout is ORCA's own anyway (columns by
step, rows by item), the mockup's canvas already does pan, zoom, follow and minimap in a few hundred lines, and
dockview stays the one library added before the freeze.

## Server (optional, after slice 2)

Additive fields that make some steps better; the page works without each one. Each updates
`docs/architecture/09` and `10` and gets a test.

- `ideas.candidates` (`[{title, kind}]`): every idea appears at once, instead of as each is checked.
- `attempt.seconds` and `attempt.checked` (elements in the neighbourhood): "checked against 214 elements in 0.5 s".
- Triage `start.groups`: the alike groups before the first verdict.
- Show it built: which judges it uses (full or lighter) at the start, not only in the result.

## Slices

A branch and a PR each (`AGENTS.md`).

1. **`feature/workings`: proposals, about a day.** `runlog.ts`, `workings.ts` for proposals (rounds, second try,
   recommend mode), `Workings.tsx`, the Steps and Workings switch and the off switch, the bottom bar's size, pop-out
   window handling, "In view" from the pilot. Tests and docs below.
2. **`feature/workings-runs`: everything else that streams, about a day.** Fix together and root causes (and their
   replays), triage, Show it built, detection.
3. **Before the freeze if there is time, else after.** Chat turns as parents, hover to show a trial in the viewer,
   the server fields above, the wider fix (`context_planner`).

Freeze Nov 3. For the video: Workings popped out to a second screen beside the model, during a live proposal and a
root cause.

## Tests and checks

- `web/tests/workings.test.mjs`: the tour's recordings (`web/public/tour/c0053.json`, `c0051.json`,
  `cell-ladder.json`, `girder-plan.json`, `cell-pipe-plan.json`) give the expected steps, verdicts, times and paths;
  a second try and a round 2 from small fixtures; triage, Show it built and detection from fixtures (slice 2).
- `web/tests/runlog.test.mjs`: start, add, end, the 12-run limit, origins.
- New imports in `App.tsx` go into both stub lists (`web/tests/app-host.mjs`, `app-replacement.test.mjs`).
- `server/tests/test_docs_map.py`: the new web files are listed in `docs/architecture/12-web-app.md`.
- Browser (Playwright, Northbank, 1440×900): #1 proposed with Workings open in the bottom bar; Activity floated over
  the model (no hole); popped out (Follow, zoom, scrub, `W` and `F` from that window); Put it back mid-run; reload;
  Classic layout; the tour; tablet (1024) and phone (390) unchanged, no sideways scroll.
- `npm run build`, `npm test`; the server tests are unchanged unless slice 3's fields land.

## Docs to update with each slice

`docs/panels.md` (Activity holds Workings, its size), `docs/architecture/12-web-app.md` (modules and state), `01`
(the journey), `20` (the owner decisions), `22` (a build log entry); `09` and `10` only with server fields; `13` with
hover in the viewer.

## Not done (later)

- Workings on phones and tablets (unless decided above).
- Comparing two runs side by side.
- Saving or sharing a run's Workings.
