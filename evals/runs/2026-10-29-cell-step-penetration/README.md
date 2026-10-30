# The PC-03 palletising cell from STEP
Result: pass

## Rev A: pass

- Opened from STEP in 1.6 s: 159 of 159 parts (classes by the model; 159 of 159 match the parts list's own IFC class).
- Detection: 110 clashes in 1.7 s; 16 of the 16 planted pairs (expected 16), 94 by design, 0 unexpected.

## C2 fix and export: pass

- The run that moves with `CT-301` h2 (same STEP group, touching): 5 parts, CT-301 flat bend 2, CT-301 riser from EP-301, CT-301 run 1, CT-301 run 2 along the west fence, CT-301 vertical bend 1.
- Check before: 1 collisions, 2 too close; after +150 mm: clear; clear of post W5.
- Exported PC-03-Palletising-Cell-RevA.orca.ifc, PC-03-Palletising-Cell-RevA.orca.step; re-read: the 5 ladder parts [150.0] mm higher; the compressed-air line 17 → 42 parts (the offset's pieces); `Fence top rail S5-SE` 40.0 mm shorter (C3 trim, at its end).

## C1 fix together: pass

- 2 clashes → 1 job (IfcPipeSegment 'PL-301 compressed air DN25 segment 2' x 2 elements: 'CV-301 side rail north', 'CV-301 side rail south'), 32 s.
- Fix: Side-step pipe west past both rails (route); checked together: clear.

## C6 route: pass

- The designer's route (reroute 200 mm north at 1.75-2.55 m, then 200 mm north at 4.25-5.05 m): clear, nearest 33 mm, 17 pieces.
- Fix together: 2 clashes → 1 job, 22 s, 2 ideas tried; fix: Reroute pipe north with extra margin past C3 and C4 (route: reroute 250 mm north at 1.70-2.60 m, then 250 mm north at 4.20-5.10 m); checked together: clear.

## C7 penetration: pass

- The opening the main needs: Ø130 mm, 220 mm deep (the wall and 10 mm proud of each face).
- Single proposal on #20: 42 s, 3 ideas tried, options ['penetration']; first penetration: Core opening for air main through west wall (Ø130 mm opening through Wall 'Plant 2 west wall 200 blockwork (existing)', review: architecture, also needs: core drill sleeve and making good by A's team, architect review).
  - option 1: Core opening for air main through west wall (penetration, 1 element(s), [0.0, 0.0, 0.0])
- Kept: provision for void written, opening cut; the main clears the wall.
- Exported STEP: `Plant 2 west wall 200 blockwork (existing)` 2655 cm³ smaller (the opening cut), 1 provision for void part in Compressed air (alpha 0.35).

## Rev B: pass

- Opened from STEP in 4.7 s: 183 of 183 parts (classes by the model; 183 of 183 match the parts list's own IFC class).
- Detection: 92 clashes in 4.1 s; 0 of the 16 planted pairs (expected 0), 92 by design, 0 unexpected.

