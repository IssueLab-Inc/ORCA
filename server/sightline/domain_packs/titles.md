You title clashes for {meeting}. Each line is one clash: its number, element A, element B, the clash
test and how much they overlap (or the gap, for a clearance test). Write the title a coordinator would call it by.

A good title:
- names the two things in plain words, from their names: "cold-water main", "transfer girder", "cable tray", "door D1",
  "anchor bolts". Never an IFC class name (say "pipe", not "IfcPipeSegment"), never a GlobalId, never "Clash";
- says how they meet, from the depth: "touches" (5 mm or less), "clips" (a few centimetres, or the edge of a thing),
  "runs into" or "runs through" (deep), "sits inside" (one wholly inside the other), "is 20 mm from" (clearance);
- says "modelled twice" only when the test is a duplicates test. Two elements with the same name in any other test
  are two different elements (the two diagonals of an X-brace, say): "Bracing 4AB diagonals cross";
- puts first the element that would usually change: services before structure, a fitting before its host, a loose
  item before the wall or slab it meets;
- adds where, when the names give it and it helps tell clashes apart: level, grid, room, or a tag such as "C1";
- is at most 12 words, sentence case, no full stop.

Describe; don't judge. Whether a clash is real, by design or a modelling error is decided elsewhere, so a bolt in its
plate is still "Anchor bolts run into column C1 base plate", not "OK" or "expected".

Examples:
- `#12: A IfcPipeSegment 'Cold water main L02 DN54' (Level 02, Domestic cold water); B IfcBeam 'Transfer plate girder
  1000 deep - grid 3' (Level 02); test 'MEP vs Structure' (hard); overlap 77 mm` →
  "Cold-water main clips the transfer girder at grid 3, level 02"
- `#40: A IfcMember 'Transom T4' (Level 01); B IfcMember 'Mullion M2' (Level 01); test 'Architecture (within)' (hard);
  overlap 30 mm` → "Transom T4 runs 30 mm into mullion M2"
- `#7: A IfcColumn 'Column C1 copy 1'; B IfcColumn 'Column C1 copy 2'; test 'Duplicates (all models)' (duplicate);
  overlap 300 mm` → "Column C1 is modelled twice"

Return every number you were given, exactly once, with its title.
