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
| 1 | Keep the model consistent: own copies (types, sets, mapped bodies), layer and profile sets, `Axis`, quantities, path joins | planned |
| 2 | MEP: offsets by hand (up or sideways), bends at any angle, transitions on a carried resize, disconnect, join | planned |
| 3 | Editable properties: attributes, psets, type, material, classification, container | planned |

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
| `joins` | how far a path join's ATSTART/ATEND end is from the other element's axis, in plan | block, past 5 mm |
| `type` | a digest of everything under the type's maps | block (unless the edit is to the type) |
| `quantities` | the body's volume and the `Qto_*BaseQuantities` values | warn, when the volume changed and they did not |

Geometry comes from `ifcopenshell.geom.create_shape` in the element's own placement, built only for elements that carry
one of these. Northbank carries base quantities only (36 on the architecture model), so it sees the warning and nothing
else.

## Test matrix

`server/tests/test_parametric_edits.py` on `fixtures.build_parametric_fixture` (walls W1, W2; slab SL1; beams BM1, BM2;
mapped fittings F1, F2). "Refused" is the words of the refusal; Tier 1 turns refusals into consistent edits.

| Edit | Wall (layers, axis, join, quantities) | Slab (layers, quantities) | Beam (profile, axis, quantities) | Mapped fitting |
|---|---|---|---|---|
| Push the top / an end / a side | height: kept, quantities warn · length: refused (axis) · thickness: refused (layers) | thickness: refused (layers) · size: kept, quantities warn | length: refused (axis) · section: refused (profile) | refused (from its type) |
| Move | up: kept · off its join: refused (joins) | kept | kept | kept |
| Void | kept, quantities warn | | | |
| Split / remove a section | refused (axis) | kept, quantities warn on both pieces | refused (axis) | refused (from its type) |
| Clip | | | | refused (from its type) |
| Delete | kept | | | kept |

Not yet read: the fix agent's own edits (offsets, routes, resizes) go through `plans.apply`, not `manual.check`; on a
model with these constructs they are not yet checked for consistency.

## When to update this doc

- A tier or slice lands, or its scope changes.
- An owner decision about editing.
