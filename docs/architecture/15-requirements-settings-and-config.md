# 15 · Requirements, settings and configuration

> **Covers:** `server/sightline/requirements.py`, `server/sightline/settings.py`, the settings side of
> `server/sightline/owner.py`, `meta_client.load_env` and `server/sightline/__init__.py`, `limits.env_int` /
> `env_float`, every environment variable the server, deploy and evals read,
> `.env.example`, `web/src/reqFile.ts`, `web/src/Requirements.tsx`, the header plumbing in `web/src/api.ts` ·
> **Checked against code:** 2026-10-30 (`fix/hardcoded-defaults`, based on `069984b`) · **Deeper design:** [docs/requirements.md](../requirements.md)

Three layers decide how ORCA behaves for a request. **Coordination requirements** are a project's own standard
(what is checked, how strictly, who may move), sent by the page as a file id. **Settings** are the owner's switches
(reasoning effort, the open-weights model, second tries, Show it built), for themselves or for everyone.
**Environment variables** are the deployment's configuration: keys, models, caps, sizes and paths. This doc covers
all three, and ends with the reference table of every environment variable. Caps and budgets are explained in
[16](16-security-caps-and-cost.md); the routes named here are listed in [10](10-http-api-and-streams.md).

## Coordination requirements

Optional. Without a file, ORCA behaves exactly as before: the L3 Balanced default compiles to the same tests and
the same clashes (464 = 464 on Northbank, 107 = 107 on the cell, measured Oct 29,
[docs/requirements.md](../requirements.md)). With one, the numbers are fixed by the file and declared cases are
settled without a model call.

### The file: `orca-requirements/1`

JSON, at most `requirements.MAX_BYTES` (64 KB). `requirements.parse` validates and normalises it: unknown fields
are dropped, numbers clamped, and anything that names a group that does not exist is dropped. A `format` other than
`orca-requirements/1` is refused (422 from `POST /api/requirements`).

| Field | What it holds | Parse rules |
|---|---|---|
| `format` | `"orca-requirements/1"` | Missing is accepted; any other value refused |
| `name`, `version`, `notes` | Shown in the dialog, the PDF and BCF | Name 80 chars; version 1–10,000 (the page bumps it on every edit, `reqFile.bump`); notes 2,000 chars |
| `level` | Design level 1–5 (`LEVELS`: Concept, Developed, Coordinated, Production, As-built) | Clamped to 1–5, default 3 |
| `strictness` | `lenient`, `relaxed`, `balanced`, `strict`, `exacting` (`STRICTNESS`) | Anything else is `balanced` |
| `groups[]` | `id`, `name`, `role` (`ROLES`: structure, services, architecture, equipment, site, other), and a selection by `teams`, `classes`, `exclude_classes`, `systems`, `files` (top level or under `select`), `source` | Id slugged (40 chars, made unique); classes must look like `Ifc…`; a group that selects nothing is dropped; at most 24 groups |
| `checks[]` | `a`, `b` (null: the group against itself), `check` (`hard`, `clearance`, `off`), `clearance_mm`, `tolerance_mm`, `reason`, `source` | Both groups must exist; one cell per pair; clearance 0–500 mm; tolerance 0.5–200 mm |
| `duplicates` | Whether to run the duplicates test | Default true |
| `rules` | The four never-a-clash rules: `same_element`, `connected`, `assembly`, `host` (`RULE_KEYS`) | Each default true |
| `who_moves[]` | In order, the group that stays put most first: `group`, `edits` (`any`, `move`, `none`), `max_move_mm`, `trims` | Group must exist, once each; largest move 0–5,000 mm (0 is none) |
| `by_design[]` | `a_classes` with `b_classes`, `reason`, `source` (user, orca, triage) | Both sides need a class; at most 20 classes a side and 40 rules |
| `penetrations[]` | Per group (and optionally one `kind` of host, a `hosts.profile` key, with `kind_name`): `rule` (`allowed`, `review`, `never`), `max_mm`, `reviewer` (structure, architecture, fire, safety, services), `reason`, `source` | Default rule `review`; size 10–5,000 mm; left out of the file when empty, so a file without it keeps its id |
| `guidance` | `triage` and `fixes`, text for Muse | 1,000 chars each (`MAX_GUIDANCE`) |
| `domain` | `construction` (a building) or `machines`: ORCA's voice, its fix pack, how teams are guessed and the default classes fixed in place | Anything else is unset; unset means as the models were opened (all from STEP: a machine). Left out when unset, so older files keep their ids |
| `stays` | IFC classes fixed in place: a fix never moves them to make room, nor a run that holds them (a trim between two that stay is still allowed). A `who_moves` group with `edits: none` stays too | Classes like `Ifc…`, at most 60; unset means the domain's (`domains.STAYS`); left out when unset |

- **Selectors** name teams, classes, systems or files, never GlobalIds, so a file can be reused on another project.
  `requirements.Matcher` puts each element in the first group that selects it (a file's team is guessed from its
  content by `document.guess_team`, cached on the scene).
- **A Muse draft is held to the models:** `requirements.suggest` parses its reply with `classes=` and `teams=` from
  the open models' inventory, so it cannot invent a class or team; an empty reply keeps the default groups.
- **The starting point** (`requirements.default_doc`, `GET /api/scenes/{sid}/requirements/default`): one group per
  team present (or, with one team, one per kind of thing: frame and structure, services, equipment and other, site),
  hard checks between every pair and within each with Site off, and who moves from structure (stays most) to
  services (moves first), naming the models' domain. It compiles to what ORCA checks with no file. A demo's scene
  starts from its own checked-in file instead (`demos.requirements_for`, [19](19-demo-data.md)).
- **What decides a scene's domain and what stays** (`Workspace.requirements_for`): the user's file when switched on,
  else the demo's own when the scene is a demo set, else none (the models decide: `domains.infer`, `domains.STAYS`).
  Only these two come from a demo's file when requirements are off; clearance, edit limits and the prompt guidance
  come only from a file the user switched on (`Workspace.fix_settings`). `requirements.stays_rule` is the one
  predicate every fix path asks (`IfcScene.stays`).
- **Clearance** (`requirements.DEFAULT_CLEARANCE_MM`, 25 mm without a file): every check takes the pair's
  (`Workspace.clearance`): a proposal, a keep, a check by hand, by chat or over MCP, an opening's search and the wider
  fix (`context_planner.validate_objective` puts it on the objective).

### Level and strictness become numbers

`requirements.resolve(doc)` turns the level and strictness into a `Params` record through the `LEVELS` and
`STRICTNESS` tables; every number they set comes from there (other code reads them only for names and prompt
words). The tables
(tolerance, smallest element, services-to-structure clearance, fix clearance, largest move, trims, the triage lean
and the "dispute below" confidence) are reproduced in [docs/requirements.md](../requirements.md), which matches the
code at this commit. Rules worth knowing:
- the resolved tolerance is kept between 1 and 200 mm (`MIN_TOLERANCE_MM`, `MAX_TOLERANCE_MM`); a check cell's own
  `tolerance_mm` is used as given (0.5–200 mm);
- `policy` takes the stricter of the level's ceiling (`edits`: L1 whole moves, L5 none) and the group's mover row;
  the largest move is the smaller of the strictness's and the row's;
- `GET /api/requirements/scale` returns both tables for the dialog (`requirements.scale`).

### What one file turns into

```mermaid
flowchart LR
    file["orca-requirements/1 file"]
    parse["requirements.parse"]
    reg["requirements.register (id)"]
    ctx["requirements.current() in the request"]
    params["requirements.resolve: Params"]
    tests["compile_tests: detect.Test per check cell, duplicates"]
    detect["Workspace.detect, detect_tests, preview"]
    settle["settle: by-design rule, no model call"]
    tprompt["prompt_text triage, overlay, model_key, rules_key"]
    audit["triage.audit_rules after the run"]
    fix["Workspace.fix_settings"]
    agentUse["agent: blocked, meets, recommend mode"]
    cut["agent.may_cut, can_cut, hosts.decide"]
    keepFixed["context_eval.element_constraints: KeepFixed"]
    reports["PDF appendix and cover, BCF comment"]
    file --> parse
    parse --> reg
    reg --> ctx
    ctx --> params
    params --> tests
    tests --> detect
    ctx --> settle
    ctx --> tprompt
    tprompt --> audit
    params --> fix
    fix --> agentUse
    ctx --> cut
    ctx --> keepFixed
    ctx --> reports
```

| Where | What it uses | Effect |
|---|---|---|
| **Detection** | `compile_tests(doc, scene)` | One `detect.Test` per check cell that is not off, ids `req:a\|b` (`req:a` within a group), with the cell's tolerance or the resolved one, the clearance from `_cell_clearance` (a clearance cell's mm, 25 when unset, times the strictness's `clearance_x`; a hard services-to-structure cell gets the level's clearance at L4 and L5), `min_size_m` and the four rules; plus `req:duplicates` over the groups that are checked. `Workspace.detect` and `detect_tests` use it when no tests are given; a rerun is compared with the last run only under the same requirements id ([06](06-geometry-and-detection.md)). |
| **Triage** | `settle`, `prompt_text(doc, "triage")`, `overlay`, `model_key`, `rules_key`, `triage.audit_rules` | A by-design pair is settled with `basis: requirement` and no call. The prompt gains only what differs from the defaults (level not L3, the strictness's lean, a tolerance other than 1 mm, clearance cells, by-design rules, guidance). Under Strict / Exacting a model "by design" below 0.6 / 0.8 confidence becomes real (`basis: strictness`). Jobs are keyed by report + `model_key` + `rules_key`, so a rule change reuses the last readings for free ([09](09-agent-workflows.md)). |
| **Fixes** | `Workspace.fix_settings` → `fix_clearance`, `policy`, `prompt_text(doc, "fixes")`, `recommend` | The clearance a fix keeps (the strictness's, or the pair's clearance cell when larger), a `Policy` per element (`edits`, `max_move_m`, `trims`), the prompt lines, and recommend mode when neither side may be edited. `agent.resolve` refuses forbidden candidates with `requirements.blocked` (Muse hears why), lists what each option `meets`, and in recommend mode asks once with `requirements.RECOMMEND` ([09](09-agent-workflows.md)). Plans and root causes add the same prompt lines (`plans.py`). |
| **Penetrations** | `penetration_rule`, `can_cut` | A group's rule (or one kind of host's) wins over Muse's reading of a host (`hosts.decide`); the opening is cut only when the host's group may be edited in any way (`agent.may_cut`, `Workspace.apply_penetration`), else only the provision for void is written ([07](07-fixes-and-edits.md)). |
| **Wider fixes** | `context_eval.element_constraints` | An element whose group may not be edited is `KeepFixed`. |
| **Hand edits** | `manual.gate` → `policy`, `blocked`, `can_cut` | A move as a fix's move (largest move applies); push/pull and align by stretching as a resize ("may only be moved whole" refuses it, the largest move applies to the push); a clip as a trim (`trims`); a void or a cut by shape only where the group may be edited in any way (`can_cut`); a split, a removed section and a delete only with `edits == "any"`. ORCA's own hard rules (`hosts.hard_rule`, structure) only warn on a hand edit ([docs/manual-edits.md](../manual-edits.md)). |
| **Reports** | `requirements_html`, `Workspace.requirements_info` | The PDF's cover says what it was checked against, the clearance sentence uses the required clearance, an appendix lists the file; BCF topics get a "Checked against" comment ([14](14-files-in-and-out.md)). |

### Registration and the header

```mermaid
sequenceDiagram
    participant P as Page (api.ts)
    participant M as _OwnerContext middleware
    participant R as requirements registry
    P->>M: POST /api/requirements with the file
    M->>R: parse, then register
    R-->>P: id, doc as read, params, label, model_key
    P->>M: any /api call with header X-Sightline-Requirements
    alt the id is known
        M->>R: requirements.enter(id)
        Note over M: the handler and its workers see requirements.current()
    else the id is forgotten (a restart)
        M-->>P: 409 requirements_unknown
        P->>M: POST /api/requirements again (reRegister)
        P->>M: the same call once more with the new id
    end
```

- **Content-addressed.** `requirements.doc_id` is the first 16 hex characters of a sha256 of the canonical JSON
  (`canonical`: `to_dict`, sorted keys). The same file always gets the same id. The registry keeps the 500 most
  recently used (`REGISTRY_MAX`) in memory. Registering a file the server already knows is free; a new one takes one
  use of `SIGHTLINE_REQUIREMENTS_PER_HOUR` / `_PER_DAY`.
- **The header.** `api.ts` sends `X-Sightline-Requirements: <id>` with every call (`settingsHeader`). The
  `_OwnerContext` middleware puts the file in a context variable (`requirements.enter` / `leave`). `owner.spawn` and
  `owner.submit` copy the context into stream workers and model-call pools, so a triage worker sees the same file.
- **A forgotten id** on any `/api/` path answers 409 `{"detail": "requirements_unknown"}` before the handler runs.
  `api.ts` `send` registers the file again and retries once; the upload stream does the same (`reRegister`).
- **Agent links** store the page's id (`Link.requirements`, set at create and on every context PUT); MCP tool calls
  run under it with `requirements.using` ([11](11-mcp-and-agent-links.md)).
- **Routes:** `POST /api/requirements`; `GET /api/requirements/scale`; `GET /api/scenes/{sid}/requirements/default`
  (the start plus `requirements.inventory`: files and their teams, classes, systems, storeys, STEP groups);
  `POST /api/scenes/{sid}/requirements/suggest` (one Muse Spark call, `domain_packs/requirements.md`, costs one
  proposal); `POST /api/scenes/{sid}/requirements/preview` (runs detection with the file and with the defaults,
  without keeping either; 64 results cached; a preview not fully cached takes one use of
  `SIGHTLINE_PREVIEW_PER_HOUR` / `_PER_DAY`).

### In the browser

- `web/src/reqFile.ts`: the file as the page keeps it (`localStorage` key `sightline.requirements`, the file and
  whether it is in use), `serialise` / `download` (`<name>.orca-requirements.json`) / `parseUpload`, and pure edits
  that bump the version: `setCell`, `setMover`, `shiftMover`, `addByDesign` (Insights' **Add to requirements**),
  `removeByDesign`, `setPenetration`, `addPenetration` (an opening option's host reading, for that kind of host only).
- `web/src/Requirements.tsx` (`RequirementsDialog`): level cards, the strictness slider with the numbers it sets
  and the expected count (from preview), the check grid, who moves, by-design rules with Muse's audit (Keep rule /
  Remove rule), openings for services, guidance, Suggest with Muse Spark, Download, Upload, Start from the models,
  "Use these requirements" and "Use them and check again" ([12](12-web-app.md)).

## Settings

`server/sightline/settings.py` holds settings for everyone; `owner.py` carries the owner's own settings on their
requests. Only the owner can read or change either (`GET` / `PUT /api/settings`, 403 otherwise; the owner menu in
`web/src/Owner.tsx`, "For me" and "For everyone").

| Key | Values | Default when unset (environment) | What it decides |
|---|---|---|---|
| `open_weights` | true, false, null | `SIGHTLINE_OPEN_WEIGHTS == "1"` (off) | Titles, triage, STEP part classes and host readings on Muse Spark Open, when a host key is set (`meta_client.triage_model_info`); off, they run on Muse Spark |
| `effort` | minimal, low, medium, high, null | `META_REASONING_EFFORT` (low) | Muse Spark's reasoning effort: proposals, chat, plans, reports |
| `triage_effort` | same | `TRIAGE_REASONING_EFFORT` (none) on the open-weights host; Muse Spark's own effort otherwise | The triage and titles model's effort |
| `escalation` | off, button, auto, null | `SIGHTLINE_ESCALATION` (button) | Whether a second try on Muse Wonder is offered, or made at once after a failed proposal |
| `escalation_effort` | minimal, low, medium, high, null | `META_ESCALATION_EFFORT` (medium) | Muse Wonder's effort for second tries |
| `built_views` | true, false, null | `SIGHTLINE_BUILT_VIEWS == "1"` (off) | Whether Show it built is offered and drawn for kept fixes |

- **The store.** In a Modal container (`MODAL_TASK_ID` set) the Modal Dict `sightline-settings`, key `settings`,
  which survives restarts and redeploys; otherwise the JSON file `SIGHTLINE_SETTINGS_FILE` (default
  `server/.sightline-settings.json`, gitignored). Read once and cached in memory (`settings.current`); a store that
  cannot be read or written is logged and the in-memory value is used, so a setting never fails a request. `PUT`
  takes any subset; null puts a key back to its default; an unknown key or value is a 400.
- **The owner's header.** The page sends `X-Sightline-Settings` (JSON) with every call once the owner has unlocked
  (`setOwnerSettings` in `api.ts`, kept in `localStorage` `sightline.owner`). The server reads it only when the
  owner cookie checks out (`owner.enter`). Keys: `effort`, `triage_effort`, `escalation_effort` (an effort),
  `escalation` (off, button, auto), `built_views` and `open_weights` (booleans), and `no_caps` (true unless sent as
  false: the owner skips the demo caps by default, [16](16-security-caps-and-cost.md)). Unknown keys and values are
  dropped.
- **What a request gets.** `GET /api/models` tells the page which triage model this request would use, whether
  second tries and Show it built are on for it, and the upload limits, so its copy matches.

### Precedence

```mermaid
flowchart TB
    need["A request needs a setting"]
    judge{"A built-view judge's effort"}
    fixed["Fixed: the judge's own effort (meta_client.FIXED_EFFORT)"]
    isOwner{"The owner's request, with the key in X-Sightline-Settings"}
    ownerVal["The owner's value (owner.py context variables)"]
    forAll{"Set for everyone (settings store)"}
    allVal["Everyone's value (Modal Dict or JSON file)"]
    envVal["Environment default (settings.defaults, or the model's own effort)"]
    need --> judge
    judge -->|"yes"| fixed
    judge -->|"no"| isOwner
    isOwner -->|"yes"| ownerVal
    isOwner -->|"no"| forAll
    forAll -->|"yes"| allVal
    forAll -->|"null"| envVal
```

`settings.open_weights`, `escalation` and `built_views` apply this order directly; reasoning effort is applied by
`MetaChatModel.effort` (`owner.effort(role)`, then `settings.effort_for(role)`, then the effort the model was built
with). Details of the model side: [08](08-ai-models-prompts-and-spend.md).

## Environment variables

### How they are loaded

- **`.env` at the repo root** (gitignored; start from the checked-in `.env.example`). `meta_client.load_env` reads
  `KEY=value` lines, skips comments and lines without `=`, strips whitespace (not quotes: write values without
  quotes) and sets each with `os.environ.setdefault`, so **a real environment variable always wins**.
- **Loaded before any setting is read.** The package's `__init__.py` calls `load_env()`, so it runs on the first
  import of any `sightline` module, before that module's own code: the web server (`sightline.app`), the stdio MCP
  server, tests, evals and spikes all see `.env`, and **every variable below can be set there**, including those
  read at import. `MetaChatModel`, `transcribe`, `voice_live` and `built` call it again before reading keys
  (harmless: a value already set is kept).
- **Read once.** Variables marked "import" below, and what `app.py` reads at module level (the caps, the upload
  sizes, `SIGHTLINE_VOICE_LIVE_MAX_S`, `SIGHTLINE_WEB_DIST`), are read once, when their module is imported: a change
  to them needs a server restart. The rest are read each time they are used.
- **Empty values.** Numbers are read with `limits.env_int` / `env_float`: unset or empty (`NAME=`) is the default,
  so an empty cap is no limit, or its own default for requirements files (120 an hour) and previews (60 an hour).
  A value that is not a number raises where it is read: the server stops at start, or, for
  `SIGHTLINE_TRIAGE_WORKERS` and `SIGHTLINE_CONTEXT_*`, the triage or wider-fix run fails.
  `spend.limit` reads an empty or unreadable `SIGHTLINE_WONDER_MAX_USD_DAY` as 25, and an empty
  `SIGHTLINE_BUILT_CACHE` is its default. Elsewhere an empty string is a value: `SIGHTLINE_SAMPLE_EXCLUDE=` keeps
  every class, `META_REASONING_EFFORT=` sends no effort, `SIGHTLINE_OWNER_TOKEN=` means no owner.
- **Modal** sets the deploy's values in the image (`deploy/modal_app.py`, `.env(...)`) and the keys and owner token
  from the `sightline-meta` secret ([17](17-deployment-and-operations.md)). `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET`
  are for the Modal CLI only; no code reads them.
- **Never** print or commit a value. The browser never sees a key ([16](16-security-caps-and-cost.md)).

### Reference

"Modal" is the value `deploy/modal_app.py` sets, where it sets one. Caps count per visitor per rolling hour and for
everyone per rolling day; 0 means no limit, and unset or empty is the default column
([16](16-security-caps-and-cost.md)).

**Models and keys**

| Variable | Default | Read in | What it does |
|---|---|---|---|
| `META_API_KEY` | none (secret) | `meta_client.MetaChatModel`, `transcribe`, `escalation_info`; `voice_live.handshake`; `built.restyle` | Meta Model API key for Muse Spark, Muse Wonder, Muse Image and Muse Voice Transcribe. Without it every Muse call fails |
| `META_API_BASE_URL` | `https://api.meta.ai/v1` | `MetaChatModel`, `transcribe`, `voice_live.url`, `built.restyle` | Base URL for chat completions, Responses, ASR |
| `META_MODEL` | `muse-spark-1.3-contributor` | `MetaChatModel`, `triage_model_info` | Muse Spark's model id (also triage's when open weights are off) |
| `META_REASONING_EFFORT` | `low` | `MetaChatModel`, `settings.defaults` | Muse Spark's effort; empty sends none |
| `META_ESCALATION_MODEL` | `muse-wonder-1.0` | `meta_client.escalation_info`, `built.judge_model` | Second tries and Show it built's judges |
| `META_ESCALATION_EFFORT` | `medium` | `meta_client.escalation_model`, `settings.defaults` | Muse Wonder's effort for second tries |
| `META_IMAGE_MODEL` | `muse-image-1.0` | `built.restyle` | Show it built's image model |
| `META_VOICE_MODEL` | `muse-voice-transcribe-1.0` | `meta_client.transcribe`, `voice_live.handshake` | Speech recognition model |
| `META_VOICE_REALTIME_URL` | `wss://` + the host of `META_API_BASE_URL` + `/v1/asr/realtime` | `voice_live.url` | Live voice socket at Meta |
| `TRIAGE_API_KEY` | none (secret) | `meta_client.triage_model_info`, `triage_model`; `app._settings_state` | Key for the open-weights host (Baseten); without it triage uses Muse Spark |
| `BASETEN_API_KEY` | none (secret) | Same, when `TRIAGE_API_KEY` is unset | The same key under Baseten's name |
| `TRIAGE_API_BASE_URL` | `https://inference.baseten.co/v1` | `meta_client.triage_model` | Open-weights host |
| `TRIAGE_MODEL` | `meta-models/muse-spark-open` | `meta_client.triage_model_info` | Open-weights model id |
| `TRIAGE_IMAGES` | `1` | `meta_client.triage_model_info` | `0` sends triage no clash pictures (a text-only host) |
| `TRIAGE_REASONING_EFFORT` | empty (none sent) | `meta_client.triage_model`, `settings.defaults` | The open-weights model's effort |
| `SIGHTLINE_MODEL_LABELS` | empty | `meta_client.model_label` (each call) | JSON object, model-id prefix → the name people read (`{"acme-coder": "Acme Coder"}`), over the built-in Muse names (`meta_client.LABELS`); the longest prefix wins. The page gets each role's name from `GET /api/models` (`labels`) |
| `SIGHTLINE_MODEL_PRICES` | empty | `meta_client.prices`, `cost` (each call) | JSON object, model-id prefix → [USD per million input tokens, per million output tokens], over `meta_client.PRICES` (Muse Wonder's). Spend and the day's budget count what it prices |
| `META_STREAMS_REASONING` | unset (auto) | `MetaChatModel` | `1` or `0`: the host streams reasoning summaries (the Responses endpoint) or not. Unset: only Meta's own host is assumed to |
| `SIGHTLINE_MODEL_TIMEOUT_S` | 120 | `MetaChatModel` (each client) | How long one model call may take (proposals, chat, triage, titles, plans) |
| `SIGHTLINE_ESCALATION_TIMEOUT_S` | 240 | `meta_client.escalation_model` | A second try's model calls |
| `SIGHTLINE_JUDGE_TIMEOUT_S` | 240 | `built.judge_model`, `spark_judge_model` | Show it built's judges |
| `SIGHTLINE_VOICE_TIMEOUT_S` | 60 | `meta_client.transcribe` | One recorded voice clip's transcription |
| `SIGHTLINE_HOSTS_TIMEOUT_S` | 60 | `service.HOSTS_TIMEOUT_S` (import) | A host reading for openings; slower leaves the defaults |

**Caps and budgets**

| Variable | Default | Modal | Read in | What it caps |
|---|---|---|---|---|
| `SIGHTLINE_PROPOSE_PER_HOUR` / `SIGHTLINE_PROPOSE_PER_DAY` | 0 / 0 | 20 / 300 | `limits.ProposeLimit.from_env` → `app.propose_limit` | Proposals and everything charged as one |
| `SIGHTLINE_ESCALATE_PER_HOUR` / `SIGHTLINE_ESCALATE_PER_DAY` | 0 / 0 | 3 / 30 | `ProposeLimit.escalate_from_env` | Second tries on Muse Wonder |
| `SIGHTLINE_CHAT_PER_HOUR` / `SIGHTLINE_CHAT_PER_DAY` | 0 / 0 | 40 / 1500 | `ProposeLimit.chat_from_env` | Chat messages |
| `SIGHTLINE_BUILT_PER_HOUR` / `SIGHTLINE_BUILT_PER_DAY` | 0 / 0 | 6 / 60 | `app.built_limit` | Show it built requests |
| `SIGHTLINE_TITLES_PER_HOUR` / `SIGHTLINE_TITLES_PER_DAY` | 0 / 0 | not set | `app.title_limit` | Titling runs |
| `SIGHTLINE_DETECT_PER_HOUR` / `SIGHTLINE_DETECT_PER_DAY` | 0 / 0 | not set | `app.detect_limit` | Detection runs |
| `SIGHTLINE_VOICE_PER_HOUR` / `SIGHTLINE_VOICE_PER_DAY` | 0 / 0 | 60 / 2000 | `app.voice_limit` | Voice clips and live sessions |
| `SIGHTLINE_MODEL_UPLOADS_PER_HOUR` / `SIGHTLINE_MODEL_UPLOADS_PER_DAY` | 0 / 0 | 10 / 200 | `app.model_upload_limit` | Model uploads |
| `SIGHTLINE_REQUIREMENTS_PER_HOUR` / `SIGHTLINE_REQUIREMENTS_PER_DAY` | **120** / 0 | not set | `app.requirements_limit` | New requirements files registered |
| `SIGHTLINE_PREVIEW_PER_HOUR` / `SIGHTLINE_PREVIEW_PER_DAY` | **60** / 0 | not set | `app.preview_limit` | Requirement previews not in the cache |
| `SIGHTLINE_LINKS_PER_HOUR` / `SIGHTLINE_LINKS_PER_DAY` | 0 / 0 | 10 / 500 | `app.link_limit` | Agent links made |
| `SIGHTLINE_AGENT_CALLS_PER_HOUR` | 0 | 600 | `app.agent_call_limit` | MCP tool calls per link per hour |
| `SIGHTLINE_WONDER_MAX_USD_DAY` | 25 | 25 | `spend.limit` (each check) | Muse Wonder and Muse Image spend per UTC day, all visitors; 0 is no limit |

**Sizes, memory and search bounds**

| Variable | Default | Modal | Read in | What it does |
|---|---|---|---|---|
| `SIGHTLINE_UPLOAD_MAX_MB` | 200 | 150 | `app.UPLOAD_MAX_MB` | Navisworks report uploads, all files; also the default for model uploads |
| `SIGHTLINE_UPLOAD_MAX_FILES` | 5000 | not set | `app.UPLOAD_MAX_FILES` | Files in one report upload |
| `SIGHTLINE_MODEL_UPLOAD_MAX_MB` | `SIGHTLINE_UPLOAD_MAX_MB` | 150 | `app.MODEL_UPLOAD_MAX_MB` | Model uploads, all files together, unpacked; the page reads it from `GET /api/models` |
| `SIGHTLINE_MAX_SCENES` | 0 (no limit) | 8 | `service.MAX_SCENES` (import) | Open model sets held in memory |
| `SIGHTLINE_SCENE_BUDGET_MB` | 0 (count only) | 300 | `service.SCENE_BUDGET_MB` (import) | IFC bytes of the open scenes held |
| `SIGHTLINE_MAX_REPORTS` | 0 (no limit) | 8 | `service.MAX_REPORTS` (import) | Open clash reports held (each scene's current list of kept checks is evicted last, and made again from its checks if it goes) |
| `SIGHTLINE_MAX_CHECKS` | 12 | not set | `checks.MAX_CHECKS` (import) | Checks kept per open scene (the open models and each check on filters); past it the oldest check on filters goes, never the open models ([docs/detection.md](../detection.md), "Kept checks") |
| `SIGHTLINE_BIG_MODEL_MB` | 50 | not set | `scene.BIG_MODEL_BYTES` (import) | From this federation size every element's box is measured through CGAL |
| `SIGHTLINE_WIDER_FIX_MAX_MB` | 100 | not set | `context_planner.WIDER_MAX_MB` (import) | Largest models a wider fix is offered for (it copies them) |
| `SIGHTLINE_STEP_MAX_PARTS` | 20000 | not set | `step.MAX_PARTS` (import) | Parts in one STEP file |
| `SIGHTLINE_STEP_MAX_TRIANGLES` | 5000000 | not set | `step.MAX_TRIANGLES` (import) | Triangles in one STEP conversion |
| `SIGHTLINE_VOICE_LIVE_MAX_S` | 120 | not set | `app.VOICE_HANDS_FREE_MAX_S` | How long a hands-free voice session may run (hold to talk is 60 s) |
| `SIGHTLINE_TRIAGE_WORKERS` | 8 | not set | `app._start_triage`, `GET /api/models` (`triage_workers`, the card's "n at a time") | Triage model calls at a time |
| `SIGHTLINE_TITLE_BATCH` | 40 | not set | `titles.BATCH` (import) | Clashes per titling call |
| `SIGHTLINE_TITLE_WORKERS` | `SIGHTLINE_TRIAGE_WORKERS` | not set | `titles.WORKERS` (import) | Titling calls at a time (the same host as triage) |
| `SIGHTLINE_AGENT_ROUNDS` / `SIGHTLINE_AGENT_OPTIONS` | 3 / 3 | not set | `agent.ROUNDS`, `agent.OPTIONS` (import) | A proposal's model rounds, and the verified options it stops at |
| `SIGHTLINE_PLAN_MAX_ITEMS` | 8 | not set | `plans.MAX_ITEMS` (import) | Clashes one Fix together or root-cause plan takes on |
| `SIGHTLINE_PLAN_WORKERS` / `SIGHTLINE_PLAN_ROUNDS` | 4 / 2 | not set | `plans.PLAN_WORKERS`, `plans.PLAN_ROUNDS` (import) | A plan's items proposed at a time, and model rounds per item |
| `SIGHTLINE_ESCALATION_ROUNDS` | 2 | not set | `escalation.ROUNDS` (import) | Model rounds of a second try |
| `SIGHTLINE_ESCALATION_NEAR_M` / `SIGHTLINE_ESCALATION_NEAR_MAX` | 5 / 80 | not set | `escalation.NEAR_M`, `NEAR_MAX` (import) | The wider neighbourhood a second try is told about: how far, and how many elements |
| `SIGHTLINE_ESCALATION_ESTIMATE_USD` | 1.0 | not set | `escalation.ESTIMATE_USD` (import) | What a second try holds against the day's budget while it runs |
| `SIGHTLINE_CHAT_MAX_STEPS` / `SIGHTLINE_CHAT_SESSIONS` / `SIGHTLINE_CHAT_HISTORY` | 8 / 200 / 40 | not set | `chat.MAX_STEPS`, `MAX_SESSIONS`, `MAX_HISTORY` (import) | Model calls per chat message, chats held, messages kept per chat |
| `SIGHTLINE_AGENT_LINK_TTL_H` / `SIGHTLINE_AGENT_LINK_MAX_AGE_H` | 12 / 24 | not set | `agents.TTL`, `MAX_AGE` (import) | An agent link's life after its last use, and at most |
| `SIGHTLINE_AGENT_LINKS` / `SIGHTLINE_AGENT_LINK_JOBS` | 200 / 16 | not set | `agents.MAX_LINKS`, `JOBS_PER_LINK` (import) | Agent links held, and jobs per link |
| `SIGHTLINE_DETECT_CAP` | 5000 | not set | `detect.CAP` (import) | Clashes kept per test (a test that reaches it is partial) |
| `SIGHTLINE_MODEL_UPLOAD_MAX_FILES` | 8 | not set | `app.MODEL_UPLOAD_MAX_FILES` (import) | Model files in one upload; the page reads it from `GET /api/models` |
| `SIGHTLINE_EXPORTS_KEEP_S` | 3600 | not set | `app.EXPORTS_KEEP_S` (import) | How long written models and exports are kept |
| `SIGHTLINE_VOICE_HOLD_MAX_S` | 60 | not set | `app.VOICE_HOLD_MAX_S` (import) | How long hold-to-talk may run |
| `SIGHTLINE_CONTEXT_MODEL_CALLS` | 6 | not set | `context_planner.Limits.from_env` (each run) | Model calls in one wider-fix search |
| `SIGHTLINE_CONTEXT_TRIALS` | 12 | not set | same | Arrangements a wider fix may evaluate |
| `SIGHTLINE_CONTEXT_SECONDS` | 120 | not set | same | Time a wider-fix search may take |
| `SIGHTLINE_CONTEXT_ALTERNATIVES` | 3 | not set | same | Verified wider fixes kept |
| `SIGHTLINE_CONTEXT_RADIUS_M` | 2.5 | not set | same | First neighbourhood radius, metres |

The five `SIGHTLINE_CONTEXT_*` values are ceilings: `Limits.__post_init__` refuses anything not above 0 or above
its default, so a bad value fails the wider-fix run with a `ValueError` rather than widening it.

**Features and behaviour**

| Variable | Default | Modal | Read in | What it does |
|---|---|---|---|---|
| `SIGHTLINE_OWNER_TOKEN` | empty (no owner) | secret | `owner._token` (each request) | The owner token, at least 24 characters ([16](16-security-caps-and-cost.md)) |
| `SIGHTLINE_OPEN_WEIGHTS` | `0` | `0` | `settings.defaults` | Default for `open_weights` |
| `SIGHTLINE_ESCALATION` | `button` | not set | `settings.defaults` | Default for `escalation` (off, button, auto) |
| `SIGHTLINE_BUILT_VIEWS` | `0` | `0` | `settings.defaults` | Default for `built_views` |
| `SIGHTLINE_OFFSET_CORNERS` | `bends` | not set | `edits.default_corners` | A value starting `sq` makes offsets turn with square corners instead of bend fittings |
| `SIGHTLINE_CONNECTED_MOVES` | `carry` | not set | `connections.mode` (each call) | How a move treats joints: `carry` the fittings beyond the run and stretch the segments it runs along, `refuse` one that would pull a joint apart, or `off` (moves as before joints were known) ([docs/connections.md](../connections.md)) |
| `SIGHTLINE_CARRY_MAX` | 12 | not set | `connections.CARRY_MAX` (import) | Most parts a move may take along before it is refused |
| `SIGHTLINE_SAMPLE_EXCLUDE` | `IfcGeographicElement,IfcSpace,IfcBuildingElementProxy` | not set | `service.SAMPLE_EXCLUDE` (import) | Classes whose clash tests sample reports leave out; empty keeps everything |

**Paths**

| Variable | Default | Read in | What it does |
|---|---|---|---|
| `SIGHTLINE_SETTINGS_FILE` | `server/.sightline-settings.json` | `settings._file` | Settings store outside Modal |
| `SIGHTLINE_BUILT_CACHE` | `$TMP/sightline-built` | `built.CACHE` (import) | Built-view pictures |
| `SIGHTLINE_WEB_DIST` | `web/dist` | `app.WEB_DIST` | The built web app served at `/` when its `index.html` exists |
| `DEMO_MODELS` | `../demo-models` beside the repo | `evals/step_cell.py`, `detection_cell.py`, `detection_navisworks.py`, `escalation.py` | A clone of IssueLab's private demo-models repo, for the evals ([18](18-testing-and-evals.md)) |

**Deploy**

| Variable | Default | Modal | Read in | What it does |
|---|---|---|---|---|
| `MODAL_TASK_ID` | unset | set by Modal | `settings._modal_dict` | Its presence switches the settings store to the Modal Dict |
| `SIGHTLINE_PUBLIC_URL` | unset | the deploy's URL | `mcp_server.build` (import) | The address MCP clients show as ORCA's website; unset, none is sent |
| `SIGHTLINE_TRUST_FORWARDED` | unset | `0` | `limits.client_id` | N proxies in front that each append to `X-Forwarded-For`: visitors are keyed by the N-th entry from the right instead of the peer. 0 on Modal, whose edge strips the header and gives the visitor as the peer |

### Standalone brand-tool overrides

The approved [`assets/brand/orca/`](../../assets/brand/orca/README.md) library has two optional tooling-only overrides.
`ORCA_SUPPORT_FONT` selects a local font file for outlining supporting text in static exports; Windows defaults to
Segoe UI, and no font file is redistributed. `ORCA_BROWSER` selects the Chromium executable for the motion browser
check; Windows uses installed Edge when available, otherwise Playwright's Chromium is used. These are not application
or deployment settings and need no `.env` entries. Brand-tool inventory checked 2026-10-30 against `0390a12` plus this slice.

### `.env.example`

The checked-in template lists what a local run usually needs: `META_API_BASE_URL`, `META_API_KEY`, `META_MODEL`,
`META_REASONING_EFFORT`, `TRIAGE_API_KEY` (and, commented, the other `TRIAGE_*` and `SIGHTLINE_TRIAGE_WORKERS`),
`SIGHTLINE_OWNER_TOKEN` (with how to make one), the demo caps (commented: 0 is no limit; unset or empty is the
default, which is no limit except requirements files and previews), `SIGHTLINE_VOICE_LIVE_MAX_S` and the
`SIGHTLINE_CONTEXT_*` bounds. Any other variable in the tables above can go there too. Copy it to `.env` and fill
in only what you need; it never holds a value.

## When to update this doc

- A new, renamed or removed environment variable, a changed default, or a variable moved between import time and
  call time (and `.env.example` with it). `server/tests/test_docs_map.py` fails when one is missing here. A new
  number is read with `limits.env_int` / `env_float`; `server/tests/test_env_file.py` checks that `.env` reaches the
  settings read at import and that empty numbers take their defaults.
- A new field, rule or limit in `requirements.parse`, a new table row in `LEVELS` / `STRICTNESS`, or a new place
  that reads `requirements.current()`.
- A change to registration (`register`, `doc_id`, `REGISTRY_MAX`), the header or the 409 retry in `api.ts`.
- A new setting in `settings.Settings` or a new key in the owner's header (`owner.settings`), or a change to the
  store or the order of precedence.
