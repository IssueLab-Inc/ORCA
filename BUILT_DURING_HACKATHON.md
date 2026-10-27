# Built during the hackathon

The Meta Global AI Developer Hackathon building period runs Oct 27 – Nov 4, 2026. Everything in this
repository was written during that period, starting with the first commit on Oct 27. The git history is
the record.

## New during the event

- The Sightline web app (`web/`): IFC viewer, picking, isolation, move previews, options panel.
- The Sightline server (`server/`): scene over IfcOpenShell, connected runs, element moves and IFC
  export, the geometry check, the propose → verify → retry → rank agent, the construction domain pack,
  the web API and the MCP server.
- The Meta model integration (Muse Spark).
- The spikes, tests and the synthetic test model.

## Pre-existing, not built during the event

- **ClashWise** (clashwise.ai), IssueLab's clash-management product, private. Sightline does not include
  ClashWise code. Connecting the two (ClashWise's Wise assistant calling Sightline's MCP server) is planned
  after the hackathon and is not part of this submission.
- **The Northbank demo models**, used as demo data, from `IssueLab-Inc/ClashWiseDemoModels`.
- Open-source libraries listed in the README.

If any module is later adapted from ClashWise, it is listed here with its source before it is committed.
