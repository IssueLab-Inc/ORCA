# The 3-minute demo video

**Status (Oct 31):** script agreed, every shot tested on a local server at `main` (below: "Shots, as tested"). Two
picture swaps for the new filters are proposed and tested, for the owner to agree (Script, "Proposed"). To record
by the Nov 3 freeze; submit Nov 4 before noon ET ([20](architecture/20-decisions-limits-and-roadmap.md), "The hackathon
frame"). Nov 2: a script records each shot as its own Recordly take ("Before recording", "Recording the takes").
Nov 2, after the owner tested the takes: the cell's beat is #22 with its fix asked for in Chat (in place of #29), `duct`
and `cell-22` switch to four views on camera, Workings stays docked in its bar at full height, and the window is
maximized. Nov 2: a "what's next" line proposed for the last shot (Script, 2:50), matching the README and
[submission.md](submission.md); the live app is kept warm, so a take no longer meets a cold start after a quiet spell.

## What it has to do

The hackathon scores Impact 30%, Use of Meta AI tooling 25%, Technical depth and execution 20%, and Demo 25% (a
working, impressive demo that holds up live, and the quality of the video). The video has to reach people who have
never worked on a building, so it uses plain words (below) and keeps the technical names for the submission text
and the README.

Owner decisions (Oct 30):
- **Theme:** both, as one story. It opens in our world, Theme 1 ("Build for Your World"): a problem IssueLab knows
  firsthand. It turns to the frontier, Theme 2 ("Push the Frontier"): the same loop on a robot cell from a factory floor.
  One idea runs underneath, so the story doesn't split: AI proposes a change to a real design, and geometry proves it
  before anyone sees it. The building keeps most of the time; the cell is the turn, not a second demo.
- **Voice:** a narrator, with captions burned in.
- **Hook:** "Each design works. Together, they don't."
- **No jargon** (BIM, IFC) unless it is needed and explained.

## Plain words

| Instead of | Say |
|---|---|
| BIM, IFC, federated model | "3D designs", "the designers' own files". IFC appears only on screen, on the export button |
| clash | Once: "a clash: two things designed into the same space" |
| clearance | "room to spare" |
| transfer girder, web opening | "the main steel beam", "the hole already in the beam" |
| triage | "sorts" |
| restricted space (ISO 10218-2) | "the robot's safety zone" |
| STEP, CAD, BCF | "the engineers' files", "a report for each team" |
| MCP | "your own AI agent" |
| 400 mm, 50 mm | "40 centimetres", "5 centimetres" in the voice; the app keeps millimetres |
| Workings | "you can watch it work" |

Meta's models keep their names, because that is a quarter of the score: Muse Spark, Muse Spark Open, Muse Wonder and
Muse Image. Each is named once, with what it does.

## Script (about 400 words, about 2:55 with pauses)

| Time | Picture | Narration |
|---|---|---|
| 0:00–0:12 | Three see-through drawings of one floor, one per team, slide together; where a duct passes through a beam, it glows | "Every building is designed by several teams at once: one for the structure, one for air and water, one for the walls. Each design works. Together, they don't." |
| 0:12–0:26 | Northbank opens; the outer walls fade to show the steel and the services | "Where they collide is a clash: two things designed into the same space. We've sat in the meetings where teams spend days finding them, and longer arguing about who moves. Miss one, and the builders find it on site." |
| 0:26–0:40 | The notch: "Checking the models"; 464 appear; Triage on Muse Spark Open, Workings drawing its calls (4×) | "ORCA checks every part against every other: 464 clashes, found in four seconds. Muse Spark Open, an open-weights model, reads them all and finds the five that need a fix." |
| 0:40–1:12 | #1, the duct through the beam; four views (plan, section, elevation beside 3D); Propose fixes; Workings: Muse Spark's round, the idea, ORCA's check turning teal; Before and After in all four | "Take this one: an air duct running straight through the main steel beam. Muse Spark looks at it from three angles, reads the measurements, and proposes a real change to the design. Then ORCA tries it in the model. Is the clash gone? Is there room to spare? Did it hit anything else? You can watch it work. This one passes first time: lift the duct 40 centimetres, through the hole already in the beam, with 5 centimetres to spare." |
| 1:12–1:22 | ORCA's fix beside Northbank's later revision. Caption: "Northbank: a demo building with a later design revision to compare against" | "The building's next design revision made the same move. On all three clashes at this beam, ORCA matched it." |
| 1:22–1:42 | Show it built (4×); Workings: Muse Image's rounds, the pixel check, the judges; the picture with the wipe slider over ORCA's view | "Not everyone reads technical drawings. Muse Image turns ORCA's view into a picture of what will be built, and Muse Wonder judges check it against the design before you see it. We learned Image can't design a fix, because it invents shapes. So it only paints what has already been checked." |
| 1:42–1:54 | Accept this fix; the design changes; Export; the PDF report | "Accept, and the design changes. ORCA hands back the files the designers' own software opens, with a report for each team." |
| 1:54–2:34 | The robot cell in four views; #22, a compressed-air pipe through one of the plant's columns; in Chat, "Find a fix for clash #22."; Muse Spark runs ORCA's fix agent, Workings drawing it; the verified fix in every view, then in the Clash panel (owner, Nov 2: in place of #29) | Draft, for the owner: "We built ORCA for buildings, our world. Then we gave it a robot cell from a factory floor: a different world, the same problem. Here an air pipe runs through one of the plant's columns. Just ask for a fix, in plain words. Muse Spark runs the same loop: it proposes changes, ORCA checks each against the whole cell, and only a fix that passes comes back. In this cell, ORCA found all 17 clashes we had planted." |
| 2:34–2:42 | #13, the operator's screen: No verified fix, and what decides it | "And when nothing passes, ORCA changes nothing, and tells you what's in the way." |
| 2:42–2:50 | A voice command; an AI agent asking ORCA for a fix | "Ask it out loud, or let your own AI agent drive it." |
| 2:50–3:00 | The wordmark settles in the notch; Observe · Resolve · Check · Apply. Proposed (Nov 2, for the owner): for the last 4 s, a line of text under the wordmark, apart from the narration's captions: "Next: fixes that land in the designers' own tools, and checks against photos and scans of the site." | "Each design worked. Now, together, they do. ORCA: AI you can trust to change real designs, because it checks every change." |

### Proposed: where the filters go (Oct 31; the opening's agreed by the owner Nov 2)

Filters, colours and the Properties panel came after the script was agreed ([filters.md](filters.md)). The script is
already at about 2:55, so they go into two shots that exist, as pictures only: no new narration, no added time.

| Slot | Picture today | Proposed picture | Why there |
|---|---|---|---|
| 0:12–0:26 | Northbank opens; the outer walls fade to show the steel and the services | Northbank opens; **Colour by… Discipline** gives each team its own colour; a Hide filter takes the walls and the site away and the views close in on what is left by themselves; a low side angle (or X-ray) so the services show between the floors | The narration has just named three teams; the picture shows them as three colours, then the steel and services the clash story needs |
| 2:42–2:50 | A voice command; an AI agent asking ORCA for a fix | The voice command is **"Isolate the services and colour them by system."**: the services alone, framed, a colour per system with the key, then the agent | "Ask it out loud" becomes something anyone sees at once; it is Muse Voice Transcribe and Muse Spark driving the model, which also counts for Meta tooling |

Optional, picture only: while #1 is picked (0:40–1:12), keep the Properties panel in view, so the duct's breadcrumb
(Northbank › … › Level 02) and its icon bar are on screen. Not narrated.

Honesty: Northbank is a demo building made by IssueLab, and its "next design revision" is a later model of it (the
caption says so). The cell's clashes are called planted.

## How it scores

| Criterion | Where |
|---|---|
| Impact | The firsthand problem; days of finding and arguing down to minutes; matching the later revision; the same loop in a factory; what's next (proposed) |
| Meta tooling | Four Muse models with four jobs, each visible in Workings: Spark Open sorts at scale, Spark reasons from three views and the numbers (and runs the fix agent when asked in Chat), Wonder takes a longer look when Spark finds nothing, Image paints a checked fix under Wonder's judges. The finding: Image can't design, so ORCA never lets it |
| Technical depth | The geometry check after every idea; real edits to the real files; a refusal that explains itself (#13) |
| Demo | Recorded live; waits sped up with a visible "4×" badge, never faked |

## Shots, as tested (Oct 30–31)

Local server at `main` (`2ac7cce`, then the Wonder lane: [workings.md](workings.md)), open weights and Show it built
on, Chromium at 1440×900. Times are wall clock in the browser.

| Shot | Result | Time |
|---|---|---|
| Open Northbank | 464 listed | about 25 s to load; the check 3.7–4.0 s |
| Triage all 464 | Muse Spark Open; "5 need a fix of 464"; Workings draws its calls and verdicts | 86 s |
| #1 duct, Propose fixes | Muse Spark's first idea verified: offset up 400 mm through the girder opening, 50 mm clear | 29 s |
| #1, Show it built | Picture kept: gate F 0.82, worst tile 0.17, both Muse Wonder judges "faithful"; the duct rising with bends through the opening (520 px: show it in the panel, not full screen) | 85 s |
| #2 tray, Propose, then Look for a better fix | Spark: a straight raise refused (it would drag the tray's joints), then an offset up 250 mm (50 mm clear). Wonder: 4 of 5 ideas passed, a shorter offset (0.6 m of tray instead of 0.8 m) | 32 s, 35 s |
| Cell #29 fence post N3, Propose, then Look for a better fix | Spark: west 90 and north 320 mm, 107 mm clear (once after a failed idea, once first time). Wonder: north 360 mm, 124 mm clear, ranked first | 34–45 s, 34–38 s |
| Cell #13 HMI stand, Propose, then Ask Muse Wonder | 7 Spark ideas, 10 Wonder ideas, none verified; No verified fix with what decides it | 82 s, 108 s |
| #16 footing × lift pit wall | No longer a Wonder case: Spark trims the wall end as a model cleanup | 16 s |
| Colour by Discipline, hide Site and Architecture (Oct 31, local, this branch) | Four colours, then MEP and Structure only, framed by itself (applying a filter zooms); the key lists the two on screen. The filters' index arrives with the classes and levels, about 9 s after the model is drawn while ORCA's check runs: wait for **Colour by…** | under 3 s once the index is in |
| "Isolate the services and colour them by system." (typed; the voice goes through chat) | Muse Spark, one tool call: 844 elements isolated, 9 systems, the views framed on them; the reply lists each system with its count | 7 s |

## Before recording

- The Wonder lane ([workings.md](workings.md)) is merged and deployed (Oct 31): check the video shows the Muse Wonder lane.
- On the live app, the owner signs in (owner menu) and switches on, For me: the open-weights model (triage is on Muse
  Spark otherwise) and Show it built (Muse Image; on for everyone since Nov 2, so this only keeps it on if that changes). The owner is exempt from the caps (Muse Wonder 3 an hour per
  visitor), so retakes don't run out.
- Workings stays docked in its bar along the bottom, at the full height ORCA gives it for a run (380 px), never floated
  or in a window of its own (owner, Nov 2); use Fit when a run ends. The script's setups put it there before each take.
- The viewer starts each take on 3D only; `duct` and `cell-22` switch to four views on camera (Views, then Four views).
- The opening's filters are agreed (Nov 2): **Clear all** in Filters before #1, so the clash shots look as tested.
  Filters are kept per set of models in the browser, so clear them between takes too.
- Re-measure every number on the day. A number that comes out differently changes its line, never the other way.

### Recording the takes

Each shot is its own take in Recordly, a desktop screen recorder that draws the cursor where a script clicks and zooms
in on each click. `web/scripts/record-demo.cjs` drives ORCA in Chrome and tells Recordly when to start and stop.
Recordly is not part of ORCA (it is AGPL-3.0, ORCA is MIT): the script loads Recordly's Playwright helper from a
Recordly checkout beside this one (`../Recordly`; elsewhere `--recordly <dir>` or `RECORDLY_DIR`) and copies nothing
from it.

1. **Start Recordly** from its checkout with the control server on, and leave it running (PowerShell):
   `$env:RECORDLY_CONTROL = "1"; npm run dev`. The script never starts it; it stops at once if Recordly isn't running
   or a take was left recording.
2. **Once, sign in:** `node web/scripts/record-demo.cjs --login --url https://dodzikojo--orca-web.us-east.modal.run/#owner`.
   Chrome opens ORCA with the takes' own profile (`%LOCALAPPDATA%\orca-demo-profile`, outside git). Sign in as owner
   (the gear), switch on, For me, the open-weights model and Show it built (Muse Image), then close the window: the
   script prints "Sign in as owner, switch on the open-weights model and Show it built (Muse Image), then close the
   window". The profile keeps both for every take; without Show it built (Muse Image) the `built` shot stops before it
   records, saying so.
3. **The takes**, from the repository root. Live: add `--url https://dodzikojo--orca-web.us-east.modal.run/#owner`
   (without `--url` they go to a local server, `http://localhost:8765`).
   - Every shot: `node web/scripts/record-demo.cjs --url https://dodzikojo--orca-web.us-east.modal.run/#owner`
   - One shot again: add `--only duct`; several: `--only built,accept`
   - The opening without its filter beats: `--only open --no-filters`; without its X-ray: `--no-xray`. (`--filters`
     still runs: it is the default now.)

| Shot | Script | The take | Waits up to |
|---|---|---|---|
| `open` | 0:12–0:26 | Open the Northbank demo, the check, 464 listed; Filters, Colour by… Discipline (the cursor goes to the list and the choice is set there: Chrome's own drop-down is a window of its own, which a window recording doesn't capture), a Hide filter on Site and Architecture, the views closing in; then Visual style: X-ray (the services between the floors) | 180 s to open |
| `triage` | 0:26–0:40 | Triage all, until "N need a fix of 464"; Fit in Workings. RETAKE when the model left clashes unread | 180 s |
| `duct` | 0:40–1:12 | #1 (the camera flies to it in the one 3D view); Views › Four views, so the plan, section and elevation open on it; Propose fixes, the verified options; Fit; Before, After, in all four views. RETAKE when no option verifies | 300 s |
| `revision` | 1:12–1:22 | Northbank with `Northbank-MEP-Rev04.ifc` in place of MEP, from the camera the duct take ended on with a section box round #1, in X-ray: to set beside the duct take's After | 180 s to open |
| `built` | 1:22–1:42 | Show it built on #1's first option, the picture; Fit; the wipe slider dragged across | 180 s |
| `accept` | 1:42–1:54 | Accept this fix; Export (the IFC saved); Menu › Report, then (3 s on, its own zoom) Build the report, Download (the PDF saved) | 300 s |
| `cell-22` | 1:54–2:34 | Starts with #22's row on screen (the list filtered to it before the take when it isn't); Views › Four views; #22; Chat: types "Find a fix for clash #22.", Send; Muse Spark runs ORCA's fix agent (its `propose_fixes` tool) while Workings draws the run; then the Clash panel with the verified fix (counted once ORCA has played the run's ideas, after the chat's answer). RETAKE when the chat doesn't run the fix agent on #22 or it verifies nothing | 300 s |
| `cell-13` | 2:34–2:42 | #13, Propose fixes, then Ask Muse Wonder (as tested; kept, owner Nov 2). RETAKE when an option verifies or Wonder isn't offered | 300 s each |
| `voice` | 2:42–2:50 | Chat: types "Isolate the services and colour them by system.", Send, Muse Spark's reply | 180 s |

- **Setups are not recorded.** Before each take the script opens the models when the shot needs them afresh, clears
  Filters (**Clear all**), puts the viewer back on 3D only (the layout is kept in the browser), and docks Activity in
  its bar along the bottom (**Put it back** when it is away, the bar opened when collapsed) with its Workings view
  chosen (turned on if it was off) and the bar at Workings' full height: ORCA's own fit, which grows a short bar to
  380 px when Workings is chosen, or a drag of the bar's top edge when it was sized taller by hand. The opening starts
  from the start page, so when the browser keeps a filter, four views, Workings off or Activity off its bar, its
  setup puts that right in Northbank first. The opening's filters stay for `triage`.
- **Order.** Shots run in the order `open`, `triage`, `duct`, `built`, `accept`, `revision`, `cell-22`, `cell-13`,
  `voice`, whatever order `--only` gives: Northbank, its triage and #1's options carry from `duct` to `accept`, and
  `revision` uses the camera `duct` ended on (kept as the saved view "Demo: ORCA's fix for #1"). A shot run alone sets up
  what it needs, unrecorded: `accept` alone first runs triage and a proposal for #1.
- **What it prints:** each take's `shot`, `videoPath` and `projectPath`, then a summary where each shot is `ok`,
  `RETAKE` (it ran, but what it shows has to be taken again, and why) or `FAILED` (and why); it exits 1 unless every
  shot is `ok`. A failure inside a take still stops the take (its footage is kept) and the next shot goes on. A shot
  whose turn comes while Recordly is still recording a take fails at once, before its setup. Ctrl+C stops the take that
  is recording (or about to start), keeping its footage, then closes Chrome. The exported IFC and the PDF go to
  `%LOCALAPPDATA%\orca-demo-downloads` for the edit (the PDF's pages are not in a take).
- **The live app stays warm** (`min_containers=1`, Nov 2), but its first answer after a redeploy is a cold start: the
  start page is waited for up to 180 s.
- **Zooms:** clicks meant to get their own zoom are at least 3 s apart (Recordly merges clicks under 2.5 s apart into
  one). Only the cursor is drawn: typing shows as the text appearing.
- **The window** is Chrome in app mode, maximized on the primary display (the script prints the page size it got, and
  stops before recording if the window won't maximize), titled "ORCA · AI design coordination"; a Chrome or Edge
  window with ORCA open in a tab is told apart by its exact title. Leave it where the script puts it.
- **Check before the day:** `node web/scripts/record-demo.cjs --dry-run --headless --only open` runs a shot's steps with
  no Recordly and no window, and saves where each take ended as a picture (`orca-demo-dry-run` beside the profile). Use
  it against a local server: on the live app the steps are real (models opened, Muse called).

## Production notes

- Captions burned in (judges often watch muted); light music, none under the key lines.
- One clean take per beat; waits at 4× with a badge (triage, Show it built, Wonder).
- Record the cell's #22 until the chat's run shows a verified fix (the script marks a take without one RETAKE).
