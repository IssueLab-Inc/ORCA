Put IFC models here (they are not committed). The server lists every `*.ifc` in this folder.

Generate the small test model:

    cd server && uv run python -m sightline.fixtures ../samples/fixture-clash.ifc

Sample Navisworks clash reports go in `reports/<name>/`: the XML at the top of that folder, plus the images it links
to. For Northbank, copy `sampled-clashes.xml` and the `tests/**/*.png` of a three-view export from
`ClashWiseDemoModels/northbank/StructuredOutputs/<run>/` into `reports/northbank-navisworks/`.

For the demo, copy the Northbank IFCs from `IssueLab-Inc/ClashWiseDemoModels` (check its licence before hosting them publicly).
