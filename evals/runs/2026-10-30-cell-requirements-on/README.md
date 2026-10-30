# The PC-03 palletising cell from STEP
Result: pass

## Rev A: pass

- Opened from STEP in 1.0 s: 161 of 161 parts (classes by the model; 161 of 161 match the parts list's own IFC class).
- Detection: 112 clashes in 10.3 s; 17 of the 17 planted pairs (expected 17), 95 by design, 0 unexpected.

## C2 fix and export: pass

- The ladder moved with its joints: 4 parts move (CT-301 flat bend 2, CT-301 run 1, CT-301 run 2 along the west fence, CT-301 vertical bend 1); CT-301 riser from EP-301 [150.0] mm taller, its foot [0.0] mm (on the panel).
- C6 by a move (segment 3 north 250 mm): carries 2 parts, 2 segments shorter; hits ES-2 emergency stop station (pallet A exit).
- Check before: 1 collisions, 1 too close; after +150 mm: clear; clear of post W5.
- Exported PC-03-Palletising-Cell-RevA.orca.ifc, PC-03-Palletising-Cell-RevA.orca.step; re-read: the 4 ladder parts [150.0] mm higher; the compressed-air line 17 → 42 parts (the offset's pieces); `Fence top rail S5-SE` 40.0 mm shorter (C3 trim, at its end).

## C1 fix together: pass

- 2 clashes → 1 job (IfcPipeSegment 'PL-301 compressed air DN25 segment 2' x 2 elements: 'CV-301 side rail south', 'CV-301 side rail north'), 43 s.
- Fix: Offset PL-301 down 150 mm past both side rails (offset); checked together: clear.

## C6 route: pass

- The designer's route (reroute 200 mm north at 1.75-2.55 m, then 200 mm north at 4.25-5.05 m): clear, nearest 33 mm, 17 pieces.
- Fix together: 2 clashes → 1 job, 60 s, 2 ideas tried; fix: Local side-step route of air line past C3 and C4 (route: reroute 250 mm north at 1.60-2.70 m, then 250 mm north at 4.10-5.20 m); checked together: clear.

## C7 penetration: pass

- The opening the main needs: Ø130 mm, 220 mm deep (the wall and 10 mm proud of each face).
- Single proposal on #60: 97 s, 3 ideas tried, options ['penetration']; first penetration: Core Ø130 mm opening for DN50 main through west wall (Ø130 mm opening through Wall 'Plant 2 west wall 200 blockwork (existing)', review: architecture, also needs: sleeve, flashing and sealing to external face and making good existing blockwork, architecture review 300 mm from wall edges; sleeve; flashing and sealing to external face; make good existing blockwork).
  - option 1: Core Ø130 mm opening for DN50 main through west wall (penetration, 1 element(s), [0.0, 0.0, 0.0])
- Kept: provision for void written, opening cut; the main clears the wall.
- Exported STEP: `Plant 2 west wall 200 blockwork (existing)` 2655 cm³ smaller (the opening cut), 2 provision for void parts (C7 and C8) in Compressed air, Electrical (alpha 0.35).

## C8 gland hole: pass

- Single proposal on #65: 35 s, 4 ideas tried, options ['move', 'move', 'penetration'].
- Glanded opening for C-302 conduit through EP-301 top gland plate: Ø34 mm opening through Plate 'EP-301 top gland plate 3 mm (cable entry)' (fitted); host: allowed; a fitted gland, no clearance round it; needs cable gland or grommet to enclosure IP rating (muse); hole: hole 34 mm in 500 mm of host (7%); review: none; also needs: cable gland or grommet to enclosure IP rating by panel builder; cable gland or grommet to enclosure IP rating.
- Kept: a 34 mm round fitted hole, cut; the conduit clears the plate.
- Exported STEP: `EP-301 top gland plate 3 mm (cable entry)` 2.72 cm³ smaller (the gland hole).

## Rev B: pass

- Opened from STEP in 0.6 s: 185 of 185 parts (classes by the model; 185 of 185 match the parts list's own IFC class).
- Detection: 93 clashes in 5.1 s; 0 of the 17 planted pairs (expected 0), 93 by design, 0 unexpected.

