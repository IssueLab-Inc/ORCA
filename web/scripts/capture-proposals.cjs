// The proposal clips for the README and (--landing) the landing page: live proposal runs recorded in ORCA's own app, as
// animated WebP time-lapses.
//
// Each run opens a demo the way a visitor does, picks one clash, chooses Propose fixes and waits for the verified
// options (a real Muse Spark call: the server needs META_API_KEY), flips Before / After, then opens Activity in its
// own window and replays the run's Workings there. Frames come from the browser's screencast; the encoder
// (`timelapse.py`, Pillow from the server's environment) speeds the waits up and stamps the speed on every frame.
//
//   cd server && uv run uvicorn sightline.app:app --port 8765      (built web app; the demo models in samples/)
//   node web/scripts/capture-proposals.cjs [--url http://localhost:8765] [--only duct,cell] [--landing] [--keep] [--gpu]
//   node web/scripts/capture-proposals.cjs [--landing] --from <kept folder>      (encode a kept recording again)
//
// Writes docs/media/proposals/<name>.webp (the whole app) and <name>-workings.webp (the Workings replay).
// --landing writes the landing page's clips instead: web/public/demos/fix-northbank.webp and fix-cell.webp (the 3D view
// alone) and workings.webp (the Workings graph alone, Northbank's run), each with a -still.webp of its last frame for
// people who ask for less motion. --keep keeps the frames and the times, and --from encodes them again (another pace,
// another badge) without a new proposal. --gpu draws with the machine's graphics card instead of SwiftShader (Direct3D
// on Windows: 20 frames a second against 2 for Northbank under SwiftShader, which skipped the ideas being tried).
// Each run is a fresh proposal, so the options and wording can differ from the last capture.
const { execFileSync } = require("child_process");
const path = require("path");
const fs = require("fs");
const os = require("os");

const arg = (name, fallback) => { const i = process.argv.indexOf(name); return i > 0 ? process.argv[i + 1] : fallback; };
const URL = arg("--url", "http://localhost:8765");
const ONLY = arg("--only", "");
const LANDING = process.argv.includes("--landing"), KEEP = process.argv.includes("--keep"), FROM = arg("--from", "");
const GL = process.argv.includes("--gpu")
  ? ["--enable-gpu", "--ignore-gpu-blocklist", `--use-angle=${{ win32: "d3d11", darwin: "metal" }[process.platform] ?? "vulkan"}`]
  : ["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"];
const ROOT = path.resolve(__dirname, "..", "..");

// What to open and which clash (its #N in the demo's list). `workings`: also write the Workings replay clip.
// `landing`: the clip's name on the landing page, and `landingWorkings` the one Workings clip there.
const RUNS = [
  { name: "duct", open: /Open the Northbank demo/, clash: 1, workings: true, landing: "fix-northbank", landingWorkings: "workings" },
  { name: "tray", open: /Open the Northbank demo/, clash: 2 },
  { name: "cold-water", open: /Open the Northbank demo/, clash: 3 },
  { name: "cell", open: /Open the machine cell/, clash: 66, workings: true, landing: "fix-cell" },
];
const FPS = 10;
// The README shows the whole app. The landing's cards are about 500 px wide, where the whole app's words are too small
// to read: it shows the 3D view alone (the left and bottom bars collapsed, the rail cropped off) and the Workings graph
// alone, each recorded in a small window at twice the pixels, the graph zoomed in further. Badges: where the speed sits
// (the 3D view, the graph).
//
// The pace, [from, to, speed] on the recording's clock (`at`, the times `mark` took). The README's: the camera's flight
// and the wait for Muse Spark fastest, the options and Before / After readable. The landing's is shorter: the wait at
// 6x but its last 5 s (the ideas tried in the model) at 2x; in Workings, Muse Spark's round at 10x, then ORCA's checks
// and the rank at half speed (on the graphics card they took 1.2 s of the replay, too quick to read), ending on the
// verified option rather than on the whole run, too small at that size.
const CUT = LANDING
  ? { out: path.join(ROOT, "web", "public", "demos"), app: { width: 1110, height: 435 }, workings: { width: 720, height: 540 },
      scale: 2, width: 1000, appBadge: "0.6,0.965", workingsBadge: "0.02,0.965", badgePx: "26", zoomIns: 4,
      appPace: (at) => { const tries = Math.max(at.propose, at.options - 5);
        return [[at.clash - 0.3, at.propose, 6], [at.propose, tries, 6], [tries, at.options, 2], [at.options, at.end, 3]]; },
      workingsPace: (at) => { const checks = Math.max(at.replay + 3.4, at.done - 1.2);
        return [[at.replay + 0.4, at.replay + 3.4, 2], [at.replay + 3.4, checks, 10], [checks, at.done + 0.6, 0.5],
          [at.done + 0.6, at.done + 1.4, 1]]; } }
  : { out: path.join(ROOT, "docs", "media", "proposals"), app: { width: 1440, height: 900 }, workings: { width: 1200, height: 675 },
      scale: 1, width: 960, appBadge: "0.525,0.555", workingsBadge: "0.02,0.875", badgePx: "", zoomIns: 2,
      appPace: (at) => [[at.clash - 0.3, at.propose, 6], [at.propose, at.options, 4], [at.options, at.end, 3]],
      workingsPace: (at) => [[at.replay - 0.5, at.replayed, 2]] };

async function screencast(ctx, page, dir, t0) {
  fs.mkdirSync(dir, { recursive: true });
  const cdp = await ctx.newCDPSession(page); let n = 0;
  cdp.on("Page.screencastFrame", async (f) => {
    const t = (f.metadata.timestamp * 1000 - t0) / 1000;
    fs.writeFileSync(path.join(dir, `f${String(n++).padStart(5, "0")}_${t.toFixed(3)}.jpg`), Buffer.from(f.data, "base64"));
    try { await cdp.send("Page.screencastFrameAck", { sessionId: f.sessionId }); } catch { /* page closed */ }
  });
  const box = page.viewportSize();
  await cdp.send("Page.startScreencast", { format: "jpeg", quality: 90, maxWidth: box.width, maxHeight: box.height });
  return () => cdp.send("Page.stopScreencast");
}

// The landing's frames. The screencast sends the page at its CSS size even at twice the pixels, so a small window comes
// out blurred; a screenshot of just the part to keep comes at full scale (about 26 a second under SwiftShader, and ten
// is plenty for a time-lapse at 2-6x).
async function snapshots(ctx, page, dir, t0, clip) {
  fs.mkdirSync(dir, { recursive: true });
  const cdp = await ctx.newCDPSession(page); let n = 0, on = true;
  const loop = (async () => {
    while (on) {
      const a = Date.now();
      try {
        const { data } = await cdp.send("Page.captureScreenshot", { format: "jpeg", quality: 90, clip: { ...clip, scale: CUT.scale } });
        const t = ((a + Date.now()) / 2 - t0) / 1000;
        fs.writeFileSync(path.join(dir, `f${String(n++).padStart(5, "0")}_${t.toFixed(3)}.jpg`), Buffer.from(data, "base64"));
      } catch { break; }   // the page closed
      await new Promise((r) => setTimeout(r, Math.max(0, 100 - (Date.now() - a))));
    }
  })();
  return async () => { on = false; await loop; };
}

// The part of the window to keep: the element's box, from `after`'s right edge when given, trimmed about its middle to
// `ratio` (width / height) when given.
async function clipOf(page, sel, { after, ratio } = {}) {
  const v = page.viewportSize(), b = await page.locator(sel).first().boundingBox();
  let x0 = Math.max(0, b.x), y0 = Math.max(0, b.y), x1 = Math.min(v.width, b.x + b.width), y1 = Math.min(v.height, b.y + b.height);
  if (after) { const r = await page.locator(after).first().boundingBox(); x0 = r.x + r.width + 6; }
  if (ratio) {
    const w = x1 - x0, h = y1 - y0;
    if (w / h > ratio) { const d = (w - h * ratio) / 2; x0 += d; x1 -= d; } else { const d = (h - w / ratio) / 2; y0 += d; y1 -= d; }
  }
  return { x: Math.round(x0), y: Math.round(y0), width: Math.round(x1 - x0), height: Math.round(y1 - y0) };
}

function encode(frames, out, badge, segments) {
  execFileSync("uv", ["run", "-q", "python", path.join(__dirname, "timelapse.py"), frames, out, String(CUT.width), String(FPS),
    ...segments.map(([a, b, s]) => `${a.toFixed(2)}:${b.toFixed(2)}:${s}`)],
    { cwd: path.join(ROOT, "server"), stdio: "inherit", env: { ...process.env, BADGE: badge, BADGE_PX: CUT.badgePx,
      STILL: LANDING ? out.replace(/\.webp$/, "-still.webp") : "" } });
}

async function record(browser, run, tmp, workings) {
  const ctx = await browser.newContext({ viewport: CUT.app, deviceScaleFactor: CUT.scale });
  const t0 = Date.now(), at = { run: run.name };
  const mark = (m) => { at[m] = (Date.now() - t0) / 1000; console.log(`  ${at[m].toFixed(1)} s ${m}`); };
  const page = await ctx.newPage();
  await page.goto(URL);
  await page.getByRole("button", { name: run.open }).first().click();
  await page.waitForSelector("button.clash-main", { timeout: 180000, state: "attached" });
  await page.waitForTimeout(4000);
  const clash = page.locator("button.clash-main").filter({ has: page.getByText(`#${run.clash}`, { exact: true }) }).first();
  if (!(await clash.count())) {   // the list draws only the rows on screen: filter it down to the clash
    await page.getByLabel("Filter clashes").fill(`#${run.clash}`);
    await clash.waitFor({ state: "attached" });
  }
  let stop;
  if (LANDING) {
    // Pick the clash while its list is open (a collapsed bar draws no rows; in a list this narrow the row's actions
    // cover the button), give the window to the 3D view, step back to the whole model, then fly to the clash on camera
    // with the F key (the rail's button would scroll the short stage to reach it).
    await clash.evaluate((b) => b.click());
    await page.waitForTimeout(3000);
    for (const edge of ["left", "bottom"]) { await page.getByRole("button", { name: `Collapse the ${edge} bar` }).first().click(); await page.waitForTimeout(600); }
    const c = await page.locator("main.stage canvas").first().boundingBox();
    await page.mouse.move(c.x + c.width / 2, c.y + c.height / 2);
    await page.keyboard.press("h");
    await page.waitForTimeout(2500);
    stop = await snapshots(ctx, page, path.join(tmp, "app"), t0, await clipOf(page, "main.stage", { after: "nav.rail", ratio: 16 / 10 }));
    await page.waitForTimeout(1500);
    await page.keyboard.press("f");
  } else {
    stop = await screencast(ctx, page, path.join(tmp, "app"), t0);
    await page.waitForTimeout(500);
    await clash.click();
  }
  mark("clash"); await page.waitForTimeout(4000);
  await page.locator('[data-tour="propose"]').click(); mark("propose");
  await page.waitForSelector(".card-body.option", { timeout: 300000 });
  await page.waitForFunction(() => !document.querySelector('[data-tour="propose"]')?.textContent?.includes("Working"), null, { timeout: 300000 });
  mark("options"); await page.waitForTimeout(3000);
  const options = page.locator(".card-body.option"), count = await options.count();
  const pick = async (i) => { if ((await options.nth(i).getAttribute("aria-pressed")) !== "true") await options.nth(i).click(); await page.waitForTimeout(3000); };
  await pick(0);
  for (const m of ["Before", "After", "Before", "After"]) {
    const b = page.locator(".compare .seg button", { hasText: m });
    if (await b.count()) { await b.first().click(); await page.waitForTimeout(1600); }
  }
  for (let i = 1; i < Math.min(count, 3); i++) await pick(i);
  if (count > 1) await pick(0);
  mark("end"); await stop();
  console.log(`  ${count} verified option(s): ${(await options.locator(".opt-title").allInnerTexts()).join(" | ")}`);

  if (workings) {
    const bottom = page.getByRole("button", { name: "Open the bottom bar" });
    if (await bottom.count()) { await bottom.first().click(); await page.waitForTimeout(800); }
    const [pop] = await Promise.all([ctx.waitForEvent("page"), page.getByRole("button", { name: "Open Activity in its own window" }).click()]);
    await pop.setViewportSize(CUT.workings);
    await pop.waitForTimeout(2500);
    const dir = path.join(tmp, "workings");
    const stopPop = LANDING ? await snapshots(ctx, pop, dir, t0, await clipOf(pop, ".wk-canvas")) : await screencast(ctx, pop, dir, t0);
    for (let i = 0; i < CUT.zoomIns; i++) { await pop.getByRole("button", { name: "Zoom in" }).click(); await pop.waitForTimeout(300); }
    await pop.getByRole("button", { name: "Follow" }).click();
    await pop.waitForTimeout(1000);
    mark("replay"); await pop.getByRole("button", { name: "Replay" }).click();
    await pop.waitForTimeout(1500);
    await pop.waitForFunction(() => [...document.querySelectorAll("button")].some((b) => b.textContent?.trim() === "Replay"), null, { timeout: 180000 });
    mark("done"); await pop.waitForTimeout(1500);
    await pop.getByRole("button", { name: "Fit" }).click(); await pop.waitForTimeout(3000);
    mark("replayed"); await stopPop();
  }
  await ctx.close();
  return at;
}

// The clip's names: the landing's, or the README's.
const names = (run) => LANDING ? { name: run.landing, workings: run.landingWorkings }
  : { name: run.name, workings: run.workings && `${run.name}-workings` };

function encodeRun(run, at, tmp) {
  const { name, workings } = names(run);
  encode(path.join(tmp, "app"), path.join(CUT.out, `${name}.webp`), CUT.appBadge, CUT.appPace(at));
  if (workings && fs.existsSync(path.join(tmp, "workings"))) {
    encode(path.join(tmp, "workings"), path.join(CUT.out, `${workings}.webp`), CUT.workingsBadge, CUT.workingsPace(at));
  }
}

(async () => {
  fs.mkdirSync(CUT.out, { recursive: true });
  if (FROM) {
    const at = JSON.parse(fs.readFileSync(path.join(FROM, "times.json"), "utf8"));
    encodeRun(RUNS.find((r) => r.name === at.run), at, FROM);
    return;
  }
  const { chromium } = require("playwright");   // only to record: --from needs Pillow alone
  const browser = await chromium.launch({ args: GL });
  for (const run of RUNS.filter((r) => (!LANDING || r.landing) && (!ONLY || ONLY.split(",").includes(r.name)))) {
    console.log(`${run.name}: clash #${run.clash}`);
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "orca-proposals-"));
    const at = await record(browser, run, tmp, names(run).workings);
    fs.writeFileSync(path.join(tmp, "times.json"), JSON.stringify(at, null, 1));
    encodeRun(run, at, tmp);
    if (KEEP) console.log(`  frames and times kept in ${tmp} (--from to encode again)`);
    else fs.rmSync(tmp, { recursive: true, force: true });
  }
  await browser.close();
})();
