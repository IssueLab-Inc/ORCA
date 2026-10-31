# 22 · Build log (Oct 27 – Oct 30)

> Moved verbatim from `CLAUDE.md` ("Status and next steps") on Oct 30, so the agent guide stays short. This is
> history: each entry records what was built, measured and decided at the time, and its numbers (test counts,
> timings) were true then. The topic docs [01](01-product-and-journeys.md)–[21](21-glossary-and-naming.md) describe
> the code as it is now; where they and this log disagree, the code and the topic docs win.
>
> New work adds a short dated entry at the end (what changed, where in the code, how it was checked, any owner
> decision) **and** updates the topic docs it touches (see [README.md](README.md), "Keeping these docs current").

Done: skeleton, federated scene, neighbourhood check, agent loop (tested with a scripted model), API, MCP server,
Northbank spikes 1–4, Modal deploy script (`deploy/modal_app.py`: one container, because scenes live in memory;
proposal caps in `server/sightline/limits.py`). Proposal scores go in `evals/results.csv` (append-only; see
evals/README.md). Historical Oct 27 validation: 66 server tests (`cd server && uv run pytest -q`), web build (`cd web && npm run build`).

Wider fixes (Oct 28): the approved program spans isolated geometry/connection checks, a bounded planner/API/chat
slice and whole-proposal review/acceptance in the viewer. Read `docs/superpowers/specs/2026-10-28-context-fixes.md`,
`docs/superpowers/plans/2026-10-28-context-review-fixes.md` and `docs/superpowers/context-fixes-progress.md` for the
current delivery/verification state. Context offsets support exact plain rectangular/circular profiles on horizontal
straight services, with vertical or lateral detours; compound/sloped routes and hollow, rounded or U profiles are
unsupported. Structural adequacy and service performance require designer review. Exact unchanged authored external
frame defects remain acknowledged review evidence; new geometry or connection violations reject. Earlier test counts
below are historical snapshots, not the current suite size.

Live (Modal app `orca` since Oct 29): https://dodzikojo--orca-web.us-east.modal.run. Deployed Oct 27 (Northbank in `samples/`; a #042
proposal took 121 s, 15 attempts, 3 verified options). Behind the cloud session's proxy the Modal CLI needs
`uv tool install 'modal[api-proxy-support]'`. Triage eval over Navisworks results: `evals/navisworks_triage.py`
(evals/README.md): 6/6 answer key, 129/129 non-physical, 51/55 touches on 317 Northbank results (Muse Spark Open: 6/6,
129/129, 49/55).

Navisworks clash reports (Oct 27): `server/sightline/reports.py` reads the XML (standard flat tags and the
three-view export's grouped tags); the app opens samples from `samples/reports/<name>/` or uploads, lists clashes by
test with their A/B/C images, matches them to the open model (Northbank: 290/317, the rest are Site elements) and
re-measures on selection (now 317/317 with Site). Proposals on a report clash get its images. Muse Spark tool calling works natively on
`api.meta.ai` (OpenAI `tools`, 2 s round trip, streaming): the chat over reports + model is next (plan below).

Local offsets (Oct 27): `server/sightline/edits.py` splits a straight extruded segment (profile upright or on its
side), raises/lowers the middle with 90° bend fittings and short risers (Bends, below), keeps the original GlobalId on the
first piece and re-chains ports; tried in an IfcOpenShell transaction and undone. `edits.passages` finds openings in
the obstacle by ray casting (Northbank's girder openings are cut into its geometry, no IfcOpeningElement). With that
text Muse Spark's first proposal passes on #042/#057/#061 at Rev04's heights (evals/README.md). UI: offset preview,
**Accept this fix** (server applies, browser reloads that file), re-measure.

UX pass (Oct 27): `POST /propose/stream` streams the agent's steps as NDJSON (thinking, ideas, checking, attempt,
result); the UI shows a live status line and an "Agent activity" table. `META_REASONING_EFFORT=low` by default and the
loop stops after the first round with a verified option: a proposal now takes ~17 s (was 60-100 s). Options carry
`before` meshes: Before / After / Both (orange ghost) and a before/after summary, framed on the change. Fixed
clashes are marked in the list (every report entry with the same pair) and the panel; accepted offset pieces stay
with their element on later selections.

Viewer overhaul (Oct 27): modes Shaded / X-ray / Context (within 2.5 m) /
Isolate, with the focus pair drawn as its own meshes over the batched buffers (no copies) and outlined through other
geometry; section box (clipping planes) around the clash; marker + label at the clash point; animated camera; presets
Top/Front/Right/Iso, Fit, Go to clash; per-model visibility; measure (point to point, Δxyz); properties card on single
click (double-click still picks A/B); screenshot; keys 1-4 H F X C I V S E M Esc. Navigation frames the zone where the
two elements meet (overlap or gap + margin, distance from the field of view), runs on every click, and falls back to
the report's clash point; ports are shown by their owning element (`match()` returns `show`).

Chat (Oct 27): `server/sightline/chat.py`, Muse Spark tool loop (≤8 model calls per message) over the Workspace:
report_summary (per class pair: count, worst mm, touching, non-physical), list/get clash, look_at_clash_images (sent
as a user message, tool results are text only), measure, describe/find elements, find_openings, check_move/offset,
propose_fixes (the agent; counts against proposal caps), show_clash and set_view (page actions). `POST /api/chat`
streams NDJSON; sessions in memory. UI: right pane tab "Chat with ORCA"; chat-driven proposals fill the options
panel and the activity table. Gotcha: Chromium's `scrollIntoView` returns a Promise; an effect that returns it
breaks React's cleanup and blanks the panel, so effects use braces.

Plans (Oct 27): `server/sightline/plans.py`. Batch: agent per distinct pair in parallel threads (`agent.resolve(lock=)`:
model calls overlap, geometry trials serialise on `Workspace.lock`, an RLock that every geometry operation takes),
then `verify_together` applies all fixes in one multi-file transaction and checks each against everything incl. the
other fixes. Root causes: hubs = elements with ≥2 real partners (physical, overlap > 1 mm, not fixed), cross-discipline
first, plus geometry hits missing from the report; `build_root_cause` asks Muse (`domain_packs/root_cause.md`) for
cause + strategy (move_hub / fix_partners). Northbank: girder plan with #042/#057/#061 (the last not in the report) at
Rev04 heights, ~45-58 s. Plans cost one proposal per pair (`ProposeLimit.take_many`, all or nothing); a root cause costs one for the cause and is charged for its fixes only if it needs edits (`build_root_cause(charge=)`). Demo caps: 20 proposals per visitor per hour, 300 a day. UI pass: lucide
icons with `data-tip` tooltips, viewer icon rail, Clash / Plan / Chat tabs, multi-select + "Fix n together" bar,
Root causes card.

Insights (Oct 27): `plans.patterns` groups real clashes by class pair + files (≥3 pairs); `triage_patterns` = one
Muse call (`domain_packs/patterns.md`) → by_design (+ clash rule) / modelling_error / real_problem. Root-cause strategy
`as_designed` returns a plan with no edits and `advice`. UI: Insights panel (all root causes, patterns, Explain), a
client-side `reviewed` state (by design / for author) that root causes, patterns and plans exclude like fixes.
Northbank: 11 patterns; bolts/plates, columns/slabs, beams/columns, curtain-wall joints → by design; duplicate braces,
low base plates → modelling error; lift pit walls vs footings → real problem.

Bulk triage (Oct 27): `server/sightline/triage.py`. Sure rules first (non-physical class, touch ≤ 1 mm; no model
call), then one strict-JSON call per clash, 8 workers, same prompt/schema as `evals/navisworks_triage.py`.
`meta_client.triage_model()`: Muse Spark Open on Baseten (`TRIAGE_API_KEY`/`BASETEN_API_KEY`, `TRIAGE_API_BASE_URL`,
`TRIAGE_MODEL`, `TRIAGE_IMAGES`) else Muse Spark; json_schema refused (400/422) → JSON mode with the schema in the
prompt. `triage.Job` is shared per sample report (`sample:<root>`; uploads per id), replays to late subscribers; a run
costs one proposal. `POST /api/reports/{rid}/triage/stream`, `GET /api/reports/{rid}/triage`. UI: Triage card (progress,
verdict filter chips, Set aside / Flag), row tags, reading in the clash panel. Northbank on Muse Spark: 317 in 119 s,
184 by rule, answer key real/high/MEP.

Muse Spark Open (Oct 27): Baseten's name is `meta-models/muse-spark-open` (`/v1/models`); it takes strict json_schema
and images; no reasoning_effort is sent. Eval on all 317 (`evals/runs/2026-10-27-northbank-open-triage/`): 6/6 answer key,
129/129 non-physical, 49/55 touching (Muse Spark 51/55), 0 failures, median 6.1 s vs 10.0 s; agrees with Muse Spark on
299/317, but called the B1 pad footing vs lift pit wall (−471 mm, real) by_design. Deployed with `TRIAGE_API_KEY` in the
`sightline-meta` secret: a live run starts with `"open_weights": true`, 317 in 189 s (184 by rule, median call 7.9 s,
max 33 s; slower end to end than Muse Spark's 119 s because of the tail).

Viewer fixes (Oct 27): a move option frames where the moved element meets the other side (`Viewer.frameFix`), not the
whole run; the wheel zooms to the cursor. When both sides resolve to one element (35 of Northbank's 317: a port and its
own valve, two Navisworks parts of one door) it is drawn purple (`Side = "ab"`) with a note in the clash panel.

The agent drives the viewer (Oct 27): `agent.resolve(trials=True)` (single proposals and chat; not plans, which run
agents in parallel) emits `{"type": "trial", index, kind, moved, delta_m, pieces}` with the candidate in place before
its check, and attempts carry `hit_ids`. `web/src/pilot.ts` plays them at a readable pace (catches up when steps
queue): amber while checking, teal when clear, hits magenta, camera via `frameFix`, slow orbit (`Viewer.orbit`) while
Muse thinks; the result shows once the steps on screen finish. Any camera move or click in the viewer
(`Viewer.onUserCamera`) is a takeover: the pilot clears what it drew and stops, the agent keeps going; the pill's
**Let ORCA drive** resumes from the next idea. Historical validation: 50 server tests.

Start page (Oct 27): the empty viewer shows `About.tsx` (what a clash is, what ORCA does, colour legend, glossary,
"try it" steps; written for people new to BIM) with **Open the Northbank demo**: the sample report first (its list shows
at once), then the default models, now including Site (all 317 report clashes link; 290 without it). The header's
**How it works** opens the same page as a dialog. Side panels resize from their inner edge (remembered per browser).
Until a report or the models are open the app is a landing page (`.app.landing`: no panels or dock; the header carries
the demo button): what happens after the click, measured numbers (15-25 s to a verified fix, 3/3 designer fixes, 317
triaged in 3-4 min), built-with. Keep those numbers true to measured runs if they change.

Demo report trimmed (Oct 27): sample reports drop every clash test involving IfcGeographicElement, IfcSpace or
IfcBuildingElementProxy (`service.SAMPLE_EXCLUDE`, env `SIGHTLINE_SAMPLE_EXCLUDE`; uploads are kept whole). Northbank:
217 clashes in 52 tests (was 317 in 73), all linked; ids are renumbered (#042 is c0053). Triage of the 217 on Muse Spark
Open: 213 s, 99 by rule, 0 errors, #042 real/high. The eval scripts still read the full package (317).

Muse Spark's reasoning (Oct 27): the chat completions API hides it (reasoning tokens counted, text not returned), but
Meta's Responses endpoint streams reasoning summaries (`reasoning: {summary: "auto"}`, strict json_schema and images
work there too). `MetaChatModel.complete_json_reasoning` uses it when someone is watching (`resolve(trials=True)`:
single proposals and chat), emitting `{"type": "reasoning", round, text}`; falls back to chat completions on 400/404/422
and never for other hosts. About 2-3 notes per round, the first after ~3.5 s ("detailed" gave no more). UI: live notes
under Understanding (`Thinking` in App.tsx), the pilot's status line, then folded into "How Muse Spark reasoned".

Clash pictures read by colour (Oct 27): `web/src/clashImage.ts` reads each Navisworks picture in the browser (512 grid,
~8 ms): red A, green B, and where they meet (the red-green blend of a see-through view, or the seam where a solid pair
touches). List and panel thumbnails zoom to that zone (`ClashThumb`, read when scrolled into view); the image dialog has
outlines, the zone in amber, and Zoom to the clash. SAM 3.1 (`sam-3.1` on api.meta.ai, via /v1/responses; output is
special-token text, `meta-sam-parser` decodes it) was tried first: on these flat renders it found nothing from text
prompts and, from point prompts, outlined 52-91% of each element and never the overlap, so colour does this job.
SAM fits site photos and video, not Navisworks renders.

Voice (Oct 27): Chat's mic button records (`web/src/voice.ts`: MediaRecorder, then decoded, mixed to mono and resampled
to 16 kHz WAV in the browser), `POST /api/transcribe` forwards it to Muse Voice Transcribe (`POST /v1/asr/transcribe`,
multipart: `request` JSON {model, audioEncoding "WAV", mode "PUSH_TO_TALK", keywords, languageBias} + `audio`; reply
`transcript`), biased to BIM words and the open report's clash names, and the transcript is sent as a chat message, so
voice drives everything chat can. Caps `SIGHTLINE_VOICE_PER_HOUR/DAY`, 60 s / 3 MB per clip. Checked end to end with a
fake microphone (format accepted, audio duration right); recognition itself is untested here: no speech audio could be
fetched or generated in the cloud session.

Live voice (Oct 29; design in `docs/voice.md`, code `server/sightline/voice_live.py`, `LiveVoice` in `web/src/voice.ts`):
Muse has no text-to-speech, so voice got real-time recognition instead. The mic streams 16 kHz PCM (an AudioWorklet
resamples) over `/api/voice/live`, which relays to `wss://api.meta.ai/v1/asr/realtime` (the key goes in Meta's first
frame, so the browser cannot connect itself). **Hold to talk** is the default: captions in the message box while held,
sent on release (final ~0.3 s after); a quick tap latches. **Hands-free** (toggle, `sightline.voice.handsfree`,
`ENDPOINTING`): each sentence is sent at the pause, queued while ORCA answers. One session = one voice cap use; same
origin only; the owner cookie reaches sockets via `_OwnerContext`; the socket failing falls back to the upload path.
Audio may run 1.5 s ahead of the clock (Meta garbles a 5 s burst, takes 3 s). Speech recognition is now tested with
espeak-ng speech (`apt-get install espeak-ng` works in the cloud session) through the relay and in Chromium with a fake
microphone; keywords turned "supply adequate" into "supply air duct". Status notes sit above the input so the mic
doesn't move. Live on Modal since Oct 29: Modal's edge passes the socket through (espeak speech: first words at 1.5 s,
final 0.5 s after the end; hands-free sentences at each pause; another origin gets 403; the browser flow works on the
live URL). Not yet checked: a human voice on a real microphone.

Export (Oct 27): edits accumulate in the scene's in-memory models (moves, offsets, trims, plans); export writes each
edited discipline file once, with all its edits (a zip when several changed). Only kept fixes mark a file edited:
`IfcScene.translate` no longer does (trials move and move back with it), `Workspace.apply` / `apply_offset` /
`apply_trim` call `mark_edited`. Before, one tried move made export return an "edited" but unchanged file instead of
409. Edits live in memory: a container restart or opening the models again starts clean.

The view follows activity, not the tab (Oct 28): `viewPlan` in App.tsx. A plan (Fix button or chat) takes the view at
once (old clash's highlight and marker cleared, then the plan's elements and fixes); picking a clash, proposing or the
Clash tab gives it back; the Plan tab takes it again. A chat reply that built a plan and then points at a clash only
selects it (`selectClash(c, keepPlan)`), and the list highlight follows the view. Before, a plan started from chat
moved the camera but left the old clash highlighted and the plan undrawn until the Plan tab was opened.

Bends (Oct 28): offsets turn with radiused 90° bend fittings by default, as Rev04 does (`edits.apply_offset(corners=)`,
env `SIGHTLINE_OFFSET_CORNERS=square` for the old square corners). Pieces: straight, bend, riser, bend, middle, bend,
riser, bend, straight (9; 7 when the rise leaves no riser). Bends are IfcDuctFitting / IfcPipeFitting /
IfcCableCarrierFitting / IfcCableFitting, PredefinedType BEND, closed IfcTriangulatedFaceSet (8 facets per 90°), own
placement, storey and systems, two ports each, chained into the run. Radius `edits.bend_radius`: one profile depth,
less when the rise is short (min(depth, (rise - 40 mm)/2): Rev04's 180 mm duct, 100 mm tray, 54 mm pipe exactly); falls
back to square when the bend would fold (inside radius < 5 mm) or the class has no fitting. Agent checks pieces[1:-1];
`_describe` tells Muse the bend footprint. Answer key still 3/3 first try at Rev04 heights with bends.

Joints and trims (Oct 27): `verify.check` also runs collision without touching, because the intersection query misses
some overlaps (two boxes with flush faces: Clash7's transom 30 mm into a mullion came back as a 0 mm gap); depth is then
the boxes' smallest overlap. Third fix kind **trim** (`edits.butt_trim` / `apply_trim`): cut a member's end back to
butt the other's face. `edits.member_axis` finds the long axis, extrusion or rectangle profile (Northbank's transoms are
1.65 m x 120 mm plans extruded 60 mm). A trim may touch its partner and only fails on contacts new or worse than before
(`agent._try_trim`; plans the same). `_describe` says when a clash is at a joint. Replies carry `advice`; the UI shows
it with what blocked the ideas when nothing passes (`NoFix`). Clash7: 86 s and 0/15 before, 13-23 s and a verified trim
first try now. Answer key unchanged (3/3 first try, rows in results.csv). The viewer glows while the pilot drives.

Reports and BCF (Oct 28): `server/sightline/document.py`, header **Report** (`web/src/ReportDoc.tsx`). Scope: one PDF,
one per team or one per model (the user picks). Team per model is guessed from content (class histogram; name only
breaks ties) and confirmed in the dialog. Acting team: whose element a fix changes, else triage's `responsible`, else
structure stays > architecture > site, services move; every team with an element reviews. Real clashes and clashes with
a fix get a page (Navisworks view cropped by colour, original + fix captured in the browser by `Viewer.capture` 1.4 s
after an option is picked and at accept, Muse Spark's explanation marked AI-drafted, review table); model errors in a
table for authors; noise grouped by test. DRAFT until each page has a review from every team involved (reviews:
in-app `ReviewBlock`, name + decision, kept in localStorage per report; no login yet). BCF 2.1 zip: one topic per page,
assigned to the acting team, comments = explanation + reviews, coloured pair and camera. Needs triage done; costs one
proposal. HTML → PDF with WeasyPrint (Modal image apt-installs pango/harfbuzz).

Not a clash (Oct 28): `web/src/noClash.ts` decides when a report clash needs no fix: same element (purple), a
non-physical side (port, space, opening), a touch (|Navisworks| ≤ 1 mm and ORCA measures no overlap), no overlap in
the open model, or triage by_design / non_physical. The clash panel then shows why and **Mark as not a clash**
(a by-design review) in place of Propose fixes and Try a move ("Propose a fix anyway" overrides); list rows get a
muted tag and cannot be ticked for Fix together. An ORCA overlap > 1 mm beats a 0 mm Navisworks touch.

Triage knows what is settled (Oct 28): rule verdicts carry `basis` (non_physical / touch / same_element), an
understanding that starts "Not a clash:" and names the elements, and a `fix_hint` with the clash rule that stops it
coming back. With `scene_id` (stream and GET), `_triage_facts` settles one-element pairs from the open model: no model
call, and `Job.learn` corrects a run that already asked, keeping the model's answer as `model_reading` (corrections go in
before the replayed "done"). The browser overlays the rest (`shownTriage` in App.tsx): a model "real"/"model error"
gives way to Mark as not a clash (`basis: reviewed`) or noClash's geometry (incl. ORCA's no-overlap measure), with
the model's reading kept. Northbank on Muse Spark Open with the models open: 217 in 181 s, 111 settled (50 touch, 49
non-physical, 12 same element), 106 asked.

Guided tour (Oct 28): `web/src/Tour.tsx`, from the landing page (**Take the guided tour**) or the header (**Tour**).
30 steps in 10 acts: the problem, triage (Muse Spark Open), one live fix (#042 duct: propose, pilot, before/after),
"hold on" (the girder has two more), a trim (Clash7 transom, c0051, accepted), root cause via chat ("Why are there so
many clashes on Level 02? Fix the root cause." → girder plan for duct + tray + CW, accepted), patterns (Explain, mark by
design), your standard (Oct 29: Add to requirements on that pattern, open Requirements, L4, Strict with the expected
count, the grid, Use them; targets `data-tour=add-requirement|requirements|req-levels|req-strict|req-grid|req-apply`;
TourState `reqOpen`, `requirements`, `reqRules`; Escape closes the dialog, not the tour), sign-off (review on #042, Report, build), hand-off (PDF, BCF, Export IFC), close (numbers). Each step spotlights
a real control (`data-tour` attributes) and moves on when the app reaches the state (`TourState`); "Show me" clicks it.
Live Muse steps offer **Watch a recorded run** after 45 s (plan 75 s) or on error: real runs recorded on Oct 27 in
`web/public/tour/` (c0053 18 s, c0051 trim 9 s, girder plan 35 s), replayed through the same pilot/plan code and
labelled as recorded; accepting a replayed fix edits the model for real. `plans.root_causes(only=)`: a requested hub
may have one clash left in the report plus geometry hits (the girder after #042 is fixed).

Streams on Modal (Oct 28): Modal's edge zstd-compresses responses for browsers and held NDJSON streams back until a
buffer filled: in the browser, triage sat at 0 for 77-170 s and Muse Spark's reasoning arrived with the result (local
runs were fine: no edge). It ignores `Cache-Control: no-transform`; `app._ndjson` sends every stream with
`Content-Encoding: identity`, which it passes through (first verdicts 0.5-2.5 s, proposal reasoning at ~4.7 s). Test
a stream with `Accept-Encoding: gzip, deflate, br, zstd`, as browsers send.

Triage reasoning (Oct 28): Muse Spark Open streams `reasoning_content` deltas on chat completions, from ~0.6 s, also
with strict json_schema. `MetaChatModel.complete_json_streamed` reads them; `triage_report(reasoning=True)` (the shared
`Job`) emits `{"type": "reasoning", id, text}` every 0.6 s per clash and keeps the whole reasoning on the verdict
(`reasoning`, ≤ 6000 chars). `Job.follow` skips reasoning sent before a subscriber joined. UI: the Triage card's
"Muse Spark Open is reading n now" (newest four clashes, the end of what it is writing, click to open) and "How the
triage model reasoned" in the clash panel. The tour scrolls any target out of view (window or panel) into view once
per element, including controls that appear later.

Report and triage (Oct 28): the browser sends the verdicts it shows (`triage`, without reasoning) with a report
request, and the server uses them over its shared run, which can be gone (restart) or running again (someone pressed
Triage again): that left "Triage the report first" with no way out during the tour. The error now offers Triage all.
Landing (Oct 28): hero = headline, lede, the two buttons side by side and a one-line load note, beside the before/after
picture; "Once it's open" (left / middle / right) is its own three-card row.

Triage and Insights UI (Oct 28): Triage leads the left panel. Before a run: "Step 1 · sort the report", one line on why,
a full-width "Triage all n clashes". Running: two stages, "n settled by rule" (by basis: touch, same element, not physical; no
model) and "Muse Spark Open has read k of m" with its own bar (verdict colours, the unread rest striped), then the live
reading. Done: "n need a fix of N", the bar (a segment per verdict, click to filter), a row per verdict
(name, what it means, count; click to filter; the real row is `data-tour=triage-real`), "Set aside n as noise" /
"Flag n for their authors" (then a done chip), and a footer with time, rule count and model. Insights: header with
counts in its subtitle, a purpose line per part, root causes with chips (clashing, level, across disciplines, not in the
report), patterns as "11× Mechanical fastener with Plate" and one "Explain the n patterns with Muse Spark" button.
Tooltips: `Tooltips` (ui.tsx) draws every `data-tip` in one fixed layer above the page, flips sides when there is no
room and clamps to the window (was CSS ::after, cut off by panel and window edges).

Not a clash, don't fix (Oct 28): c0087 (pad footing C1 vs ground beam grid C, -150 mm) got "trim the pad footing 900 mm"
as a verified option: half the pad's bearing, which geometry cannot judge. `edits.butt_trim` now refuses anything not
slender (`SLENDER = 3`: length at least 3x across, measured off its own mesh), and `_try_trim` marks a trim within one
model `cleanup`; `_joint_text` tells Muse so. UI: "Model cleanup, not a coordination clash" with Mark as not a clash
above such options, a "model cleanup" chip, "Accept this cleanup". Eval `evals/not_a_clash.py` (+ `not_a_clash.csv`):
pad/ground beam, transom/mullion, beam/column: 3/3 by design, 0/3 touch what must stay, 3/3 cleanup only.

Owner settings (Oct 28): `server/sightline/owner.py`. `SIGHTLINE_OWNER_TOKEN` (≥ 24 chars, in the `sightline-meta` Modal
secret; never in git, chat or the browser's scripts). `POST /api/owner/unlock` checks it once (constant time; wrong
tokens capped 5/hour per visitor, 50/day) and sets a signed cookie (HttpOnly, Secure, SameSite=Strict, Path=/api, 30
days, keyed on the token: a new token logs everyone out); `/api/owner/lock` clears it. `_OwnerContext` (ASGI middleware)
marks each request; only then is `X-Sightline-Settings` read (effort, triage_effort, no_caps) into context variables
that `MetaChatModel.effort` uses (role "triage" for the triage model). `owner.spawn` / `owner.submit` carry them into
stream workers and model-call pools. `_take` skips the demo caps for the owner. UI: `Owner.tsx`, a gear in the header
for the owner, or on a page opened with `#owner`; chip "owner · effort …". When GitHub sign-in comes, `cookie_ok`
becomes "signed in as an allowed login"; the rest stays. Historical validation: 79 server tests.

See-through elements (Oct 28): web-ifc's style alpha now reaches the viewer. Each model has a second BatchedMesh,
`glass`, for elements with alpha < 0.99 (a robot's restricted space, mesh guards, glazing), drawn without depth writes with
per-element alpha (`setColorAt` with a Vector4); in focus they get a tinted see-through material. A pick takes the first
solid hit and falls back to glass, so a zone does not swallow clicks on what stands inside it. Demo set 2 is
the demo-models repo's `palletising-cell/` (PC-03: STEP + IFC, Rev A with five planted problems, Rev B fixed). ORCA's
offset (C1), move (C2) and trim (C3) pass on it. (A move of something standing on the floor, the C5 HMI, used to fail
because the check counted the floor contact: fixed Oct 30, "A move keeps what it stands on" below.)

ORCA detection (Oct 28): design in `docs/detection.md`, code `server/sightline/detect.py`; no Navisworks report
needed.
- **Default tests:** every pair of model files, each file against itself (one model alone is named after its file),
  and duplicates. Hard tests use 1 mm.
- **Never a clash:** rules for same element, joined by ports, one assembly (aggregates/nests) and door in its wall
  (`IfcRelFillsElement`). These, and touches, are counted per test, not reported.
- **Engine:**
  - a sort and sweep over `IfcScene.bounds()` (the completeness argument);
  - one triangle tree per run: intersection, then collision without touching;
  - `_Solids`, an exact separating-axis depth for rectangular extrusions, which also catches fully flush overlaps
    that both queries miss;
  - `model-offset` towards the middle when the federation lies over 200 m from the origin (the tree drops overlaps
    there);
  - one result per pair, capped at 5,000 per test (`partial`).
- **Depth:** how far one must move to clear the other. Exact for rectangular solids, else min(intersection figure,
  box separation). The intersection figure alone is wrong both ways: a 0.5 mm touch read 200 mm, a 40 mm rail read
  20 mm. So #057 now reads −100 mm and #061 −77 mm (−400 mm was the old figure).
- **Ids and reruns:**
  - Ids are `s` + a hash of the test and the GlobalId pair, so they are stable.
  - `Workspace.detect` keeps the last run per scene: a rerun marks clashes new or active and lists resolved only
    when both elements were still checked.
  - Views and "not a clash" marks carry over to a rerun.
  - The report has `origin: "sightline"` and `temporary=True` (its own run folder).
  - The clash panel's "Now" uses `detect.measure_pair` for these reports.
- **API:**
  - `GET /api/scenes/{sid}/detect/tests`;
  - `POST /api/scenes/{sid}/detect/stream` (NDJSON: phase, start, test, test_done, done; cap
    `SIGHTLINE_DETECT_PER_HOUR`/`DAY`);
  - `POST /api/reports/{rid}/clashes/{cid}/images` (A/B/C PNGs captured in the browser by `Viewer.captureClash`,
    then used by the agent, triage and the PDF);
  - chat tool `detect_clashes`.
- **UI:**
  - `Detect.tsx`: a setup card when models are open and no report is, and a summary card over a detected report
    (coverage table, resolved/new chips, Detect again);
  - "Find clashes in the open models" in the Clash report menu;
  - "Found by ORCA" / "Now" in the clash panel;
  - chat-run detection adopts its report without remounting the chat (`chatReport`).
- **Evals:** Northbank, 633 clashes in 7-12 s; 117/117 of the sampled real Navisworks overlaps; answer key 3/3
  (Navisworks has no #061). Cell: Rev A 13/13 planted, 0 unexpected; Rev B 0.
- **End to end in the browser:** detect → #061 → views captured → Muse Spark proposed "up 280 mm through the beam
  opening" (Rev04's height) in 44 s → accept → Detect again: 1 resolved, 0 new.
- **Tour and landing:** now on detection (below).

Clash numbers and titles (Oct 28): no "Clash39".
- **Numbers:** every clash has `number`, shown as #N, unique across the whole report (not per test).
  - Navisworks reports number by position, so c0053 is #53. Their own label is kept as `ref` and shown as a small
    reference ("Navisworks Clash1") in the panel and the PDF.
  - Detection numbers are stable across reruns (`state["numbers"]`): a new clash takes the next number, and a
    resolved clash's number is never reused.
- **Names:** `name` is now the plain name from the two elements (`reports.plain_name`: "A × B"). `label` is
  "#N title-or-name".
- **Titles:** `titles.py` with `domain_packs/titles.md`.
  - The triage model (Muse Spark Open) titles every clash from text facts, 40 per call, 8 calls at a time, with
    strict JSON. Northbank's 633 detected clashes take 60 s.
  - `POST /api/reports/{rid}/titles/stream` runs one shared job per report (`_title_jobs`, keyed like triage; cap
    `SIGHTLINE_TITLES_PER_HOUR`/`DAY`). `GET .../titles` returns them.
  - The browser starts titling as soon as any report opens. Titles stream into the list ("Muse is naming n…") and
    are carried to reruns by id.
  - The prompt says "modelled twice" only in a duplicates test. Muse first called Northbank's X-brace diagonals (same
    name, same box, 3 m apart in shape) duplicates. Insights' Oct 27 "duplicate braces → modelling error" is likely
    the same misreading.
- **Everywhere else:**
  - `Report.clash()` accepts "#39" and "39", so chat tools and voice can use numbers; chat refers to "#39 title".
  - Voice keywords are element names and titles, not clash names.
  - PDF and BCF titles use the label.
  - The tour finds its clashes by element pair (below), not by number.
- **Web tests:** `web/tests/app-host.mjs` and `app-replacement.test.mjs` stub App's imports. A new import in App
  needs adding to both lists, or `npm test` fails to resolve it.

Coordination first (Oct 28, owner decision): ORCA's own check is the golden path; Navisworks is secondary.
- **Wording:** "design coordination" for the job and its outputs, "clash" for one geometric item. Landing hero "An AI
  design coordinator for 3D models"; header menu **Coordinate** ("Check the open models" first, then "Or import a
  Navisworks clash report"); Detect card "Coordinate the models"; a run's report "Coordination · N models"; PDF "Design
  coordination report"; chat prompt "design coordination app". Code identifiers stay `clash`/`report`; BCF TopicType
  stays "Clash". Navisworks stays named where it is a fact: an imported clash's reference, the BCF tools list, the
  README's "Works with Navisworks reports", the recorded plan's cause text.
- **Golden path:** "Open the Northbank demo" / "Watch ORCA fix a clash" open the four models and run the check
  (`openDemo` → `runDetect(null, id)`); the golden path then opens the duct × girder clash (#1) and proposes. Measured:
  list at 22 s, Muse's first idea (+400 mm offset through the web opening, Rev04's height) verified at 42 s into the
  proposal, so the landing says "~40 s to a verified fix" (the old 15-25 s was the imported report).
- **Tour:** `TOUR.duct` / `TOUR.joint` are GlobalId pairs; `clashOfPair` in App.tsx finds them in whatever report is
  open (detected: #1 and #15). Step targets may be functions of `TourState` (`duct`/`joint` carry id and number). The
  recorded runs (`web/public/tour/`, recorded on the imported report as c0053/c0051) are fetched by role; the girder
  plan's clash ids are re-pointed by element pair at replay (`replayPlan`), so "not in the report" reflects this report.
- **Triage of a detected run:** 633 clashes, 98 model calls (alike groups read once), 214 s on Muse Spark Open; 13 real
  (answer key 3/3 real, high, MEP; the B1 pad footing vs lift-pit wall; site trees and paving), 491 by design, 128
  model errors. Landing: "7 s to check 1,961 elements", "633 clashes sorted in 3½ min". The clash panel says when a
  verdict was "read once for n alike clashes".

Header, thumbnails, Site (Oct 28):
- **Header:** the name is "ORCA", centred with the logo (`.bar` is a three-column grid:
  `.bar-side`, brand, `.bar-side.end`). No model names or report title in the header; the element count sits after
  Models. Below 1280 px, How it works and Tour drop their text labels (`.lbl`).
- **List thumbnails for detected clashes:** they have no pictures until opened, so `Viewer.thumbClash` draws a small view A
  (JPEG) off screen in one task, as a row scrolls into view (`LazyThumb` in ReportList.tsx; queue in App.tsx, one per
  frame, newest first, paused while a proposal, plan, replay, reload or check runs). `captureClash` and `thumbClash` share
  `Viewer.posed`.
- **Site out of the default check:** tests involving a Site model are listed but off; duplicates cover the building
  models. Northbank: 464 clashes in 1,732 elements, ~4 s; triage 39 calls, 101 s, 5 real (answer key 3/3). Landing and
  tour numbers follow.

Owner and everyone settings (Oct 28, owner decision): the open-weights model costs per hour on Baseten, so it is off
unless switched on. `server/sightline/settings.py` holds settings for everyone (open_weights, effort, triage_effort;
None = environment default: `SIGHTLINE_OPEN_WEIGHTS` "0", `META_REASONING_EFFORT`, `TRIAGE_REASONING_EFFORT`), stored
in the Modal Dict `sightline-settings` (when `MODAL_TASK_ID` is set) else `SIGHTLINE_SETTINGS_FILE` (default
`server/.sightline-settings.json`, gitignored). Precedence: the owner's header > everyone's > environment
(`MetaChatModel.effort`, `settings.open_weights()` → `triage_model()`; off = Muse Spark with a note). Owner-only
`GET/PUT /api/settings`. UI: Owner menu "For me" / "For everyone"; header chip shows the owner's open-weights override.
Tests use a per-test store (`tests/conftest.py`).

Insights, Triage, thumbnails (Oct 28, owner feedback):
- **Copy follows the active model:** `GET /api/models` (`meta_client.triage_model_info`, the same decision
  `triage_model` uses) tells the browser whether titles and triage run on Muse Spark Open or Muse Spark; the Triage
  card, tour and landing say which (`triageOpen`). The landing's 464-in-2-min stat says it was measured on Open.
- **Insights doesn't jump:** patterns are read once per report and show their open clashes from `resolved` (a pattern
  with none left stays in place, dimmed, with a ✓); root causes are re-read but keep their places (`keepPlaces` in
  App.tsx; a hub that drops out stays as a "Done" row). Action columns and the count chip have fixed widths so a
  change never reflows a row. Checked: rows' tops and heights identical before and after marking a pattern.
- **Filter to a pattern or root cause:** the funnel button sets `listFocus` (App.tsx) → ReportList shows only those
  ids with a chip ("Pattern: Beam with Beam · 133 of 133 shown ✕"). One filter at a time: it and the triage filter
  clear each other.
- **Compact Triage:** a chevron collapses the card to the count and the bar (segment tooltips carry verdict, meaning
  and the click; an info icon carries time, rule count and model). Compact by default once a run is done; the choice
  is kept (`sightline.triage.compact`). In compact the red segment is the tour's `triage-real` target.
- **Thumbnails flashed in the viewer:** `thumbClash` renders into the visible canvas (`preserveDrawingBuffer`), and a
  shot taken after the frame's own render showed until the next frame. `Viewer.posed` now renders the restored view
  before returning; the queue draws one thumbnail per 60 ms (setTimeout). Checked by sampling the canvas between frames
  while scrolling: the old build jumped 45 levels of brightness, the new one 0.
- **Patterns are read automatically** once per report and models (`explainPatterns(quiet)` in App.tsx, skipped while
  a proposal, plan or replay runs; a failure leaves the Explain button). Their mark / flag / fix buttons need that
  reading, which is why they seemed missing. Northbank: verdicts ~35 s after the list.
- **A filter gives the list the room:** with a pattern or root cause filter on, Triage goes compact unless opened for
  that filter (`forceCompact`). (Superseded Oct 29 by the Clashes / Insights tabs, below: Insights and the run's
  summary now live in their own tab.)

STEP models (Oct 28, owner decision; design in `docs/step.md`, code `server/sightline/step.py`):
- **Conversion:** STEP → IFC on open (`cadquery-ocp` 8.0 in the same process as IfcOpenShell: checked, no conflict).
  Parts become triangulated elements with name, colour/alpha, pset `ORCA_STEP` (Group, Label, Source); groups
  become IfcGroups, not assemblies; GlobalIds from file hash + label path.
- **Classes:** the titles' model picks each part's class from name and group (`domain_packs/step_classes.md`).
- **Cache:** by file hash (`samples/step-cache` is deployed so the demo's first opening is ~1.5 s, not ~35 s).
- **Fixes:** moves only. `IfcScene.step_run`: parts of the same STEP group that touch move together.
- **Export:** writes `<name>.orca.step` back (`step.export`, component locations), zipped with the IFC.
- **Upload:** `POST /api/models/upload` (IFC/STEP, caps `SIGHTLINE_MODEL_UPLOAD_MAX_MB`,
  `SIGHTLINE_MODEL_UPLOADS_PER_HOUR/DAY`); Models › Upload models.
- **Second demo:** the landing's "A machine cell, from its STEP file" (`cellSample`, `openDemo([cellSample])`).
- **Results (`evals/step_cell.py`):** Rev A 144 parts, classes 144/144, 13/13 planted, 0 unexpected; Rev B 0 planted;
  C2 ladder +150 mm verified and written back. In the browser Muse Spark proposed exactly that move.
- **Modal image:** needs `libgl1` for OCP.

Cell fixes and tour (Oct 28, owner feedback on Fix together for #61/#68: two agents, both failed, a wall of text):
- **Exact STEP bars and rods:** `step._prism` writes plain cylinders and boxes as `IfcExtrudedAreaSolid` (cell: 97
  exact, 47 meshes), so offsets and trims work on STEP parts. Export now replaces changed prototypes and adds new pieces
  (offset middles, risers, bends) to the part's group with its name and colour (`service.step_changes`; docs/step.md).
  Place shapes with `BRepBuilderAPI_Transform`, never `.Moved()` (names and colours are lost on write).
- **One problem, one agent:** `plans.merge_shared` merges Fix-together pairs that share a movable element into one item
  (`others`), and the agent is told every obstacle. A shared fixed element (the girder) is not merged.
- **No trimming guarding for a service:** `_try_trim` refuses to trim a fixed element when the other side can move (the
  first ladder recording cut post W5 down to the tray).
- **Plain-words failures:** `plans.failure_summary`: one line per idea ("up 150 mm: hits …", by name) plus the advice;
  the Plan panel lists them and says "Nothing to accept yet" when nothing verified.
- **Cell tour:** `CELL_STEPS` in Tour.tsx (12 steps), from the landing's **Take the cell tour** or the header's Tour
  when the cell is open (`tourWhich`). Clashes found by part names (`CELL`, `clashOfNames`); recorded runs
  `web/public/tour/cell-ladder.json` and `cell-pipe-plan.json`.
- **Eval:** `evals/step_cell.py`: C1 one job, verified; C2 +150; C3 trim 40 mm; exported air line 7 → 15 parts.

Landing demo cards (Oct 29, owner decision): the hero keeps "Watch ORCA fix a clash" and a "Pick a demo" link; below
it, two equal cards (`DemoCard` in About.tsx: picture, what it is, what it shows, measured chips, Open + Tour; the
`data-tour` demo/cell targets moved with their buttons). The README's "Two demos" table uses the same pictures and
numbers: change both together. Pictures are captured in ORCA's own viewer (not the DemoModels renders, which
predate the event) by `web/scripts/capture-demos.cjs` → `web/public/demos/*.webp`; recapture after visual changes.

Agents over MCP (Oct 29, owner decision; docs/mcp.md):
- **Connect an agent:** a pairing link (`agents.py`: `orca_` token, sha256 kept, 12 h sliding, 24 h max, revocable,
  in memory) ties an MCP client to the visitor's session.
  - The page PUTs its context (scene, report, clash, fixed) and follows `GET /api/links/{token}/events` (NDJSON,
    reconnects every 4 min).
  - Events: the chat's ui events, plus `open_models`, `applied`, `follow_triage`, `capture_request`, `agent_call` /
    `agent_result`.
  - UI: `web/src/Agent.tsx`, the header button and pill. Handled by `onAgentEvent` in App.tsx, which reuses
    `onChatEvent`.
- **The MCP server:** `mcp_server.build(ws | getter, Hooks, local=)`, 28 tools.
  - It reuses `chat.Chat._run` (one tool layer with the chat), plus session, pictures, jobs, apply_fix / apply_plan,
    triage, report and export.
  - Remote at `/mcp`: a Starlette `Route` inserted first, `_McpGate` (401 without a live token, `?key=` → header,
    `Content-Encoding: identity`).
  - Stateless with JSON responses. A new session manager per lifespan (`_mcp_transport`; it runs only once).
  - Stdio: `python -m sightline.mcp_server`, with its own local link.
  - Expected failures are `ToolError`s, so the agent reads why.
  - Long work is a job (`wait_s`, then `get_job`).
- **Caps:** `SIGHTLINE_LINKS_PER_HOUR`/`DAY`, `SIGHTLINE_AGENT_CALLS_PER_HOUR`. Proposals are charged to the link's
  creator, and the owner's links have no caps.
- **Measured (local):** a real `mcp` client plus a browser on the same link ran #58 end to end:
  - show → A/B/C taken by the page in 8 s → capture_view → propose (an offset, verified, 28 s) → apply_fix;
  - the page shows "1 fixed".

  Stdio opened the cell from STEP.
- **Later:** accounts (GitHub sign-in) and saved projects; OAuth on `/mcp` for claude.ai connectors.
- **Time left and resume (Oct 29, owner feedback):**
  - **Time left:** "expires 06:49 PM" had the creation time's clock digits (12 h later), and it never refreshed. The
    dialog now shows time left ("11 h 52 min left", the exact time in a tooltip, "expiring soon" in the last 30 min),
    on the server's clock (`server_time` → `clock_offset`).
  - **Kept current:** from `hello`, each `agent_call` (`expires_at`), and `GET /api/links/{token}` every 60 s. That
    GET does not renew; a context PUT or an agent call does.
  - **Resume:** the session (scene, report, files, fixes, link) is kept in `localStorage` (`sightline.session`), and
    the landing shows "Pick up where you left off" while `GET /api/scenes/{id}` (`Workspace.scene_info`: files,
    STEP names, last detection) answers.
    - `resumeSession` reopens it through `open(files, existing)`, plus `loadReport`, the saved fixes and the
      fixes the link's agent applied while no page was open (`Link.applied`), and reattaches the link.
  - **A closed tab** doesn't stop the agent: `get_session` adds a note naming the page-only tools.
  - **Eviction:** `Workspace.keep` (live links' scenes and reports, `Links.kept`) is evicted last. Modal
    `max_inputs` is 64.
  - **Muse Code:**
    - the dialog's first tab: the settings JSON only (`muse mcp add` does not exist: "unknown muse mcp subcommand",
      owner, Oct 29) (`~/.config/muse/settings.json`, `schema_version` 1, `mcpServers`, `"mode":
      "optional"`, because `required` aborts runs when a link expires);
    - read tools carry `readOnlyHint`, so Muse Code runs them without approval prompts;
    - Muse Code supports OAuth (`muse mcp login`), which fits the later OAuth work.
  - **Token on its own (Oct 29, owner):** the dialog leads with Token (masked, show, copy) and Server rows (`CopyField`
    in Agent.tsx); only the token changes between sessions. The client settings sit under "First time? Set up your
    agent", open until this browser has made a link (`sightline.agent.setup`). Muse Code's tip: `"Bearer ${ORCA_TOKEN}"`
    once, then only the env var changes.
  - **Resume card:** `.about section` (a column, centred) had swallowed the card's row layout, so it is a `div` now.
    - Layout: one row with an icon, the text, then Resume / Start fresh; it stacks below 560 px.
    - Title: the project name from the files' shared prefix (`projectName`: "Northbank"), with chips for models,
      clashes, fixed, and "Agent connected · time left".
    - Start fresh also revokes the saved link.

Coordination requirements (Oct 29, owner decision; design in `docs/requirements.md`, code
`server/sightline/requirements.py`, `web/src/Requirements.tsx`, `web/src/reqFile.ts`):
- **What it is:** an optional `orca-requirements/1` JSON file: a design level (L1 Concept to L5 As-built, industry-neutral,
  RIBA/LOD/product phase only as hints), a strictness (lenient to exacting; covers both flagging and fixing; strict
  fixes cautiously), groups (by team, class, system or file, never GlobalId), a check matrix (hard, clearance, off),
  who moves (edits any/move/none, largest move, trims), by-design class pairs, and guidance for Muse. No file means
  today's behaviour exactly.
- **What it compiles into:** detection tests (`req:a|b`, plus the new `Test.min_size_m`); triage rules (`basis:
  requirement`), the strictness overlay (a low-confidence by-design becomes real under Strict) and prompt lines; and
  `Workspace.fix_settings` (clearance, `Policy`, prompt lines, recommend mode) for proposals, plans and root causes.
  `context_eval` keeps a never-edited group fixed.
- **Muse stays in the loop:** it drafts a file (`POST .../requirements/suggest`, one proposal), reads what no rule
  settles, audits each by-design rule after triage (`triage.audit_rules`; a disputed rule marks its clashes), and
  recommends instead of editing where nothing may be edited (`agent._recommend`). Options carry `meets`.
- **Triage prompt says only what differs from the defaults.** L3 Balanced adds nothing. Measured: "every hard clash
  matters" in the L3 line turned Muse Spark's 12 model errors into 80 on Northbank.
- **Plumbing:**
  - Pages register a file (`POST /api/requirements`, content-addressed) and send `X-Sightline-Requirements` with
    every call; a forgotten id is a 409 `requirements_unknown`, and `api.ts` registers again and retries.
  - Triage jobs are keyed by `model_key` + `rules_key`. A rule change continues from the last run's readings for
    free; another prompt shows the last run as `stale`, with today's rules applied.
  - Agent links carry the page's id.
  - `GET /requirements/scale`, `GET .../requirements/default`, `POST .../requirements/preview` (detection without a
    report, cached; caps `SIGHTLINE_REQUIREMENTS_PER_HOUR`, `SIGHTLINE_PREVIEW_PER_HOUR`).
- **UI:** header **Requirements** (the pill shows "L4 · Strict"). The dialog has level cards, a strictness slider with
  what it sets and the expected count, the grid, who moves, rules with Muse's audit, guidance, Suggest with Muse Spark,
  Download / Upload / Start from the models, and "Use them and check again". Insights has **Add to requirements** on
  by-design patterns. Detect and Triage cards say what they ran under, and a recommendation shows in the clash panel
  and the PDF.
- **Measured (Northbank, Muse Spark):**
  - L3 Balanced 464 = 464 (cell 107 = 107, same pairs); L4 Strict with Muse's draft 830.
  - Muse's L4 Strict draft took 36 to 85 s: structure never edited, MEP 50 mm to structure, six by-design pairs.
  - #1 under Strict: offset +400 mm through the web opening, 50 mm ≥ 40 mm required, within the 400 mm limit.
  - L5: the same change recommended, nothing edited.
  - Add to requirements on "Beam with Column": 102 settled at once.
- **Web tests:** `requirements.test.mjs`; App's new imports are in both stub lists (`setRequirements` is in the api
  stubs).

Small models and a blank project (Oct 29, owner feedback on an uploaded ~100 mm load-cell STEP: a huge clash ring,
framing far out, thumbnails with the part a speck):
- **Viewer distances were building-sized floors** (0.5 m least margin and `2r + 0.5` in `zoneCamera`, 1.5 m in
  `flyToBox`, 2 m in `view`, the marker's 0.3 scale floor, 2.5 m context, 4 m / 1 m section box, 1 m / 0.6 m fallback
  zones, a 10 mm near plane). Now `Viewer.reach(metres, share)` keeps each building value but never more than a share
  of the scene's diagonal (`sceneDiag`, cached per load), and `zoneCamera`'s least margin is also bounded by the pair
  (a quarter of their union, twice the zone). The marker keeps a constant screen size (no floor), the near plane goes
  down to 0.5 mm. `posed` uses `zoneCamera`, so A/B/C pictures and list thumbnails follow.
- **Checked:** a generated 5-part load cell (110 mm, 2-12 mm overlaps; the appmeas.co.uk zip sits behind a Cloudflare
  challenge here) frames the shaft and nut filling the view, thumbnails readable; Northbank #1 and #40 frame as before.
- **Blank project:** the landing hero's **Use your own models** (`onBlank`, `data-tour=blank`) opens the workspace with
  `ProjectStart.tsx` in the stage: a drop zone / Choose files for IFC or STEP (→ `openDemo(files)`: upload, open, check),
  Import a report folder, Back to the demos. `landing` is `!stats && !report && !blank`; Tour hides until something is
  open; on a phone the bottom sheet stays away (`starting`) until something opens.

Next, in order.
1. ✅ Spike 4 passed with images (spikes/README.md). ✅ Opening heights fed as text (`edits.passages`).
2. ✅ Local-offset edit, verified on #042/#057/#061 at Rev04's heights. ✅ Bends. Later: sideways offsets, splitting
   at fittings.
3. ✅ Viewer: context/x-ray modes, section box, measure (above). ✅ A/B/C capture in the browser (detected clashes).
   Still to do: plan view.
4. ✅ Agent loop end to end in the UI, streamed. ✅ Chat panel with tools. Later: expose the report tools on the MCP
   server too.
5. ✅ Bulk triage, live on Muse Spark Open (Baseten). ✅ Voice. ✅ Export IFC. ✅ PDF reports + BCF. ✅ ORCA
   detection (no Navisworks needed). ✅ #N numbers and Muse titles. ✅ Demo, tour and landing on detection. ✅ STEP
   models and the palletising cell (from STEP) as the second demo.
6. ✅ Escalating to Muse Wonder (`docs/escalation.md`) and ✅ Show it built (`docs/show-it-built.md`), both below.
   Muse Image cannot design a fix (Oct 29: it redraws the geometry and invents numbers); it only restyles one.
7. Freeze Nov 3, record video; submit Nov 4 before noon ET.

Later (not in the hackathon build): user accounts and saved projects; STEP machines placed inside building models;
offsets and trims on meshed STEP parts.

Phones and tablets (Oct 29, owner decision; design in `docs/mobile.md`, code `web/src/layout.ts`, `Sheet.tsx`,
`AppMenu.tsx`, CSS "Responsive" at the end of `index.css`):
- **Layouts:** above 1100 px the desktop as before (checked box for box against `main` at 1280/1440/1920). 761-1100 px
  a tablet: model + right pane, the clash list a drawer (header **Clashes**). 760 px and below a phone: the model full
  width with a bottom sheet (peek / half / full) holding Clashes · Fix · Plan · Chat over App's own panes (re-placed
  by CSS, never remounted), and a peek line with the one next step (Propose fixes, Accept, Next clash). Header actions
  sit in **Menu** (`MenuSheet`); the header's Models / Coordinate bodies are shared render functions, so tests that
  open those popovers still work.
- **The sheet follows activity** (`follow()` in layout.ts, one effect in App.tsx): report or models open → list;
  a clash picked → Fix at half; proposing or planning → peek (watch the pilot); the result → half, scrolled to the
  options. Moving it by hand wins until the next event.
- **Touch** (`(pointer: coarse)`, any width): 44 px targets, tap an element for its card (Set as A / B, then a "now
  pick B" toast), long press picks A then B, the rail becomes **Tools** + Go to clash + Fit on a phone, press and hold
  any `data-tip` control to read it (`data-tip-tap` shows on a tap), popovers open as bottom sheets, dialogs go full
  screen with a pinned title, the requirements matrix and tables stack, the lightbox swipes, hints say tap.
- **Tour:** picks the visible copy of a target, `TourActions.reveal` opens the sheet tab / drawer / menu that hides
  it, docks its card above or below on a phone, and says tap.
- **Checked:** Playwright profiles iPhone 13 / SE, Pixel 7, iPad Mini (both ways), desktop: no sideways scroll, no
  unnamed or undersized control on touch profiles, and the golden path by touch (live proposal, accept, Next clash).
- **Web tests:** App's new imports (`./layout`, `./Sheet`, `./AppMenu`, icons `List`, `Menu`) are in both stub lists;
  `tests/layout.test.mjs` covers the breakpoints, snapping and `follow()`.

Insights patterns (Oct 29, owner feedback): each pattern is a card: the count and the pair on one line
(`.pattern-head`), the levels/size line, Muse's verdict and the rule across the card (`.insight-more`), and a foot
with Add to requirements and the buttons (`.pattern-foot`), so the pair's name no longer wraps beside the buttons.

Room for the list (Oct 29, owner feedback: "we can barely see one clash"): the left pane over a report has two tabs
(`ReportList` `view`, `leftView` in App.tsx). **Clashes**: the report title and test count, Triage folded to one
line (before a run its button sits in the head; after, "7 need a fix of 464" and the bar; it opens while running),
the search with its filters on one row, and the list, which scrolls on its own (min 200 px). **Insights**: the impact
line, the run's summary (Coordinate the models, Detect again, coverage) and Insights. Insights no longer narrows to the
filtered row; its filter and tick buttons switch to Clashes. The tour's `reveal` switches the tab on every layout. On a
phone the report title row is hidden and the sheet's status line hides at full height when it has no button.
Measured, list top / clashes in view: desktop 1440x900 from below the fold to 275 px / 14; iPhone 13 at full from 1
row to 6.

Renamed to ORCA (Oct 29, owner decision; was Sightline). Everything people see or get in their files says ORCA: the
app, the PDF and BCF, the MCP server name `orca`, export names `<name>.orca.ifc` / `.orca.step`, the STEP pset
`ORCA_STEP` (`scene.step_source` also reads the old `Sightline_STEP`, so older caches still open), and the Modal app
`orca`. **Internal names kept** (renaming them would break deployed config or saved state): the Python package
`sightline` (`server/sightline`), env vars `SIGHTLINE_*`, the Modal secret `sightline-meta` and Dict
`sightline-settings`, the header `X-Sightline-Settings`, the owner cookie `sightline_owner`, browser storage keys
`sightline.*`, a report's `origin: "sightline"`, and the model convention `Pset_SightlineConstraints`.

Fix kinds in one registry (Oct 29, owner decision; design in `docs/edits.md`): groundwork for reroute, resize and
penetration requests (planned, in that order, in `docs/edits.md`).
- **Registered once per layer:** `agent.TRIES` / `agent.PARAMS` (try an idea), `plans.IN_TRIAL` / `plans.EXTRA_FILES`
  (a plan's joint check), `plans.KEEP` behind `plans.apply` (keep it; the plan, MCP `apply_fix` and the new
  `POST /api/scenes/{sid}/fix/apply` all use it), `requirements.SIZED` / `change_size`, and `web/src/fixKinds.ts`
  (name, edit text, clearance, framing, review). A kind nobody registered is refused ("unknown kind"), never tried as
  a move.
- **Newer kinds** carry `edit` (parameters, `summary`, `key`) and `review` (who must review before building).
- **Ranking:** `agent.TIERS`: plain geometry fixes, then resize, then penetration; a round with only those doesn't
  end the search.
- **Several obstacles:** `Clash.others` (a plan's merged item): placed along the run in Muse's text, and a split run's
  end pieces are checked against all of them (before, only the first). Failed attempts tell Muse where they hit
  (`Attempt.where`).
- **Fixed on the way:** the "largest move" limit measured a lateral offset as 0 mm; it now measures how far it goes.
- **Checked:** answer key 3/3 first try at Rev04 heights (rows in `evals/results.csv`); 399 server tests, 53 web tests.
- **Web tests:** App imports `./fixKinds`; both stub harnesses compile the real module (`compiled("../src/fixKinds.ts")`).

Reroute (Oct 29, owner decision; design in `docs/edits.md`, code `edits.apply_route`, `agent._try_route`): the fourth
kind of fix, for what one offset can't pass.
- **Shape:** `{"kind": "route", "steps": [{from_m, to_m, up_m, side_m}]}`, up to 3 steps on the run's own axes
  (`edits.run_frame`: up square to the run; side = left of its direction, named by compass in Muse's text). Steps that
  share a boundary change straight from one offset to the next; each change is one axis (a round pipe may roll: both
  at once). One step straight up is tried and kept as an offset.
- **Geometry:** 90° bends and risers per change (`bend_radius` on its own jump, the section's size in its own plane;
  square corners for the whole route if any bend would fold). `_build_chain` (moved out of `apply_offset` unchanged)
  chains copies, fittings and ports for both; a one-step route builds exactly the offset's meshes. Slopes up to 15°
  keep their fall; vertical runs and falling drainage are refused; level drainage only steps sideways (`is_gravity`).
- **What Muse reads:** `edits.free_bands` (room beside or above each obstacle, clear of everything along that stretch:
  rays round the profile's outline every 30 mm, a ray inside a solid counts as blocked, only bands reachable from the
  line count), "no side offset clears all of them in one stretch" when only separate detours fit, and for a single
  report clash the movable element's other clashes within 3 m (`Workspace._nearby`, told, never required; never the
  fixed side's partners). Prompt: `construction.md` "route".
- **Everywhere:** `TRIES`/`PARAMS`/`IN_TRIAL`/`KEEP` entries, `Workspace.check_route`/`apply_route`, chat and MCP
  `check_route`; the page needed nothing new (slice 0's `fixKinds.ts` and `/fix/apply`).
- **STEP:** `IfcWall` is now a class STEP parts may take (`step.CLASSES`, `step_classes.md`).
- **Demo case:** the cell's C6 (demo-models repo, Oct 29: plant walls drawn see-through, columns C3/C4, PL-302, ES-2;
  Rev A 159 parts, 16 planted pairs). Only a detour round each column clears.
  - In the browser, a single proposal on #22 (PL-302 × C3) got "Reroute pipe north past C3 and C4" (250 mm round each,
    53 mm clear) in 37 s, accepted through `/fix/apply`.
  - `evals/step_cell.py`: C6 Fix together → one job, a verified route in 31 s; classes 159/159; 16/16 planted.
- **Checked:** answer key still 3/3 first try at Rev04 heights; 418 server tests, 53 web tests; landing and README cell numbers and
  `web/public/demos/cell.webp` updated.

Accept in place (Oct 29, owner decision; `docs/edits.md` "Keeping a fix"): a kept fix no longer reloads its file.
- **Server:** apply replies and the link's `applied` event carry `Workspace.patch` (`scene_id`, `revision_before`,
  `revision`, `meshes` from `edits.meshes(render=True)`: unwelded, normals, style colour and opacity, file); every apply
  reports `changed`. Open, upload and scene-info replies carry `revision`.
- **Page:** `applyToViewer` (App.tsx) patches through `Viewer.patch` → `viewer/patch.ts` when the page is at
  `revision_before` (`sceneRevision` ref), else reloads the changed files as before. Batches keep spare room
  (`patch.ROOM`); `makeRoom` packs, then grows ×2; new pieces take their mesh's colour, else their origin's; a
  see-through piece makes the model's glass batch when it has none.
- **Checked:** Northbank golden path and the cell's route accepted with no file download (headless Chromium); 4 server
  tests (`test_accept_in_place.py`), 3 web tests (`viewer-patch.test.mjs`, real three.js batches). Web test harness:
  `viewer-load.test.mjs` compiles the real `./patch`.

Penetrations (Oct 29, owner decision; design in `docs/edits.md` "Penetration", code `edits.penetration` /
`apply_penetration`, `agent._try_penetration`): the fifth kind of fix, an opening asked for where a straight service
crosses a wall or slab.
- **Hosts:** `IfcWall` / `IfcSlab` with extruded bodies only. Beams, columns, footings, piles, members, doors, windows
  and curtain walls are refused (the girder is never cut); so is a hole the host would not surround by 50 mm.
- **Opening:** the section + clearance + 5 mm all round, rounded up to 10 mm, round or rectangular, square to the
  service, through the host's depth (rays from both faces) and 10 mm proud. Cell C7: Ø130 mm, 220 mm deep.
- **Always a provision for void** in the service's model (`IfcBuildingElementProxy` PROVISIONFORVOID; IFC2X3 by
  ObjectType; `Pset_ProvisionForVoid`; see-through orange). It is never physical (`scene.not_physical`: no box, not
  in `products()`). **The opening** (`IfcOpeningElement` voiding the host) is cut in trials always, and when kept only
  with no requirements or when the host's group may be edited (`requirements.can_cut`); otherwise `cut: false`,
  `blocked_by`, the clash stays open and the page records "Opening requested" (evidence "recommended"; PDF "Opening
  requested"; plans and MCP report `not_cut`).
- **Check:** the service must clear the host by the clearance; elsewhere only contacts new or worse count. Option
  clearance = the opening's gap. Review: structure for slabs and load-bearing walls, else architecture; a fire rating
  adds fire-stopping. Tier 2 (after plain fixes and resize). Under "move only" requirements it is allowed (it asks).
- **Muse is told** the opening a penetration would ask for, who cuts and reviews it, and that a service running out of
  both faces must keep crossing; walls and slabs are no longer described as runs to split.
- **Everywhere:** `TRIES`/`IN_TRIAL`/`EXTRA_FILES`/`KEEP`, `plans.KEEPS_CONTACTS`, chat and MCP `check_penetration`,
  `Workspace.check_penetration` / `apply_penetration`; STEP export cuts the host (`BRepAlgoAPI_Cut`) and adds the
  provision for void to the service's group. The viewer draws the host see-through in the preview and frames the
  provision for void.
- **Checked:** `tests/test_penetration.py` (15, incl. IFC2X3 and the endpoint/plan/patch); answer key still 3/3 first
  try at Rev04 heights; `evals/step_cell.py` C7: Muse offers the opening (36 s), kept and cut, the STEP's wall 2,655
  cm³ smaller with the provision for void in Compressed air; in the browser accepted in place, no file download.

Which hosts take an opening (Oct 29, owner decision; `docs/edits.md` "Which hosts", code `server/sightline/hosts.py`,
`domain_packs/penetrations.md`): beyond walls and slabs, Muse judges which kinds of element can take a hole.
- **Order:** hard rules (`hosts.hard_rule`: columns, doors, windows, curtain walls, piles, footings, stairs, railings,
  lifts, services and equipment, glazing by name or material, see-through proxies, and a **transfer element**: a beam
  or member a column or wall stands on; Northbank's girder, which column B3 stands on) > the requirements'
  `penetrations` rules per group (allowed / review / never, largest size, reviewer; omitted from the file when empty, so
  its id is unchanged) > Muse's reading of each kind of host > the default (walls and slabs only).
- **Muse's reading** (`hosts.read`, triage model, strict JSON, cached by kind for the server's life, read before a
  proposal's first round): verdict, reviewer, fit (annular or fitted gland), limits (hole share of depth, distance from
  ends and edges, middle third), conditions. Standard `Pset_*Common` facts only: a project's own psets (Northbank's
  answer-key pset) never reach it. `Workspace.hosts_model` (none when a test injects the proposal model).
- **The hole** (`hosts.check_hole`) against the limits; numbers on the option card (`hostRows` in fixKinds.ts).
  Fitted openings: service + 1 mm, may touch. Openings in anything but a wall or slab rank after (`agent.tier`).
- **Page:** Requirements dialog "Openings for services"; an opening read by Muse has **Add to requirements**, a rule
  for that kind of host in its group only (`kind` = `hosts.profile` key, `edit.host_kind`), never the whole group. App imports `ClipboardPlus`, `addPenetration`, `hasPenetration`, `hostRows` (stubs updated).
- **Cell C8** (demo-models): the 400 V feed's 32 mm conduit through EP-301's 3 mm gland plate. Rev A 161 parts, Rev B
  185, 17 planted pairs. `step_classes.md` now names conduits (CONDUITSEGMENT); `samples/step-cache` regenerated.
- **Checked:** `tests/test_hosts.py` (12); `evals/penetration_hosts.py` 25/25 on Muse Spark (18 kinds in one call,
  34-41 s); `evals/step_cell.py` C7 and C8 (Ø34 mm fitted gland hole, kept, exported plate cut); answer key 3/3 first try
  at Rev04 heights; 449 server tests, 59 web tests; C8 in the browser accepted in place.
- **Review fixes (Oct 29):** host model resolved per request (60 s timeout), Muse's limits sanitised, narrow gland
  plates still read, keeping an opening re-checks the hole, fitted options claim no clearance.

Resize (Oct 29, owner decision; `docs/edits.md` "Resize", code `edits.resize_size` / `apply_resize`,
`agent._try_resize`): the sixth kind of fix, a flatter section where an obstacle leaves too little depth.
- **Shape:** `{"kind": "resize", "split_m": [a, b], "depth_m", "keep": "bottom" | "top" | "centre"}`; ORCA picks the
  width: a duct keeps its equivalent diameter (Huebscher, to 5 mm, at most 4:1), a tray its cross-section (at least
  50 mm deep). Pipes, round ducts, any profile but a plain `IfcRectangleProfileDef` (hollow, rounded, channel), STEP
  parts, sloped runs and non-finite values refused with the reason.
- **Geometry:** original, transition (`IfcDuctFitting` TRANSITION / `IfcCableCarrierFitting` REDUCER, lofted mesh, faces
  at most 30°), resized middle (its own profile, keep face level), transition, rest; through `_build_chain`, which now
  takes straights with their own profile and transition pieces. The middle and transitions carry the new size (name,
  profile name, copied properties, `ORCA_Resize` pset); a centre-kept resize is sized by half its change (`face_move`).
- **Review** services, performance line in `also_needs`; tier 1. Muse is told the depth that fits over or under the
  obstacle and the width it makes (`_resize_text`). Everywhere: `TRIES`/`PARAMS`/`IN_TRIAL`/`KEEP`, `Workspace.check_resize`
  / `apply_resize`, chat and MCP `check_resize`.
- **Checked:** `tests/test_resize.py` (11, `fixtures.build_resize_fixture`); answer key 3/3 first try at Rev04 heights;
  460 server tests; in the browser on the uploaded fixture Muse's only verified fix was "Flatten duct to 225 mm deep
  under the beam" (710 x 225 mm), accepted in place. No planted demo case.

Bigger uploads (Oct 29, owner decision: target 500 MB; design and measurements in `docs/uploads.md`, `evals/README.md`
"Big models"):
- **Way in:** the page checks the server's cap first (`GET /api/models`: `model_upload_max_mb`; `web/src/uploads.ts`),
  gzips each file over 1 MB (`CompressionStream`, IFC packs about 5x), sends it with XHR (upload progress) to
  `POST /api/models/upload/stream` (NDJSON: received, STEP events, opening, `boxes` done/total, a `tick` every 5 s, done
  or error). The server refuses before reading (411 without Content-Length, 413 over the cap), unpacks `.gz` parts in
  a thread, 1 MiB per gunzip step, capping the unpacked size as it goes and refusing a truncated archive
  (`app._receive_models` / `_unpack`); a 409 `requirements_unknown` re-registers and resends once (`reRegister`). An
  uploaded IFC is drawn from the visitor's own file, not downloaded back.
- **Boxes** (`IfcScene.bounds`): meshes through CGAL (`hybrid-cgal-simple-opencascade`, 1 ms vs 20-30 ms), every
  element through it from 50 MB (`SIGHTLINE_BIG_MODEL_MB`), in batches of 2,000 (one iterator held a 150 MB model's
  shapes: 4.8 GB → 1.4 GB), threads from `sched_getaffinity`, progress callback. Northbank's boxes, order and 464
  detected clashes are identical (checked).
- **Detection's sweep** had no lower bound (quadratic): 500 MB 482 → 18 s; Northbank identical.
- **Holding:** `SIGHTLINE_SCENE_BUDGET_MB` (IFC bytes, Modal 300) besides the count, room made before a new scene is
  read (`Workspace._evict`); mesh-only bodies go through CGAL by one rule (`scene.meshes_only`); wider fixes refused above
  `SIGHTLINE_WIDER_FIX_MAX_MB` (100: they copy the models); exports older than an hour deleted.
- **Measured** (local, 4 CPUs): 150 MB through the page 123 s, 250 MB 194 s, 500 MB 484 s (2.8 GB server peak, 1.4 GB
  JS heap). Cap stays **150 MB** on the demo by the plan's rule (about two minutes); 500 MB is blocked by box time and
  web-ifc drawing on the main thread (next: a Web Worker). `evals/big_models.py`, `big_models_browser.cjs`.
- **Checked:** `tests/test_uploads.py` (7), `web/tests/uploads.test.mjs` (3); 467 server tests, 62 web tests; golden
  path unchanged. App imports `./uploads` (both harnesses compile it).
- **After the reviews of PRs 26-32 (Oct 29):** 491 server tests, 63 web tests; answer key 3/3 first try at Rev04 heights
  (Muse's girder opening refused as a transfer element); `evals/step_cell.py` passes (C1, C2, C6, C7, C8, Rev B 0);
  golden path accepted in place, no file download.

Escalating to Muse Wonder (Oct 29, owner decision; `docs/escalation.md`, code `server/sightline/escalation.py`,
`spend.py`, `agent._try_combined`): a second, longer try on a larger model, for a clash Muse Spark could not fix or to
look for a better fix.
- **Model and money:** `meta_client.escalation_model()` (`META_ESCALATION_MODEL`, default `muse-wonder-1.0`, $4 / $20
  per M tokens, no contributor tier). `MetaChatModel.usage` counts tokens (both endpoints, every final event);
  `PRICES` by id prefix. One day's budget for every Wonder call, `SIGHTLINE_WONDER_MAX_USD_DAY` ($25): a request
  claims its estimate when let through (`spend.claim`, checked and held in one step) and its work takes the claim
  over (`spend.held`). Caps `SIGHTLINE_ESCALATE_PER_HOUR` / `_PER_DAY` plus one proposal, both or neither
  (`ProposeLimit.take_all`). Setting `escalation` off / button / auto (+ `escalation_effort`), owner menu.
- **The brief:** the first try (ideas, why each failed, what it hit by name, fixes found), openings and room past
  the elements it ran into most, every element within 5 m, the kinds from the registry. The last try per scene and
  pair is kept (`Workspace.last_try`, plan items too) and read only while its scene revision and requirements id
  still match: a kept edit or a rule change makes its verified options stale.
- **Combined fixes:** a seventh kind, 1-3 steps (move / offset / route) on different elements, one on A or B, never
  structure (`agent.stays`, by inheritance) and nothing but services besides A and B; tried in one trial, checked
  together, kept all or nothing (`edits.kept_files`), each split run's pieces as its own group (`groups` on
  `/fix/apply`); ranks after one element's fix.
- **Page:** NoFix **Ask Muse Wonder**, **Look for a better fix with Muse Wonder** under verified options, the same on a
  failed Fix-together item; model chips; the pilot names the model; a failed second try puts the first's options
  back. Chat and MCP: `propose_fixes(escalate=true)`.
- **E0** (`evals/escalation.py`): on the 6 of 21 real clashes Spark left unfixed, Spark again 0/6, Spark + brief 3/6,
  Wonder + brief 5/6 ($2.01 in all, ~2 min each). Four of Wonder's are C4 posts lifted off their slab, because a moved
  element's existing embedment counted as a clash (the C5 HMI's floor contact): the move check now keeps what an
  element stands on and refuses a lift off it (Oct 30, below).
  B1 moves a pad footing (structure; no review chip yet). Answer key 3/3 first try at Rev04 heights.
- **Checked:** 520 server tests, 64 web tests; in the browser Northbank #1 got Spark's offset and, on Look for a better
  fix, Wonder's "Shorter offset up 400 mm through girder opening", both verified and chipped.

Show it built (Oct 29, owner decision; `docs/show-it-built.md`, code `server/sightline/built.py`, `web/src/BuiltView.tsx`,
`Viewer.captureBuilt`): Muse Image restyles ORCA's own view of a verified fix as a clean presentation render, checked
against the model before anyone sees it.
- **Capture:** `Viewer.captureBuilt(fix, pair, classOf)` in one task: a cutaway of 12 directions chosen by class costs
  (`GET /api/scenes/{sid}/classes`; slabs/roofs/coverings become the section, zones never drawn), then look, ids and
  normals from one camera. The ids pass swaps the batches' materials (an override material would draw pieces white).
- **Check:** outline from ids + normals; two restyles at once (Responses, reasoning high); pixel gate (coarse edges
  F ≥ 0.55, worst tile ≤ 0.45); two Muse Wonder judges per picture with the ids picture to read the model view by,
  either unfaithful fails it; one more pair told the differences; else "Muse Image couldn't keep to the model here".
  Cached by a hash of the passes and the prompt version (`SIGHTLINE_BUILT_CACHE`, `/api/built/<key>.jpg`).
- **Money and who:** `built_views` (owner menu, For me / For everyone; `SIGHTLINE_BUILT_VIEWS`, default off). $0.62
  held per request against the day's Wonder budget; over it, three Muse Spark judges (the lighter check, named in the
  tooltip) while the pictures still fit. Caps `SIGHTLINE_BUILT_PER_HOUR` / `_PER_DAY`. Never a trim or a cleanup.
- **Page:** **Show it built** on the chosen option and per verified fix in the Plan panel: the stage in words, then
  the picture over ORCA's view with a wipe, **Lines from the model**, the check in a tooltip, the label "Illustration
  by Muse Image from ORCA's model view. The model is the record." and what the cutaway took away. Accept (single,
  plan, replayed) captures the fix as proposed and draws it in the background; the clash panel shows "As it could
  look built". The report dialog waits for those and draws missing ones (at most 10); the PDF's fix page gets the
  third picture or "No built view: …"; the BCF keeps the true capture. Chat `show_it_built`; MCP later.
- **Once, keyed on the fix:** page keys are pair + kind + numbers + edit (titles repeat); a picture being drawn is
  shared (page and server: `built.make` once per key); cache files written whole; a lighter-checked picture is drawn
  again and checked by Wonder when it can be; judges keep their own effort (`meta_client.FIXED_EFFORT`); passes refused from their
  header when oversized.
- **Checked:** `tests/test_built.py` (11), `test_document.py`; in the browser Northbank #1's offset drew in ~70 s
  (outline 0.94, both judges faithful), the cell's C6 route in ~80 s (0.88), wipe and lines work, Accept carried the
  picture to the kept fix, and accept → triage → Report put it on the PDF's fix page as the fourth picture.
- **Web tests:** App imports `./BuiltView` (`BuiltView`, `builtStep`, `cutText`) and the icon `Building2`: both stub
  lists updated. The harness's transform cannot read `for (const [a, b] of …)` in App: use keys instead.
- **After the final review (Oct 30):** pictures frame a combined fix by run and colour each piece by its run
  (`agent._tagged`: `origin`, `part`), leave a penetration's provision for void undrawn (the opening stays open) and
  anything not physical out; a kept fix whose pieces the page can't find is framed by the elements it changed. The
  `escalating` event carries the first try's options (chat keeps them if the second try fails); a plan whose model
  changed since it was checked can't be accepted (`planStale`); the stdio MCP hook respects the off switch; the owner's
  page asks `/api/models` again after a change for everyone; a report draws at most 10 pictures and says so for the
  rest. Known, not fixed: a combined step that moves another team's service doesn't add that team as a reviewer in the
  PDF and BCF; a second try's options aren't de-duplicated against the first's.

A move keeps what it stands on (Oct 30, owner request; `docs/edits.md`, code `verify.supports` / `keep_supports`):
- **Why:** the cell's fence posts move as a run with their M10 anchors cast 70 mm into the slab, so every horizontal move
  hit the slab; Muse Wonder lifted posts 100-200 mm off it to pass (E0). The C5 HMI's floor contact failed the same way.
- **Rule:** for moved elements that are not runs (`IfcFlowSegment` / `IfcFlowFitting`) nor see-through zones
  (`scene.opacity`), what they stand on or sit in (base at a host's top or ≤ 300 mm into it, `verify.stands_on`) is kept
  when no deeper than before (a touch stays a touch); lifted off everything it stood on fails ("standing on nothing"),
  sunk deeper fails, anything new it cuts into is a clash. Never the clash's partner. Clearance is to what is near it.
- **Where:** `agent._try_move` (partners = B and a plan item's others), `plans.verify_together`, and
  `Workspace.verify_move(obstacles=)` (the page's manual move sends B; chat / MCP `check_move(obstacle=)`); without an
  obstacle every contact counts. Combined move steps keep the old rule. Runs are untouched, so the answer key and every
  service move check as before.
- **Checked:** `tests/test_supports.py` (8); `evals/step_cell.py` passes (C1, C2, C3, C6, C7, C8, Rev B 0); Muse Spark
  single proposals now fix C4 first try with plain moves (post N3/N4 350 mm north, 21-25 s, no lifts), where before
  every horizontal move failed; C5 still has no fix (every direction hits a conveyor, tray or filter: real); 540 server
  tests, 64 web tests.

`.env` before every setting (Oct 30, owner request; code `server/sightline/__init__.py`, `limits.env_int` /
`env_float`; docs [15](15-requirements-settings-and-config.md), [10](10-http-api-and-streams.md)):
- **Why:** `app.py` imported its modules before it called `load_env()`, so the settings they read at import
  (`SIGHTLINE_MAX_SCENES`, `SIGHTLINE_SCENE_BUDGET_MB`, `SIGHTLINE_MAX_REPORTS`, `SIGHTLINE_SAMPLE_EXCLUDE`,
  `SIGHTLINE_STEP_MAX_PARTS` / `_MAX_TRIANGLES`, `SIGHTLINE_BIG_MODEL_MB`, `SIGHTLINE_WIDER_FIX_MAX_MB`,
  `SIGHTLINE_BUILT_CACHE`) ignored a value set only in `.env` on local runs. Modal sets real variables, so the deploy
  was unaffected. An empty cap (`SIGHTLINE_PROPOSE_PER_HOUR=`) reached `int("")` and stopped the server at import,
  although `.env.example` said "off when empty or 0"; it also implied every cap is off when unset, but requirements
  files (120 an hour) and previews (60) have defaults of their own.
- **Now:** the package's `__init__.py` calls `meta_client.load_env()`, so `.env` is read on the first import of any
  module (web server, stdio MCP, tests, evals) and before any setting; real environment variables still win. Every
  number setting is read with `limits.env_int` / `env_float`: unset or empty is the default, anything else that is not
  a number still raises. An empty `SIGHTLINE_BUILT_CACHE` is its default (it would have been the working directory).
  `.env.example` says what unset, empty and 0 mean and lists the two caps that default on.
- **Checked:** `tests/test_env_file.py` (3; a fresh interpreter on a copy of the package beside its own `.env`): before
  the change `.env`'s `SIGHTLINE_MAX_SCENES=7` read as 0 and an empty cap stopped the import with `ValueError`. 553
  server tests. Locally, uvicorn started with a `.env` holding empty caps (`/api/models` answered, with the model
  upload size set there); importing the app with the same file gave `SIGHTLINE_MAX_SCENES=1` as the Workspace's
  limit, no proposal limit and requirements files at 120 an hour.

Chat and MCP take their routes' caps; a visitor is the peer (Oct 30, owner request; code `plans.read_patterns`,
`chat.Chat._run`, `mcp_server` `caps` / `Hooks.detect`, `limits.client_id`; docs 09 and 16):
- **Pattern readings:** chat and MCP `find_patterns` made a fresh Muse Spark call every time, uncharged; the route
  charged one proposal and cached per report. Now all three go through `plans.read_patterns`: one proposal for a
  reading not made yet, kept on the Workspace (64), a caller who comes while it is being made waits for it, and
  no patterns cost nothing (the route used to charge one for an empty reading).
- **Detection:** chat and MCP `detect_clashes`, and MCP `open_models` checking on the server, now take one detection
  run (`SIGHTLINE_DETECT_PER_HOUR` / `_PER_DAY`) like `/detect/stream`, charged to the visitor or the link's creator,
  never the owner. Off on Modal, as before.
- **Who a visitor is:** measured with a throwaway Modal app, from outside and from inside Modal: the edge strips any
  client `X-Forwarded-For` (one value, a list, junk, two header lines), sets none, and gives the app the caller's own
  address as the peer, HTTP and WebSocket. `X-Real-IP` and `Forwarded` pass through as the client wrote them. So
  the old "first entry" rule was harmless on Modal (no header ever arrived) but would let a visitor pick their own
  identity behind a proxy that appends. The deploy now sets `SIGHTLINE_TRUST_FORWARDED` 0; any N > 0 takes the N-th
  entry from the right. The live app needs nothing now; its next deploy picks up the setting.
- **Checked:** 559 server tests (9 new: `test_limits.py` 3, `test_chat.py` 3, `test_mcp.py` 2, `test_plans.py` 1;
  the 5 chat and MCP ones fail on the old code, as do the spoofing ones); locally with Muse Spark, a chat asked to check
  the models after the visitor's one detection run got "refused: detection runs used" and said so.

ORCA in every download, and the cell tour on the current cell (Oct 30, owner request; `docs/architecture/14`, `19`, `21`):
- **Downloads:** the report is `orca-report.pdf` (`orca-report-<team or model>.pdf`, zipped as `orca-report.zip`) with
  `orca-issues.bcfzip`; a multi-file export is `<project>-orca.zip` (`app.export_zip_name`; `service.project_name`, the
  page's `projectName` rule: "Northbank-orca.zip", one STEP model "PC-03-Palletising-Cell-RevA-orca.zip", else
  `orca-export.zip`). Temp folders keep `sightline-*`.
- **The PDF names the triage model that ran** (`document.triage_by`): the triage run's `info`, else
  `meta_client.triage_model_info()` (a restart); was always "Muse Spark Open".
- **Cell tour:** 161 parts, eight problems / 17 pairs, "17 of 17"; Accept steps (both tours) say the viewer swaps in the
  changed parts without reloading. The Oct 28 recordings named parts of the 144-part STEP (STEP GlobalIds follow its
  bytes), so they could not be drawn or accepted; re-recorded live on the current STEP (ladder: 120 mm offset first,
  100 mm whole-ladder raise second; pipe plan: a 900 mm route west). Muse ranks a comfortable offset over the
  designers' 150 mm raise, so the ladder copy names the option on screen (`TourState.optionKinds`); act "A move" is
  now "One fix".
- **Recorded-run offer:** a failed or empty live proposal also ends "done", so the offer never showed on an error;
  now it does (`liveMissed`), and a plan that fails to start moves the tour on to the step that offers its recording.
- **Checked:** 552 server tests, 69 web tests (`tour.test.mjs` new); `evals/detection_cell.py` Rev A 17/17, 0
  unexpected (`evals/runs/2026-10-30-cell-detection/`); in headless Chromium the cell tour live (recording) and again
  with the live streams refused: both recordings offered, replayed and accepted in place (one model download, at open),
  all 12 steps; the live export and report downloads carry the new names.

Keeping a fix tries it again (Oct 30, owner request; [07](07-fixes-and-edits.md) "Keeping a fix", code `plans.recheck` /
`plans.apply`, `edits.kept_files`):
- **Why:** `POST .../fix/apply`, `.../plan/apply` and the older `/apply`, `/offset/apply`, `/trim/apply` rebuilt a fix from
  the page's kind and parameters without checking it again, so any client could keep an edit that was never verified
  (an arbitrary move, an offset with any split or height), and a plan refused part way kept the fixes before it.
- **Now:** every keep goes through `plans.apply`: each option is tried again as its proposal tried it (`plans.CANDIDATE`
  back to Muse's parameters, `agent.TRIES` with the clearance, policies and recommend-only `Workspace.fix_settings` sets
  for the clash it names), several are checked together (`verify_together`), then all are kept in one
  `edits.kept_files` (now re-entrant, and restoring the edited marks, revision and history on failure) or none. What
  the trial made is kept: a move's whole run, the trim's end at the joint. A fix that no longer passes is a 409
  (`plans.NotVerified`) with why. Options carry `pair` and `others` (`agent.resolve`); the page sends every kind to
  `/fix/apply` with the clash pair, plans send each item's; the old routes need their partner (`obstacles` / `other`).
- **Checked:** `tests/test_keep_verified.py` (9); existing tests now keep honest fixes (one export test was keeping an
  offset the second model's beam blocked); `web/tests/accept.test.mjs`. On Northbank in the browser, Muse Spark's
  "Offset duct up 400 mm through girder opening" on #1 was re-checked at keep (50 mm, 21 elements) and patched in
  place; tampered options on the same scene (tray up 100 mm, the cold water main not moved, the kept offset sent again,
  no pair) were refused in 0.4-1.0 s with the scene unchanged. The girder root-cause plan (duct +400, tray +250, cold
  water +280 mm and three trims) was kept through `plans.apply` in 7.4 s; the same plan sent again was refused. 559
  server tests, 65 web tests.

Joints (Oct 30, owner decision after a fix moved the cell's PL-302 segment 3 off column C3 and left it apart from its
bend; design in `docs/connections.md`, code `server/sightline/connections.py`): slice 1 of 3 (joints → moves that
carry and stretch → hover highlight).
- **Joints:** connected ports (read live), and for STEP parts (no ports) flow parts of one group meeting face to face:
  a straight segment offers its two caps, anything else its large planar faces; within 2 mm, normals opposed, the face
  centre inside the other's triangle. Ends: "start"/"end" cap or "side" (a branch). Classes: straight / rigid
  (fittings, in-line valves, dampers, meters) / stays (equipment, terminals, filters, structure, non-flow).
- **Runs:** `connections.run` = straight segments joined cap to cap, the element first; a non-flow part keeps
  `connected_run` without flow parts. `scene.connected_run` is unchanged (the wider-fix planner uses it).
- **A move that would pull a joint apart is refused** (`plan_move`, `SIGHTLINE_CONNECTED_MOVES` refuse | carry | off):
  `_try_move` ("cannot keep its joints: …", the joints as hits), combined steps, plans (`joint` hits),
  `Workspace.verify_move` (`reason`) / `apply` (`/apply` 422), chat and MCP `check_move`, the page's manual move ("Not
  tried: …"). Muse reads what each side is joined to (`connections.describe`); `construction.md` says joints stay joined.
- **Measured:** every Northbank MEP segment is joined at an end; answer key 3/3 first try at Rev04 heights (Muse stopped
  proposing whole moves of joined runs); cell #22 gets only routes; the cell's 40 flow parts' joints in 3.8 s.
- **Tests:** `tests/test_connections.py` (`fixtures.build_joints_fixture`: a PL-302 with ports, a tee, a valve, a
  filter; a STEP air line written with OCP and classified by a stand-in); `test_accept_in_place` moves whole runs.

Moves that keep their joints (Oct 30, slice 2 of connections; `docs/connections.md`): `SIGHTLINE_CONNECTED_MOVES` is
`carry` by default.
- **The walk** (`connections.plan_move`): fittings and in-line valves beyond a run go along; a straight segment the move
  runs along (< 0.5 mm across) gets longer or shorter at that end; a rectangular segment covered end-on at its side (a
  ladder riser under its bend) grows that way; any other segment goes along; equipment, terminals, filters,
  structure, KeepFixed, a branch off a segment's side, a piece < 50 mm or > 12 parts along: refused, named.
- **`edits.stretch`** (cap: extrusion depth and start; side: new rectangle profile and position; ports at that face
  shifted without turning; shared bodies refused). `apply_move`, `check_joints` (ports ≤ 2 mm, STEP faces still meet),
  `trial_move` / `check_applied` (moved parts ignore what they're joined to; stretched segments count only contacts new
  or worse than `baseline`).
- **Still kind "move":** `edit` {summary, key, run, carried, stretched, joints}, `preview` = stretched meshes;
  `Workspace.apply(expect=edit)` plans again and refuses a changed key; the page accepts a move with `edit` through
  `/fix/apply`, draws stretched pieces (`Viewer.showOptions`, `captureBuilt`), the manual move previews them. Combined
  steps carry and refuse overlapping steps; `verify_together` reports two items changing one element as a conflict;
  Muse reads per direction what keeps the joints (`describe`).
- **Measured:** cell C2 lifts 4 parts and the riser 150 mm taller on its plate (STEP export too); C6 as a move keeps
  its joints but hits ES-2; #61 in the browser: "move up 100 mm; takes … along; riser 100 mm longer", accepted in place;
  Northbank census `evals/joints.py` (195 of 1,992 dry plans keep their joints, median 16 ms); answer key 3/3. Cell
  tour: ladder copy updated, `web/public/tour/cell-ladder.json` recorded again (its move option carries).
- **Tests:** `tests/test_connected_moves.py` (walk, refusals, tolerance, promotion, tee, stretch, agent, keep with a
  stale key, plans, STEP ladder export), `test_accept_in_place` (a lone move takes its joined end segment along).

See connections (Oct 30, slice 3 of connections; `docs/connections.md`, code `connections.graph`, `web/src/links.ts`,
`Viewer.setLinks`):
- **Graph:** `GET /api/scenes/{sid}/connections`: edges `[a, b, kind, source]` (joint, assembly, hosted, rests_on,
  contact), plus stops, systems, assemblies and names; cached by revision and contacts. Detection now keeps the pairs that only touch
  (run state `contacts`). `Workspace.describe` (card, chat and MCP `describe_element`) gives `links` by kind with
  names, `systems` and `part_of`. Northbank 0.38 s (875 rests on, 650 joints, 26 hosted, 6 contacts).
- **Page:**
  - Alt (Option) + point, or the **Connections** toggle (rail, key L; the phone's Tools sheet), lights what an element
    is linked to, by kind: joined `#2563eb`, rests on / supports green, hosted brown, assembly slate, touches light
    blue. A label names it with counts, and Shift lights the whole run (to equipment) and its assembly.
  - A click or tap with the toggle on does the same and the card lists the links (a name selects and frames it).
  - A carrying move's option shows what it takes along in blue.
  - The layer is hidden in A/B/C pictures, thumbnails and built views.
- **Phone popovers** now render into the body: inside the rail they sat under the bottom sheet.
- **Web tests:** App imports `./links` (both harnesses compile it); `tests/links.test.mjs`, `tests/viewer-links.test.mjs`.

Sign-offs kept per report (Oct 30; code `web/src/signoffs.ts`, `Report.requirements_id`):
- **Why:** review sign-offs were kept in `localStorage` under the report's title, and every detection run is titled
  "Coordination · N models", so one project's or run's reviews showed on another with the same model count. The PDF
  stays DRAFT until each page has a review from every team involved, so those reviews could lift it wrongly.
- **Key:** a detection run's per clash, under its id (`sightline.signoffs:clash:<id>`). The id hashes the test and the
  GlobalId pair, so a rerun, a requirements change (Add to requirements makes a new requirements id) or opening fewer
  of the same models keeps a clash's reviews, and another project's clashes never share them. An imported report's
  under its title and sorted files (`sightline.signoffs:import:<title>:<files>`), since a Navisworks id is a place in
  its file; opening the same report again (a new report id each time) finds them. The server names a run's
  requirements on the report (`requirements_id` in the summary), for the record.
- **Old entries:** a title-keyed one moves over when a report with that title opens, for the clashes that report has
  (a detection run's ids name their elements, so another project's never match), never over a newer review; the rest
  wait for their own report, and the old key goes when it is empty (`migrateTitleKeyed`).
- **Review fixes before merging:** the first version keyed a run by its requirements and files and deleted every
  title-keyed entry on load, so a rule change or a deploy lost sign-offs, and an imported report lost them on reopening.
- **Checked:** `tests/test_detect.py` (a run names its requirements), `web/tests/signoffs.test.mjs` (5: keys, a rerun
  under new rules and with fewer models, junk and no storage, the migration with an imported report and two projects of
  one title, the page); 80 web tests.

About ORCA (Oct 30, owner request; code `web/src/AboutOrca.tsx`, `web/src/aboutRoute.ts`, CSS "About ORCA" in
`index.css`):
- **What:** a full page over the app, in six tabs (Overview, How it works, The fixes, The AI, Under the hood, Proof and
  limits), presenting the architecture map's story for visitors and judges. It replaces the header's "How it works"
  dialog (the old `About` in dialog mode); the landing keeps `About` and gains a "Go deeper" card. Header, phone menu
  and landing open it; `#about` / `#about/<tab>` is its address (pushed on open, so Back closes it).
- **Animations:** the ORCA loop (a dot round Observe, Resolve, Check, Apply), Northbank #1 before and after (the duct
  raised through the web opening), a before/after picture per fix kind, an auto-advancing six-stage pipeline, the
  propose-check-retry loop, flowing architecture links, count-up numbers, sections fading up as they scroll in. All
  CSS/SVG, no new dependency; `prefers-reduced-motion` shows the "after" states, still.
- **Numbers:** only the measured ones the landing and README already use (464 in about 4 s, ~40 s, 3 of 3, 17 of 17,
  161 parts, 25 of 25 hosts, 150 MB in about two minutes). Change them with the landing's.
- **Checked:** `npm run build`, `npm test` (`tests/about.test.mjs`, 5; App's stub lists take `AboutOrca` and compile
  `aboutRoute`); in Chromium at 1440x900 and 390x844 (touch) every tab renders, no console errors, no sideways scroll,
  Escape / Close / Back close it, the tab bar follows the chosen tab, and reduced motion shows the fix pictures' after
  state.

Navigate freely, and drawing views beside 3D (Oct 30; design [docs/views.md](../views.md); code `web/src/viewer/views.ts`,
`cube.ts`, `drawing.ts`, `annotate.ts`, `Viewer.ts`, `web/src/ViewPanes.tsx`, `ViewerToolbar.tsx`, `App.tsx`,
`server/sightline/datums.py`; branch `feature/drawing-views`):
- **Why:** once a clash was picked there was no plain model to move around in, and one view only, where coordinators
  read a clash in plan at its level and in section through it (owner, Oct 29–30).
- **Navigation:** leaving a clash (Esc, one thing at a time, or ✕ on the clash chip; not while ORCA works on it); Fly to
  clash (on: every click on a clash takes every unpinned view there); F frames the selection first; orbit about the
  point under the pointer (`OrbitControls`' target slid along the view ray, about 8 ms a press); a view cube with 26
  directions and Home; orthographic; back and forward; Home and saved views per project; a section box round the clash,
  the selection or what is in view, with grips.
- **Styles and visibility:** Shaded, Consistent colours, Shaded with edges, Hidden line and X-ray (G); with a clash in
  Shaded the rest grey or in its own colours; the selection blue in every view; filters by model, class and level; hide
  and isolate for now (element card, cyan frame and chip). Wireframe left out (three.js cannot draw a `BatchedMesh`
  as wireframe).
- **Drawing views:** Single, Two, Quad (Q); plans, a section, elevations as orthographic cameras with global clip planes;
  paper fills, cut faces filled by stencil parity (grey hatch, red, green, purple, amber where A and B overlap), the
  pair's hidden parts ghosted, linework and a heavy cut outline from normals and depth in one composite shader; grids,
  levels, a revision cloud with `#N`, the other views' marks, title, scale and north. Every clash click sets each
  unpinned view: plan at its storey with the cut through it, section along the run that moves with a far clip 2 m
  beyond the pair, elevation facing the section's way. Headers set view range, presets, far clip and crop; handles
  in other views drag a section's line, ends, far clip and sides, a plan's cut and bottom, a section's crop (Esc
  reverts). A right click in a drawing turns the 3D view there.
- **Server:** `GET /api/scenes/{sid}/datums` (`datums.py`): levels merged across files at world z, grid axes (a sample
  scene with none reads `<prefix>-Grids.ifc` as context, never added to the scene), each element's storey.
- **Captures unchanged:** every capture goes through `fullCanvas` with the user's style, filters, hides, selection and
  projection lifted, and restores the drawings' version so thumbnails redraw nothing.
- **Checked:** in Playwright on Northbank (software GL): A/B/C, thumbnails, `capture()` and Show it built's passes
  byte-identical in Single and Quad and with a style, filters, a hide and orthographic on; redraws in Quad: idle 0,
  orbiting 0 (the plan's 3D camera mark only), a new clash 3; a cut dragged in a section from +3.058 to +3.568 and a
  section line moved in plan; phone shows Single only with no sideways scroll. `server/tests/test_datums.py` (6),
  `web/tests/views.test.mjs` (11), `web/tests/drawing.test.mjs` (4); 95 web tests; `npm run build` and `tsc` clean.
  Frame times on a real GPU are still to measure.

Review of the drawing views (Oct 30; PR review on `feature/drawing-views`; code `web/src/viewer/Viewer.ts`, `drawing.ts`,
`views.ts`, `cube.ts`, `web/src/ViewPanes.tsx`, `App.tsx`):
- **Drawing:** everything but the pair is counted for cut faces (back faces up, front down) instead of parity, so a post
  set in a wall or a car built of overlapping parts fills instead of leaving a paper hole (checked against the parity
  render of Level 01: only those overlaps differ). The redraw key includes the look and up, so an elevation turned
  from its header redraws. The section box cuts Shaded with edges and Hidden line.
- **Panes:** new panes frame the clash or the model, never the IFC origin; the header's Section starts through the
  model's middle; the drawings' own visibility is built on a layout change; annotation canvases are cleared only when
  their size changes (maximise and back kept them blank); the splitter stays within 0.2–0.8 and lets go on a cancelled
  drag, with no text selected; a maximised 3D pane keeps its way back to the layout.
- **State:** the view cube's Home gets its click; plans open on Level 01 once the real levels arrive; two names for one
  floor no longer make a 0 m storey (`views.nextAbove`); Go to the clash is off once the clash is gone; Back is off
  right after opening models; Esc keeps the clash in a clash plan or a wider fix; classes and storeys are read again
  after a kept fix, each request on its own; the menus re-render at most once a frame, with counts and the model's box
  cached.
- **Checked:** 102 web tests (a same-height level, an elevation's key), build and `tsc` clean; in Chromium on
  Northbank: Isolate then Quad shows the whole model in the plan, North elevation redraws, annotations survive
  maximise and back, the splitter stops at 0.8 and stays put after, Home picks nothing, Go to the clash off after
  leaving, Back off after opening, the plan opens on Level 01.
- **Narrow panes (owner feedback, same day):** a drawing's header overflowed its pane at smaller widths (the picker
  squeezed to nothing, maximise outside the header). It now folds (range words, then pin / go / fit into the range
  menu) and the picker shrinks last; the title block and scale bar stack when they would meet. Checked in Chromium in
  Quad at 1600, 1366 and 1180 px: no control outside its header in any pane.

Drawing views after the live smoke test (Oct 30; owner's smoke test of the deploy; code `web/src/viewer/drawing.ts`,
`Viewer.ts`, `annotate.ts`, `web/src/ui.tsx`, `App.tsx`):
- **The viewer went blank** (a lost WebGL context, the owner's screenshot: every WebGL picture gone, the 2D layers
  left): each drawing pane's targets were 4× multisampled, about 90 MB a pane at 2× pixels on a large screen. Drawings
  now have no multisampling (they differ from before by a pixel at some edges), a pane hidden by a maximised one gives
  its targets back, and the edge styles' targets go when the style does. A lost context is announced on the stage and
  every pane is drawn again when it comes back (a reload offered after 5 s); captures return nothing meanwhile and the
  thumbnail queue waits, so no black pictures reach the list or the server.
- **Panning a drawing stuttered:** every pointer move redrew it. A pan or zoom now moves the last picture and draws once
  it rests; a view that cuts starts its camera at the cut (nothing above a plan's cut, nothing behind a section line is
  drawn) and the passes that clip at a bottom or far clip stop there; a pane composites only when its picture changes.
- **Blinking:** a resize cleared the canvas after the frame's drawing; the canvas is now resized only when its size
  changes, and drawn again at once.
- **The plan's 3D camera mark changed size** as the orbit point moved to what was under the pointer: it is now a fixed
  size.
- **The page scrolled** with a rail menu open (the Visibility list, the Camera and Views menus on shorter windows):
  menus now stay inside the window, moving up and scrolling inside when taller.
- **Checked** in Chromium on Northbank (software GL): panning a plan, 60 moves, no redraws while it goes on and one at
  rest; ten wheel steps, one redraw after; orbiting the 3D, no drawing redraws or composites; a context lost and
  restored with `WEBGL_lose_context`: the notice, then every pane back with the same content, no black thumbnails;
  A/B/C, thumbnails, `capture()` and Show it built's passes still byte-identical in Single and Quad; the rail menus at
  1600×1000, 1440×800 and 1366×700 leave the page its height; drawings at rest match the merged build in the section,
  elevation and 3D panes (no multisampling aside) and in the plan apart from the camera mark; 102 web tests.
- **Esc closed a menu and left the clash** (found in the live check after the deploy): with a rail or pane menu open,
  Esc now closes only the menu (`Popover` stops the key there, before `App`'s window listener).

Approved identity and motion library (Oct 30, owner request; `assets/brand/orca/`, design in
`docs/brand-assets.md`):
- **Identity:** owner selected direction 05 / ORCA Type: custom geometric wordmark and split-O symbol. Added the
  shared vector master, outlined SVGs, transparent PNGs, icon/favicons, maskable variants, print PDF/EPS, social/video
  graphics, palette tokens, approved concept reference and usage guide for the upcoming redesign.
- **Motion:** Orbit, Breathe and Resolve loading loops, a demonstrative four-phase cycle, Settle and Reveal;
  animated SVG, transparent APNG and GIF previews; dependency-free native elements and React TypeScript wrappers.
  Production phases follow real events, one-shot effects settle, and web motion honours reduced-motion preferences.
- **Repository handoff:** kept outside the served application; locked generator dependencies, one geometry source,
  portable browser selection, ignored intermediate/archive directories, and reproducible build/check commands.
- **Checked:** production web build; 102 web tests; 9 architecture-map tests; strict React wrapper type check;
  actual gallery/native-element/standalone-SVG browser checks (motion, pause, size/speed/theme, accessible labels,
  safe dynamic text, real phase control, one-shot final states, reduced motion, 320/390/768 px and desktop layouts);
  static and motion export validation. The pack is ready for integration in a subsequent application redesign.

Measure in every view, and the rail split (Oct 30; owner request; design [docs/measure.md](../measure.md); code
`web/src/viewer/measure.ts`, `Viewer.ts`, `web/src/MeasurePanel.tsx`, `ViewerToolbar.tsx`, `App.tsx`):
- **Measure everywhere:** M works in the 3D view and in every drawing. In a drawing both points lie on its plane (a
  plan measures on its cut, a section in its plane), with a drawing's ticks at the ends; the 3D view shows every
  measurement. A rubber band with its length runs to the pointer before the second click.
- **Snapping** (on by default; the panel's toggle or N): ends, midpoints and edges of the element under the pointer
  (its feature edges), and in a cut drawing the cut outline, joined into straight runs so a face split in two triangles
  has one midpoint; the elements 10 px round it when that gives nothing. A glyph shows what it found.
- **Several measurements** in the Measure panel (beside the rail; drag its header, fold it): copy one or all (length,
  components, view and both ends in model coordinates), delete one, clear all. The old single 3D measure goes.
- **The rail:** in Two and Quad the 3D view's own tools (modes, style, section box, outlines, connections, Home, camera,
  saved views) move into the 3D pane, folded to its height; go to clash, measure, views, visibility and the screenshot
  stay at the left. Fly to clash moves to the Views menu.
- **Checked** in Chromium on Northbank (software GL), Quad: snaps on a grid of pointer positions (plan: 8 ends, 4
  midpoints, 24 edges; 3D: 5 ends, 3 midpoints, 7 edges); measurements in the plan (on its cut, Δz 0), the 3D view and
  the section; Copy all to the clipboard; delete, Clear all, N, Esc (first point, then the tool), drag and fold; the
  rails in Single, Two, Quad and with the plan maximised, at 1600×1000 and 1366×768 (the 3D group inside its pane each
  time); A/B/C, thumbnails, `capture()` and Show it built's passes still byte-identical; `web/tests/measure.test.mjs`
  (6); 108 web tests.

Panels that dock, collapse, float and pop out (Oct 30; `feature/dockable-panels`; design [docs/panels.md](../panels.md);
code `web/src/dock.tsx`, `web/src/dockLayout.ts`, `web/src/App.tsx`, `web/src/ui.tsx`, `web/src/Tour.tsx`,
`web/src/index.css`, `web/public/popout.html`):
- **Owner decisions:** a real docking library (dockview 8.5.1, MIT, pinned with `overrides`; never its paid package),
  before the freeze, the default layout the classic one, pop-out windows in the first version.
- **How:** each panel's content is drawn into a slot that only moves, so nothing `App` draws remounts; the classic
  layout (phones, tablets, the landing, the Classic switch) places the same slots as `display: contents`, so its CSS is
  unchanged. Side bars keep their tabs on top while open and collapse to a strip; `setTab` shows the panel in the dock;
  a dock tab runs the classic tab handler; the layout is saved per browser with pop-outs put back; the tour brings
  panels home. Keys, tooltips and popovers work in a pop-out window.
- **Found on the way:** a floating panel's opaque scroller culled the WebGL canvas under it (fixed: docked slots draw
  no background); StrictMode disposed the dock's subscriptions (fixed: let go only on a real unmount); dockview's
  `clear()` leaves side bars collapsed (Reset removes them). The blank viewer (a lost WebGL context) was fixed on
  `main` meanwhile (the entry above) and merged in.
- **Checked:** `web/tests/dock.test.mjs` (7); 109 web tests; `npm run build` and `tsc` clean; bundle +93 kB JS and
  +11 kB CSS gzipped. In Playwright on Northbank (software GL): the default layout; float, collapse, reopen, tab
  clicks; Chat popped out (styles, typing, a tooltip, M reaching the page), its window closed and popped out again;
  reload with a popped-out, a floating and a collapsed panel; Reset; Classic; the tour gathering panels; #1 proposed
  with the Clash panel floating, put back mid-run and accepted (1 fixed); tablet and phone unchanged.

Review of the panels (Oct 30; PR review on `feature/dockable-panels`; code `web/src/dock.tsx`, `dockLayout.ts`,
`App.tsx`, `index.css`, `ReportList.tsx`, `Chat.tsx`, `ui.tsx`):
- **Saved layouts:** a floating or pop-out window split into several groups is written as a grid; reading only a group's
  views threw the whole layout away on reload (`windowViews`). After `fromJSON` the model is locked against drops
  again (dockview restores `no-drop-target` as `true`).
- **The dock:** one `components` object (a new one each render re-laid the dock out several times a second while an
  agent worked); the handle and pop-out windows let go on a real unmount, and only the handle this dock published;
  `tab` follows whatever brings Clash, Plan or Chat to the front; the tour reopens closed panels; tab padding inside the
  part that sees clicks (an edge click collapsed the bar); the scroll memory prunes removed scrollers; the badges and
  side widths computed once (`clashBadge`, `planBadge`, `PANE`).
- **Pop-outs:** the clash list scrolls its row in its own document; hands-free voice follows the chat's window.
- **After merging main:** a menu in a dock panel was cut off at the panel's edge; `Popover` keeps it inside the
  window narrowed by whatever clips it (`roomFor`).
- **Checked:** 111 web tests (a split floating and pop-out window, shared widths); in Chromium on Northbank: an edge
  click on the right bar's active tab leaves it at 380 px; after a reload the model's group saves `no-drop-target`;
  Chat closed, the tour opens it again; the Visibility menu fits the Model panel at 1440×800.

Properties of any element (Oct 30; `feature/element-properties`, on top of the panels; code `server/sightline/properties.py`,
`service.py`, `app.py`, `web/src/Properties.tsx`, `App.tsx`, `dock.tsx`, `dockLayout.ts`):
- **What:** a click selects any element, also through a see-through view (a click that meets nothing in focus takes the
  faded element behind); on a desktop the Properties panel floats in where the old card was and can be docked or popped
  out; it shows the card, then type, materials, size, attributes, every property set and quantity set (SI), with a
  filter and click to copy. Classic layout, tablets and phones: the card with All properties.
- **Server:** `GET /api/scenes/{sid}/elements/{gid}/properties`; the demo models' own set shows as "Model data",
  without its scripting note.
- **Also on the panels branch:** the docked page could scroll (dockview parks hidden panels' layers below the dock;
  measured scrollHeight 1750 in a 900 px window, shifted 203 px): the app and dock area now clip.
- **Checked:** `server/tests/test_properties.py` (5), `web/tests/properties.test.mjs` (4); 113 web tests, 115 after the
  panels review merged in; build clean.
  In Playwright on Northbank: #1 in focus (X-ray), a click on the faded furniture behind selects it; the girder reads
  Steel S355, 400 × 12000 × 1000 mm, Model data without its scripting note; the filter; Esc empties the panel; the
  classic card's All properties; the page never scrolls.

The owner's test of the panels (Oct 30; `fix/dock-empty-bars-tooltips`; code `web/src/dock.tsx`, `dockLayout.ts`,
`index.css`; [docs/panels.md](../panels.md)):
- **Empty side bars give their room to the model** (`fitEdges`, dockview's `setEdgeGroupVisible`): a bar whose panels
  all floated, popped out, closed or moved beside the model is hidden; it comes back at its width when a panel docks
  there. A saved layout whose pop-out emptied a bar shows the bar again (`withoutPopouts`).
- **On top:** the dock area is its own stacking layer, so tooltips (200) and dialogs (40) are above dockview's floating
  panels (999 and up); a rail or view header with an open menu rises to 5000 while it is open.
- **Pop out a bar's only panel:** dockview does nothing for it (it won't take an edge group out), so Open in New Window
  never worked for Coordination or Activity. `popOut` floats it first and `returnToBars` puts it back in its bar when the
  window closes. Floated panels step down and left so none covers another's tabs.
- **Checked:** 121 web tests (`dock.test.mjs`: a bar emptied by a pop-out shows again on load); build clean. In
  Chromium on Northbank at 1440×900: Coordination floated, model 750 → 1060 px; all five floated, model 1440 × 850, kept
  after a reload; Clash put back, right bar at 380 px; Coordination, Activity and a lone Clash out and back through the
  button and the menu; Reset; a floating panel's tooltip, a rail tooltip, the Visibility menu and a Quad view's menu
  over floating panels, and the panel on top again once a menu closes.

When the server lets go of the models (Oct 30; code `server/sightline/app.py`, `web/src/api.ts`, `App.tsx`,
`BuiltView.tsx`, `index.css`):
- **Found:** "No built view. Model not loaded. Open it again." under Show it built, and Try again failing the same way.
  Modal's logs: every deploy (v16 16:50, v17 16:56, v19 18:07 UTC) and the 20-minute idle scale-down (17:34) started a
  fresh process, which holds no scenes; the page kept its old scene id, so its next calls (`built/stream`, then
  `fix/apply`, element cards for 17 minutes) answered 404. Not eviction: one to three scenes were open, the cap is 8.
- **Server:** `_scene` and `_report` add `X-Sightline-Gone: scene:<id>` / `report:<id>` to their 404 (`_gone`; only a
  hex id goes back in a header).
- **Page:** `api.ts` `send` hands that to App's handler (`setGoneHandler`, `goneOf`); App shows one notice in place of
  the calls' own errors, drops `fixes` and accepted `evidence`, hides Export, and **Open them again** (`reopenGone`)
  reopens the same samples and runs the same check, or reopens the same sample report; uploads go back to the file
  picker. A failed Show it built offers the reopen instead of Try again (`BuiltView`'s `reopen`). What is gone is kept
  by id (`goneIds`) and the notice derived while rendering: clearing it in an effect let the old report's flag paint
  once (1.4 s in Chromium) when the reopened check's report arrived.
- **Checked:** `test_api.py::test_a_scene_or_report_the_server_let_go_says_so`; `web/tests/gone.test.mjs` (3; each
  breaks when the error line, the fixes, Show it built's reopen or the stale-id guard is left out); 607 server tests,
  124 web tests, build clean. In Chromium on Northbank against a local server restarted mid-session: a clash picked
  after the restart brings the notice naming the models (its report call failed first; the scene probe followed), no
  error line, Export hidden; **Open them again** reloads the models and the check, with no notice or error after.

The ORCA notch, menu and brand in the app (Oct 30; code `web/src/Brand.tsx`, `App.tsx`, `AppMenu.tsx`, `ViewPanes.tsx`,
`viewer/Viewer.ts`, `index.css`, `web/index.html`, `web/public/brand/`, `server/sightline/document.py`):
- **Header:** the desktop's header bar is gone; the panels and the model reach the top of the window. The wordmark
  (20 px) hangs from the model's top edge in a notch, and clicking it opens About ORCA. The model's top right corner
  holds the pills, Export and **Menu**, which opens `MenuSheet` (the phone's panel) on every layout, with Panels and
  layout on a desktop. Phones and tablets keep their bar with the wordmark or the app icon. Mockups were agreed first.
- **Progress:** the notch grows while ORCA works (`notchStatus`: opening models with one bar segment per model, the
  check, triage, proposing, a plan, a wider fix). While the first models open, `LoadCard` lists the real steps:
  `open()` records the server's answer, each downloaded file and each model drawn (`Viewer.load`'s new `onDrawn`
  callback, which yields so the count paints). Every `.spinner` is the split-O. A kept fix (`markFixed`) shows a toast
  where the mark settles once.
- **Brand:** navy accent and ink text from the kit's tokens; the adaptive favicon, ICO, Apple, Android and maskable
  icons, manifest and `og.png`; a boot splash with the Reveal letters in `index.html`; the PDF cover's lockup.
- **Tests:** `app-host.mjs` opens Models and Coordinate through the menu (`menu()`), and both stub lists name `./Brand`.
- **Checked:** 124 web tests, build clean; server tests below. In Chromium at 1440×900 on Northbank: landing,
  loading card (opened 4.7 s, 4 of 4 downloaded 5.1 MB, 1,961 elements drawn), working notch ("Checking the models")
  clear of Export, loaded model, the menu, a selected clash with its chip under the notch, and the PDF cover rendered
  with WeasyPrint.

A machines pack and a persona per domain (Oct 30; code `server/sightline/domains.py`, `domain_packs/machines.md`, the six
shared prompts, `service.py`, `plans.py`, `chat.py`, `triage.py`, `document.py`, `app.py`):
- **Why:** every prompt said "senior BIM coordinator", so the palletising cell was triaged, fixed, chatted about and
  reported on as a building.
- **What:** `domains.of(ws, scene_id)` reads a scene opened wholly from STEP as `machines`, everything else as
  `construction`. The fix agent reads `machines.md` (a mechanical integration engineer's rules for static coordination:
  anchored frames and robot bases stay, guarding and safety zones stay intact, maintenance access, conveyor lines; never
  a claim about robot motion), with construction's fix kinds and output contract word for word. Chat, triage, report,
  report summary, patterns and root cause fill `{role}` per domain; construction's text is byte-identical.
- **Checked:** `test_domains.py` (11); 618 server tests; `evals/step_cell.py` passes on the real models (17 of 17
  planted pairs, C1, C2, C3, C6, C7, C8, Rev B 0 planted; `evals/runs/2026-10-30-cell-step-machines/`).

Team names typed, titles and the rule audit by domain (Oct 30; code `domains.py`, `titles.py`, `triage.py`,
`document.py`, `app.py`, `domain_packs/titles.md`, `triage.md`, `report.md`, `web/src/ReportDoc.tsx`, `api.ts`):
- **Teams:** no team name is fixed any more. The report dialog has a text field per model (a cleared field goes back to
  the guess; a list suggests the names in use). `document.TEAMS` and the web's `TEAMS` are gone. ORCA's guess stays a
  building discipline from the model's content, and becomes the model's own name for a machine cell or a model with
  nothing to go on. Triage's `responsible` is held to the guessed teams (`triage.schema_for`); the report translates it
  to the typed name for that model, ranks typed names by their model's guessed discipline (`STAYS_FIRST`), and
  `report.md` names the typed teams.
- **Titles:** `titles.md` says `{meeting}` ("a BIM coordination meeting" or "a machine cell design review"); the page
  sends `?scene_id=` so a cell's titles are written for its domain. **Rule audit:** `triage.AUDIT` takes `{role}`.
- **Checked:** `test_domains.py` (14: titles and audit by domain, guesses never fixed, typed names in the report and its
  prompt); 621 server tests; 124 web tests, build clean. In Chromium on Northbank: the dialog's first model retyped to
  "Acme Mechanical" kept it; the second cleared and left went back to "MEP".

Workings (Oct 30, owner decision; code `web/src/runlog.ts`, `workingsGraph.ts`, `Workings.tsx`, `Activity.tsx`, `App.tsx`,
`dock.tsx`, `pilot.ts`, `index.css`, `server/sightline/agent.py`; design [docs/workings.md](../workings.md)):
- **What:** the Activity panel draws each run as it happens, as lanes (who started it, Muse, ORCA) of steps joined by
  edges: proposals (rounds, ideas, checks, a second try, the stop, the rank, the options), Fix together and root
  causes (a row per item), triage (rules, alike groups, the model's calls, verdicts, dots along the busy edges), Show
  it built (rounds, the pixel gate, judges, the retry) and ORCA's check. Follow, zoom, Fit, a minimap, event labels, a
  timeline to replay a finished run, a picker for the last 12 runs, "in view" on the idea the pilot shows. It is the
  panel's default view beside Steps (`W`), with an off switch in the panel and in Panels and layout; the bottom bar
  grows to 380 px for a run and gives the room back on Steps; phones and tablets keep Steps.
- **How:** a run log written by the trackers that already gather each run (so the chat, an agent over MCP and the
  tour's replays show, each named), pure builders per kind, and a canvas that takes its timers and sizes from the
  window it is in, so it works floated and popped out. The `ideas` event now names its candidates, so a round's ideas
  show together. No new dependency.
- **Checked:** 135 web tests (`workings.test.mjs`, 11, on the tour's recordings and fixtures); `test_agent.py` for
  `ideas.candidates`; build clean. In Chromium on Northbank against a local server: the demo's check; a live proposal
  on #1 (the duct) followed at a readable zoom; the cable tray with Activity floated, then popped out mid-run, `W` in
  that window; off and on again; Fix together on #1–#3 (37 s, 18 steps); triage of all 464 (58 s); the cold-water
  main's ideas shown together. Show it built was not run live (it spends Muse Wonder's budget).
- **Review (PR 58):** `workings.ts` became `workingsGraph.ts` (it and `Workings.tsx` differ only in case, which breaks
  the build on Windows and macOS); a run whose tracker finds newer work has taken over is ended then, and a detection
  that throws or a triage stream that closes without `done` is ended too; titles come from the pair being worked on;
  `stopAll` moved to `open()`; live runs are never let go of; meshes are dropped from logged events and Show it built
  keeps no capture; the bar goes back only from Workings' own height; detection phases last until the next event; a
  judge without a verdict draws; Follow's glide is no longer cut short; a newer run takes over from a picked one;
  effects measure only when the drawing changes; the edit words come from `fixKinds.ts`; `checking.kind` matches
  `ideas.candidates`. And the server now times each check: `attempt` has `seconds` and, for a passing fix, `checked`,
  which a plan's `item` events pass on with the failure's `reason`; Workings shows them. 607 server tests, 136 web
  tests.


Collapsed side bars' strips (Oct 30; owner report; `web/src/index.css`): the active tab's underline crossed the turned
text and the tabs touched (their padding was horizontal only). In a vertical header the tabs now have 12 px above and
below with 4 px between, and the active one is marked on the strip's inner side. Checked in Chromium on Northbank: the
left, right and bottom bars collapsed; web tests and build clean.

Workings in the viewer, rejecting a fix, landing in view (Oct 30; owner requests; `web/src/App.tsx`, `Workings.tsx`,
`workingsGraph.ts`, `runlog.ts`, `Activity.tsx`, `fixKinds.ts`, `api.ts`, `index.css`):
- **A check in the viewer:** pointing at a geometry check (or its idea) in Workings shows that trial in place, teal when
  it passed and amber with its hits lit when not; a click keeps it and takes the camera (and the view from the pilot).
  Trials keep their pieces in the run log for the newest three proposals. [docs/workings.md](../workings.md).
- **Reject:** beside Accept; the option folds away with an optional why and Undo, the next open option is chosen, the
  report stops proposing it, and the next proposal (or second try) sends the rejections as `notes`.
  [docs/edits.md](../edits.md), "Rejecting a fix".
- **Landing in view:** when a proposal's result lands, the Clash panel (its own scroll box, never the page) scrolls to
  Verified options, once per result.
- **Workings is off · Turn it on** in the Activity panel's status line when Workings is switched off.
- **Timeline alignment:** each lane's label is placed on its own bars, the clock sits on the bars' line, the first tick
  starts at the track's edge, and the picker, Replay and speeds line up on the bars while they share its line.
- **Docs:** the gaps found on review: `sightline.workings` and the dock's keys in 05's storage table, the run log in
  03's proposal flow, Panels and layout's place (the Menu) in workings.md and panels.md.
- **Checked:** 139 web tests (two new in `workings.test.mjs`, one in `fix-kinds.test.mjs`); build clean. In Chromium
  on Northbank against a local server: the duct's offset shown on hover and kept; the cable tray's failed whole-run
  raise kept from far out (camera to it, hits lit); the duct's only option rejected "because the ceiling void above is
  reserved for sprinklers", the next request carrying it and Muse Spark's understanding repeating it (no other fix in
  8 ideas, 138 s); the panel scrolled to the result; Workings off and on from the status line; the timeline on one line
  (1,182 and 1,582 px) and wrapped (about 720 px). No page errors.

Nothing fixed to one project, domain, demo or vendor (Oct 30; owner decisions: the requirements fully decide, demos get
requirements of their own; code `requirements.py`, `domains.py`, `demos.py` and `demos/*.json`, `scene.py`,
`service.py`, `agent.py`, `connections.py`, `context_eval.py`, `context_planner.py`, `meta_client.py`, `app.py`,
`mcp_server.py`, the prompts, `web/src/aiNames.ts`, `names.ts`, `Requirements.tsx`, `App.tsx` and the panels):
- **The requirements decide:** `Doc.domain` (building or machine) and `Doc.stays` (classes fixed in place, plus groups
  allowed no edits) are new optional fields (older files keep their ids). `IfcScene.stays` replaces `FIXED_CLASSES`,
  `agent.STAYS` and `Element.fixed` everywhere (combined steps, trims, joints, the wider fix, a second try's brief,
  nearby clashes, plan merges), asking `Workspace.requirements_for`: the user's file, else the demo's own, else the
  domain's default classes. Detection and requirements guess teams in the scene's domain. The dialog has "Kind of
  project" and "Fixed in place".
- **Demos in one place:** `demos.py` holds the demo sets, start labels, tours, the demo models' property set and smart
  tags, and each demo's default requirements (`northbank.json`, `palletising-cell.json`, from `default_doc` with the
  domain and classes written out). `GET /api/samples` lists them; the page picks, labels and finds the cell from them,
  and file names lose whatever prefix the set shares (`names.ts`), not "Northbank-".
- **Clearance:** `requirements.DEFAULT_CLEARANCE_M` replaces every 0.025; `Workspace.clearance` gives a check by hand,
  by chat or over MCP, an opening search and the wider fix the pair's required clearance; `report.md` says it.
- **Prompts:** `escalation.md` and `context.md` through `domains.prompt`; no example is a demo's answer any more
  (Rev04's +400 mm duct and split 2.6-4.4 m, the cell's C6 route at 1.75-2.55 / 4.25-5.05 m); per-domain title
  examples; triage's tolerance is the test's; no fixed 2.5 m; "fixed in place" for "structure" as a rule.
- **Settings:** `SIGHTLINE_PUBLIC_URL` (MCP website, set by the deploy), `SIGHTLINE_MODEL_LABELS` / `_PRICES`,
  `META_STREAMS_REASONING`, timeouts and about 20 limits; `GET /api/models` sends each role's model name and the
  panels use it (`aiNames.ts`). Voice keywords come from the domain and the open models, not Northbank.
- **Checked:** 629 server tests (`test_defaults.py`, 8 new), 139 web tests, build clean. Evals on the real models,
  this branch against main: the answer key with images, 3/3 first try at Rev04 heights (+0.40, +0.25, +0.28 m) on
  main, here with requirements off, and here with Northbank's own requirements switched on (`--requirements demo`);
  text only, main 3/3 and here 3/3 with them on, and off #061 first try in 3 of 4 runs (its one miss found +0.28 m
  second). `evals/step_cell.py` passes off and on (17 of 17 planted pairs, C1, C2, C3, C6, C7, C8, Rev B 0).
  Northbank's check: 464 clashes in 1,732 elements, unchanged. In Chromium: the start buttons from the demos, the
  requirements dialog on Northbank (Building, the eight classes), switched to Machine and a class removed.
- **Merged with main after #61:** its Reject words name the model the server reports (`labels.proposal`), not
  "Muse"; 629 server tests, 142 web tests, build clean.

Collapsed side bars' strips, centred (Oct 30; owner report; `web/src/index.css`): turned text stacks from the right, so a
strip tab's content sat against the right edge of the 40 px strip (22–39 px): on the left bar the text touched the
marker line and on the right bar it sat far from it. The tab's content now fills the strip and centres across it
(11–28 px, the same gap on both sides). Checked in Chromium on Northbank at 3× scale, both bars collapsed.

Properties floating or on the right (Oct 30; owner request; `feature/properties-dock-right`; code `web/src/dock.tsx`,
`dockLayout.ts`; [docs/panels.md](../panels.md)): a floating Properties panel has Dock Properties on the right (a tab
after Chat); Float floats it again; where it was last put (button, Float or a drag) is kept in
`sightline.dock.properties` and the next selection after a close or reload opens it there. With four tabs a bar's tabs
behind the front one show as icons with a tooltip, so nothing goes behind dockview's overflow menu. Checked: 143 web tests
(`dock.test.mjs`: the stored place); in Chromium on Northbank, float → dock right → select with Clash in front → close
and select → reload and select (all in the right bar, no overflow) → Float → close and select (floating); the tabs get
their names back when Properties closes.

Muse Wonder's own lane in Workings (Oct 31; testing the demo video's shots; `fix/workings-wonder-lane`; code
`web/src/workingsGraph.ts`; [docs/workings.md](../workings.md)): a proposal drew a second try's steps in Wonder's
colour but under the "Muse Spark" lane label. A second try now adds a Muse Wonder lane under the first model's (only
when Wonder runs), with its own timeline row. Found while testing the video's shots on a local server at `main` with
open weights and Show it built on, which also ran Show it built live for the first time (duct #1: 85 s, gate F 0.82,
kept) and Wonder on the tray (#2), the cell's fence post N3 (#29, ranked first) and the HMI stand (#13, no fix).
Checked: 143 web tests (`workings.test.mjs`: the lane, its steps, bar and row); build clean; in Chromium on #29 at
Fit.

The demo video's script (Oct 31; owner decisions Oct 30; `docs/demo-video`; [docs/demo-video.md](../demo-video.md)):
both themes as one story (our world, then the frontier), a narrator, plain words, and every shot tested first on a
local server at `main` with open weights and Show it built on: triage on Muse Spark Open (86 s, 5 need a fix), the duct
on Muse Spark (29 s, +400 mm at 50 mm, first idea), Show it built on it (85 s, F 0.82, both Muse Wonder judges
faithful), Wonder beating Spark on the cell's fence post N3 (#29, a straight 360 mm move at 124 mm, ranked first) and
on the tray (#2, a shorter offset), and the HMI stand (#13) ending in No verified fix. The footing × lift pit wall
(#16), Wonder's Northbank case in the Oct 29 eval, is now fixed by Spark alone (a trim). The decision is in
[20](20-decisions-limits-and-roadmap.md).

The repo is `IssueLab-Inc/ORCA` (Oct 31; owner decision; `docs/repo-name`): renamed on GitHub so the link on the
application and the submission says ORCA. Repo only: the code's internal `sightline` names stay
([21](21-glossary-and-naming.md), "Internal names kept on purpose"). Nothing in the code or docs used the old name;
README's "Run it" now starts with the clone. Checked: `git fetch` on the new remote, `test_docs_map.py`.

Orbit round the selection and the clash (Oct 31; owner request; code `web/src/viewer/Viewer.ts`, `App.tsx`):
- **What:** with an element selected, a left drag in the 3D view orbits round it (the middle of its box) instead of the
  point under the pointer; while ORCA works on a clash (`clashBusy`), a drag with nothing selected orbits round the
  clash. The camera and its target turn together round the pivot (`orbitAround`), so the pivot stays put on screen.
  The pilot's slow turn while ORCA thinks (`orbit(true)`) first glides the view sideways to centre the clash, keeping
  its angle and distance, then turns round it.
- **Checked:** `web/tests/viewer-orbit.test.mjs` (2: the pivot keeps its place on screen and its distance, no roll, no
  tilt past vertical); in Chromium on Northbank, the supply air main selected and the view orbited 6 m round it with
  the duct at the same pixel; a proposal with the target first panned 6.4 m off the clash: autoRotate on, the target
  glided to the clash (9 mm off) and the orbit flag on while ORCA worked; 145 web tests, build clean.

A patterns reading's 502 (Oct 31; owner request to look into it; code `web/src/api.ts`):
- **What happened:** in a live check, the automatic Insights patterns reading (`POST /api/reports/{id}/patterns/{scene}/
  triage`) came back 502. It never reached the server: Modal's request log has every other call of that visit, and none
  for it; the server returns 502 only for a failed requirements draft or transcription. So the gateway in front of the
  server answered it (Modal's edge, or the cloud session's own proxy the test browser went through). The same reading
  run again with the page left open came back 200 in 21.7 s; it is a slow, silent request (one model call, no bytes
  until the end), and the quiet automatic reading then left the patterns unread with no word until Explain was pressed.
- **What changed:** `api.triagePatterns` asks again after a 502, 503, 504 or no answer (twice, after 1.5 s and 4 s). It
  cannot charge twice: `plans.read_patterns` keeps the reading per report, scene and patterns, and a caller who comes
  while it is being made waits for it and gets the same reading.
- **Checked:** `web/tests/gateway-retry.test.mjs` (2); web tests and build.

Filter the clash list by status (Oct 31; owner request; code `web/src/ReportList.tsx`):
- **What:** once a clash is fixed or reviewed, the list's filters offer All, To fix, Fixed and Reviewed, each with its
  count (To fix is the old "Hide resolved" checkbox, which it replaces). The header's "N fixed" and "N reviewed" chips
  are buttons for the same filter; with nothing fixed or reviewed the filter is off. A filter opens every group.
- **Checked** in Chromium on Northbank: no filter before a fix; #1 fixed by a real proposal and accepted, then All 464,
  To fix 463 (none fixed among them), Fixed 1 (#1); the "1 fixed" chip turns the filter on and off with the select
  following; 145 web tests, build clean.


The Triage card and the top of the clash list, laid out again (Oct 31; owner request; code `web/src/Triage.tsx`,
`web/src/ReportList.tsx`, `web/src/index.css`):
- **What:** before a run the card's head is "Triage" with a Step 1 pill and one line, "Find the few that need a fix",
  and **Triage all n clashes** fills the card's width under it, folded or not (it used to share the head's line, the
  subtitle wrapping to three); the fold now opens how triage works there too. The report's line keeps to one line:
  "Muse Spark is naming n…" became a "Naming n…" pill whose tip names the model. The search has its own row, so its
  hint reads whole; the filters go under it only when they change something ("In the model" when some clashes are not
  in the open models, so not on Northbank; the status picker once anything is fixed or reviewed; "n shown" at the
  end). Set aside and Flag share the card's width. The card lines up with the list's edges (12 px).
- **Checked** in Chromium at 1600×1000, 1366×768 and a 390 px phone, every card state (idle folded and open, running,
  done folded and open, with the triage answer stubbed): no wrapped subtitle or truncated search hint; no filter row on
  a fresh report, then "228 reviewed", the status picker and "236 shown" after Set aside and To fix; the Insights
  tab's Detect card unchanged; 145 web tests, build clean.

Seat: one element bears on another (Oct 31, owner request after Northbank's #16, a lift-pit wall 500 mm into pad
footing B1; design in `docs/edits.md` "Seat", code `edits.seat` / `apply_seat`, `agent.seat_of` / `_try_seat`):
- **Why:** the detail a designer draws there is the wall bearing on the pad (its foot stops at the pad's face, its top
  carries on over it). ORCA could only trim the wall's whole end or move one of them. Asked for as a capability, not
  a fix for one clash: decided from the geometry for any pair, never a class list.
- **What:** a seventh kind, `seat`. When an element comes down into another and stands at least 50 mm above its top,
  its foot landing in it (at most 100 mm below its bottom), the support a straight prism under its top, the cut at most
  half of it, neither a run nor a zone: a recess (`IfcOpeningElement` RECESS) shaped as the support's top face, from
  below the foot to the top. The support's contact is proved by construction, not measured (the check's box depth
  would call an L-shaped element's flush faces an overlap); everything else no closer than before. Structure reviews it
  (`domains.SEAT_REVIEW`); the requirements treat it as a trim. Muse reads a "Bearing" line with what a seat would cut.
- **Everywhere:** the registry (`TRIES`, `PARAMS`, `IN_TRIAL`, `KEEPS_CONTACTS`, `KEEP`, `CANDIDATE`), `Workspace.check_seat`
  / `apply_seat`, chat and MCP `check_seat` (32 tools), both domain packs ("Seven kinds of fix"), `fixKinds.ts`.
- **A 1 mm bedding joint:** the recess clears the support by 1 mm all round. Flush, Northbank's seated wall still
  re-measured as -500 mm (the collision query saw the coplanar faces and fell back to the boxes' overlap).
- **Measured:** Northbank #16 (lift pit wall into pad B1): Muse Spark proposed the seat first (13 s), verified, ranked
  above a trim; 0.20 x 0.50 x 0.65 m cut, 10% of the wall, its top 350 mm on the pad; nothing else closer; kept in
  place in the browser; Detect again: 1 resolved, 0 new. `tests/test_seat.py` (15); 644 server tests, 148 web tests;
  answer key 3/3 first try at Rev04 heights (rows in `evals/results.csv`); `evals/step_cell.py` passes.

No layout patches behind the load card (Oct 31; owner report; code `web/src/viewer/Viewer.ts`):
- **What happened:** with two or four views chosen, opening models from the start page showed the layout's empty panes
  behind "Loading 4 models": the 3D view's sky in one quarter, drawing paper in the others. The panes' headers are
  hidden until models are drawn, but the one canvas still painted each pane's background in its rectangle.
- **What changed:** `drawFrame` draws one empty 3D view over the whole stage while no models are open, whatever the
  layout. The layout stays chosen and its panes return with the models. Opening models over models already open was
  not affected: the old ones stay on screen in their layout until the new ones replace them (`Viewer.load` stages first).
- **Checked:** `web/tests/viewer-empty-stage.test.mjs` (2; the first fails on the old code); in Chromium at 1600×1000,
  loading Northbank from the start page in the four-view layout now shows the same even stage as the single layout,
  and the four views (two in the two-view layout) are back once it is drawn; web tests and build.

More model formats on the roadmap (Oct 31; owner decision; no code changed):
- **What happened:** the owner asked whether ORCA could open the formats a web viewer lists (GLB, glTF, OBJ, STL,
  PLY, 3DS, FBX, 3MF, DAE, VRML, X3D, SKP, DWG, DXF, DWF, SVG, STEP, IGES, IFC, 3DM; IES recognised only).
- **What changed:** they wait until after the freeze, and come in only as models ORCA checks, converted to IFC on the
  server like STEP, never as a view-only viewer; glTF/GLB first. Recorded in
  [20](20-decisions-limits-and-roadmap.md) (an owner decision, and "Later" with what to build) and CLAUDE.md's "Later".
- **Checked:** a throwaway script (not committed) wrote `tests/test_step.py`'s cell out as GLB and as IGES with
  OpenCASCADE and ran each through `step.convert` with only `step._read` swapped. GLB gave the six parts, their
  groups, metres and the same three clashes as the STEP, as meshes; IGES came in as one part with no clashes.

Design tools and site data on the roadmap (Oct 31; owner direction; no code changed):
- **What changed:** two "Later" sections in [20](20-decisions-limits-and-roadmap.md). Connectors into design tools: what
  every connector does (send with native ids, receive kept fixes, apply them natively, moves first), then a table of
  building, mechanical, plant and robot-cell, and coordination tools with each one's way in and how feasible it is,
  and an order to explore. Site data aligned to the model with SAM 3.1: capture, alignment, segmentation, lifting to
  3D, matching and measuring on the server, and what ORCA would do with it. Also an owner-decision row and CLAUDE.md's
  "Later".
- **Checked:** SAM 3.1 against Meta's release notes and model page (released March 27, 2026, open weights). The design
  tools' ways in are their makers' published SDKs and APIs; none was built or tried.
