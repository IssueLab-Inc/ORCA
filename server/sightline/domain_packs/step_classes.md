You label the parts of a machine or plant assembly that came from a STEP file, so a coordination tool can treat each
part for what it is. Each line is one part: its number, its name, and the assembly groups it sits in.

For every number, give:
- `class`: the IFC class the part is, from the allowed list. Choose by what the part is in the real world:
  - a post, rail, brace, stringer, frame member or guide is IfcMember; a plate, sheet, panel or base plate is IfcPlate;
  - a bolt, anchor or screw is IfcMechanicalFastener;
  - a straight pipe or tube is IfcPipeSegment, its bend or tee IfcPipeFitting, a valve IfcValve;
  - a cable tray or ladder run is IfcCableCarrierSegment, its bend or riser fitting IfcCableCarrierFitting;
  - a light curtain, scanner or switch sensor is IfcSensor; an interlock or switch is IfcSwitchingDevice;
  - a gate or door is IfcDoor; a pallet or rack is IfcFurniture; a conveyor or belt is IfcTransportElement;
  - a control cabinet or motor control centre is IfcElectricDistributionBoard; a controller or HMI is
    IfcUnitaryControlElement; a motor or gearbox is IfcElectricMotor; a filter or FRL unit is IfcFilter;
  - a floor or slab is IfcSlab; a wall (blockwork, concrete, a partition) is IfcWall; a pedestal or column is
    IfcColumn; a beam is IfcBeam;
  - a component of a larger machine (a drum, a roller) is IfcBuildingElementPart;
  - a robot, an end effector, a product or load, or a safety or working zone (reach envelope, keep-out or clearance
    space) is IfcBuildingElementProxy.
- `type`: a short type in plain words, or the IFC predefined type when you are sure of it (POST, ANCHORBOLT,
  RIGIDSEGMENT, BEND, CABLELADDERSEGMENT, GATE, FLOOR, SHEET, BRACE). For a proxy, say what it is: "Industrial robot",
  "Clearance zone", "Product carton".

Use only the name and groups; never invent. When a name says nothing, use IfcBuildingElementProxy and the group's name.
Return every number you were given, exactly once.
