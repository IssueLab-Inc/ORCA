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
| 0b | A parametric fixture with every construct above, a model-consistency check in every edit's check, and a test matrix of every op on every construct | planned |
| 1 | Keep the model consistent: own copies (types, sets, mapped bodies), layer and profile sets, `Axis`, quantities, path joins | planned |
| 2 | MEP: offsets by hand (up or sideways), bends at any angle, transitions on a carried resize, disconnect, join | planned |
| 3 | Editable properties: attributes, psets, type, material, classification, container | planned |

## Test matrix

Filled in as Tier 0b lands: each hand op against each construct, either kept consistent or refused in words.

## When to update this doc

- A tier or slice lands, or its scope changes.
- An owner decision about editing.
