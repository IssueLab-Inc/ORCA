# The PC-03 palletising cell from STEP
Result: pass

## Rev A: pass

- Opened from STEP in 1.7 s: 159 of 159 parts (classes by the model; 159 of 159 match the parts list's own IFC class).
- Detection: 110 clashes in 1.8 s; 16 of the 16 planted pairs (expected 16), 94 by design, 0 unexpected.

## C2 fix and export: pass

- The run that moves with `CT-301` h2 (same STEP group, touching): 5 parts, CT-301 flat bend 2, CT-301 riser from EP-301, CT-301 run 1, CT-301 run 2 along the west fence, CT-301 vertical bend 1.
- Check before: 1 collisions, 2 too close; after +150 mm: clear; clear of post W5.
- Exported PC-03-Palletising-Cell-RevA.orca.ifc, PC-03-Palletising-Cell-RevA.orca.step; re-read: the 5 ladder parts [150.0] mm higher; the compressed-air line 17 → 41 parts (the offset's pieces); `Fence top rail S5-SE` 40.0 mm shorter (C3 trim, at its end).

## C1 fix together: pass

- 2 clashes → 1 job (IfcPipeSegment 'PL-301 compressed air DN25 segment 2' x 2 elements: 'CV-301 side rail north', 'CV-301 side rail south'), 52 s.
- Fix: Offset pipe down 150 mm under both rails (offset); checked together: clear.

## C6 route: pass

- The designer's route (reroute 200 mm north at 1.75-2.55 m, then 200 mm north at 4.25-5.05 m): clear, nearest 33 mm, 17 pieces.
- Fix together: 2 clashes → 1 job, 31 s, 3 ideas tried; fix: Reroute north 240 mm past C3 and C4 (route: reroute 240 mm north at 1.75-2.55 m, then 240 mm north at 4.25-5.05 m); checked together: clear.

## Rev B: pass

- Opened from STEP in 2.9 s: 183 of 183 parts (classes by the model; 183 of 183 match the parts list's own IFC class).
- Detection: 92 clashes in 3.0 s; 0 of the 16 planted pairs (expected 0), 92 by design, 0 unexpected.

