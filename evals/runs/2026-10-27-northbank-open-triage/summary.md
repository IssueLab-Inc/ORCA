# Triage run: 2026-10-27-northbank-open-triage

Model `meta-models/muse-spark-open`, images A/B/C, prompt `server/sightline/domain_packs/triage.md`, strict JSON schema.

- Clashes: 317; replies: 317; failed calls: 0; median latency 6.1 s (max 26.0 s)
- Verdicts: by_design 145, non_physical 130, real_clash 21, modelling_error 21

## Against the metadata reference

| Reference | Expected | Clashes | Match |
|---|---|---|---|
| answer_key | real_clash, and move/modify the service | 6 | 6/6 (100%) |
| non_physical | non_physical | 129 | 129/129 (100%) |
| touching | by_design or non_physical | 55 | 49/55 (89%) |

### Misses

| Clash | Pair | mm | Reference | Verdict / action | Model's reading |
|---|---|---|---|---|---|
| test-074-IfcGeographicElement--Site--vs-I-0e31aa09/clash-0002-0174991f | IfcGeographicElement 'Tree canopy' vs IfcLightFixture 'Riverside lighting column 5 m' | -0.5 | touching | real_clash / move_B | Element A is a tree canopy volume and Element B is a 5 m riverside lighting column. At ~5.0 m height the column just penetrates the edge of the canopy by 0.5 mm, appearing to pass through it in one view and just touching in the orthogonal view. This is a real site coordination problem because foliage will obstruct light distribution and future growth will envelop the fitting. |
| test-924-IfcFurniture--Architecture--vs-I-c66731f4/clash-0161-00ee823a | IfcFurniture 'Task chair' vs IfcFurniture 'Task chair' | -0.0 | touching | modelling_error / fix_model | Both elements are IfcFurniture 'Task chair' instances on Level 02 from the same architecture model. They are placed at the identical location and their volumes overlap with a signed distance of -0.0 mm. This is a duplicate/overlapping placement, not an intended design connection, and is a model cleanliness issue rather than a constructability conflict. |
| test-924-IfcFurniture--Architecture--vs-I-c66731f4/clash-0001-46185d83 | IfcFurniture 'Tea point counter with base units' vs IfcFurniture 'Tea point counter with base units' | -0.0 | touching | modelling_error / fix_model | Both elements are the same IfcFurniture type 'Tea point counter with base units' on Level 03 from the same architecture model. They are placed at the identical location [9.52, -2.62, 8.86] with -0.0 mm overlap and coincide almost perfectly in all views. This is a duplicate instance, not a coordination conflict between different building systems. |
| test-1176-IfcCurtainWall--Architecture--vs-23ce9abd/clash-0006-96206683 | IfcDoor 'Main entrance - automatic sliding doors' vs IfcDoor 'Main entrance - automatic sliding doors' | -0.0 | touching | modelling_error / fix_model | Both elements are the same IfcDoor 'Main entrance - automatic sliding doors' from Northbank-Architecture.ifc hosted in 'Curtain wall S - Level 01'. The green horizontal header/transom sits directly on the top edge of the red vertical door leaf and they only touch at -0.0 mm. This is not a coordination clash between different systems but a duplicated/over-segmented model of the same door assembly at a designed joint. |
| test-1176-IfcCurtainWall--Architecture--vs-23ce9abd/clash-0004-2b0be7f4 | IfcDoor 'Main entrance - automatic sliding doors' vs IfcDoor 'Main entrance - automatic sliding doors' | -0.0 | touching | modelling_error / fix_model | Both elements are identical instances of the 'Main entrance - automatic sliding doors' IfcDoor hosted in 'Curtain wall S - Level 01' on Level 01. They occupy the same opening and overlap along the vertical edge with a signed distance of -0.0 mm, effectively just touching. This indicates a duplicated door placement in the same curtain wall, not a coordination conflict between different systems. |
| test-1176-IfcCurtainWall--Architecture--vs-23ce9abd/clash-0003-6470ce70 | IfcDoor 'Main entrance - automatic sliding doors' vs IfcDoor 'Main entrance - automatic sliding doors' | -0.0 | touching | modelling_error / fix_model | Both elements are IfcDoor instances with the identical name 'Main entrance - automatic sliding doors' hosted in the same 'Curtain wall S - Level 01' on Level 01. They occupy the same opening and only touch/overlap at -0.0 mm at their vertical edges near floor level. This is not a service-vs-structure conflict but the same door placed twice in the same location. |

### Answer-key clashes

- **#042** test-216-IfcDuctSegment--MEP--vs-IfcProje-e962c793/clash-0001-a90d5b0d (-150.0 mm): real_clash, high, modify_A. Element A is a 600x300 mm supply-air duct main on Level 02 (red) and Element B is a 1000 mm deep transfer plate girder on grid 3 (green). The duct crosses perpendicular to the girder and penetrates its solid web with 150 mm overlap, missing the adjacent rectangular web openings visible in the images. A transfer girder is a primary structural element that cannot be cut on site, so this is a real hard clash requiring design coordination. Fix: Reroute duct to avoid transfer girder or obtain engineered penetration design and model a coordinated opening/sleeve; do not penetrate transfer plate girder without structural approval.
- **#042** test-660-IfcBeam--Structure--vs-IfcDuctSe-b544ed0f/clash-0001-0e0fcb14 (-150.0 mm): real_clash, high, modify_B. Element A is a 1000mm deep transfer plate girder on grid 3 and Element B is a 600x300 supply air duct. The duct crosses perpendicular to the girder and penetrates the solid web by 150mm, missing the adjacent pre-formed rectangular openings visible in the beam. A transfer girder is primary structure and cannot be notched on site, so this is a genuine hard conflict. Fix: Reroute/shift the duct to align with the nearest approved web opening or obtain structural design for a new opening with stiffening - do not cut transfer girder as modelled.
- **#057** test-764-IfcCableCarrierSegment--MEP--vs-ae35a75c/clash-0002-0dc88101 (-40.0 mm): real_clash, high, modify_A. Element A is a 300x100 LV cable tray on Level 02 and Element B is a 1000mm deep transfer plate girder on grid 3 at the same level. The tray crosses perpendicular to the girder at the same elevation with 40mm overlap, so the tray volume penetrates the beam. A transfer plate girder cannot be penetrated or notched without a designed structural opening, so this is a genuine coordination conflict. Fix: Reroute the cable tray with a vertical offset to pass clear under/over the transfer girder; do not penetrate the 1000mm transfer girder without a formally designed structural opening.
- **#057** test-764-IfcCableCarrierSegment--MEP--vs-ae35a75c/clash-0001-9f3b9a98 (-60.0 mm): real_clash, medium, move_A. Element A is a 300x100 mm LV power cable tray at Level 02 and Element B is a 1000 mm deep transfer plate girder on grid 3. The tray runs perpendicular to the girder and hits the solid web near its bottom edge with 60 mm overlap, missing the nearby preformed rectangular openings visible in the girder. This is a physical hard clash that would prevent installation, not an intended connection. Fix: Raise/lower the tray ~60-100 mm to centre it in the designated opening in the transfer girder, or have Structure review/enlarge the opening if tray elevation is fixed.
- **#057** test-953-IfcBeam--Structure--vs-IfcCableC-c69d263a/clash-0002-6d2fc775 (-40.0 mm): real_clash, high, modify_B. The red element is a 1000 mm deep transfer plate girder and the green element is a 300x100 mm LV cable tray. They cross perpendicularly at the same elevation on Level 02 with a 40 mm hard overlap exceeding the 25 mm tolerance. A tray cannot penetrate a transfer girder without a designed opening, so this is a genuine physical conflict. Fix: Reroute the tray with a vertical offset to pass clear under the 1000 mm girder, or coordinate a formal penetration/opening design with Structure.
- **#057** test-953-IfcBeam--Structure--vs-IfcCableC-c69d263a/clash-0001-400cc345 (-60.0 mm): real_clash, high, move_B. Element A is a 1000 mm deep transfer plate girder (primary structure) and Element B is a 300x100 LV cable tray. The tray runs perpendicular and overlaps the girder web by 60 mm instead of passing through one of the nearby rectangular penetrations visible in the girder, creating a hard physical conflict. Fix: Lower/raise or offset the cable tray to align with the provided opening in the transfer girder with required clearance, or obtain structural approval for a new/modified opening.

## Verdicts by class pair (unscored where no reference applies)

| Pair | real_clash | by_design | non_physical | modelling_error |
|---|---|---|---|---|
| IfcAirTerminal vs IfcSpace |  |  | 5 |  |
| IfcBeam vs IfcBeam | 2 | 4 |  | 2 |
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
| IfcColumn vs IfcSlab |  | 12 |  | 1 |
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
| IfcDoor vs IfcDoor |  |  |  | 7 |
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
| IfcFooting vs IfcWall | 3 | 4 |  | 1 |
| IfcFurniture vs IfcFurniture |  | 3 |  | 2 |
| IfcFurniture vs IfcSlab |  | 5 |  |  |
| IfcFurniture vs IfcSpace |  |  | 5 |  |
| IfcGeographicElement vs IfcGeographicElement |  | 4 | 1 |  |
| IfcGeographicElement vs IfcLightFixture | 2 |  |  |  |
| IfcGeographicElement vs IfcWall |  | 3 |  |  |
| IfcMechanicalFastener vs IfcPlate |  | 11 |  |  |
| IfcMember vs IfcMember | 3 | 10 |  | 4 |
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
