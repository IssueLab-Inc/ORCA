// The README's proposal clips: live proposal runs recorded in ORCA's own app, as animated WebP time-lapses.
//
// Each run opens a demo the way a visitor does, picks one clash, chooses Propose fixes and waits for the verified
// options (a real Muse Spark call: the server needs META_API_KEY), flips Before / After, then opens Activity in its
// own window and replays the run's Workings there. Frames come from the browser's screencast; the encoder
// (`timelapse.py`, Pillow from the server's environment) speeds the waits up and stamps the speed on every frame.
//
//   cd server && uv run uvicorn sightline.app:app --port 8765      (built web app; the demo models in samples/)
//   node web/scripts/capture-proposals.cjs [--url http://localhost:8765] [--only duct,cell]
//
// Writes docs/media/proposals/<name>.webp (the whole app) and <name>-workings.webp (the Workings replay).
// Each run is a fresh proposal, so the options and wording can differ from the last capture.
const { chromium } = require("playwright");
const { execFileSync } = require("child_process");
const path = require("path");
const fs = require("fs");
const os = require("os");

const arg = (name, fallback) => { const i = process.argv.indexOf(name); return i > 0 ? process.argv[i + 1] : fallback; };
const URL = arg("--url", "http://localhost:8765");
const ONLY = arg("--only", "");
const ROOT = path.resolve(__dirname, "..", "..");
const OUT = path.join(ROOT, "docs", "media", "proposals");

// What to open and which clash (its #N in the demo's list). `workings`: also write the Workings replay clip.
const RUNS = [
  { name: "duct", open: /Open the Northbank demo/, clash: 1, workings: true },
  { name: "tray", open: /Open the Northbank demo/, clash: 2 },
  { name: "cold-water", open: /Open the Northbank demo/, clash: 3 },
  { name: "cell", open: /Open the machine cell/, clash: 66, workings: true },
];
const WIDTH = 960, FPS = 10;
const APP_BADGE = "0.525,0.555", WORKINGS_BADGE = "0.02,0.875";   // where the speed sits: inside the 3D view, the graph

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

function encode(frames, out, badge, segments) {
  execFileSync("uv", ["run", "-q", "python", path.join(__dirname, "timelapse.py"), frames, out, String(WIDTH), String(FPS),
    ...segments.map(([a, b, s]) => `${a.toFixed(2)}:${b.toFixed(2)}:${s}`)],
    { cwd: path.join(ROOT, "server"), stdio: "inherit", env: { ...process.env, BADGE: badge } });
}

async function record(browser, run, tmp) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const t0 = Date.now(), at = {};
  const mark = (m) => { at[m] = (Date.now() - t0) / 1000; console.log(`  ${at[m].toFixed(1)} s ${m}`); };
  const page = await ctx.newPage();
  await page.goto(URL);
  await page.getByRole("button", { name: run.open }).first().click();
  await page.waitForSelector("button.clash-main", { timeout: 180000, state: "attached" });
  await page.waitForTimeout(4000);
  const stop = await screencast(ctx, page, path.join(tmp, "app"), t0);
  await page.waitForTimeout(500);
  await page.locator("button.clash-main").filter({ has: page.getByText(`#${run.clash}`, { exact: true }) }).first().click();
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

  if (run.workings) {
    const [pop] = await Promise.all([ctx.waitForEvent("page"), page.getByRole("button", { name: "Open Activity in its own window" }).click()]);
    await pop.setViewportSize({ width: 1200, height: 675 });
    await pop.waitForTimeout(2500);
    const stopPop = await screencast(ctx, pop, path.join(tmp, "workings"), t0);
    for (let i = 0; i < 2; i++) { await pop.getByRole("button", { name: "Zoom in" }).click(); await pop.waitForTimeout(300); }
    await pop.getByRole("button", { name: "Follow" }).click();
    await pop.waitForTimeout(1000);
    mark("replay"); await pop.getByRole("button", { name: "Replay" }).click();
    await pop.waitForTimeout(1500);
    await pop.waitForFunction(() => [...document.querySelectorAll("button")].some((b) => b.textContent?.trim() === "Replay"), null, { timeout: 180000 });
    await pop.waitForTimeout(1500);
    await pop.getByRole("button", { name: "Fit" }).click(); await pop.waitForTimeout(3000);
    mark("replayed"); await stopPop();
  }
  await ctx.close();
  return at;
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ args: ["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"] });
  for (const run of RUNS.filter((r) => !ONLY || ONLY.split(",").includes(r.name))) {
    console.log(`${run.name}: clash #${run.clash}`);
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "orca-proposals-"));
    const at = await record(browser, run, tmp);
    // The camera's flight and the wait for Muse Spark go fastest; the options and Before / After stay readable.
    encode(path.join(tmp, "app"), path.join(OUT, `${run.name}.webp`), APP_BADGE,
      [[at.clash - 0.3, at.propose, 6], [at.propose, at.options, 4], [at.options, at.end, 3]]);
    if (run.workings) encode(path.join(tmp, "workings"), path.join(OUT, `${run.name}-workings.webp`), WORKINGS_BADGE,
      [[at.replay - 0.5, at.replayed, 2]]);
    fs.rmSync(tmp, { recursive: true, force: true });
  }
  await browser.close();
})();
