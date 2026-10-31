# Demo models

These eight synthetic, IssueLab-owned models ship with ORCA under the repository's [MIT licence](../LICENSE),
copyright 2026 IssueLab Inc. They contain no customer data. A normal clone includes them; no private access,
separate download or Git LFS is required.

## Included files and provenance

| Files | Purpose | Creation period |
|---|---|---|
| `Northbank-Architecture.ifc`, `Northbank-MEP.ifc`, `Northbank-Site.ifc`, `Northbank-Structure.ifc` | The four files opened by the Northbank demo card | Before the hackathon; baseline data |
| `Northbank-Grids.ifc` | Shared grid/level reference | Before the hackathon; baseline data |
| `Northbank-MEP-Rev04.ifc` | Designer's fixed revision, for comparison with ORCA's fixes | Before the hackathon; baseline data |
| `PC-03-Palletising-Cell-RevA.step` | The machine demo, with planted coordination problems | During the hackathon |
| `PC-03-Palletising-Cell-RevB.step` | Designer's fixed machine revision | During the hackathon |

Together the files are about 15 MB. They are generated outputs copied byte for byte from IssueLab's private
demo-models repository; no generator code, Revit files or other application code is copied. Original metadata,
IFC GlobalIds, geometry and federation coordinates are preserved. `.gitattributes` disables newline conversion
for these files. Regenerate them in the source repository rather than editing the IFC/STEP text by hand.

**Northbank is a pre-existing synthetic baseline asset**, used to demonstrate and evaluate ORCA, not a model
created during the challenge. ORCA's application code was written during the challenge. The full disclosure is
in [BUILT_DURING_HACKATHON.md](../BUILT_DURING_HACKATHON.md).

## Open the demos

Follow [the local setup](../README.md#run-locally), then use the landing page's demo cards. The server lists every
`*.ifc`, `*.step` and `*.stp` at the top of this folder. The fixed revisions are available from **Models** and are
not opened alongside the originals by default.

IFC opens without an API key. STEP converts to IFC when opened; AI part classification needs a configured model
key. Without it the geometry still converts, with generic IFC classes, so the classified machine demo's results
can differ. For a first check without credentials, use the IFC fixture described in the README.

## Optional local files and evaluation data

Other files in `samples/` remain gitignored: use this folder for local models, fixture outputs, reports and
conversion caches. Do not commit customer data. The deploy copies supported data files from this folder to the
public app, so review its contents before deploying.

- Generate the small fixture, from the repo root:
  `uv run --directory server --locked python -m sightline.fixtures ../samples/fixture-clash.ifc`.
- Optional Navisworks reports go in `reports/<name>/`, with XML at the top and the referenced images at their
  relative paths. The Northbank three-view export is not included; the built-in detection demo needs no such report.
- `step-cache/` can hold ready, classified STEP conversions. To prepare it, create the directory, configure a
  model key, and open each STEP once. IFC and manifest files are saved by the STEP's hash. The cache is not bundled.
- Some [evals](../evals/README.md) require generator-side answer keys, extra IFCs or Navisworks exports from the private
  source repository. `DEMO_MODELS` selects that checkout. Those evals are separate from public local setup and unit tests.

The model files needed for both public demo cards are included. A separate public model download is not required.
