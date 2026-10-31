# Built during the hackathon

The Meta Global AI Developer Hackathon building period runs Oct 27 – Nov 4, 2026. ORCA's application code was
written during that period, starting with the first commit on Oct 27. The git history is the record. This
repository also includes pre-existing synthetic baseline models and depends on third-party libraries, as
disclosed below; those are not claimed as code or assets created during the challenge.

## New during the event

- The ORCA web app (`web/`): the IFC viewer (modes, section box, measure, captures), the clash list, triage, insights,
  the clash panel, chat and voice, the plan panel, the report dialog, the guided tours and the landing page.
- The ORCA server (`server/`):
  - the scene over IfcOpenShell, the geometry check, ORCA's own clash detection;
  - edits: moves, local offsets with bends, trims, wider fixes;
  - the propose → verify → retry → rank agent, plans and root causes, triage and clash titles;
  - Navisworks report import, the PDF report and BCF, IFC export;
  - STEP conversion and STEP write-back;
  - the web API, the MCP server, owner settings and demo caps.
- The Meta model integration (Muse Spark, Muse Spark Open, Muse Voice Transcribe).
- The domain packs, spikes, tests, evals and the synthetic test models.
- The approved direction-05 ORCA identity and motion kit (`assets/brand/orca/`): generated concept reference,
  manually authored vector masters, static and animated exports, native elements, React wrappers and build/check scripts.
- The PC-03 palletising cell demo models (generated during the event by IssueLab's own scripts): Rev A and Rev B
  STEP files are bundled in `samples/` under this repository's MIT licence. Their generator source is not included.

## Pre-existing, not built during the event

- **The Northbank demo models**, used as a baseline asset for demonstrations and evaluation: generated before the
  event by IssueLab's own scripts. The six IFC files are bundled in `samples/` under this repository's MIT licence
  so judges can reproduce the demo. They are synthetic, contain no customer data, and are not claimed as work
  created during the challenge. Their generator source is not included. See [samples/README.md](samples/README.md).
- Open-source libraries listed in the README.

No earlier IssueLab product code is included. If any module is ever adapted from earlier work, it is listed here with
its source before it is committed.
