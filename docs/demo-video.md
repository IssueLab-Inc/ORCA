# The 3-minute demo video

**Status (Oct 31):** script agreed, every shot tested on a local server at `main` (below: "Shots, as tested"). Two
picture swaps for the new filters are proposed and tested, for the owner to agree (Script, "Proposed"). To record
by the Nov 3 freeze; submit Nov 4 before noon ET ([20](architecture/20-decisions-limits-and-roadmap.md), "The hackathon
frame").

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
| 0:40–1:12 | #1, the duct through the beam; Propose fixes; Workings: Muse Spark's round, the idea, ORCA's check turning teal; Before and After | "Take this one: an air duct running straight through the main steel beam. Muse Spark looks at it from three angles, reads the measurements, and proposes a real change to the design. Then ORCA tries it in the model. Is the clash gone? Is there room to spare? Did it hit anything else? You can watch it work. This one passes first time: lift the duct 40 centimetres, through the hole already in the beam, with 5 centimetres to spare." |
| 1:12–1:22 | ORCA's fix beside Northbank's later revision. Caption: "Northbank: a demo building with a later design revision to compare against" | "The building's next design revision made the same move. On all three clashes at this beam, ORCA matched it." |
| 1:22–1:42 | Show it built (4×); Workings: Muse Image's rounds, the pixel check, the judges; the picture with the wipe slider over ORCA's view | "Not everyone reads technical drawings. Muse Image turns ORCA's view into a picture of what will be built, and Muse Wonder judges check it against the design before you see it. We learned Image can't design a fix, because it invents shapes. So it only paints what has already been checked." |
| 1:42–1:54 | Accept this fix; the design changes; Export; the PDF report | "Accept, and the design changes. ORCA hands back the files the designers' own software opens, with a report for each team." |
| 1:54–2:34 | The robot cell; #29, a fence post inside the robot's safety zone; Spark's fix; Look for a better fix; the Muse Wonder lane in Workings; Wonder's move ranked first | "We built ORCA for buildings, our world. Then we gave it a robot cell from a factory floor: a different world, the same problem. Here a fence post stands inside the robot's safety zone. Muse Spark finds a fix. Then Muse Wonder, a larger model, takes a longer look at everything Spark tried, and finds a better one: one straight move, with more room to spare. ORCA checks that too, and ranks it first. In this cell, ORCA found all 17 clashes we had planted." |
| 2:34–2:42 | #13, the operator's screen: No verified fix, and what decides it | "And when nothing passes, ORCA changes nothing, and tells you what's in the way." |
| 2:42–2:50 | A voice command; an AI agent asking ORCA for a fix | "Ask it out loud, or let your own AI agent drive it." |
| 2:50–3:00 | The wordmark settles in the notch; Observe · Resolve · Check · Apply | "Each design worked. Now, together, they do. ORCA: AI you can trust to change real designs, because it checks every change." |

### Proposed: where the filters go (Oct 31, for the owner to agree)

Filters, colours and the Properties panel came after the script was agreed ([filters.md](filters.md)). The script is
already at about 2:55, so they go into two shots that exist, as pictures only: no new narration, no added time.

| Slot | Picture today | Proposed picture | Why there |
|---|---|---|---|
| 0:12–0:26 | Northbank opens; the outer walls fade to show the steel and the services | Northbank opens; **Colour by… Discipline** gives each team its own colour; a Hide filter takes the walls and the site away; Zoom to them, from a low side angle (or X-ray) so the services show between the floors | The narration has just named three teams; the picture shows them as three colours, then the steel and services the clash story needs |
| 2:42–2:50 | A voice command; an AI agent asking ORCA for a fix | The voice command is **"Isolate the services and colour them by system."**: the services alone, framed, a colour per system with the key, then the agent | "Ask it out loud" becomes something anyone sees at once; it is Muse Voice Transcribe and Muse Spark driving the model, which also counts for Meta tooling |

Optional, picture only: while #1 is picked (0:40–1:12), keep the Properties panel in view, so the duct's breadcrumb
(Northbank › … › Level 02) and its icon bar are on screen. Not narrated.

If a take of #29 shows a failed Spark idea (it did in one of two runs), add after "Muse Spark finds a fix": "Its first
idea fails, and ORCA says why; the second passes."

Honesty: Northbank is a demo building made by IssueLab, and its "next design revision" is a later model of it (the
caption says so). The cell's clashes are called planted.

## How it scores

| Criterion | Where |
|---|---|
| Impact | The firsthand problem; days of finding and arguing down to minutes; matching the later revision; the same loop in a factory |
| Meta tooling | Four Muse models with four jobs, each visible in Workings: Spark Open sorts at scale, Spark reasons from three views and the numbers, Wonder takes a longer look and beats Spark's fix, Image paints a checked fix under Wonder's judges. The finding: Image can't design, so ORCA never lets it |
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
| Colour by Discipline, hide Site and Architecture, Zoom to them (Oct 31, local, this branch) | Four colours, then MEP and Structure only, framed; the key lists the two on screen. The filters' index arrives with the classes and levels, about 9 s after the model is drawn while ORCA's check runs: wait for **Colour by…** | under 3 s once the index is in |
| "Isolate the services and colour them by system." (typed; the voice goes through chat) | Muse Spark, one tool call: 844 elements isolated, 9 systems, the views framed on them; the reply lists each system with its count | 7 s |

## Before recording

- The Wonder lane ([workings.md](workings.md)) is merged and deployed (Oct 31): check the video shows the Muse Wonder lane.
- On the live app, the owner signs in (owner menu) and switches on, For me: the open-weights model (triage is on Muse
  Spark otherwise) and Show it built (off on the deploy). The owner is exempt from the caps (Muse Wonder 3 an hour per
  visitor), so retakes don't run out.
- Workings is cramped in the default bottom bar. Float Activity or open it in its own window, make it tall, and use Fit
  when a run ends.
- If the filters shots are agreed: **Clear all** in Filters before #1, so the clash shots look as tested. Filters are
  kept per set of models in the browser, so clear them between takes too.
- Re-measure every number on the day. A number that comes out differently changes its line, never the other way.

## Production notes

- Captions burned in (judges often watch muted); light music, none under the key lines.
- One clean take per beat; waits at 4× with a badge (triage, Show it built, Wonder).
- Record the cell's #29 until a take shows Wonder's move ranked first (two of two runs so far).
