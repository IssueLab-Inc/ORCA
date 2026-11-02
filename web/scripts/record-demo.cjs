// The demo video's takes (docs/demo-video.md): each shot of the script recorded by Recordly as a take of its own, the
// cursor drawn where this script clicks and an auto-zoom on each click.
//
// Recordly is a separate desktop screen recorder (AGPL-3.0), not part of ORCA: this script loads its Playwright helper
// and Playwright from a Recordly checkout and copies nothing from it. Start Recordly yourself with its control server
// on before the takes (docs/demo-video.md, "Before recording"); this script never starts it.
//
//   node web/scripts/record-demo.cjs --login [--url <ORCA>]           once: sign in as the owner in the takes' profile
//   node web/scripts/record-demo.cjs [--url <ORCA>] [--only duct,built] [--no-filters] [--no-xray]
//   node web/scripts/record-demo.cjs --dry-run --headless --only open  no Recordly: a shot's steps, nothing recorded
//
// A shot is { name, setup(page), take(page) }. Its setup is not recorded: it opens the models, clears Filters and floats
// Activity (Workings) in the page. Its take is one Recordly take with the agent cursor: every visible click glides there.
// If anything fails inside a take, the take is still stopped (its footage kept), the failure reported, and the next
// shot goes on; a take that ran but shows the wrong thing (Muse Wonder's move not ranked first, say) is a RETAKE. Ctrl+C
// stops the take that is recording, keeping its footage. Shots run in the order of SHOTS, whatever --only's order.
const path = require("path");
const fs = require("fs");
const os = require("os");
const { createRequire } = require("module");

const ROOT = path.resolve(__dirname, "..", "..");
const VIEWPORT = { width: 1440, height: 900 };   // as every shot was tested (docs/demo-video.md, "Shots, as tested")
const GAP = 3000;        // Recordly merges clicks under 2.5 s apart into one zoom: 3 s gives a click its own
const LONG = 180000;     // triage (86 s as tested) and Show it built (85 s), and opening the models
const RUN = 300000;      // a proposal, a second look by Muse Wonder, the report
const VOICE_LINE = "Isolate the services and colour them by system.";
const VIEW = "Demo: ORCA's fix for #1";   // the saved view the later revision is shown from
// The later revision (Northbank-MEP-Rev04) in place of today's MEP model.
const REVISION = ["Northbank-Architecture.ifc", "Northbank-MEP-Rev04.ifc", "Northbank-Site.ifc", "Northbank-Structure.ifc"];
const NOT_REVISION = ["Northbank-MEP.ifc", "Northbank-Grids.ifc"];
const DEMO = { northbank: '[data-tour="demo"]', cell: '[data-tour="cell"]' };

const USAGE = `Records the demo video's shots, each as a Recordly take of its own (docs/demo-video.md).

  node web/scripts/record-demo.cjs [options]

  --url <url>        the ORCA to record (default http://localhost:8765)
  --only <shot,...>  only these shots; they run in this order whatever order is given:
                     open      Northbank opens: Colour by Discipline, Site and Architecture hidden, then X-ray
                     triage    Triage all, Workings drawing its calls
                     duct      #1 Propose fixes, Workings, Before / After
                     built     Show it built on #1's fix, the wipe slider
                     accept    Accept this fix, Export, the PDF report
                     revision  the later revision (Rev04), from the camera the duct take ended on
                     cell-29   the machine cell's #29: Propose, Look for a better fix
                     cell-13   the cell's #13: no verified fix, then Muse Wonder's second look
                     voice     types "${VOICE_LINE}" in Chat
  --no-filters       the opening without its filter beats (Colour by, the Hide filter); --filters is the default
  --no-xray          the opening without its last beat, Visual style: X-ray
  --login            open the takes' profile and record nothing: sign in as the owner, then close the window
  --profile <dir>    the browser profile the takes use (default %LOCALAPPDATA%\\orca-demo-profile)
  --recordly <dir>   the Recordly checkout (default: RECORDLY_DIR, else ../Recordly beside this repository)
  --dry-run          no Recordly: run each shot's steps, say what would be recorded and save where each take
                     ended as a picture (orca-demo-dry-run beside the profile)
  --headless         no visible window (only with --dry-run: Recordly can't record a window nobody sees)
  --help             this text`;

// ------------------------------------------------------------------ arguments

function defaultProfile(env = process.env) {
  return env.LOCALAPPDATA ? path.join(env.LOCALAPPDATA, "orca-demo-profile") : path.join(os.homedir(), ".orca-demo-profile");
}

function parseArgs(argv, env = process.env) {
  const o = { url: "http://localhost:8765", only: null, filters: true, xray: true, login: false, profile: defaultProfile(env),
    recordly: env.RECORDLY_DIR || path.resolve(ROOT, "..", "Recordly"), dryRun: false, headless: false, help: false };
  const value = (i) => {
    if (argv[i + 1] === undefined || argv[i + 1].startsWith("--")) throw new Error(`${argv[i]} needs a value`);
    return argv[i + 1];
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--url") o.url = value(i++);
    else if (a === "--only") o.only = value(i++).split(",").map((s) => s.trim()).filter(Boolean);
    else if (a === "--profile") o.profile = path.resolve(value(i++));
    else if (a === "--recordly") o.recordly = path.resolve(value(i++));
    else if (a === "--filters") o.filters = true;   // the default since Nov 2; kept so older commands still run
    else if (a === "--no-filters") o.filters = false;
    else if (a === "--no-xray") o.xray = false;
    else if (a === "--login") o.login = true;
    else if (a === "--dry-run") o.dryRun = true;
    else if (a === "--headless") o.headless = true;
    else if (a === "--help" || a === "-h") o.help = true;
    else throw new Error(`Unknown argument: ${a} (--help lists them)`);
  }
  const unknown = (o.only ?? []).filter((s) => !SHOT_NAMES.includes(s));
  if (unknown.length) throw new Error(`No shot called ${unknown.join(", ")}: the shots are ${SHOT_NAMES.join(", ")}`);
  if (o.only && !o.only.length) throw new Error("--only needs at least one shot");
  if (o.headless && !o.dryRun) throw new Error("--headless needs --dry-run: Recordly can't record a window nobody sees");
  if (o.login && (o.dryRun || o.headless)) throw new Error("--login opens a window to sign in: leave out --dry-run and --headless");
  try { new URL(o.url); } catch { throw new Error(`--url is not a URL: ${o.url}`); }
  return o;
}

/** The shots to run, in SHOTS' order. */
function selectShots(shots, only) {
  return only ? shots.filter((s) => only.includes(s.name)) : shots;
}

/** Recordly's helper and Playwright, from the Recordly checkout (nothing of Recordly lives in this repository). */
function loadRecordly(dir) {
  const helperFile = path.join(dir, "tools", "playwright", "recordly-playwright.cjs");
  if (!fs.existsSync(helperFile)) {
    throw new Error(`No Recordly checkout at ${dir} (looked for tools/playwright/recordly-playwright.cjs): pass --recordly <the Recordly checkout> or set RECORDLY_DIR`);
  }
  const helper = require(helperFile);
  let playwright;
  try {
    playwright = createRequire(path.join(dir, "tools", "playwright", "package.json"))("playwright");
  } catch {
    throw new Error(`Playwright isn't installed in ${path.join(dir, "tools", "playwright")} (--recordly ${dir}): run "npm install --ignore-scripts" there`);
  }
  return { helper, chromium: playwright.chromium };
}

// ------------------------------------------------------------------ takes

/** Start a take of the window titled `title`. Window titles match as a substring, so another browser window with ORCA
 * open makes the title ambiguous; then the window named exactly so is picked by its id. */
async function startTake(recordly, title) {
  const options = { source: { windowTitle: title }, agentCursor: true };
  try {
    return await recordly.start(options);
  } catch (error) {
    if (!/ambiguous/i.test(error.message)) throw error;
    const exact = (await recordly.sources()).filter((s) => s.kind === "window" && s.name === title);
    if (exact.length !== 1) {
      throw new Error(`${error.message} (${exact.length} windows are titled exactly "${title}": close the others)`);
    }
    return recordly.start({ ...options, source: { id: exact[0].id } });
  }
}

/** The take now starting or recording, so Ctrl+C can stop it: a take left running makes the next start fail. */
const takeState = () => ({ client: null, starting: null, recording: false, cursor: null, stopping: null, interrupted: false });
const live = takeState();

/** Detach the cursor, then stop the take (its footage kept), once, whoever asks first: the take or Ctrl+C. */
function stopOnce(take) {
  take.stopping ??= (async () => {
    await take.cursor?.detach().catch(() => undefined);
    return take.client.stop();
  })();
  return take.stopping;
}

/**
 * Ctrl+C or the console closing: stop the take, keeping its footage. A take still starting is waited for, then stopped.
 * Resolves to stop's answer, or null when nothing was recording.
 */
async function interruptTake(take = live) {
  take.interrupted = true;
  if (take.starting) {
    if (!(await take.starting.then(() => true, () => false))) return null;
  } else if (!take.recording && !take.stopping) {
    return null;
  }
  return stopOnce(take).catch(() => null);
}

/**
 * One take: start, draw the cursor, run `take`, then always detach the cursor and stop, so the footage is kept even
 * when the take failed. Resolves { started, failure, result, cursor } and never throws.
 */
async function runTake({ recordly, page, title, take, log = console, current = live }) {
  Object.assign(current, { client: recordly, starting: null, recording: false, cursor: null, stopping: null });
  let started = false, failure = null, result = null;
  try {
    current.starting = startTake(recordly, title);
    await current.starting;
    started = true;
    current.recording = true;
    current.starting = null;
    if (current.interrupted) throw new Error("Stopped by Ctrl+C");
    current.cursor = await recordly.attachCursor(page);
    await take();
  } catch (error) {
    failure = error;
  }
  current.starting = null;
  let counts = null;
  const cursor = current.cursor;
  if (cursor && !current.stopping) {
    current.cursor = null;   // detached here, so the stop below doesn't detach it again
    try { await cursor.detach(); } catch (error) { log.warn(`  The last cursor events didn't reach Recordly: ${error.message}`); }
    const { lastError, ...rest } = cursor.stats();
    counts = rest;
    if (!rest.accepted) log.warn("  Recordly accepted no cursor events: this take has no drawn cursor");
    else if (rest.failed || lastError) log.warn(`  Some cursor events failed to send${lastError ? `: ${lastError.message}` : ""}`);
  }
  if (started) {
    try {
      result = await stopOnce(current);
    } catch (error) {
      log.error(`  Stopping the take failed: ${error.message}`);
      failure = failure ?? error;
    }
  }
  current.recording = false;
  return { started, failure, result, cursor: counts };
}

// ------------------------------------------------------------------ the page

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Poll `check` until it is true, or fail naming what was awaited. */
async function until(check, timeout, what) {
  const end = Date.now() + timeout;
  for (;;) {
    if (await check()) return;
    if (Date.now() > end) throw new Error(`Gave up after ${Math.round(timeout / 1000)} s waiting for ${what}`);
    await sleep(250);
  }
}
const shown = (locator) => locator.first().isVisible();
const usable = async (locator) => (await locator.first().isVisible()) && (await locator.first().isEnabled());

/** Unrecorded clicks: straight there. */
const plainClick = (locator) => locator.first().click();

/** What this script left on the page, so the next shot's setup can reuse it. Forgotten after any failure. */
const state = { scene: null, triaged: false, proposal: null, fixed: false };
function forget() { Object.assign(state, { scene: null, triaged: false, proposal: null, fixed: false }); }

/** The mouse out of the way (no hover tip or highlight at the start of a take): the top edge, over the header. */
async function rest(page) {
  const width = await page.evaluate(() => window.innerWidth);
  await page.mouse.move(width / 2, 4);
}

/** The start page, loaded afresh (a reload starts a new page: nothing open, every panel where it was left). Waits long:
 * the live app's first answer after a quiet spell comes from a cold start. */
async function landing(page, url) {
  forget();
  await page.goto("about:blank");
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: LONG });
  const demo = page.locator(DEMO.northbank).first();
  await until(() => usable(demo), LONG, `"Open the Northbank demo" on ${url}`);
}

/** The clash list after a check: rows drawn and the triage card in. The dock keeps its last tabs, so Filters may be in
 * front of the list (the opening ends there): the list's own tab is brought forward, now and then, until it shows. */
async function listReady(page) {
  const rows = page.locator("button.clash-main").first();
  let asked = 0;
  await until(async () => {
    if (await rows.count()) return true;
    const list = tab(page, "clashes");
    if (Date.now() - asked > 2000 && (await list.count())) { asked = Date.now(); await list.click({ timeout: 2000 }).catch(() => undefined); }
    return false;
  }, LONG, "the clash list");
  await page.locator('section[data-tour="triage"]').first().waitFor({ state: "visible", timeout: 60000 });
  await sleep(2000);
}

/** Open a demo afresh from the start page: a new scene, so no fix, proposal or triage carries over. */
async function openDemo(page, url, which) {
  await landing(page, url);
  await page.locator(DEMO[which]).first().click();
  await listReady(page);
  state.scene = which;
}

const tab = (page, id) => page.locator(`[data-panel-tab="${id}"]:visible`).first();

/** Filters' Clear all, then back to the clash list. Filters are kept per set of models in the browser, so a take that
 * coloured or hid something leaves it for the next (docs/demo-video.md). */
async function clearFilters(page) {
  await tab(page, "filters").click();
  const editor = page.locator(".feditor:visible");
  if (await shown(editor)) await editor.getByRole("button", { name: "Cancel" }).first().click();
  const head = page.locator(".fpanel-head").first();   // there once the filters' index is in, about 9 s after drawing
  if (await head.waitFor({ state: "visible", timeout: 60000 }).then(() => true, () => false)) {
    const clear = page.locator(".fpanel").getByRole("button", { name: "Clear all" });
    if (await shown(clear)) await clear.first().click();
  } else {
    console.warn("  Filters didn't read the models within 60 s: not cleared");
  }
  await tab(page, "clashes").click();
  const search = page.getByLabel("Filter clashes").first();   // the list's own filter too (#29 is found through it)
  await search.waitFor({ state: "visible", timeout: 10000 });
  if (await search.inputValue()) await search.fill("");
}

/** Activity (Workings) floating inside the page, or back in its bottom bar. Never in a window of its own: a window
 * recording would not see it. */
async function placeActivity(page, where) {
  const activity = tab(page, "activity");
  if (!(await activity.count())) { console.warn("  No Activity panel: Workings stays where it is"); return; }
  await activity.click();
  // Its own group's buttons only: a bar it left can still hold a hidden "Float Activity".
  const group = page.locator(".dv-groupview").filter({ has: page.locator('[data-panel-tab="activity"]:visible') }).last();
  const button = group.getByRole("button", { name: where === "float" ? "Float Activity" : "Put it back" });
  if (await shown(button)) { await button.first().click({ timeout: 5000 }); await sleep(600); }
}

/** Activity showing Workings, as the app's own controls set it (kept in the browser, `sightline.workings`): turned on
 * when it is off, and its Workings tab chosen over Steps. */
async function showWorkings(page) {
  const turnOn = page.locator(".wk-off").getByRole("button", { name: "Turn it on" });
  if (await shown(turnOn)) { await turnOn.first().click({ timeout: 5000 }); await sleep(300); }
  const work = page.getByRole("tablist", { name: "Activity view" }).getByRole("tab", { name: /Workings/ }).first();
  if ((await work.isVisible()) && (await work.getAttribute("aria-selected")) !== "true") await work.click({ timeout: 5000 });
  if (!(await work.isVisible())) console.warn("  Activity shows no Workings tab: Workings may not be drawn in this take");
}

/** Before a clash shot (docs/demo-video.md, "Before recording"): no filters, Workings floated where it can be seen,
 * the Clash panel in front. */
async function prepareClashShot(page) {
  await clearFilters(page);
  await placeActivity(page, "float");
  await showWorkings(page);
  await tab(page, "clash").click({ timeout: 5000 }).catch(() => undefined);
}

/** The row of clash #n. The list draws only the rows on screen, and a closed group none: open the group, else filter
 * the list down to the number. */
async function clashRow(page, n, click) {
  const row = page.locator("button.clash-main")
    .filter({ has: page.locator(".clash-name", { hasText: new RegExp(`^#${n}$`) }) }).first();
  const visible = (ms) => row.waitFor({ state: "visible", timeout: ms }).then(() => true, () => false);
  if (await visible(3000)) return row;
  const group = page.locator(".groups details").filter({ has: row }).first();
  if ((await row.count()) && !(await group.evaluate((d) => d.open))) {   // never toggle an open group shut
    await click(group.locator("summary"));
    if (await visible(5000)) return row;
  }
  const search = page.getByLabel("Filter clashes").first();
  await click(search);
  await search.fill("");
  await search.pressSequentially(`#${n}`, { delay: 60 });
  await row.waitFor({ state: "visible", timeout: 15000 });
  return row;
}

/** Pick clash #n and wait until it can be fixed (the camera flies there and the three views are taken). */
async function pickClash(page, n, click) {
  const row = await clashRow(page, n, click);
  await click(row.locator(".clash-name"));   // its #N: the row's own buttons cover the middle once the mouse is over it
  await page.locator(".clash-row.pick").filter({ has: row }).first().waitFor({ state: "attached", timeout: 15000 });
  const propose = page.locator('button[data-tour="propose"]:visible');
  const anyway = page.locator('[data-tour="fix-anyway"]:visible');
  if (!(await shown(propose)) && !(await shown(anyway)) && (await tab(page, "clash").count())) await click(tab(page, "clash"));
  await until(async () => (await usable(propose)) || (await shown(anyway)), 60000, `#${n}'s Propose fixes`);
}

/** Wait out a run of the agent: the Propose button says "Working…" while it lasts. */
async function settle(page, timeout, what) {
  const working = page.locator('button[data-tour="propose"]', { hasText: "Working" });
  if (!(await working.first().waitFor({ state: "attached", timeout: 20000 }).then(() => true, () => false))) {
    throw new Error(`${what} didn't start within 20 s`);
  }
  await until(async () => (await working.count()) === 0, timeout, what);
  await sleep(1500);
}

/** What the clash panel shows after a run. */
async function outcome(page) {
  const options = page.locator(".card-body.option:visible");
  return {
    options: await options.count(),
    titles: await options.locator(".opt-title").allInnerTexts(),
    nofix: await shown(page.locator("div.nofix:visible")),
    wonderFirst: (await options.first().locator(".chip.model.wonder").count()) > 0,
  };
}

/** Propose fixes for the picked clash and wait for the verified options or the no-fix card. */
async function propose(page, click, n) {
  const anyway = page.locator('[data-tour="fix-anyway"]:visible');
  const button = page.locator('button[data-tour="propose"]:visible');
  if (!(await shown(button)) && (await shown(anyway))) await click(anyway);
  await until(() => usable(button), 60000, `#${n}'s Propose fixes`);   // busy while the camera flies and the views are taken
  await click(button);
  await settle(page, RUN, `#${n}'s proposal`);
  return outcome(page);
}

/** Fit Workings to the whole run, when it is on screen. */
async function fitWorkings(page, click) {
  const fit = page.locator(".wk-tbtn:visible", { hasText: "Fit" });
  if (await shown(fit)) await click(fit);
  else console.warn("  Workings' Fit isn't on screen (Workings off, or Activity closed?)");
}

/** Clash #1 with its verified options on screen, the first chosen: reused from the duct take when it is still there. */
async function ensureProposal(page, ctx, n) {
  const reuse = state.scene === "northbank" && state.proposal === n && !state.fixed
    && (await page.locator(".card-body.option:visible").count()) > 0;
  if (!reuse) {
    await openDemo(page, ctx.url, "northbank");
    await prepareClashShot(page);
    await pickClash(page, n, plainClick);
    const result = await propose(page, plainClick, n);
    state.proposal = n;
    if (!result.options) throw new Error(`#${n} got no verified option this time: run it again`);
  }
  const first = page.locator(".card-body.option:visible").first();
  if ((await first.getAttribute("aria-pressed")) !== "true") await first.click();
  await sleep(1000);
}

/** Triage done on the open Northbank (the report sorts its pages by it). Started here, unrecorded, when it is not. */
async function ensureTriaged(page, ctx) {
  if (state.scene !== "northbank") await openDemo(page, ctx.url, "northbank");
  const card = page.locator('section[data-tour="triage"]').first();
  if (!(await card.evaluate((s) => s.classList.contains("done")))) {
    const go = card.locator(".triage-go");
    if (await shown(go)) await go.first().click();
    await page.locator('section[data-tour="triage"].done').first().waitFor({ state: "visible", timeout: LONG });
  }
  state.triaged = true;
}

/** A saved view of the camera now, with a section box round the clash on screen, replacing one of the same name (kept
 * in the browser for these models). The box is switched off again after, so the next shots look as tested. */
async function saveView(page, name) {
  const section = page.locator('button[aria-label^="Section box"]:visible').first();
  const boxed = (await section.count()) && (await section.getAttribute("aria-pressed")) !== "true";
  if (boxed) { await section.click(); await sleep(1500); }
  await page.locator('button[aria-label="Saved views"]:visible').first().click();
  const menu = page.getByRole("menu", { name: "Saved views" }).first();
  const old = menu.getByRole("button", { name: `Delete ${name}`, exact: true });
  while (await old.count()) { await old.first().click(); await sleep(200); }
  await menu.getByRole("textbox", { name: "Name for this view" }).fill(name);
  await menu.getByRole("button", { name: "Save this view" }).click();
  await menu.getByRole("button", { name, exact: true }).waitFor({ state: "visible", timeout: 5000 });
  await page.keyboard.press("Escape");
  if (boxed) { await sleep(300); await section.click(); }
}

/** Whether a saved view of that name is kept in this browser (for any set of models). */
function hasView(page, name) {
  return page.evaluate((n) => Object.keys(localStorage).filter((k) => k.startsWith("sightline.views."))
    .some((k) => { try { return (JSON.parse(localStorage.getItem(k)).saved ?? []).some((v) => v.name === n); } catch { return false; } }),
  name).catch(() => false);
}

/** Visual style: X-ray, everything see-through. */
async function xray(page, click) {
  await click(page.locator('button[aria-label^="Visual style:"]:visible'));
  await click(page.locator(".pop.open").getByRole("menuitemradio", { name: /^X-ray/ }));
}

/** Drag the mouse along a line at about 60 steps a second. */
async function drag(page, from, to, y, ms) {
  const steps = Math.max(2, Math.round(ms / 16));
  for (let i = 1; i <= steps; i++) { await page.mouse.move(from + ((to - from) * i) / steps, y); await sleep(16); }
}

/** Save a download where the edit can find it, and say where. */
async function keep(download, dir) {
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, download.suggestedFilename());
  await download.saveAs(file);
  console.log(`  saved ${file}`);
}

// ------------------------------------------------------------------ the shots

const SHOTS = [
  {
    name: "open",
    async setup(page, ctx) {
      await landing(page, ctx.url);
      // Filters and the dock are kept in the browser: a floated Activity or a kept filter would show in the opening.
      const tidy = await page.evaluate(() => {
        let floating = false, filtered = false;
        try { floating = JSON.stringify(JSON.parse(localStorage.getItem("sightline.dock.v1") ?? "null")?.floatingGroups ?? []).includes('"activity"'); } catch { /* none kept */ }
        for (const k of Object.keys(localStorage)) {
          if (!k.startsWith("sightline.filters.")) continue;
          try { if (JSON.parse(localStorage.getItem(k))?.rules?.length) filtered = true; } catch { /* none kept */ }
        }
        return floating || filtered;
      });
      if (tidy) {
        await openDemo(page, ctx.url, "northbank");
        await clearFilters(page);
        await placeActivity(page, "home");
        await landing(page, ctx.url);
      }
      await page.locator(DEMO.northbank).first().scrollIntoViewIfNeeded();
      await rest(page);
    },
    async take(page, ctx) {
      await sleep(1000);
      await ctx.click(page.locator(DEMO.northbank));
      await listReady(page);   // the check, then the clashes listed
      state.scene = "northbank";
      ctx.log(`  ${await page.locator(".report-head h2").first().innerText().catch(() => "")}`.trimEnd());
      await sleep(GAP);
      if (ctx.filters) {
        // Agreed Nov 2 (docs/demo-video.md): Colour by Discipline, then a filter hiding Site and Architecture.
        await ctx.click(tab(page, "filters"));
        const colourBy = page.locator('.fpanel-head select[aria-label="Colour by"]').first();
        await colourBy.waitFor({ state: "visible", timeout: 60000 });   // the filters' index arrives after the drawing
        await sleep(GAP);
        const discipline = await colourBy.evaluate((s) => [...s.options].find((o) => /^Discipline\b/.test(o.textContent.trim()))?.value);
        if (!discipline) throw new Error('"Colour by…" offers no Discipline');
        // The cursor goes to the list and the choice is set there: a click would open Chrome's own drop-down, a window of
        // its own that a window recording doesn't capture.
        await ctx.glide(colourBy);
        await colourBy.selectOption(discipline);
        await sleep(GAP);
        await ctx.click(page.locator(".fpanel-head").getByRole("button", { name: "New filter" }));
        const editor = page.locator(".feditor").first();
        const models = editor.locator('xpath=.//span[contains(@class,"flabel") and normalize-space(.)="Models"]/following-sibling::div[1]//details/summary');
        await ctx.click(models);
        for (const model of [/Architecture/, /Site/]) await ctx.click(editor.locator(".pick-item", { hasText: model }));
        await ctx.click(models);
        await ctx.click(editor.getByRole("radio", { name: /Hide/ }));
        await ctx.click(editor.getByRole("button", { name: /Add filter/ }));
        await sleep(5000);   // the views close in on what is left by themselves
      }
      if (ctx.xray) {
        await xray(page, ctx.click);   // the outer walls fade (with the filters: the services show between the floors)
        await sleep(4000);
      }
    },
  },
  {
    name: "triage",
    async setup(page, ctx) {
      // The opening ends on Filters (its filters stay for this take): the list, with the triage card, comes forward.
      if (state.scene === "northbank") {
        await tab(page, "clashes").click({ timeout: 5000 }).catch(() => undefined);
        await page.locator('section[data-tour="triage"]').first().waitFor({ state: "visible", timeout: 10000 }).catch(() => undefined);
      }
      const idle = state.scene === "northbank" && !state.triaged && (await shown(page.locator('section[data-tour="triage"] .triage-go')));
      if (!idle) await openDemo(page, ctx.url, "northbank");
      await placeActivity(page, "float");   // the opening's filters stay: the clash shots clear them
      await showWorkings(page);
      await tab(page, "clash").click({ timeout: 5000 }).catch(() => undefined);
      await rest(page);
    },
    async take(page, ctx) {
      await sleep(1000);
      await ctx.click(page.locator('section[data-tour="triage"] .triage-go'));
      state.triaged = true;
      await page.locator('section[data-tour="triage"].done').first().waitFor({ state: "visible", timeout: LONG });
      const said = (await page.locator('section[data-tour="triage"]').first().innerText()).match(/\d+\s+needs? a fix\s+of\s+\d+/);
      ctx.log(`  ${said ? said[0].replace(/\s+/g, " ") : "triage done"}`);
      const unread = page.locator('section[data-tour="triage"] .triage-unread:visible');
      if (await shown(unread)) ctx.retake(`triage left clashes unread ("${(await unread.first().innerText()).trim()}"): the model didn't answer them all`);
      await sleep(GAP);
      await fitWorkings(page, ctx.click);
      await sleep(4000);
    },
  },
  {
    name: "duct",
    async setup(page, ctx) {
      // A fresh #1: a proposal on screen, or the fix kept, means its models open again (and triage with them).
      if (!(state.scene === "northbank" && state.proposal === null && !state.fixed)) await openDemo(page, ctx.url, "northbank");
      await prepareClashShot(page);
      await clashRow(page, 1, plainClick);   // on screen when the take starts
      await rest(page);
    },
    async take(page, ctx) {
      await sleep(1000);
      await pickClash(page, 1, ctx.click);
      await sleep(GAP);
      const result = await propose(page, ctx.click, 1);
      state.proposal = 1;
      if (!result.options) return ctx.retake(`#1 got no verified option${result.nofix ? " (No edit passed the geometry check)" : ""}`);
      ctx.log(`  ${result.options} verified: ${result.titles.join(" | ")}`);
      await sleep(GAP);
      await fitWorkings(page, ctx.click);
      for (const which of ["Before", "After"]) {
        await sleep(GAP);
        await ctx.click(page.locator(".compare .seg button", { hasText: new RegExp(`^${which}$`) }));
      }
      await sleep(GAP);
    },
    // The camera this take ended on, kept so the later revision can be recorded from the same place.
    after: (page) => saveView(page, VIEW),
  },
  {
    name: "built",
    async setup(page, ctx) {
      await ensureProposal(page, ctx, 1);
      if (await shown(page.locator(".card.pick .built"))) {   // already drawn: a fresh proposal for a fresh picture
        forget();
        await ensureProposal(page, ctx, 1);
      }
      await rest(page);
    },
    async take(page, ctx) {
      await sleep(1000);
      const show = page.locator('button[data-tour="show-built"]:visible');
      if (!(await shown(show))) throw new Error('No "Show it built" on #1\'s fix: switch it on for you in the owner settings (--login)');
      await ctx.click(show);
      await page.locator("figure.built.done:visible, .built.failed:visible").first().waitFor({ state: "visible", timeout: LONG });
      const failed = page.locator(".built.failed:visible");
      if (await shown(failed)) throw new Error(`Show it built: ${(await failed.first().innerText()).split("\n")[0]}`);
      await sleep(GAP);
      await fitWorkings(page, ctx.click);
      await sleep(GAP);
      // The wipe: to the middle, then dragged across ORCA's view and the picture, and back.
      const slider = page.getByRole("slider", { name: /Wipe between/ }).first();
      await ctx.click(slider);
      const box = await slider.boundingBox();
      const y = box.y + box.height / 2, x = (f) => box.x + box.width * f;
      await page.mouse.down();
      let at = 0.5;
      for (const to of [0.12, 0.88, 0.5]) { await drag(page, x(at), x(to), y, 1200); at = to; }
      await page.mouse.up();
      await sleep(GAP);
    },
  },
  {
    name: "accept",
    async setup(page, ctx) {
      await ensureProposal(page, ctx, 1);
      await ensureTriaged(page, ctx);   // the report can only be built after triage
      await rest(page);
    },
    async take(page, ctx) {
      await sleep(1000);
      await ctx.click(page.locator('button[data-tour="accept"]:visible'));
      await until(async () => (await page.locator(".clash-row.fixed").count()) > 0
        || (await page.locator("a.export .export-n").count()) > 0, 120000, "the fix to be kept");
      state.fixed = true;
      state.proposal = null;
      await sleep(GAP);
      const [ifc] = await Promise.all([page.waitForEvent("download", { timeout: LONG }),
        ctx.click(page.locator('a.export[data-tour="export"]:visible'))]);
      await keep(ifc, ctx.downloads);
      await sleep(GAP);
      await ctx.click(page.locator('button[data-tour="menu"]:visible'));
      await ctx.click(page.locator('.menu-sheet [data-tour="report"]'));
      const dialog = page.getByRole("dialog", { name: "Coordination report" });
      const build = dialog.locator('[data-tour="build"]');
      await until(() => usable(build), 60000, "Build the report (it needs triage)");
      await sleep(GAP);   // Report and Build each get their own zoom
      await ctx.click(build);
      const download = dialog.locator('[data-tour="download"]');
      await download.waitFor({ state: "visible", timeout: RUN });
      await sleep(GAP);
      const [pdf] = await Promise.all([page.waitForEvent("download", { timeout: 60000 }), ctx.click(download)]);
      await keep(pdf, ctx.downloads);
      await sleep(GAP);
    },
  },
  {
    name: "revision",
    async setup(page, ctx) {
      if (!(await hasView(page, VIEW))) {   // no duct take kept its camera: #1's own, as picking it flies there
        console.warn(`  No saved view "${VIEW}" from a duct take: using the camera that picking #1 flies to`);
        await openDemo(page, ctx.url, "northbank");
        await clearFilters(page);
        await pickClash(page, 1, plainClick);
        await sleep(4000);
        await saveView(page, VIEW);
      }
      // The same models with the later revision of MEP in place of today's: picked in the Menu's model list on the
      // start page, opened, then checked as the demo is.
      await landing(page, ctx.url);
      await page.locator('button[data-tour="menu"]:visible').first().click();
      const sheet = page.locator(".menu-sheet").first();
      for (const f of [...REVISION, ...NOT_REVISION]) {
        const box = sheet.locator(`input[type="checkbox"][value="${f}"]`).last();   // with models open, the last list opens instead
        if (await box.count()) await box.setChecked(REVISION.includes(f));
      }
      await sheet.locator("#open").click();
      const check = page.locator('section[data-tour="detect"] .triage-go');
      await until(() => usable(check), LONG, "the later revision's models to open");
      await check.first().click();
      await listReady(page);
      state.scene = "revision";
      await prepareClashShot(page);   // laid out as the duct take was, so the two frames match
      await rest(page);
    },
    async take(page, ctx) {
      await sleep(1000);
      // The duct take's camera and its section box round #1, then X-ray: with no clash picked nothing is greyed out,
      // so the revision's duct through the beam's opening shows through what the box keeps in front of it.
      await ctx.click(page.locator('button[aria-label="Saved views"]:visible'));
      await ctx.click(page.getByRole("menu", { name: "Saved views" }).getByRole("button", { name: VIEW, exact: true }));
      await sleep(GAP);
      await xray(page, ctx.click);
      await sleep(5000);
    },
  },
  {
    name: "cell-29",
    async setup(page, ctx) {
      await openDemo(page, ctx.url, "cell");   // fresh every time: #29 is retaken until Wonder's move ranks first
      await prepareClashShot(page);
      await clashRow(page, 29, plainClick);    // the list drawn down to #29, so the take starts on its row
      await rest(page);
    },
    async take(page, ctx) {
      await sleep(1000);
      await pickClash(page, 29, ctx.click);
      await sleep(GAP);
      const first = await propose(page, ctx.click, 29);
      state.proposal = 29;
      ctx.log(`  Muse Spark: ${first.options ? first.titles.join(" | ") : "no verified option"}`);
      await sleep(GAP);
      await fitWorkings(page, ctx.click);
      await sleep(GAP);
      // Muse Wonder's second look: "Look for a better fix" beside options, "Ask Muse Wonder" on the no-fix card.
      const again = page.locator(first.options ? 'button[data-tour="better-fix"]:visible' : '[data-tour="escalate"]:visible');
      if (!(await shown(again))) throw new Error("Muse Wonder isn't offered on #29 (the owner's second-try setting?)");
      await ctx.click(again);
      await settle(page, RUN, "Muse Wonder's second look at #29");
      const second = await outcome(page);
      ctx.log(`  after Muse Wonder: ${second.titles.join(" | ") || "no verified option"}`);
      if (!second.wonderFirst) ctx.retake("Muse Wonder's option isn't ranked first in this take");
      await sleep(GAP);
      await fitWorkings(page, ctx.click);
      await page.locator(".card-body.option:visible").first().scrollIntoViewIfNeeded().catch(() => undefined);
      await sleep(4000);
    },
  },
  {
    name: "cell-13",
    async setup(page, ctx) {
      if (!(state.scene === "cell" && state.proposal !== 13)) await openDemo(page, ctx.url, "cell");
      await prepareClashShot(page);
      await clashRow(page, 13, plainClick);
      await rest(page);
    },
    async take(page, ctx) {
      await sleep(1000);
      await pickClash(page, 13, ctx.click);
      await sleep(GAP);
      const first = await propose(page, ctx.click, 13);
      state.proposal = 13;
      if (first.options) return ctx.retake(`#13 got ${first.options} verified option(s) this time: not the no-fix picture`);
      await sleep(GAP);
      await fitWorkings(page, ctx.click);
      await sleep(GAP);
      const ask = page.locator('[data-tour="escalate"]:visible');   // as tested (owner, Nov 2: keep it): Ask Muse Wonder
      if (await shown(ask)) {
        await ctx.click(ask);
        await settle(page, RUN, "Muse Wonder's second look at #13");
        const second = await outcome(page);
        if (second.options) return ctx.retake(`Muse Wonder found ${second.options} verified option(s) for #13: not the no-fix picture`);
        await sleep(GAP);
        await fitWorkings(page, ctx.click);
      } else {
        ctx.retake("Ask Muse Wonder wasn't offered on #13 (the owner's second-try setting?)");
      }
      await page.locator("div.nofix:visible").first().scrollIntoViewIfNeeded();   // and what decides it
      await sleep(4000);
    },
  },
  {
    name: "voice",
    async setup(page, ctx) {
      if (state.scene !== "northbank") await openDemo(page, ctx.url, "northbank");
      await clearFilters(page);
      await placeActivity(page, "home");
      await rest(page);
    },
    async take(page, ctx) {
      await sleep(1000);
      await ctx.click(tab(page, "chat"));
      await sleep(GAP);
      const message = page.getByRole("textbox", { name: "Message" }).first();
      await until(() => message.isEnabled(), 30000, "Chat");
      await ctx.click(message);
      await message.pressSequentially(VOICE_LINE, { delay: 45 });
      await sleep(800);
      const replies = page.locator(".chat-log .msg.assistant");
      const before = await replies.count();
      await ctx.click(page.locator('button[data-tour="chat-send"]:visible'));
      const send = page.locator('button[data-tour="chat-send"]').first();
      await until(async () => (await replies.count()) > before && (await send.innerText()).trim() === "Send"
        && !(await replies.last().locator(".spinner").count()), LONG, "Muse Spark's reply");
      await sleep(5000);
    },
  },
];
const SHOT_NAMES = SHOTS.map((s) => s.name);

// ------------------------------------------------------------------ running

const LEFT_RUNNING = "Recordly is still recording a take (one left running?): stop or cancel it in Recordly, then run again";

/** Chrome for the takes. Ctrl+C is this script's to handle (it stops the take first), not Playwright's. */
async function launch(chromium, options, url) {
  const own = { channel: "chrome", acceptDownloads: true, handleSIGINT: false, handleSIGTERM: false, handleSIGHUP: false };
  try {
    const context = await chromium.launchPersistentContext(options.profile, options.headless
      ? { ...own, headless: true, viewport: VIEWPORT, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] }
      : { ...own, headless: false, viewport: null, args: [`--app=${url}`] });
    context.setDefaultNavigationTimeout(LONG);   // the live app's first answer can be a cold start
    return context;
  } catch (error) {
    if (/already in use|ProcessSingleton/i.test(error.message)) {
      throw new Error(`The profile ${options.profile} is open in another window (a --login window?): close it, then run again`);
    }
    throw error;
  }
}

/** An error in one line: Playwright's own first line, and what it was waiting for. */
function brief(error) {
  const lines = String(error.message || error).split("\n");
  const waited = lines.find((l) => /waiting for /.test(l));
  return waited ? `${lines[0]} (${waited.trim().replace(/^- /, "")})` : lines[0];
}

/** A shot's line in the summary: ok, RETAKE (it ran, but what it shows has to be taken again) or FAILED. */
function summaryLine(r) {
  const word = { ok: "ok", retake: "RETAKE", failed: "FAILED" }[r.status];
  return `  ${r.shot.padEnd(9)} ${word.padEnd(6)}${r.videoPath ? `  ${r.videoPath}` : ""}${r.why ? `  (${r.why})` : ""}`;
}
/** Non-zero when any shot is to be taken again or failed. */
const exitCodeOf = (results) => (results.every((r) => r.status === "ok") ? 0 : 1);

async function record(shot, ctx) {
  const { page, recordly } = ctx;
  console.log(`\n${shot.name}`);
  const failed = (why) => ({ shot: shot.name, status: "failed", why });
  // A take left recording (this run's Ctrl+C missed, another script): this shot's start would be refused anyway.
  if (recordly) {
    let status;
    try { status = await recordly.status(); } catch (error) { console.error(`  ${brief(error)}`); return failed(brief(error)); }
    if (status.recording) { console.error(`  ${LEFT_RUNNING}`); return failed(LEFT_RUNNING); }
  }
  // A dry run's picture of where the page ended, to look at instead of a recording.
  const picture = async (suffix = "") => {
    if (recordly) return;
    const file = path.join(ctx.dryRunShots, `${shot.name}${suffix}.png`);
    fs.mkdirSync(ctx.dryRunShots, { recursive: true });
    await page.screenshot({ path: file }).then(() => console.log(`  [dry run] where it ended: ${file}`), () => undefined);
  };
  try {
    await shot.setup(page, ctx);
  } catch (error) {
    await picture("-setup");
    forget();
    console.error(`  Setup failed, nothing recorded: ${brief(error)}`);
    return failed(`setup: ${brief(error)}`);
  }
  const title = await page.title();
  // After a take that ran, unrecorded: what the next shots need from it (the duct's camera).
  const after = async () => {
    try { if (shot.after) await shot.after(page, ctx); } catch (error) { console.warn(`  After the take: ${brief(error)}`); }
  };
  ctx.retakeWhy = null;
  const verdict = (failure) => failure ? { status: "failed", why: brief(failure) }
    : ctx.retakeWhy ? { status: "retake", why: ctx.retakeWhy } : { status: "ok" };
  if (!recordly) {
    console.log(`  [dry run] would record the window "${title}" with the agent cursor`);
    let failure = null;
    try { await shot.take(page, ctx); console.log("  [dry run] would stop the take here"); } catch (error) { failure = error; }
    await picture();
    if (failure) { forget(); console.error(`  Failed: ${brief(failure)}`); } else await after();
    return { shot: shot.name, ...verdict(failure) };
  }
  const { failure, result, cursor } = await runTake({ recordly, page, title, take: () => shot.take(page, ctx) });
  if (failure) forget();
  else await after();
  console.log(`  shot: ${shot.name}`);
  console.log(`  videoPath: ${result?.videoPath ?? "(none)"}`);
  console.log(`  projectPath: ${result?.projectPath ?? "(none)"}`);
  if (result?.saveError) console.warn(`  saveError: ${result.saveError}`);
  if (cursor) console.log(`  cursor events: ${JSON.stringify(cursor)}`);
  if (failure) console.error(`  Failed${result ? " (the footage is kept)" : ""}: ${brief(failure)}`);
  return { shot: shot.name, ...verdict(failure), videoPath: result?.videoPath, projectPath: result?.projectPath };
}

/** Ctrl+C (or the console closing): stop the take, keeping its footage, close Chrome, exit 130. A second one exits now. */
function onInterrupt(session) {
  let exiting = false;
  return (signal) => {
    if (exiting) process.exit(130);
    exiting = true;
    console.error(`\n${signal}: ${live.starting || live.recording ? "stopping the take (its footage is kept)…" : "stopping"}`);
    void interruptTake(live)
      .then((result) => { if (result?.videoPath) console.error(`  videoPath: ${result.videoPath}\n  projectPath: ${result.projectPath}`); })
      .finally(async () => { await session.context?.close().catch(() => undefined); process.exit(130); });
  };
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.help) { console.log(USAGE); return; }
  const { helper, chromium } = loadRecordly(options.recordly);
  const session = { context: null };
  const interrupted = onInterrupt(session);
  for (const signal of ["SIGINT", "SIGTERM", "SIGHUP"]) process.on(signal, interrupted);

  // Fail fast, before a window opens, when Recordly isn't there or a take was left running.
  let recordly = null;
  if (!options.login && !options.dryRun) {
    recordly = await helper.connect();
    if ((await recordly.status()).recording) throw new Error(LEFT_RUNNING);
  }

  const url = options.login && !new URL(options.url).hash ? `${options.url}#owner` : options.url;   // #owner shows the gear
  const context = await launch(chromium, options, url);
  session.context = context;
  try {
    // The --app window's page (Recordly's helper finds it); headless has none, so the first page goes there at once.
    const page = await helper.openAppPage(context, url, { timeoutMs: options.headless ? 1 : 5000 });
    if (options.login) {
      console.log("Sign in as owner, switch on the open-weights model and Show it built, then close the window");
      await new Promise((resolve) => { context.once("close", resolve); page.once("close", resolve); });
      return;
    }
    if (!options.headless) {
      try {
        await helper.sizeWindowForViewport(page, VIEWPORT);
      } catch (error) {
        throw new Error(`${error.message}: the takes need a ${VIEWPORT.width}×${VIEWPORT.height} page; use a bigger display or less scaling`);
      }
    }

    const shots = selectShots(SHOTS, options.only);
    const downloads = path.join(path.dirname(options.profile), "orca-demo-downloads");
    const dryRunShots = path.join(path.dirname(options.profile), "orca-demo-dry-run");
    const ctx = { page, recordly, url: options.url, filters: options.filters, xray: options.xray, downloads, dryRunShots,
      click: (locator) => helper.glideClick(page, locator.first()),
      glide: (locator) => helper.glideTo(page, locator.first()),   // the cursor there, no click
      retake: (why) => { ctx.retakeWhy = why; console.warn(`  Retake: ${why}`); },
      log: (line) => console.log(line) };
    const results = [];
    for (const shot of shots) results.push(await record(shot, ctx));

    console.log(`\n${options.dryRun ? "Dry run" : "Takes"}:`);
    for (const r of results) console.log(summaryLine(r));
    process.exitCode = exitCodeOf(results);
  } finally {
    await context.close().catch(() => undefined);
  }
}

module.exports = { SHOT_NAMES, SHOTS, USAGE, defaultProfile, parseArgs, selectShots, loadRecordly, startTake, runTake,
  interruptTake, takeState, summaryLine, exitCodeOf };

if (require.main === module) {
  main().catch((error) => {
    console.error(error.message || error);
    process.exitCode = 1;
  });
}
