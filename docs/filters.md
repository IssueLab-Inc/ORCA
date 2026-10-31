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
isolate stay as they are ([views.md](views.md), "Visibility"). Filters are for viewing only: the check, triage, fixes
and the pictures sent to the model never see them.

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
  elements; the page reads it again after a kept fix (`infoRev`). **Built outside `Workspace.lock`** (it only reads, as
  the requirements' inventory does), so a big model's first build stalls no one, and kept only if no edit landed
  meanwhile (review, Oct 31). An object IfcOpenShell cannot read is skipped and logged, not the whole index. If the
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
  winning, and a value ticked off lets a lower rule colour it. **Show colours** turns every colour off at once;
  **Grey the rest** greys what no rule colours (only while something is coloured). Rules reorder with up and down.
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
quick class and level checkboxes; the filters (hide, then isolate); the mode round the focus
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
  System, class, level, model…), `invert`, `name`; and `grey_rest`. Voice goes through chat, so it works by voice too.
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

## Tests

- `web/tests/filters.test.mjs` (10): conditions as the server matches them; every condition holding, unfinished ones
  left out, invert; hide, isolate and colour together (top colour wins, isolates add up, grey the rest); colour by
  value (chosen colours, palette by place, values ticked off, what it counts); counts among the other conditions,
  names, sets, a new filter's colour; the key (only colours on screen); what counts as applying a filter and what it
  frames; `migrate`; the palette against the reserved
  colours.
- `web/tests/viewer-filters.test.mjs` (6): hides, isolates and colours reach the batch, with grey for the rest;
  captures never see them; lit links leave out what a filter hides; what drawings show for each setting; a drawing's
  fill pass takes the colours on paper and gives the 3D ones back; framing takes the 3D view and every unpinned
  drawing there, not a pinned one.
- `server/tests/test_facets.py` (9): every element with its file, class, storey (as `datums.storeys`), type and
  material; numbers kept as numbers in SI from a millimetre file; the hidden note never in the index; every kind of
  value (classification, group, layers, enumerated, list, complex parts, what the type gives; no ranges or tables);
  conditions matched as the page does and close-match suggestions; kept until an edit; the route and its 404.
  `facets.resolve` turns what chat asks for into the page's rule, and fails with the closest names (never the hidden
  note).
- `server/tests/test_chat.py`, `test_mcp.py`: `set_filters` and `clear_filters` reach the page; an unknown class is
  refused with the closest. `web/tests/filters-chat.test.mjs`: chat's filters replace its own, pause the user's and
  give them back.
