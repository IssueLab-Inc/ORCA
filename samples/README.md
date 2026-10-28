Put models here (they are not committed): the server lists every `*.ifc`, `*.step` and `*.stp` in this folder. A STEP
model is converted to IFC when it opens (`server/sightline/step.py`).

Generate the small test model:

    cd server && uv run python -m sightline.fixtures ../samples/fixture-clash.ifc

Sample Navisworks clash reports go in `reports/<name>/`: the XML at the top of that folder, plus the images it links
to. For Northbank, copy `sampled-clashes.xml` and the `tests/**/*.png` of a three-view export from
`ClashWiseDemoModels/northbank/StructuredOutputs/<run>/` into `reports/northbank-navisworks/`.

For the demo, copy the Northbank IFCs from `IssueLab-Inc/ClashWiseDemoModels` (check its licence before hosting them publicly).

For the second demo, copy `PC-03-Palletising-Cell-RevA.step` and `-RevB.step` from ClashWiseDemoModels
`palletising-cell/STEP/`. To ship their conversion (so the first opening after a restart does not wait about 30 s for
the part classes), create `step-cache/` here and open each STEP once with the server running locally: the converted IFC
and its manifest are saved there by the file's hash and deployed with the samples.
