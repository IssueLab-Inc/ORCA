# ORCA for agents (MCP)

Any MCP client can work on an ORCA session:
- Muse Code (Meta's coding agent);
- Claude Code or Desktop;
- an IDE.

The agent sees the models, the clashes and their pictures. It can:
- check its own ideas against the model;
- run ORCA's fix agent;
- apply fixes;
- triage;
- build the report;
- export the edited models.

When a person has ORCA open, their page follows along: the camera moves to the clash the agent shows, and fixes
appear as the agent applies them.

Code:
- `server/sightline/mcp_server.py`: the tools;
- `server/sightline/agents.py`: links, the page's channel, jobs;
- the routes and the `/mcp` mount in `app.py`;
- `web/src/Agent.tsx`: the dialog.

## Connecting

**Remote, to the session you have open.** In ORCA, choose **Connect an agent**, then **Make a link for this session**.

**After the first time, only the token changes.** The dialog leads with the token (masked; show and copy) and the
server URL, so a new session means pasting one value into your agent's settings. Or set it up once with
`"Bearer ${ORCA_TOKEN}"` (Muse Code interpolates environment variables) and change only `ORCA_TOKEN`.

The full settings for each client are under **First time? Set up your agent**, Muse Code's first:

- **Muse Code:** add ORCA to its settings file, at `~/.config/muse/settings.json`,
  `$XDG_CONFIG_HOME/muse/settings.json`, or `C:\Users\<you>\.config\muse\settings.json` on Windows.
  - Keep `"schema_version": 1`, and merge the `orca` entry into whichever key the file already uses: `mcpServers`, or
    the legacy `mcp_servers` (only one of them).
  - Check it with `muse mcp list`; `/mcp` in a session lists ORCA's tools.
  - (`muse mcp add` is not a subcommand, so there is no one-line form.)

  ```json
  {
    "schema_version": 1,
    "mcpServers": {
      "orca": {
        "transport": "streamable_http",
        "url": "https://<host>/mcp",
        "headers": { "Authorization": "Bearer <token>" },
        "mode": "optional"
      }
    }
  }
  ```

  - **Why `optional`:** Muse Code's default `mode`, `required`, aborts the whole run when a server fails, and a link
    expires or can be revoked. `optional` makes Muse Code skip ORCA with a warning instead.
  - **Keeping the token out of the file:** Muse Code interpolates `${VAR}`, so you can write
    `"Bearer ${ORCA_TOKEN}"` and set `ORCA_TOKEN` in your environment.
  - **A toolset:** select ORCA's tools with `mcp__orca__*`.

```bash
# Claude Code
claude mcp add --transport http orca https://<host>/mcp --header "Authorization: Bearer <token>"
```

```json
// Claude Desktop (claude_desktop_config.json)
{ "mcpServers": { "orca": { "command": "npx", "args": ["-y", "mcp-remote", "https://<host>/mcp",
  "--header", "Authorization: Bearer <token>"] } } }
```

- **Any other client:** connect over Streamable HTTP to `https://<host>/mcp` with the header
  `Authorization: Bearer <token>`.
- **Clients that cannot set headers:** use `https://<host>/mcp?key=<token>`.

**Local, over stdio.** This is a session of its own with no browser: open models with `open_models`, then work on them.

```bash
cd server && uv run python -m sightline.mcp_server
```

## Tools

| | Tools |
|---|---|
| Session | `get_session` (what is open, whether a browser follows), `list_models`, `open_models` |
| Clashes | `detect_clashes`, `report_summary`, `list_clashes`, `get_clash`, `get_clash_images` (A/B/C pictures), `measure_clash`, `find_root_causes`, `find_patterns`, `triage` |
| The model | `describe_element`, `find_elements`, `find_openings` |
| Fixes | `check_move`, `check_offset`, `check_route`, `check_resize`, `check_penetration`, `check_seat` (test the agent's own idea), `propose_fixes` (ORCA's fix agent), `plan_fixes_together`, `plan_root_cause`, `get_job`, `apply_fix`, `apply_plan` |
| The person's view | `show_clash`, `set_view`, `capture_view` (a picture of what they see) |
| Hand-off | `generate_report` (PDF + BCF, download link), `export_models` (IFC, and STEP for STEP models) |

**Read-only tools.** The tools that change neither the model, the open report nor the allowance declare it
(`readOnlyHint`):
- `get_session`, `list_models`, `report_summary`, `list_clashes`, `get_clash`, `get_clash_images`, `measure_clash`;
- `describe_element`, `find_elements`, `find_openings`, `find_root_causes`;
- `check_move`, `check_offset`, `check_route`, `check_resize`, `check_penetration`, `check_seat`, `get_job`;
- `show_clash`, `set_view`, `capture_view`.

Muse Code runs those without an approval prompt under on-request approvals. The rest ask: proposals, plans, applying,
detection, triage, the report, opening models, and `find_patterns` (a model call, charged once as a proposal).

The tool layer is shared with the in-app chat (`chat.Chat._run`), so the chat and an outside agent can do the same
things the same way.

**How the work runs:**
- **Long work** (a proposal, a plan, triage, the report) runs as a job. A call waits up to `wait_s` (40 s by default).
  If the job isn't done by then, it returns `{job_id, status: "running"}`, and `get_job` waits for the result. This
  keeps clients with short tool timeouts safe.
- **Nothing changes the model until `apply_fix` or `apply_plan`.** Both apply on the server. The page then patches
  the change into the viewer in place (or reloads the changed file when it is behind) and marks the clash fixed,
  exactly as when the person accepts a fix.
- **Pictures:**
  - A Navisworks report carries its own pictures.
  - For a clash ORCA found, `get_clash_images` asks the person's page to take the A/B/C views. They are saved on the
    report, where the fix agent, triage and the PDF use them too.
  - `capture_view` asks the page for what it shows now.
  - Without a page, both say so.

## Links and security

- **Capability tokens.** A link is `orca_` + 32 random bytes, shown once, in the dialog. The server keeps only its
  sha256.
- **Lifetime.** A link expires 12 hours after its last use, and 24 hours at most. **Revoke** ends it at once. A
  server restart ends every link (links live in memory, like the scenes they point at).
- **One session per link.** A link carries the visitor's context (scene, report, selected clash, fixed clashes). The
  page keeps it current (`PUT /api/links/{token}/context`), so the agent sees what the person sees.
- **Charges.** Calls are charged to whoever made the link:
  - fixes, plans, triage and the report cost proposals from the demo's allowance, like the person's own;
  - the owner's links have no caps;
  - every link has its own call cap (`SIGHTLINE_AGENT_CALLS_PER_HOUR`, 600 on the demo);
  - link creation is capped per visitor (`SIGHTLINE_LINKS_PER_HOUR`/`DAY`).
- **What the agent never gets.** It never sees a Meta key. Only the server calls Muse Spark.
- **What `/mcp` refuses.** Without a live token it answers 401 before the MCP layer runs. The transport's DNS-rebinding
  check (meant for servers on localhost) is off, because every request must carry a token.

**On Modal.**
- **One JSON response per call.** `/mcp` runs stateless (`json_response=True`), with no long-held SSE stream: Modal
  cuts requests at 10 minutes, and its edge buffers streams.
- **The page's stream.** The page follows its link with `GET /api/links/{token}/events`, an NDJSON stream sent
  uncompressed (`Content-Encoding: identity`). It ends every 4 minutes, and the page reconnects.

## When the tab closes

- **The agent keeps working.** The link and the models live on the server, not in the tab. Reading, checking,
  proposing, applying, triage, the report and export all carry on.
- **Only the page tools stop:** `capture_view`, pictures of clashes ORCA found, `show_clash` and `set_view`.
  `get_session` says the page is closed.
- **Resume.** The browser keeps the session (models, report, fixes, link) in `localStorage`. Opening ORCA again shows
  "Pick up where you left off" while the server still holds it. **Resume** reopens the same models, with every
  applied fix, the agent's included, and the page follows the link again.
- **Eviction.** The demo keeps 8 model sets in memory. Those that live links point at are evicted last.
- **What ends a session:** a server restart, or eviction when every held set is linked.
- **Time left.** The dialog shows the link's time left, kept current from the server. Each agent call renews it to
  12 hours, never past 24 hours from when it was made.

## Measured (Oct 29, local)

**Remote.** A real MCP client (the `mcp` Python package over Streamable HTTP), with a browser following the same link
on the PC-03 cell:
- `show_clash` #58 moved the person's camera;
- `get_clash_images` had the page take and return A/B/C in 8 s;
- `capture_view` returned the live view;
- `check_move` worked as expected;
- `propose_fixes` returned "Local up-offset of tray over post head", verified, in 28 s;
- after `apply_fix`, the page reloaded the model and showed "1 fixed";
- `export_models` returned the download link.

**Stdio.** The local server opened the cell from STEP, checked it (107 clashes) and answered the same tools.

## Later

- **Accounts:** GitHub sign-in on top of links, so projects and links survive a restart. Today `owner.cookie_ok`
  becomes "signed in as an allowed login".
- **Saved projects:** persistence on Modal.
- **OAuth on `/mcp`:** so clients sign in instead of pasting a token. Muse Code already supports OAuth 2.1 for remote
  servers (`muse mcp login <server>`, with dynamic client registration), and claude.ai's custom connectors expect it.
