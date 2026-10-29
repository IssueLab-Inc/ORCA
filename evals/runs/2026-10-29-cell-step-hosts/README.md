# The PC-03 palletising cell from STEP
Result: pass

## Rev A: pass

- Opened from STEP in 35.6 s: 161 of 161 parts (classes by the model; 160 of 161 match the parts list's own IFC class).
- Detection: 112 clashes in 1.9 s; 17 of the 17 planted pairs (expected 17), 95 by design, 0 unexpected.

## C2 fix and export: pass

- The run that moves with `CT-301` h2 (same STEP group, touching): 5 parts, CT-301 flat bend 2, CT-301 riser from EP-301, CT-301 run 1, CT-301 run 2 along the west fence, CT-301 vertical bend 1.
- Check before: 1 collisions, 3 too close; after +150 mm: clear; clear of post W5.
- Exported PC-03-Palletising-Cell-RevA.orca.ifc, PC-03-Palletising-Cell-RevA.orca.step; re-read: the 5 ladder parts [150.0] mm higher; the compressed-air line 17 → 42 parts (the offset's pieces); `Fence top rail S5-SE` 40.0 mm shorter (C3 trim, at its end).

## C1 fix together: pass

- 2 clashes → 1 job (IfcPipeSegment 'PL-301 compressed air DN25 segment 2' x 2 elements: 'CV-301 side rail south', 'CV-301 side rail north'), 27 s.
- Fix: Offset pipe down 180 mm past both side rails (offset); checked together: clear.

## C6 route: pass

- The designer's route (reroute 200 mm north at 1.75-2.55 m, then 200 mm north at 4.25-5.05 m): clear, nearest 33 mm, 17 pieces.
- Fix together: 2 clashes → 1 job, 24 s, 3 ideas tried; fix: Detour north past C3 and C4 (route: reroute 240 mm north at 1.70-2.60 m, then 240 mm north at 4.20-5.10 m); checked together: clear.

## C7 penetration: pass

- The opening the main needs: Ø130 mm, 220 mm deep (the wall and 10 mm proud of each face).
- Single proposal on #20: 56 s, 3 ideas tried, options ['penetration']; first penetration: Cored opening for air main through west wall (Ø130 mm opening through Wall 'Plant 2 west wall 200 blockwork (existing)', review: structure, also needs: core-drilled Ø130 mm opening with sleeve by A's team, made good masonry and finishes, structural review; core-drilled opening with sleeve; make good masonry and finishes).
  - option 1: Cored opening for air main through west wall (penetration, 1 element(s), [0.0, 0.0, 0.0])
- Kept: provision for void written, opening cut; the main clears the wall.
- Exported STEP: `Plant 2 west wall 200 blockwork (existing)` 2655 cm³ smaller (the opening cut), 2 provision for void parts (C7 and C8) in Compressed air, Electrical (alpha 0.35).

## C8 gland hole: pass

- Single proposal on #111: 47 s, 4 ideas tried, options ['penetration'].
- Gland opening for C-302 conduit through EP-301 top plate: Ø34 mm opening through Plate 'EP-301 top gland plate 3 mm (cable entry)' (fitted); host: allowed; a fitted gland, no clearance round it; needs cable gland to maintain enclosure IP rating (muse); hole: hole 34 mm in 500 mm of host (7%); review: none; also needs: Ø34 mm fitted cable gland, B's team to cut, maintain IP rating; cable gland to maintain enclosure IP rating.
- Kept: a 34 mm round fitted hole, cut; the conduit clears the plate.
- Exported STEP: `EP-301 top gland plate 3 mm (cable entry)` 2.72 cm³ smaller (the gland hole).

## Rev B: pass

- Opened from STEP in 41.2 s: 185 of 185 parts (classes by the model; 185 of 185 match the parts list's own IFC class).
- Detection: 93 clashes in 3.5 s; 0 of the 17 planted pairs (expected 0), 93 by design, 0 unexpected.

