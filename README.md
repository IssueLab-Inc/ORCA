# ClashWise Sightline

An agent that resolves spatial conflicts in 3D models, proven on buildings.

Sightline looks at a clash (images plus model data), understands what clashes and why it matters, and,
when the IFC model is available, proposes one to three fixes by editing real model elements. Every fix
is checked with geometry before you see it: the clash is gone, there is clearance, and nothing new clashes.
You review the options in 3D and export the edited IFC.

Built for the Meta Global AI Developer Hackathon (Oct 27 – Nov 4, 2026) by IssueLab, the team behind
[ClashWise](https://clashwise.ai). See [BUILT_DURING_HACKATHON.md](BUILT_DURING_HACKATHON.md) for what
was built during the event.

## How it works

```
Browser (React + three.js + web-ifc)          Server (Python, FastAPI)
  view · pick · isolate · preview options  ⇄    Sightline core (also an MCP server)
                                                  ├─ IfcOpenShell: load, connected runs, edits, IFC export
                                                  ├─ Geometry check: collision + clearance (IfcOpenShell tree)
                                                  └─ Meta models: Muse Spark (vision, reasoning)
```

The agent loop is **propose → verify → retry → rank**: Muse Spark proposes moves from the images, the
element data and a domain pack (construction rules of thumb, in `server/sightline/domain_packs/`); the
geometry check tests each one; failures are fed back with what they hit; only verified options are shown.

The browser previews moves instantly; the server makes the real edit and is the only source of
clearance numbers. Elements are addressed by IFC GlobalId everywhere.

## Run it

Requirements: Python 3.13+, [uv](https://docs.astral.sh/uv/), Node 22+.

```bash
# server
cd server
uv sync
uv run python -m sightline.fixtures ../samples/fixture-clash.ifc   # small test model
cp ../.env.example ../.env   # then fill in the Meta Model API settings (only needed for "Propose fixes")
uv run uvicorn sightline.app:app --reload --port 8000

# web (second terminal)
cd web
npm install
npm run dev     # http://localhost:5173
```

Open a model, double-click element A then element B, and choose **Propose fixes**. **Check this move**
tries a vertical move by hand and works without any API key.

MCP server (stdio), for agents such as ClashWise's Wise:

```bash
cd server && uv run python -m sightline.mcp_server
```

## Deploy (public demo on Modal)

One container serves the built web app and the API from the same origin
([`deploy/modal_app.py`](deploy/modal_app.py)). Put the demo `*.ifc` files in `samples/` first.

```bash
cd web && npm ci && npm run build && cd ..
modal secret create sightline-meta META_API_KEY=...   # once
modal deploy deploy/modal_app.py
```

It runs one container on purpose: open models and edits live in server memory. Proposals are capped per visitor
and per day (`SIGHTLINE_PROPOSE_PER_HOUR`, `SIGHTLINE_PROPOSE_PER_DAY`, in `server/sightline/limits.py`), because
each one is a paid Muse Spark call; **Check this move** is not limited.

## Tests

```bash
cd server && uv run pytest -q      # geometry check, agent loop, web API, MCP tools
cd web && npm run build            # type-check + production build
```

## Day-1 spikes

See [spikes/README.md](spikes/README.md).

## Licences

Sightline's own code: MIT (see LICENSE). Dependencies keep their own licences: IfcOpenShell (LGPL-3.0),
web-ifc (MPL-2.0), three.js (MIT), React (MIT).
