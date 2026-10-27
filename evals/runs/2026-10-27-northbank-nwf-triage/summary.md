# Triage run: 2026-10-27-northbank-nwf-triage

Model `muse-spark-1.3-contributor`, images A/B/C, prompt `server/sightline/domain_packs/triage.md`, strict JSON schema.

- Clashes: 317; replies: 317; failed calls: 0; median latency 10.0 s (max 56.1 s)
- Verdicts: by_design 153, non_physical 129, real_clash 23, modelling_error 12

## Against the metadata reference

| Reference | Expected | Clashes | Match |
|---|---|---|---|
| answer_key | real_clash, and move/modify the service | 6 | 6/6 (100%) |
| non_physical | non_physical | 129 | 129/129 (100%) |
| touching | by_design or non_physical | 55 | 51/55 (93%) |

### Misses

| Clash | Pair | mm | Reference | Verdict / action | Model's reading |
|---|---|---|---|---|---|
| test-074-IfcGeographicElement--Site--vs-I-0e31aa09/clash-0002-0174991f | IfcGeographicElement 'Tree canopy' vs IfcLightFixture 'Riverside lighting column 5 m' | -0.5 | touching | real_clash / move_B | Element A is a modelled tree canopy and Element B is a 5 m riverside lighting column. The top of the column at about 5.0 m height penetrates the canopy volume. This is a problem because foliage at the luminaire will block light and grow around the pole. |
| test-924-IfcFurniture--Architecture--vs-I-c66731f4/clash-0161-00ee823a | IfcFurniture 'Task chair' vs IfcFurniture 'Task chair' | -0.0 | touching | modelling_error / fix_model | Both elements are Task chair furniture instances on Level 02. They occupy the same location and touch with essentially zero clearance at seat height. This is a duplicated overlapping placement, not a design coordination conflict. |
| test-924-IfcFurniture--Architecture--vs-I-c66731f4/clash-0123-9412b4df | IfcFurniture 'Task chair' vs IfcFurniture 'Task chair' | -0.0 | touching | modelling_error / fix_model | Both elements are the same Task chair type on Level 01 at the same location. The seat of one coincides with the post of the other at about 0.42 m height to form a normal chair assembly, indicating duplicate coincident placement. This is not a coordination conflict but a duplicated model instance. |
| test-924-IfcFurniture--Architecture--vs-I-c66731f4/clash-0070-226bb85c | IfcFurniture 'Task chair' vs IfcFurniture 'Task chair' | -0.0 | touching | modelling_error / fix_model | Both elements are Task chairs on Level 01. The stem of one chair is exactly concentric with the circular base of the other at floor level with 0 mm overlap. This perfect alignment indicates the same chair placed twice at identical coordinates, not a coordination conflict. |

### Answer-key clashes

- **#042** test-216-IfcDuctSegment--MEP--vs-IfcProje-e962c793/clash-0001-a90d5b0d (-150.0 mm): real_clash, high, modify_A. The red element is a 600x300 supply-air duct and the green element is a 1000 mm deep transfer plate girder at Level 02. The duct cuts perpendicularly through the solid web of the girder with 150 mm overlap, missing the adjacent formed openings. A transfer girder cannot be cut on site, so this is a blocking coordination conflict. Fix: Reroute the supply main below or around the transfer girder, or obtain structural approval for a reinforced sleeved opening.
- **#042** test-660-IfcBeam--Structure--vs-IfcDuctSe-b544ed0f/clash-0001-0e0fcb14 (-150.0 mm): real_clash, high, move_B. A 1000 mm deep transfer plate girder crosses a 600x300 supply-air main duct at Level 02. The duct intersects the girder web with 150 mm overlap, clipping the steel rather than passing cleanly through a provided opening. This blocks coordination because the primary transfer structure cannot be cut to suit services. Fix: Shift the supply duct to align with a designated opening or to clear below the transfer girder.
- **#057** test-764-IfcCableCarrierSegment--MEP--vs-ae35a75c/clash-0002-0dc88101 (-40.0 mm): real_clash, medium, modify_A. Element A is a 300x100 LV power cable tray and Element B is a 1000 mm deep structural transfer plate girder on Level 02. The tray crosses the girder with a 40 mm hard overlap. A tray cannot penetrate a primary transfer girder, so the MEP route must be changed. Fix: Offset/drop the LV cable tray to clear the soffit/flange of the 1000 mm transfer girder.
- **#057** test-764-IfcCableCarrierSegment--MEP--vs-ae35a75c/clash-0001-9f3b9a98 (-60.0 mm): real_clash, high, modify_A. Element A is a 300x100 LV cable tray and Element B is a 1000 mm deep transfer plate girder at Level 02. The tray runs into/through the girder with 60 mm overlap at the crossing. A service cannot pass through a primary transfer member without a coordinated opening, so this is a real coordination problem. Fix: Offset/reroute the tray to clear the transfer girder or get Structural approval for an enlarged sleeved opening.
- **#057** test-953-IfcBeam--Structure--vs-IfcCableC-c69d263a/clash-0002-6d2fc775 (-40.0 mm): real_clash, high, modify_B. Element A is a 1000mm deep structural transfer plate girder and Element B is a 300x100 LV power cable tray at Level 02. The tray runs perpendicular and overlaps the girder by 40mm at the crossing. A transfer girder cannot be penetrated by a tray without a designed opening, so this is a genuine coordination conflict. Fix: Reroute LV cable tray to pass under or over the 1000mm deep transfer girder with clearance, do not penetrate the girder.
- **#057** test-953-IfcBeam--Structure--vs-IfcCableC-c69d263a/clash-0001-400cc345 (-60.0 mm): real_clash, high, move_B. Element A is a 1000 mm deep structural transfer plate girder and Element B is a 300x100 mm LV cable tray. The tray runs perpendicular into the girder web at its bottom edge with 60 mm overlap instead of passing through one of the adjacent pre-formed openings. This is a physical conflict with primary transfer structure that cannot be cut on site. Fix: Lower or shift the cable tray to clear the bottom of the transfer girder or to pass through one of the existing beam openings.

## Verdicts by class pair (unscored where no reference applies)

| Pair | real_clash | by_design | non_physical | modelling_error |
|---|---|---|---|---|
| IfcAirTerminal vs IfcSpace |  |  | 5 |  |
| IfcBeam vs IfcBeam | 2 | 6 |  |  |
| IfcBeam vs IfcCableCarrierSegment | 4 |  |  |  |
| IfcBeam vs IfcColumn |  | 11 |  |  |
| IfcBeam vs IfcDuctSegment | 2 |  |  |  |
| IfcBeam vs IfcPlate |  | 6 |  |  |
| IfcBeam vs IfcSpace |  |  | 9 |  |
| IfcBuildingElementProxy vs IfcBuildingElementProxy |  | 5 |  |  |
| IfcBuildingElementProxy vs IfcGeographicElement |  | 5 |  |  |
| IfcCableCarrierFitting vs IfcCableCarrierFitting |  |  |  | 2 |
| IfcCableCarrierSegment vs IfcSpace |  |  | 5 |  |
| IfcColumn vs IfcFooting |  | 6 |  |  |
| IfcColumn vs IfcSlab |  | 13 |  |  |
| IfcColumn vs IfcSpace |  |  | 6 |  |
| IfcCovering vs IfcMember |  | 5 |  |  |
| IfcCovering vs IfcSpace |  |  | 5 |  |
| IfcCovering vs IfcWall | 1 |  |  |  |
| IfcDamper vs IfcDistributionPort |  |  | 3 |  |
| IfcDamper vs IfcSpace |  |  | 5 |  |
| IfcDistributionPort vs IfcDistributionPort |  |  | 18 |  |
| IfcDistributionPort vs IfcDuctFitting |  |  | 4 |  |
| IfcDistributionPort vs IfcDuctSegment |  |  | 2 |  |
| IfcDistributionPort vs IfcElectricDistributionBoard |  |  | 3 |  |
| IfcDistributionPort vs IfcFlowMeter |  |  | 5 |  |
| IfcDistributionPort vs IfcPipeFitting |  |  | 4 |  |
| IfcDistributionPort vs IfcPipeSegment |  |  | 7 |  |
| IfcDistributionPort vs IfcSpace |  |  | 6 |  |
| IfcDistributionPort vs IfcValve |  |  | 3 |  |
| IfcDoor vs IfcDoor |  | 6 |  | 1 |
| IfcDoor vs IfcMember |  | 3 |  |  |
| IfcDoor vs IfcSlab |  | 5 |  |  |
| IfcDoor vs IfcSpace |  |  | 5 |  |
| IfcDoor vs IfcWall |  | 5 |  |  |
| IfcDuctFitting vs IfcDuctFitting |  |  |  | 1 |
| IfcDuctFitting vs IfcSpace |  |  | 4 |  |
| IfcDuctSegment vs IfcSpace |  |  | 5 |  |
| IfcFooting vs IfcFooting |  | 6 |  |  |
| IfcFooting vs IfcMechanicalFastener |  | 12 |  |  |
| IfcFooting vs IfcPlate | 4 |  |  | 1 |
| IfcFooting vs IfcSlab |  | 4 |  |  |
| IfcFooting vs IfcWall | 4 | 4 |  |  |
| IfcFurniture vs IfcFurniture |  | 2 |  | 3 |
| IfcFurniture vs IfcSlab |  | 5 |  |  |
| IfcFurniture vs IfcSpace |  |  | 5 |  |
| IfcGeographicElement vs IfcGeographicElement |  | 5 |  |  |
| IfcGeographicElement vs IfcLightFixture | 2 |  |  |  |
| IfcGeographicElement vs IfcWall |  | 3 |  |  |
| IfcMechanicalFastener vs IfcPlate |  | 11 |  |  |
| IfcMember vs IfcMember | 4 | 9 |  | 4 |
| IfcMember vs IfcPlate |  | 2 |  |  |
| IfcMember vs IfcSpace |  |  | 5 |  |
| IfcPipeFitting vs IfcPipeSegment |  | 1 |  |  |
| IfcPipeSegment vs IfcSpace |  |  | 5 |  |
| IfcPipeSegment vs IfcValve |  | 1 |  |  |
| IfcRailing vs IfcRailing |  | 5 |  |  |
| IfcRailing vs IfcSpace |  |  | 5 |  |
| IfcSlab vs IfcStairFlight |  | 1 |  |  |
| IfcSlab vs IfcWall |  | 3 |  |  |
| IfcSpace vs IfcWall |  |  | 5 |  |
| IfcWall vs IfcWall |  | 3 |  |  |
