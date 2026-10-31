# ORCA Workings: watching the agent work

Workings draws a run as it happens: what Muse proposes, what ORCA checks and what it decides, as lanes of steps
joined by the paths between them. It lives in the Activity panel, beside the table that was there before (Steps), so
people can see the work behind each result: every idea, every geometry check, every retry and why.

It is new work, written for ORCA during the event. No code from other products. A clickable mockup was reviewed on
Oct 30 (recorded #042 and girder runs, illustrative triage and Show it built), and this is what it showed, built.

## Decisions (owner, Oct 30)

- **The name is Workings.**
- **It lives in the Activity panel**, as a second view beside Steps (`W` switches). It goes wherever the panel goes:
  the bottom bar, floating over the model, or a window of its own on a second screen ([panels.md](panels.md)).
- **It is the Activity panel's default view.** The choice is kept in this browser (`sightline.workings`).
- **It can be switched off completely**: the eye button beside the switch, or **Workings in Activity** under Panels and
  layout in the Menu. Off, the panel is Steps alone, as before Workings, and its status line says "Workings is off"
  with **Turn it on** beside it (desktop only).
- **The bottom bar grows for it**: a run starting with Workings showing makes the bar 380 px when it is shorter than
  240 px (`DockHandle.fitBar`), and going back to Steps gives the room back, but only while the bar is still the
  height Workings set. A bar the person collapsed, made taller or resized is left alone; floating and pop-out windows keep the size the person gives them.
- **Phones and tablets keep Steps only** (they keep their layouts, [mobile.md](mobile.md)).

## What it shows

Lanes are who does the work: who started the run (you on this page, the chat, an agent linked over MCP, or a recorded
run the tour plays), Muse (Spark, Spark Open, Wonder, Image) and ORCA (rules, edits, geometry checks). Steps sit in
columns in the order they happened, so nothing jumps as events land. A step that hasn't happened but could (Accept,
Look for a better fix) is drawn dashed.

| Run | Steps | Built from (`workingsGraph.ts`) |
|---|---|---|
| Proposal | the brief per round, each round (Muse's reasoning summaries and its understanding), each idea (all at once, named by `ideas.candidates`), each geometry check (in place, verified with its clearance, or what it hit), the stop rule, the ranking, the options; a second try on Muse Wonder is a branch in a lane of its own (under the first model's, so the drawing says who is working; added only when Wonder runs) that starts from the first try's attempts; a recommendation where nothing may be edited | `thinking`, `reasoning`, `ideas`, `checking`, `trial`, `attempt`, `note`, `escalating`, `result`, `error` |
| Fix together, root cause | the cause and its strategy, one row per item with its ideas and checks side by side (Muse thinks for all at once; the checks take turns), each item kept or not, the plan checked as a whole, the plan | `thinking`, `root_cause`, `plan_items`, `item`, `checking_plan`, `plan` |
| Triage | what rules settled (by basis), the alike groups, the model's calls (running ones with their reasoning, when the model streams it), open-model facts winning, the verdict counts, the audit, the end; clashes carried along the busy edges as dots | `start`, `clash` (`source`, `basis`, `alike_of`, `model_reading`), `reasoning`, `audit`, `done` |
| Show it built | ORCA's view (the look pass), each round's restyles, the pixel gate's numbers, the judges' verdicts, the retry and what it was told, the picture kept | `drawing`, `gate`, `judging`, `judged`, `retry`, `result` |
| ORCA's check | each phase, each test with its candidate pairs and clashes, what was found and the difference from the last check | `phase`, `start`, `test`, `test_done`, `done` |

**It shows only what the streams say.** Times are when each event arrived; numbers are the server's; Muse's words
are its own reasoning summaries and answers. It never writes "thoughts" of its own (the rule in `CLAUDE.md`: numbers
people see are measured).

**It costs nothing and changes nothing.** It reads events the page already receives: no new requests, no model
calls, no effect on how a run goes. Hidden behind Steps or switched off, it is not drawn; runs are still logged (the
last 12), so opening it mid-run shows the run so far.

## Using it

- **Follow** keeps the newest step in view, at a zoom that fits the lanes' height where the panel allows. A drag, a
  scroll or a zoom hands the view over; Follow takes it back (the pilot's own rule in the 3D viewer).
- **Zoom:** far out (under 60%), each step shows its title; close in, its reasoning, numbers and hits. A click pins a
  step open (its clamped text in full). **Fit** shows the whole run; a **minimap** shows where you are when there is
  room for it.
- **The timeline** under the canvas shows the run's model calls, checks and verdicts. Dragging it (or the arrow keys)
  replays a finished run from its events; **Replay** plays it again at 1×, 2×, 4× or 8×. On a live run, **Back to
  live** returns to now. Each lane's label sits on its own bars, the clock on the bars' line, and the first tick at
  the track's edge; while the run picker, Replay and the speeds share the timeline's line, they line up on its bars,
  and in a panel under 820 px the timeline takes a line of its own.
- **A check in the 3D viewer:** point at a geometry check (or the idea it checks) and its trial shows in the viewer,
  in place: teal when it passed, amber with what it hit lit when it failed, as the pilot drew it. A click keeps it
  there and takes the camera to it, taking the view from the pilot as a camera move does; a click again lets it go.
  While the pilot is driving, pointing alone does nothing. Only trials from the models open now show, and only for
  the newest three proposals (`TRIALS_KEPT`): older runs keep their steps without their shapes.
- **Runs:** the newest is shown; the picker holds the last 12 (a proposal, a triage still going, a plan, a check).
- **In view** marks the idea the pilot is showing in the 3D viewer. It trails the stream on purpose, to keep each
  trial readable.
- **Events** labels each step with the stream event behind it, for reviewers. Steps marked in amber would need more
  from the server (a `brief` event, alike groups in triage's `start`, a call-start event, which judges Show it built
  uses before its result).

## How it fits the panels ([panels.md](panels.md))

- **Drawn in the Activity slot.** Workings is a component inside `slots.activity`, so floating, popping out,
  collapsing or Put it back only moves it. Nothing remounts: zoom, Follow and the picked run survive a move.
- **Its own window.** Timers, the size check and animation frames come from the window the canvas is in now
  (`ownerDocument.defaultView`): the main window's stop when it is hidden behind. The wheel listener is the element's
  own (React's is passive). `App`'s keys already listen in pop-out windows, so `W` works there too.
- **Narrow panels:** the header drops the status line under 560 px (a container query); the footer wraps; the
  minimap hides when the canvas is under 560 px wide or 280 px tall.
- **Classic layout:** the footer is 44vh while Workings shows.

## How it works

| Part | What it does |
|---|---|
| `web/src/runlog.ts` | The runs the page watched: `start(kind, { origin, title, meta })` returns a handle; `add(event)` stamps it with seconds since the start and drops the meshes Workings never reads (`lean`: pieces, preview, before, placements), except a `trial`'s own `pieces` (the edit in place, for the viewer), which only the newest three proposals keep (`TRIALS_KEPT`); `end(error?)` once. Keeps 12, letting the oldest finished runs go first and never a live one; `stopAll` when the models are opened again (`open`). |
| Hooks in `App.tsx` | `traceStart` in each tracker that already gathers a run's events: `trackAgent` (a click, the chat, an agent over MCP and the tour's replays all pass through it), `trackPlan`, `runTriage`, `drawBuilt` (pictures drawn together are runs of their own and don't grow the panel), `runDetect` and the chat's `detect_clashes`. One run of each kind at a time: a new one ends the one it replaces, and a tracker that finds newer work has taken over ends its run then. A proposal's title is the clash or pair being worked on (the chat's from its `propose_fixes` call), and its `meta.scene` the models it ran on. `peekTrial` shows a check pointed at or kept in Workings (`Peek`) over whatever the viewer showed, frames a kept one (`frameFix`) and takes the view from the pilot for it; it ignores a peek from other models, and pointing while the pilot drives. |
| `web/src/workingsGraph.ts` | A run's events to a graph as it stood at any moment: lanes, columns, steps (actor, title, status, start and end, body and detail parts), edges (sequence, path not taken, feedback, the kept path), timeline bars and ticks, flows. One builder per kind. A proposal's checks and ideas carry their trial (`Peek`: kind, moved, delta, pieces, passed, what it hit). Pure, tested against the tour's recordings. |
| `web/src/Workings.tsx` | Draws the graph: steps as HTML on a pan-and-zoom layer, edges in SVG drawn after the steps are measured (only when the drawing changes), lane labels, Follow, zoom and Fit, Events, the minimap, the timeline with scrub and replay, the run picker (a newer run takes over from a picked one), the flow dots. The check pointed at, else the one pinned, goes to `onPeek` (not on touch: a tap pins). An error boundary keeps a run it can't draw from blanking the page. |
| `Activity.tsx` | The Steps / Workings switch and the off button; Workings when on and picked, else the table; off, "Workings is off · Turn it on". |
| `pilot.ts` | `PilotStatus.step`: the idea on screen, for "in view". |
| `agent.py`, `plans.py` | The `ideas` event carries `candidates` (`[{title, kind}]`), so a round's ideas show together; without it (older servers) each shows as it is checked. Each `attempt` carries the check's `seconds` (timed inside the lock: the edit in a trial, the check, the undo) and, for a passing fix, `checked` (elements it was tested against); a plan's `item` events pass them on with the failure's `reason`. |

**No new dependency.** A node-graph library (React Flow) was weighed: the layout is ORCA's own anyway (columns by
step, rows by item), and dockview stays the one library added before the freeze.

## Checks

- `web/tests/workings.test.mjs` (14): the run log (times, one end, finished runs let go of first and never a live one,
  stopping all, meshes dropped, a trial's pieces kept for the newest three proposals only); a check's trial for the
  viewer (passed or what it hit, the idea sharing it, one still being checked); the server's check times and counts; the tour's #042
  recording (round, three ideas, checks verified at 50 mm and the ceiling hit, stop, rank, options, ghosts) whole and
  part way; the cell's refused trim and route, the curtain wall's trim; a second try on Muse Wonder in its own lane, numbered after the
  first; a second round fed by the first's failure; a stopped run, an error, a recommendation; the girder's recorded
  root cause (three rows ending in one column, the plan checked together) whole and part way; triage counts, groups,
  running calls and flows; Show it built's rounds, gate, judges and retry; ORCA's check (each phase until the next event); a judge without a verdict; ideas named before they are checked.
  `server/tests/test_agent.py` checks `ideas.candidates` against the ideas checked, and every attempt's `seconds`.
- Browser (Chromium, Northbank, local server with the model keys): the check that runs when the demo opens; a live
  proposal on the duct (#1) followed at a readable zoom, the bar grown to 380 px; the cable tray with Activity
  floating over the model and then popped out mid-run (12 steps drawn there, `W` toggling in that window); the off
  switch and back from Panels and layout; Fix together on the three girder clashes (37 s, 18 steps); a triage of
  all 464 clashes (58 s on Muse Spark with open weights off); the cold-water main's ideas shown together. No page
  errors. Oct 30, later: the duct's offset (50 mm) pointed at in Workings showed teal in place and stayed when kept; on
  the cable tray, with the camera zoomed far out, keeping the failed "raise the whole run" check brought the camera to
  it with what it hit lit; Workings off, then Turn it on from the status line; the timeline measured on one line (a
  footer 1,182 and 1,582 px wide: the picker, Replay, bars and clock within 1.5 px of one centre) and wrapped (about
  720 px: each label on its bars, the clock on their centre, "0 s" at the track's edge).
- Browser, Oct 30 (local server on `main` with open weights and Show it built switched on, for the demo video's shots):
  triage of all 464 on Muse Spark Open (86 s, 5 need a fix) drawn with its calls and verdicts; the duct (#1) on Muse
  Spark (29 s, the first idea verified at 50 mm); **Show it built live for the first time**, on the duct's offset (85 s:
  Muse Image's rounds, the gate at F 0.82 and worst tile 0.17, the judges, the picture kept); Look for a better fix on
  the cable tray (#2, 35 s, two Wonder options) and on the cell's fence post N3 (#29, 34-38 s, Wonder's straight move
  ranked first); the cell's HMI stand (#13: 7 Spark ideas, then 10 on Wonder, none verified, 108 s) ending in No
  verified fix. Wonder's steps then sat under the "Muse Spark" lane label; they now have their own lane (checked on
  #29 at Fit: the Muse Wonder lane between Muse Spark and ORCA, with the second try, its round and ideas).

## Not done (later)

- A chat turn as the parent of the runs its tools start (today each run names its origin).
- From the server: the size of the neighbourhood a failed check looked at; the alike groups in triage's `start`; a
  call-start event; which judges Show it built uses, at its start.
- Workings on phones and tablets; comparing two runs; saving or sharing a run.
