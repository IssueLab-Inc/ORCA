# Filters: find, colour, hide and isolate by what the model says

Owner request, Oct 31: "full filtering capabilities in ORCA". Pick models, classes, floors, a property set, a property
and its values (with counts), then colour what matches, colour it by value, hide it, isolate it, grey the rest, or
invert. The Properties panel can start a filter from any value it shows, and chat and voice can set filters too.

Owner decisions (Oct 31):
- **Shared by every view.** One set of filters for the 3D view and the drawing views (colours too), with one setting
  that lets the drawings show the whole model instead.
- **A list of filters, several on at once**, like Revit's view filters or Navisworks' appearance profiles: named,
  ticked on and off, each with its own action and colour; the top one wins where two colour the same element.
- **Chat and voice drive them** (the last slice).
- **All before the Nov 3 freeze.**

The existing quick checkboxes (the toolbar's Visibility menu: models, levels, classes) and the temporary hide and
isolate stay as they are ([views.md](views.md), "Visibility"). Filters are for viewing: triage, fixes and the pictures
sent to the model never see them, and the opening check ignores them. A **check on filters** ("Checks", below) takes a
filter's conditions as what one side of a clash test compares; that is the only way a filter reaches detection.

## The index (built)

The browser keeps no IFC data once a model is drawn (`ifcLoader.ts` closes web-ifc), so the server says what each
element is: `GET /api/scenes/{id}/facets` (`facets.py`, `Workspace.facets`).

- **What it reads.** The elements the page draws and the checks see (the scene's boxes) plus spaces with a body, each
  read once with `properties.Reader`, the Properties panel's own reader. The panel and a filter therefore never
  disagree, and the demo models' hidden note can never reach a filter.
- **Facets**, by key:

  | Key | Values |
  |---|---|
  | `file`, `class` | The model file; the IFC class |
  | `storey` | The nearest building storey, as the level checkboxes and the drawing views read it (`datums.storeys`) |
  | `type`, `material` | The type's name; each material it is made of (layers and constituents too) |
  | `attr:<Name>` | Each direct attribute with one value: tag, predefined type, object type, a door's height… |
  | `pset:<Set>/<Prop>` | Each property, the type's included; a complex property's parts as `pset:<Set>/<Complex>/<Prop>`; each value of an enumerated or list value |
  | `qto:<Set>/<Name>` | Each quantity |
  | `classif:<System>` | Each classification reference's identification (else its name) |
  | `group:<IfcClass>` | Each system, zone or group, by name |

  Numbers stay numbers, in SI (lengths in metres), as the panel's rows carry them. Ranges and tables are not one value,
  so they are not indexed.
- **Shape**, inverted so it stays small: `{revision, files, elements: [GlobalId], file: [file index per element],
  facets: [{key, kind: text|number|bool, unit?, values: [v], items: [[element index]]}]}`; values sorted, numbers
  first.
- **Kept** on the scene (`IfcScene._facets`, `facets.cached` / `keep`) until a kept edit changes its revision or its
  elements; the page reads it again after a kept fix (`infoRev`). **Read and built outside `Workspace.lock`** (it only
  reads, as the requirements' inventory does), so it never waits for the opening check and a big model's first build
  stalls no one, and kept only if no edit landed meanwhile (review, Oct 31). An object IfcOpenShell cannot read is skipped and logged, not the whole index. If the
  request fails, the panel says so with **Try again**.
- **Values keep their type:** yes/no is not merged with 1/0 (Python hashes `True` like `1`).
- **Measured** (Oct 31, Northbank Structure + MEP + Architecture + Site): 1,997 elements (36 of them spaces), 46
  facets, 0.8 s to build after the boxes, about 240 KB of JSON.
- **Matching on the server** (`facets.matching`, `facets.suggest`): the same conditions as the page, for chat and MCP.

## Filters (built)

A filter (`filters.Rule`) finds elements, then does one thing with them.

- **Finding:** models, classes and floors (each a list of values with counts), then any number of property
  conditions: a property set (Element, Attributes, a property set, a quantity set, Classification, Systems and groups),
  a property, and a test: is / is not (any of several values, any case), contains, has any value, has none, between,
  less than, more than (lengths typed in mm, kept in metres). Every condition holds; one still being written is left
  out. No condition finds everything. **Invert** takes what it does not find.
- **Doing:** **Colour** (a palette colour, or any), **By value** (each value of one property its own colour: the
  Value | Items | Colour table, values ticked off left uncoloured), **Hide**, **Isolate**. A By value filter with no
  property picked takes its last condition's (`filters.withBy`), in the editor, the preview and what is kept alike.
- **Several at once** (`filters.evaluate`): hide rules hide what they find; while any isolate rule is on, only what
  some isolate rule finds shows (several add up: "Ducts" and "Pipes" shows both); colour rules colour, the top one
  winning, and a value ticked off lets a lower rule colour it. **Show colours** turns every colour off at once.
  **The rest: Show · Grey · Hide** says what happens to what no filter colours or isolates: it stays as it is, it turns
  grey (only while something is coloured), or it is hidden, so a coloured filter shows only what it finds, in its
  colours (only while something is coloured or isolated; hide filters still hide within it; a value ticked off is not
  kept). Grey and hide are one or the other. Switching to Hide frames what is left (Zoom, below). Owner request, Oct
  31: "i can filter but i can't seem to hide everything else" (Isolate did, but only from the editor and without
  colour). Rules reorder with up and down.
- **Counts** are live: each list says how many each value would leave among what the other conditions find, the
  editor how many the filter finds, the list how many each filter acts on (by value: how many it colours).
- **The panel** (`FiltersPanel.tsx`): a tab behind Coordination in the left side bar; where there is no dock (the
  classic layout, tablets, phones) a sheet over the model, from the Visibility menu's **Filters by property**. **New
  filter** opens the editor; **Colour by…** adds a colour-by-value filter for a property most elements have in one
  click; a filter's name opens it again; on hover: up, down, **Zoom to them** (what is on screen), delete. The filter being edited shows in
  the model as it is built (in its place; on top while new), and Cancel puts things back.
- **Kept** per set of models (`sightline.filters.<project>`), and in a saved view (its `rules`). Old saved views,
  without them, leave the filters as they are. `filters.migrate` reads either back, and anything unreadable gives way.

## Zoom (built)

Owner request (Oct 31): applying a filter, from anywhere, takes the views to what it acts on.

- **Applying** (`filters.applied`, comparing the filters before and after): adding a filter, switching one on, or
  saving a change to one (what it finds, its action, colour or invert), from the panel, Colour by…, a value's row in
  Properties, chat or an agent over MCP. Switching one off, deleting, renaming, reordering, Show colours and Grey the
  rest move nothing; nor do the filters a project or a saved view reads back (a saved view has its own camera), nor a
  filter being edited until it is added or saved, nor a user's filter chat gives back on clear.
- **What it frames** (`filters.zoomTarget`), once the viewer shows the new filters: the elements the applied filters
  act on (what they find; for colour by value what they colour) that are on screen; for filters that only hide, what
  is still on screen. Nothing on screen, nothing moves.
- **Every view** (`Viewer.frameEverywhere`): the 3D camera flies there, and each drawing view that is not pinned pans
  and zooms to it, keeping its level, section line and facing.
- The Properties card's isolates (**Isolate all with this value**, **Isolate this level**, the class's **Isolate them**)
  frame what they isolate too, and **Zoom to them** on a filter frames what it acts on in every view.

## What wins

Shown: a hidden model hides; the clash pair, previews and trials always show; then the temporary hide or isolate; the
quick class and level checkboxes; the filters (hide, then isolate, then Hide the rest); the mode round the focus
([views.md](views.md), "Visibility").

Colour, under the pair, selection, hits, links, previews and measure (their own layers): the top filter's colour, else
the ghost, else grey (the grey context round a clash, or Grey the rest), else the element's own.

Captures (A/B/C, built views, the MCP's pictures) lift the style, filters and colours, so what the models read never
depends on how the user is looking.

## The palette

`filters.PALETTE`: twenty colours (ten, then a second ring of ten) chosen clear of every colour another role draws
(`filters.RESERVED`: the pair's red, green and purple and their outlines, the selection's blue, hits' magenta, the six
link colours, the "before" ghost's orange, the section box and measure, the clash overlap's amber, the greys). Each is
at least ΔE 20 from all of them and 15 from each other (CIE76; `web/tests/filters.test.mjs`).

Colour by value gives the values a filter finds the palette's colours in the index's order (`filters.valueColours`);
a value ticked off keeps its place, so the others keep their colours. Past twenty values the rest share **Other**
(`filters.OTHER`), which the key shows as "Other (n values)"; chat hears the same (its reply's `other`).

## Drawings (built)

Owner decision: one set of filters for every view, with one setting that lets the drawings show the whole model.

- **What drawings show** (the Views menu's **Drawings show**, or **Drawings show the whole model** in the Filters
  panel when drawing views are open): **What the filters leave** (the default: filters, hides and colours; not the 3D
  view's Context or Isolate), **What the 3D view shows** (Context and Isolate too), or **The whole model** (no filters,
  no colours; only hidden models stay hidden). `Viewer.setDrawingsShow`.
- **Colours on paper:** each coloured element is filled in its colour a quarter of the way to the paper, so the
  linework still reads; the rest keep their file's paper tint. Cut faces keep their poché, and the 3D Hidden line style
  shows no filter colours (doc 20, known limits).
- Measured in Chromium on Northbank: the south elevation, MEP isolated and coloured by System, shows supply air, return
  air, cold water, lighting and fire alarm each in its colour; the whole model setting brings back everything, uncoloured.

## The key and small screens (built)

- **The key:** while filters colour anything, a chip over the 3D view lists up to six colours and what each means (a
  colour filter's name, a colour-by-value filter's values) and opens the Filters panel (`filters.legend`). It lists a
  colour only when an element on screen has it: not what a filter hides, nor what a higher filter colours.
- **Without the dock** (the classic layout, tablets, phones) the Filters panel is a sheet over the model, opened from
  the Visibility menu (Tools on a phone).

## From the Properties panel (built)

Every value the filters' index knows has, on hover: **Filter by this value** (a new filter finding it, in the editor,
shown live), **Colour by this property** (a colour-by-value filter on top of the list) and **Isolate all with this
value** (a temporary isolate). A storey's breadcrumb offers **Filter by this level**, and the card's **More** menu
**Filter by this class** ([panels.md](panels.md), "Properties").

## Chat, voice and agents (built)

- **`set_filters`** (chat and MCP): a list of filters, each with `classes`, `levels`, `models` (lists), `where`
  (`{property, set?, op: is|is_not|contains|has|missing|less|more|between, values?, min?, max?}`, lengths in metres),
  `action` (`colour`, `colour_by_value`, `hide`, `isolate`), `colour` (#rrggbb), `by` (the property to colour by:
  System, class, level, model…), `invert`, `name`; and `grey_rest` or `hide_rest` (grey or hide what no filter
  colours or isolates). Voice goes through chat, so it works by voice too.
- **Resolved on the server** against the same index (`facets.resolve`, which returns the rule and what it acts on): a class with or without its `Ifc` prefix, a
  level as the storey, a model by part of its file name, a property by name (or `set/name`; a property set wins over
  an attribute or quantity of the same name), values in any case. A name the models lack fails back to the model with
  the closest ones (`facets.Unresolved`), so it can try again; the hidden demo note can never be suggested. A test with
  no bound or value is refused (the page would leave it out and act on everything), but a lone number in `values` is
  taken as the bound, two as a range. A complex property's part answers to its own name ("Torque") or its path. The reply
  says how many elements each filter finds, and for a colour-by-value filter each value it colours with its count, so
  the model names what is there.
- **On the page** (`ui filters`): chat's filters (`origin: "chat"`) replace its own; the user's that were on are
  paused (`Rule.paused`) while they show, and come back with **`clear_filters`**. They show in the Filters panel like
  any other, so the user can edit, keep or delete them, and the views go to what they act on (Zoom, above).
- One line in `domain_packs/chat.md` says when to use them (kinds of element by class, level, model or property).
- Measured in Chromium on Northbank with Muse Spark: "Isolate the MEP model and colour the services by system." →
  two filters (the MEP model isolated, coloured by System), the views framed on the services, and a reply listing the
  nine systems with their counts.

## Checks (built)

Owner request (Oct 31): run ORCA's clash detection on filtered elements, from the page and over MCP and chat. Owner
decisions: side A is a filter; side B is a filter, **Everything** or **Itself** (as selection sets in a clash test);
each filter gets a one-click **What do these hit?**; chat and agents use both the elements they describe and the user's
own filters by name; the clashes **replaced the open list**, as detection did, titled with the check. Since Oct 31
(owner request, "the ability to have multiple"), a check is **kept as a check of its own** and its clashes join the
list ([detection.md](detection.md), "Kept checks").

- **A check is one detection test** (`detect.Test`) whose sides carry the filter's complete conditions
  (`Selection.filter`), found against the index when the run starts, so a rerun after a kept fix selects by properties
  again. Design and ids: [detection.md](detection.md) ("A check on filters"; numbers and diffs in "Reruns").
- **A filter as a side is what it acts on** (as `filters.actedOn`): one that colours by value takes only what it
  colours, a value ticked off left out (`Selection.filter.by`, `facets.acted`). A Colour by… filter has no
  conditions; it used to be taken as everything (owner, Oct 31: a check of "Distribution system" with Site ticked off
  in "By Model" took all 1,961 elements, the Site model too).
- **Everything is what the full check covers**: a site model is context and left out (`detect.everything`, the rule
  `default_tests` uses; `check.everything` in `detect_tests` and `Workspace.check_defaults`), unless it is all there
  is. Site elements are reached through a filter (owner decision, Oct 31).
- **What the filters show** is a side of its own: every filter that is on, together, as on screen (hide, isolate,
  Hide the rest, Show colours), found again on every run (`Selection.view`, `facets.shown`, which reads the filters as
  `filters.evaluate` does), so a kept fix's new pieces are checked. "Run a clash test on the filtered items" is this.
- **On the page** (`web/src/checks.ts`, `FiltersPanel`'s `check`): each filter's row has **What do these hit?** (that
  filter against everything, hard clashes at the check's tolerance); it is off while a check runs, before the models
  are read, and for a filter that finds nothing a check can test (spaces have no body) or everything (Check the open
  models does that). Under the list, **Check clashes** picks side A (a filter, or What the filters show), side B
  (Everything, Itself: those elements against each other, What the filters show, or another filter), hard clashes
  deeper than … mm or elements closer than … mm (on its own row; a full-width **Check clashes** button ends the block, with why it is off under it; blank:
  the defaults, `Workspace.check_defaults`, also `detect_tests`' `check`), with each filter's count, and says "Kept as
  a check of its own: its clashes join the list (pick it above the list). Checking it again replaces only its
  clashes." The choices carry the filter list's numbers (what
  each acts on, rooms included); when a side takes rooms, a line under the choices says so ("36 rooms in By Model
  aren't checked: rooms have no solid body to clash"), as rooms are never part of a clash check (owner request, Oct 31:
  "make the counts match between the list and check options"). A filter that is switched off can still be a side:
  a check reads its conditions, not what is on screen. What the filters show is off when they show nothing, or hide
  nothing (Check the open models does that).
- **Afterwards** the check is kept with the others and the list shows it (the picker over the list: All checks, or
  one check; `CheckPicker`, `checks.narrow`). Run again repeats it, also one chat or an agent ran, by its key; with no
  check of the open models kept, the run summary says "Only <check>" and offers **Check the open models**. A clash the
  full check also finds is one row with one #N, title, views, sign-offs and triage reading.
- **Chat and agents** (`detect_clashes` with `a`, `b`, `kind`, `clearance_mm`, `name`): a side is elements described
  as for `set_filters`, one of the user's filters by name, or what their filters show (`{"shown": true}`). The page
  shares its filters (`filters.shareable`: each by its name, with only its complete conditions, what it does and,
  colouring by value, by what) and how they show (`filter_view`: Hide the rest, Show colours) with every chat turn and
  the agent link's context; the `[context]` line and `get_session` say how many the filters show together. Each
  side's count is the list's (`chat.side_count`), with `rooms_not_checked` when it takes rooms. Sides are resolved and counted before a run is spent, so a misspelt filter costs no detection run.
- **Limits:** a side takes at most 30 conditions of 500 values each; an element whose
  GlobalId two open files share is read from the first file by the index and the last by detection
  ([20](architecture/20-decisions-limits-and-roadmap.md)).

## Tests

- `web/tests/filters.test.mjs` (12): conditions as the server matches them; every condition holding, unfinished ones
  left out, invert; hide, isolate and colour together (top colour wins, isolates add up, grey the rest); colour by
  value (chosen colours, palette by place, values ticked off, what it counts); counts among the other conditions,
  names, sets, a new filter's colour; the key (only colours on screen); what counts as applying a filter and what it
  frames; `migrate`; the palette against the reserved colours, twenty of them, then Other.
- `web/tests/filters-check.test.mjs` (12): a check's sides, name and test (no id, the defaults, Everything as an open
  selection, Itself as none); what a side can test; `shareable`; What do these hit? and Check clashes in the panel; a
  check from the panel is kept and joins the list (the chat goes on, the picker shows it), Run again repeats it by its
  key, Run all again, Check the open models sends every test; chat sees the filters and the check on screen, and Run
  again repeats a check chat ran.
- `web/tests/viewer-filters.test.mjs` (7): hides, isolates and colours reach the batch, with grey for the rest;
  captures never see them; lit links leave out what a filter hides; what drawings show for each setting; a drawing's
  fill pass takes the colours on paper and gives the 3D ones back; framing takes the 3D view and every unpinned
  drawing there, not a pinned one; a level's elements from the viewer's storeys; what is shown tested once per change.
- `server/tests/test_facets.py` (14): every element with its file, class, storey (as `datums.storeys`), type and
  material; numbers kept as numbers in SI from a millimetre file; the hidden note never in the index; every kind of
  value (classification, group, layers, enumerated, list, complex parts, what the type gives; no ranges or tables);
  conditions matched as the page does and close-match suggestions; kept until an edit; the route and its 404.
  `facets.resolve` turns what chat asks for into the page's rule, and fails with the closest names (never the hidden
  note). `found` and `name_for`, as the page's `found` and `nameFor`, for checks.
- `server/tests/test_detect.py`: a filter as a check's side (vs everything, itself), its id and name, ids that follow
  a pair between checks, each check diffed against its own last run, bad filters refused; chat's checks on described
  elements and on the user's filters by name, refused before a run is spent. `server/tests/test_checks.py`: kept
  checks ([detection.md](detection.md), "Kept checks").
- `server/tests/test_chat.py`, `test_mcp.py`: `set_filters` and `clear_filters` reach the page; an unknown class is
  refused with the closest. `web/tests/filters-chat.test.mjs`: chat's filters replace its own, pause the user's and
  give them back.
