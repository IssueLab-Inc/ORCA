Put IFC models here (they are not committed). The server lists every `*.ifc` in this folder.

Generate the small test model:

    cd server && uv run python -m sightline.fixtures ../samples/fixture-clash.ifc

For the demo, copy the Northbank IFCs from `IssueLab-Inc/ClashWiseDemoModels` (check its licence before hosting them publicly).
