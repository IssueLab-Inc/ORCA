# The PC-03 palletising cell from STEP
Result: pass

## Rev A: pass

- Opened from STEP in 46.1 s (first conversion, with the class call; ~1.5 s from the cache): 144 of 144 parts (classes by the model; 144 of 144 match the parts list's own IFC class).
- Detection: 107 clashes in 2.2 s; 13 of the 13 planted pairs (expected 13), 94 by design, 0 unexpected.

## C2 fix and export: pass

- The run that moves with `CT-301` h2 (same STEP group, touching): 5 parts, CT-301 flat bend 2, CT-301 riser from EP-301, CT-301 run 1, CT-301 run 2 along the west fence, CT-301 vertical bend 1.
- Check before: 1 collisions, 2 too close; after +150 mm: clear; clear of post W5.
- Exported PC-03-Palletising-Cell-RevA.orca.ifc, PC-03-Palletising-Cell-RevA.orca.step; re-read: the 5 ladder parts [150.0] mm higher; the compressed-air line 7 → 7 parts (C1 was a move this run); `Fence top rail S5-SE` 40.0 mm shorter (C3 trim, at its end).

## C1 fix together: pass

- 2 clashes → 1 job (IfcPipeSegment 'PL-301 compressed air DN25 segment 2' x 2 elements: 'CV-301 side rail south', 'CV-301 side rail north'), 100 s.
- Fix: Shift pipe west past conveyor end (move); checked together: clear.

## Rev B: pass

- Opened from STEP in 38.3 s: 152 of 152 parts (classes by the model; 152 of 152 match the parts list's own IFC class).
- Detection: 92 clashes in 3.2 s; 0 of the 13 planted pairs (expected 0), 92 by design, 0 unexpected.

