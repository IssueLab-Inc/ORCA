# Editing parity: edits that keep a real model consistent

Owner request, Nov 1: take ORCA's hand edits ([manual-edits.md](manual-edits.md)) from "works on Northbank" to "safe
on a real model", in four tiers, on the hand-edits branch. New work for ORCA: the ideas follow how an IFC authoring
tool keeps a model's parametric data true after an edit (studied, not copied); the code is ORCA's own, on IfcOpenShell.

## Why

Northbank has none of what real exports carry, so these paths were never exercised:

| Construct | Northbank | What a careless edit does to it |
|---|---|---|
| Material layer set usage (walls, slabs) | 0 | the body gets thicker, the layers still add up to the old thickness |
| Material profile set usage (beams, columns, segments) | 0 | a new profile on the body, the material profile unchanged |
| Body shared through a type (`IfcMappedItem`) | 0 | refused today; edited in place it would change every element of the type |
| `Axis` representation | 0 | the axis keeps the old length |
| Wall path joins (`IfcRelConnectsPathElements`) | 0 | the join says the walls meet; they no longer do |
| Base quantities (`Qto_*BaseQuantities`) | 36 (architecture) | the quantities keep the old sizes |

## Owner decisions (Nov 1)

1. **This face or element only, by default.** Joined parts come along only when asked (`carry`): see
   [manual-edits.md](manual-edits.md), decision 10.
2. **Shared data: this element only.** An edit to a shared layer set, profile or type body gives the edited element its
   own copy; with a type, the type is copied ("… (ORCA)") and the element reassigned to it, so the IFC stays valid.
   "Apply to the type" is an explicit choice, and then every element of the type is checked.
3. **Order:** Tier 0 → Tier 1 → Tier 2 → Tier 3; the branch is green after every slice.
4. **A layered wall or slab made thicker** changes the layer on the pushed face (the outermost on that side), the
   reference line staying where it was; refused under 1 mm.

## Tiers

| Tier | What | Status |
|---|---|---|
| 0a | This face or element only by default; `carry` to take joined parts along | done (Nov 1) |
| 0b | A parametric fixture with every construct above, a model-consistency check in every edit's check, and a test matrix of every op on every construct | done (Nov 1) |
| 1 | Keep the model consistent: own copies (types, sets, mapped bodies), layer and profile sets, `Axis`, quantities, path joins | done (Nov 1): own copies by default, Apply to the type, a carried wall's joined neighbour re-trimmed |
| 2 | MEP: offsets by hand (up or sideways), bends at any angle, transitions on a carried resize, disconnect, join | done (Nov 1): offset, join, disconnect, bends at any angle, transitions on a carried resize, a carried move re-fitting its neighbours |
| 3 | Editable properties: attributes, psets, type, material, classification, container | done (Nov 1); classifications from the panel too |

## The consistency check (Tier 0b)

`consistency.py` reads, per element and rule, what a consistent edit keeps (`measure`), and `manual.check` reads it
before the edit and again in its trial (`compare`). It compares the model with itself, never with an ideal, so a model
that was already inconsistent never blocks an edit; only what the edit makes worse does. An element the edit made (a
split's second piece) is compared with the element it came from.

| Rule | Reads | When it changed |
|---|---|---|
| `layers` | Σ LayerThickness less the body's extent along the usage's axis (AXIS2 the local y, AXIS3 the local z) | block |
| `profile` | the body's swept profile less the material profile, size by size (or its class when they differ) | block |
| `axis` | where the body starts and ends along the `Axis` (`IfcPolyline` or `IfcIndexedPolyCurve`), from its ends | block |
| `cardinal` | where a profile set usage's cardinal point (1-9 on the section's box; 10-15 for a section symmetric both ways) is from the `Axis`, across the extrusion | block |
| `joins` | how far a path join's ATSTART/ATEND end is from the other element's axis, in plan | block, past 5 mm |
| `type` | a digest of everything under the type's maps | block (unless the edit is to the type) |
| `quantities` | the body's volume and the `Qto_*BaseQuantities` values | warn, when the volume changed and they did not |

Geometry comes from `ifcopenshell.geom.create_shape` in the element's own placement, built only for elements that carry
one of these. Northbank carries base quantities only (36 on the architecture model), so it sees the warning and nothing
else.

A sixth rule, `shared`, guards the copies below: a layer or profile set other elements use that changes in place blocks
("the layer set of wall 'W1' is shared by 1 other element: changing it would change them too").

## Edits that keep it (Tier 1)

`parametric.py` runs after every hand edit, inside its transaction, the same in the check's trial and when kept
(`manual._sync`): `snapshot` reads each element before, `sync` brings its data along with its body after. Data that was
already out of line stays as it was; only what the edit moved is moved.

| What | How |
|---|---|
| Shared data (decision 2) | `own_usage`: a set the element's type gives other elements too → `root.copy_class` on the type, named "… (ORCA)", the element reassigned to it (its body kept) and given its own usage of the copied set, the usage's direction, sense, offset and cardinal point kept; a set shared another way → `material.copy_material` |
| A body from its type | `edits.make_unique` → `unmap`: the mapped items become the element's own copy of what they draw, where they draw it (`mapping`: the target after the origin, composed into each solid's position, a mesh's or a brep's points); a scaled target is refused. Faces read through the map (`solids(through_maps=True)`), so a mapped fitting pushes and pulls like any other; edits unmap first, the fix kinds never see through |
| Layers (decision 4) | The body's extent along the usage's axis before and after: the side that moved changes the layer on that side (first or last, by the sense), and `OffsetFromReferenceLine` follows the start of the layers |
| Section | A profile set usage's material profile becomes the body's new profile (assigning a usage puts the set's profile back on the body, so the edit's is put back after) |
| `Axis` | Its ends move with the body's ends, keeping how far off them they were (a joined wall's axis running to the corner stays so); a piece made without one gets its source's (`_give_axis`) |
| Base quantities | `quantities.recompute` for an element whose volume changed or that the edit made |
| Path joins | A join whose end moved off the other wall goes to the piece of a split that now holds that end; else it is left open (`geometry.disconnect_path`) and listed with the joints, kept only as **Keep with N open joints** (decision 1) |

Measured on the fixture: W1 pushed 50 mm out on its north face becomes "WT-250 (ORCA)" with its insulation 85 mm (W2
keeps 35 mm), then 20 mm on its south face grows its plaster to 35 mm with the reference line at −20 mm; BM1's top
pushed 50 mm gets "BT-UB (ORCA)" with a 450 mm section, cardinal point 5 kept, BM2 still 400 mm; W1 split at 2 m gives
two 2 m axes and quantities, the join handed to "W1 (part 2)"; F1's top pushed 100 mm is its own extrusion, F2 still
mapped, FT-BOX's map 300 mm deep.

**Apply to the type** (`scope: "type"`, the Edit tool's **Apply to the type** for push/pull and align: off by default
and again for each element). The edit changes what the type gives, for every element of it, each one checked (the
`type` or `shared` rule is kept on purpose, everything else still read; requirements gate every element):
- **A shape the type draws** (a mapped body): the element's new solids, moved back into the map's own frame
  (`parametric.to_type`, the inverse of where its map puts it), become the type's shape, and the element draws it
  through its map again. Every element mapped from it follows, each where its own map puts it: F2's north end pushed
  100 mm makes F1 100 mm longer along x, F2's map being turned 90°.
- **A section the type's profile set gives** (a side or radius): the new profile is the set's, and each other element
  takes it about its own placement, its cardinal point kept: BM1's top pushed 50 mm makes BT-UB 450 mm deep, BM1's top
  at 3.25 m (the face pushed), BM2 25 mm deeper above and below its axis. No "(ORCA)" copy.
- **A thickness the type's layer set gives** (a face square to the layers): the layer on that face grows in the
  type's own set, the edited wall's reference line kept as for one wall, and every other wall of the set has the face
  holding that layer pushed by as much through the hand edits' own push (`manual._push_face`: its openings, quantities
  and refusals as a push's), its reference line kept too. W1's north face pushed 50 mm makes WT-250's insulation
  85 mm; W2, whose layers run west, is 50 mm thicker on its west face; both 300 mm wide. A layer pulled in past
  1 mm is refused, as for one wall.
- **Refused in words:** an element without a type, an edit that changes nothing the type gives (a length or a height
  is each element's own), a wall whose usage does not say which way its layers run, and every op but push/pull and
  align.

**A carried wall end** (`manual._retrims`). A wall moved with Take joined parts along brings each wall whose end is
joined to it (a path join, ATSTART or ATEND on that wall's side) along: that end is pushed along its own axis so it meets
the moved wall as it did, in plan, through the hand edits' own push (its axis, layers, quantities and openings follow;
refused as that push would be). W2 moved 500 mm east makes W1 500 mm longer at its east end; W1 moved 500 mm north makes
W2 500 mm shorter at its south end; the join holds in both. A wall moved along its own line, or a join in line with
it, is left open and listed, as for a move on its own. Muse's plain moves do the same (`agent.joined_ends`, below).
IfcOpenShell's `geometry.regenerate_wall_representation` was not used: it redraws a wall from its layers, dropping
a body ORCA or the authoring tool shaped some other way.

**A section grown on one side** (`parametric._cardinal`). The body grows to the side pushed, as people expect, and
the element's axis goes back to its cardinal point: its placement moves across by the difference and its body back by
as much, so what is placed in it stays where it is, and a tool that draws it again from its axis, profile and cardinal
point draws the same body. BM1's top pushed 50 mm: the body 2.8 to 3.25 m, its axis at 3.025 m (cardinal point 5); a
bottom-centred beam (2) keeps its axis when its top is pushed and takes it down with its bottom.

Not yet (later): quantities ORCA does not work out (weights, surface areas, perimeters) are left and named.

## MEP by hand (Tier 2)

Three ops, on the fix kinds' own geometry, so ports chain and joints are handed on as they are for a fix
([manual-edits.md](manual-edits.md), the op table):

- **`offset`**: a section of a level duct, pipe or tray between two points, up, down or sideways square to its run, with
  90° bends (`edits.apply_offset`, `lateral_m` for sideways). In the Edit tool (F): click where it starts and ends on the
  run, then Up, Down or a compass side and how far.
- **`join`**: two segments' nearest free ends, in line (the first stretched) or square in one plane (a 90° bend fitting
  of a section depth's radius between, its ports placed and joined) (`edits.join_plan`, `join_segments`). Tool N.
- **`disconnect`**: one joint left open, kept as an open joint: a run split at a fitting. Tool X.

Measured on Northbank: clash #1 (supply air main through the transfer girder) offset by hand 400 mm up over 2.48 m
reads "Clear · nearest 50 mm · clears 1 clash" (Rev04's own fix leaves 50 mm), keeps as E1 and marks the clash fixed;
Ctrl+Z puts it back. On `fixtures.build_mep_fixture`: DA and DB square to each other join with a bend from (3.6, −0.2)
to (4.2, 0.4), both 3.6 m; DA and DC join in line, DA 4.5 m; every edit leaves the file schema-valid and comes back on
undo.

**Bends at any angle** (Nov 1, second program): `edits._bend_mesh` and `bend_end` sweep any angle under 180° (a 90°
bend is drawn as before), `bend_radius` takes the angle (two bends of θ rise 2 r (1 − cos θ)), and `apply_offset(bend_deg=)`
takes the section up a slope: a bend of θ, a straight riser along the slope, a bend of θ back, the run it takes centred on
the split point. The Edit tool's offset has **90° / 45°**; Muse's offset candidate takes `"bend_deg": 45` (the prompt
says when), carried in the option's `edit` to its recheck and keep. Measured on the run fixture: 400 mm up over 1.5 to
4.5 m with 45° bends clears the beam: 1.18 m straight, bend, a 0.32 m riser on the slope, bend, 2.35 m 400 mm up, and
back down; one joined chain, schema-valid.

**Transitions on a carried resize** (Nov 1, second program): a duct's or pipe's side or radius pushed with **Take
joined parts along** keeps its joints meeting the same size: at each joined end it is shortened by a transition's length
(no face turning more than 30°) and a transition fitting (`edits.add_transitions`, lofted by `_loft_any`: rectangles or
round, its new centreline's offset included) goes between it and what that end joined, the ports re-joined through it.
Pushed on its own, the check warns that its end no longer matches what it joins. Measured on the run fixture: the
main's north side out 100 mm, carried: the main 500 wide ends at 5.83 m, a 173 mm transition back to 400 wide meets
the end segment at 6 m.

**A carried move re-fits** (Nov 1, second program). A hand move with Take joined parts along used to take every
straight beyond the run's fittings along, and so on out until something stayed (a terminal, equipment: refused) or
twelve parts were taken (refused). Now a level straight the move goes square to, joined at its far end too, is re-fitted
instead (`connections.plan_move(refit=True)`, `Jog`; `edits.apply_jog`): its joined end goes with the move (a 150 mm
piece), a pair of bends and a riser take it back to the rest, which stays with its far joint; the joint's port frames
go with it. One with nothing at its far end is still taken along whole (fewer parts), and one that cannot be re-fitted
(too short, a move too small for a pair of bends of its section, up and across at once, a branch) is taken along as
before. Muse's moves re-fit too (`connections.refit_moves`, `SIGHTLINE_MOVE_REFIT`, on unless `off`): tried with the re-fit's pieces checked like stretched segments (new or worse contacts only), previewed (`edit.jogs`), kept (`Workspace.apply`, the pieces in `changed` so the page draws them) and checked with other fixes (`plans._in_trial_move`); a combined fix's move steps do not re-fit yet. The answer key holds with it on: 3/3 at Rev04's heights (Nov 1). On the joints fixture a lift that was refused before it was tried ("pull … apart from filter") is now tried and fails for what it really hits, the column.

Measured: on the MEP fixture, DA lifted 400 mm with the bend to DB and an air terminal at DB's far end (refused before:
"AT1 … stays where it is") keeps every joint: DB's start goes up with DA, bend, riser, bend, the rest at 2.8 m still on
the terminal; schema-valid, undone. On Northbank, 400 mm up and down for each of 332 straight runs (664 plans): 102 kept
their joints before, 370 with re-fits ("too many parts" refusals 187 to 0, "too short" 191 to 110; terminals and
equipment on the run itself still 175); 40 of them, picked at random and made in trials, hold every joint.

## What the model says, edited (Tier 3)

`property_edits.py` changes what the model says about an element, not its shape, through `ifcopenshell.api`, one change
at a time, each an entry in the edit log (kind `property`, undone and redone as any edit, stamped `ORCA_Edit` in the
export): an attribute (Name, Description, ObjectType, Tag, PredefinedType from its schema's list), a property in one of
its own sets (a number stays a number, yes and no stay booleans), its type (the body kept: a body drawn from the old type
becomes its own first), its material, a classification reference from its model, its storey or space. Refused in words:
base quantities (they follow the body), a property its type gives (every element of the type has it), a layered or
profiled element's material or type (its layers or profile come from its type).

- **Panel:** a pencil on the element's own editable rows (docs/panels.md, "Properties"); the choices come from
  `GET …/property-choices`, the change goes to `POST …/properties`. A classification row's pencil swaps the reference
  for another in one change (`replace`) or takes it off; **Add a classification** gives it one more. A reference it
  already has is refused, never given twice.
- **Muse:** `edit_property`, kept at once, but only when the person's own message this turn says the new value or names
  the target (`chat._said`).
- **Agents:** MCP `edit_property`, kept as the agent's.

Measured in Chromium on Northbank: the supply main's Tag SA-MAIN-L02-5 → SA-MAIN-L02-5R kept as E1, Ctrl+Z back,
Ctrl+Y again, the panel following each; its storey Level 02 → Level 03 from the panel's list.

## Test matrix

`server/tests/test_parametric_edits.py` on `fixtures.build_parametric_fixture` (walls W1, W2; slab SL1; beams BM1, BM2;
mapped fittings F1, F2). Each edit is kept, then the whole model is read again: every layer set, profile, axis, join and
base quantity matches its body, and every other element, type, set and map is as it was. Undo puts them back.

| Edit | Wall (layers, axis, join, quantities) | Slab (layers, quantities) | Beam (profile, axis, quantities) | Mapped fitting |
|---|---|---|---|---|
| Push the top / an end / a side | height, length, thickness on either face: kept consistent | thickness, size: kept consistent | length, section: kept consistent | top, a turned one's end: unmapped, kept |
| Move | up: kept · off its join: kept with 1 open joint | kept | kept | kept |
| Void | kept consistent | | | |
| Split / remove a section | kept, the join handed on | kept, both pieces' quantities | kept, both axes | kept |
| Clip | | | | kept |
| Delete | kept | | | kept |

## Muse's fixes keep it true too (Nov 1, second program)

The fix kinds (offset, trim, seat, route, resize, and a plain move) try their edit inside `agent._fix_trial`: after the
edit, `agent._keeps_true` brings the data along (`parametric.sync`) and reads the model again (`consistency`). A fix that
still makes it disagree, or would leave a wall's join open (a fix never does), fails its trial with the reason, so Muse
hears it in the next round ("cannot move it: it would leave its join with 'W2' open…"). Keeping a fix (`plans.apply`,
every keep route) does the same after each fix's edit and refuses all of them (`NotVerified`) when one still
disagrees. Elements that carry nothing to keep (all of Northbank's) skip it and cost nothing. Penetrations only add an
opening, and a combined fix's steps are fix kinds above.

A plain move of a wall square to a wall path-joined at its end brings that end along, as a hand move with joined parts
does (`agent.joined_ends`, `follow_joined` over `manual._retrims`): the trial pushes the end, checks both walls (each
ignoring the other, as joined parts do), and the option carries `edit.follow` and the end's preview; its keep
(`plans._keep_move`) and a plan's joint check (`_in_trial_move`) push it again, its file held with the move's
(`EXTRA_FILES`). A move along the wall's own line still fails with the open join, so Muse hears why. Measured: W2 moved
300 mm east by a fix makes W1 4.3 m, its quantity and join with it, one entry, undone whole.

Measured on the fixture with a column at BM1's end: Muse's trim of the typed beam back to the column is kept with its
`Axis` ending at 4.8 m and its `Qto_BeamBaseQuantities` Length 4.8 m, BM2 as it was.

## When to update this doc

- A tier or slice lands, or its scope changes.
- An owner decision about editing.
