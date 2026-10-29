# Built during the hackathon

The Meta Global AI Developer Hackathon building period runs Oct 27 – Nov 4, 2026. Everything in this
repository was written during that period, starting with the first commit on Oct 27. The git history is
the record.

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
- The PC-03 palletising cell demo models (generated during the event by IssueLab's own scripts, in a private repo).

## Pre-existing, not built during the event

- **The Northbank demo models**, used as demo data: generated before the event by IssueLab's own scripts, in a private
  repo. They are synthetic; no customer data.
- Open-source libraries listed in the README.

No earlier IssueLab product code is included. If any module is ever adapted from earlier work, it is listed here with
its source before it is committed.
