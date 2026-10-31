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

## Later slices

The panel, the viewer's paint, colours in drawings, the Properties panel's row actions and chat follow; each part of
this doc is written as it is built.

## Tests

- `server/tests/test_facets.py` (7): every element with its file, class, storey (as `datums.storeys`), type and
  material; numbers kept as numbers in SI from a millimetre file; the hidden note never in the index; every kind of
  value (classification, group, layers, enumerated, list, complex parts, what the type gives; no ranges or tables);
  conditions matched as the page does and close-match suggestions; kept until an edit; the route and its 404.
