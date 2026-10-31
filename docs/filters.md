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
- **Kept** on the scene (`IfcScene._facets`) until a kept edit changes its revision or its elements; the page reads it
  again with the classes and storeys after a kept fix (`infoRev`). Built under `Workspace.lock`.
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
  Value | Items | Colour table, values ticked off left uncoloured), **Hide**, **Isolate**.
- **Several at once** (`filters.evaluate`): hide rules hide what they find; while any isolate rule is on, only what
  some isolate rule finds shows (several add up: "Ducts" and "Pipes" shows both); colour rules colour, the top one
  winning, and a value ticked off lets a lower rule colour it. **Show colours** turns every colour off at once;
  **Grey the rest** greys what no rule colours (only while something is coloured). Rules reorder with up and down.
- **Counts** are live: each list says how many each value would leave among what the other conditions find, the
  editor how many the filter finds, the list how many each filter acts on (by value: how many it colours).
- **The panel** (`FiltersPanel.tsx`): a tab behind Coordination in the left side bar; where there is no dock (the
  classic layout, tablets, phones) a sheet over the model, from the Visibility menu's **Filters by property**. **New
  filter** opens the editor; **Colour by…** adds a colour-by-value filter for a property most elements have in one
  click; a filter's name opens it again; on hover: up, down, **Zoom to them**, delete. The filter being edited shows in
  the model as it is built (in its place; on top while new), and Cancel puts things back.
- **Kept** per set of models (`sightline.filters.<project>`), and in a saved view (its `rules`). Old saved views,
  without them, leave the filters as they are. `filters.migrate` reads either back, and anything unreadable gives way.

## What wins

Shown: a hidden model hides; the clash pair, previews and trials always show; then the temporary hide or isolate; the
quick class and level checkboxes; the filters (hide, then isolate); the mode round the focus
([views.md](views.md), "Visibility").

Colour, under the pair, selection, hits, links, previews and measure (their own layers): the top filter's colour, else
the ghost, else grey (the grey context round a clash, or Grey the rest), else the element's own.

Captures (A/B/C, built views, the MCP's pictures) lift the style, filters and colours, so what the models read never
depends on how the user is looking.

## The palette

`filters.PALETTE`: ten colours chosen clear of every colour another role draws (`filters.RESERVED`: the pair's red,
green and purple and their outlines, the selection's blue, hits' magenta, the six link colours, the "before" ghost's
orange, the section box and measure, the clash overlap's amber, the greys). Each is at least ΔE 22 from all of them
and 25 from each other (CIE76; `web/tests/filters.test.mjs`).

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
  colour filter's name, a colour-by-value filter's values) and opens the Filters panel (`filters.legend`).
- **Without the dock** (the classic layout, tablets, phones) the Filters panel is a sheet over the model, opened from
  the Visibility menu (Tools on a phone).

## Still to come

The Properties panel's row actions, and chat.

## Tests

- `web/tests/filters.test.mjs` (7): conditions as the server matches them; every condition holding, unfinished ones
  left out, invert; hide, isolate and colour together (top colour wins, isolates add up, grey the rest); colour by
  value (chosen colours, palette by place, values ticked off, what it counts); counts among the other conditions,
  names, sets, a new filter's colour; `migrate`; the palette against the reserved colours.
- `web/tests/viewer-filters.test.mjs` (5): hides, isolates and colours reach the batch, with grey for the rest;
  captures never see them; lit links leave out what a filter hides; what drawings show for each setting; a drawing's
  fill pass takes the colours on paper and gives the 3D ones back.
- `server/tests/test_facets.py` (7): every element with its file, class, storey (as `datums.storeys`), type and
  material; numbers kept as numbers in SI from a millimetre file; the hidden note never in the index; every kind of
  value (classification, group, layers, enumerated, list, complex parts, what the type gives; no ranges or tables);
  conditions matched as the page does and close-match suggestions; kept until an edit; the route and its 404.
