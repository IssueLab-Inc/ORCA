# The PC-03 palletising cell from STEP
Result: pass

## Rev A: pass

- Opened from STEP in 1.1 s from the cache (36.3 s on the first conversion, with the class call): 144 of 144 parts (classes by the model; 144 of 144 match the parts list's own IFC class).
- Detection: 107 clashes in 1.2 s; 13 of the 13 planted pairs (expected 13), 94 by design, 0 unexpected.

## C2 fix and export: pass

- The run that moves with `CT-301` h2 (same STEP group, touching): 5 parts, CT-301 flat bend 2, CT-301 riser from EP-301, CT-301 run 1, CT-301 run 2 along the west fence, CT-301 vertical bend 1.
- Check before: 1 collisions, 2 too close; after +150 mm: clear; clear of post W5.
- Exported PC-03-Palletising-Cell-RevA.sightline.ifc, PC-03-Palletising-Cell-RevA.sightline.step; re-read: the 5 ladder parts [150.0] mm higher; the compressed-air line 7 → 15 parts (the offset's pieces); `Fence top rail S5-SE` 40.0 mm shorter (C3 trim, at its end).

## C1 fix together: pass

- 2 clashes → 1 job (IfcPipeSegment 'PL-301 compressed air DN25 segment 2' x 2 elements: 'CV-301 side rail south', 'CV-301 side rail north'), 29 s.
- Fix: Local offset pipe down 150mm past both rails (offset); checked together: clear.

## Rev B: pass

- Opened from STEP in 1.5 s from the cache (37.3 s on the first conversion): 152 of 152 parts (classes by the model; 152 of 152 match the parts list's own IFC class).
- Detection: 92 clashes in 1.6 s; 0 of the 13 planted pairs (expected 0), 92 by design, 0 unexpected.

