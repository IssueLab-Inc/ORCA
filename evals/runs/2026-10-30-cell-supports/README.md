# The PC-03 palletising cell from STEP
Result: pass

## Rev A: pass

- Opened from STEP in 0.2 s: 161 of 161 parts (classes by the model; 161 of 161 match the parts list's own IFC class).
- Detection: 112 clashes in 1.7 s; 17 of the 17 planted pairs (expected 17), 95 by design, 0 unexpected.

## C2 fix and export: pass

- The run that moves with `CT-301` h2 (same STEP group, touching): 5 parts, CT-301 flat bend 2, CT-301 riser from EP-301, CT-301 run 1, CT-301 run 2 along the west fence, CT-301 vertical bend 1.
- Check before: 1 collisions, 3 too close; after +150 mm: clear; clear of post W5.
- Exported PC-03-Palletising-Cell-RevA.orca.ifc, PC-03-Palletising-Cell-RevA.orca.step; re-read: the 5 ladder parts [150.0] mm higher; the compressed-air line 17 → 42 parts (the offset's pieces); `Fence top rail S5-SE` 40.0 mm shorter (C3 trim, at its end).

## C1 fix together: pass

- 2 clashes → 1 job (IfcPipeSegment 'PL-301 compressed air DN25 segment 2' x 2 elements: 'CV-301 side rail south', 'CV-301 side rail north'), 67 s.
- Fix: Dog-leg pipe 900 mm west past both rails (route); checked together: clear.

## C6 route: pass

- The designer's route (reroute 200 mm north at 1.75-2.55 m, then 200 mm north at 4.25-5.05 m): clear, nearest 33 mm, 17 pieces.
- Fix together: 2 clashes → 1 job, 27 s, 2 ideas tried; fix: Detour pipe 250mm north past C3 and C4 (route: reroute 250 mm north at 1.50-2.80 m, then 250 mm north at 4.00-5.30 m); checked together: clear.

## C7 penetration: pass

- The opening the main needs: Ø130 mm, 220 mm deep (the wall and 10 mm proud of each face).
- Single proposal on #20: 61 s, 3 ideas tried, options ['move', 'penetration']; first penetration: Core Ø130 mm opening for air main through west wall (Ø130 mm opening through Wall 'Plant 2 west wall 200 blockwork (existing)', review: architecture, also needs: sleeve plus flashing and sealing to external weathering by architecture review, 150 mm from wall edges; sleeve; flashing and sealing to external weathering).
  - option 1: Lift whole air-main run over wall head (move, 41 element(s), [0.0, 0.0, 3.4])
  - option 2: Core Ø130 mm opening for air main through west wall (penetration, 1 element(s), [0.0, 0.0, 0.0])
- Kept: provision for void written, opening cut; the main clears the wall.
- Exported STEP: `Plant 2 west wall 200 blockwork (existing)` 2655 cm³ smaller (the opening cut), 2 provision for void parts (C7 and C8) in Compressed air, Electrical (alpha 0.35).

## C8 gland hole: pass

- Single proposal on #111: 58 s, 4 ideas tried, options ['move', 'penetration'].
- Gland opening for C-302 conduit through EP-301 top plate: Ø34 mm opening through Plate 'EP-301 top gland plate 3 mm (cable entry)' (fitted); host: allowed; a fitted gland, no clearance round it; needs cable gland to enclosure IP rating (muse); hole: hole 34 mm in 500 mm of host (7%); review: none; also needs: fitted Ø34 mm cable gland to enclosure IP rating by B's team; cable gland to enclosure IP rating.
- Kept: a 34 mm round fitted hole, cut; the conduit clears the plate.
- Exported STEP: `EP-301 top gland plate 3 mm (cable entry)` 2.72 cm³ smaller (the gland hole).

## Rev B: pass

- Opened from STEP in 42.9 s: 185 of 185 parts (classes by the model; 185 of 185 match the parts list's own IFC class).
- Detection: 93 clashes in 3.0 s; 0 of the 17 planted pairs (expected 0), 93 by design, 0 unexpected.

