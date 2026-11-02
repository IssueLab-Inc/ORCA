// The proposal clips for the README and (--landing) the landing page: live runs recorded in ORCA's own app, as animated
// WebP time-lapses.
//
// Each run opens a demo the way a visitor does, picks one clash, chooses Propose fixes and waits for the verified
// options (a real Muse Spark call: the server needs META_API_KEY), flips Before / After, then opens Activity in its
// own window and replays the run's Workings there. The encoder (`timelapse.py`, Pillow from the server's environment)
// speeds the waits up and stamps the speed on every frame.
//
//   cd server && uv run uvicorn sightline.app:app --port 8765      (built web app; the demo models in samples/)
//   node web/scripts/capture-proposals.cjs [--url http://localhost:8765] [--only duct,cell] [--landing] [--keep] [--gpu]
//   node web/scripts/capture-proposals.cjs [--landing] --from <kept folder>      (encode a kept recording again)
//
// Writes docs/media/proposals/<name>.webp (the whole app) and <name>-workings.webp (the Workings replay).
// --landing writes the landing page's clips to web/public/demos/ instead (RUNS, `landing`): the demo cards'
// fix-northbank and fix-cell (the 3D view alone), and one clip per step of "What ORCA does": check (the check and the
// list), understand (the Clash panel: the pictures, then Muse Spark's reasoning), workings (the Workings graph alone)
// and keep (the fix kept in the model). Each has a -still.webp of its last frame for people who ask for less motion.
// --keep keeps the frames and the times, and --from encodes them again (another pace, another badge) without a new
// proposal. --gpu draws with the machine's graphics card instead of SwiftShader (Direct3D on Windows: 20 frames a
// second against 2 for Northbank under SwiftShader, which skipped the ideas being tried).
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
const FPS = 10;

// What each run opens and does, and the clips made from it: the README's (`readme`) or the landing's (`landing`).
// A clip names its frames ("app", the main window, or "workings", Activity's own window replaying the run), its pace
// (PACE) and, on the landing, the part of the window it keeps (`crop`, measured during the run). `check`: open the
// demo and check it, no proposal. `accept`: keep the fix after Before / After.
const NORTHBANK = /Open the Northbank demo/, CELL = /Open the machine cell/;
const RUNS = [
  { name: "duct", open: NORTHBANK, clash: 1, accept: LANDING,
    readme: [{ name: "duct", pace: "readme" }, { name: "duct-workings", frames: "workings", pace: "readmeWorkings" }],
    landing: [{ name: "fix-northbank", pace: "card", crop: "stage" }, { name: "understand", pace: "understand", crop: "panel" },
      { name: "workings", frames: "workings", pace: "workings", crop: "graph" }, { name: "keep", pace: "keep", crop: "stage" }] },
  { name: "tray", open: NORTHBANK, clash: 2, readme: [{ name: "tray", pace: "readme" }] },
  { name: "cold-water", open: NORTHBANK, clash: 3, readme: [{ name: "cold-water", pace: "readme" }] },
  { name: "cell", open: CELL, clash: 66,
    readme: [{ name: "cell", pace: "readme" }, { name: "cell-workings", frames: "workings", pace: "readmeWorkings" }],
    landing: [{ name: "fix-cell", pace: "card", crop: "stage" }] },
  { name: "check", open: NORTHBANK, check: true, landing: [{ name: "check", pace: "check", crop: "list" }] },
];

// The pace, [from, to, speed] on the recording's clock (`at`, the times `mark` took).
const PACE = {
  // The README's: the camera's flight and the wait for Muse Spark fastest, the options and Before / After readable.
  readme: (at) => [[at.clash - 0.3, at.propose, 6], [at.propose, at.options, 4], [at.options, at.end, 3]],
  readmeWorkings: (at) => [[at.replay - 0.5, at.replayed, 2]],
  // A demo card: the wait at 6x but its last 5 s (the ideas tried in the model) at 2x.
  card: (at) => { const tries = Math.max(at.propose, at.options - 5);
    return [[at.clash - 0.3, at.propose, 6], [at.propose, tries, 6], [tries, at.options, 2], [at.options, at.end, 3]]; },
  // Step 1: the check as it runs (from when the models are drawn), then the list being named.
  check: (at) => { const from = Math.max(at.check, at.drawn) - 0.2;
    return [[from, at.listed + 1.5, 1], [at.listed + 1.5, at.named, 4]]; },
  // Step 2: the pictures, Muse Spark's reasoning arriving, its understanding of the clash; it ends before the options.
  understand: (at) => { const late = Math.max(at.reasoning, at.options - 10);
    return [[at.propose - 0.3, at.reasoning, 2], [at.reasoning, late, 6], [late, at.options - 0.5, 2]]; },
  // Step 3: in Workings, Muse Spark's round at 10x, then ORCA's checks and the rank at half speed (on the graphics
  // card they took 1.2 s of the replay, too quick to read), ending on the verified option rather than on the whole
  // run, too small at that size.
  workings: (at) => { const checks = Math.max(at.replay + 3.4, at.done - 1.2);
    return [[at.replay + 0.4, at.replay + 3.4, 2], [at.replay + 3.4, checks, 10], [checks, at.done + 0.6, 0.5],
      [at.done + 0.6, at.done + 1.4, 1]]; },
  // Step 4: the fix in After, Accept, the model edited and checked again.
  keep: (at) => [[at.end - 2, at.kept + 4, 1]],
};

// The README shows the whole app. The landing's cards are about 500 px wide, where the whole app's words are too small
// to read: its clips keep one part of a small window recorded at twice the pixels (the 3D view with the left and bottom
// bars collapsed, the Clash panel, the list, the Workings graph zoomed in further). Badges: where the speed sits in
// each part, clear of the words (fractions; y is the badge's bottom edge). The panel is words throughout: no badge,
// and the landing says that clip is sped up.
const CUT = LANDING
  ? { out: path.join(ROOT, "web", "public", "demos"), app: { width: 1110, height: 435 }, check: { width: 1110, height: 680 },
      workings: { width: 720, height: 540 }, scale: 2, width: 1000, zoomIns: 4,
      badges: { stage: "0.6,0.965", panel: "none", graph: "0.02,0.965", list: "0.7,0.97" } }
  : { out: path.join(ROOT, "docs", "media", "proposals"), app: { width: 1440, height: 900 }, workings: { width: 1200, height: 675 },
      scale: 1, width: 960, zoomIns: 2, badges: { app: "0.525,0.555", workings: "0.02,0.875" } };

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

// The landing's frames: the whole window, at full scale. The screencast sends the page at its CSS size even at twice
// the pixels, so a small window comes out blurred; a screenshot comes at full scale (ten a second is plenty for a
// time-lapse at 2-6x). Each clip crops its part afterwards, so one run gives several.
async function snapshots(ctx, page, dir, t0) {
  fs.mkdirSync(dir, { recursive: true });
  const cdp = await ctx.newCDPSession(page), v = page.viewportSize(); let n = 0, on = true;
  const clip = { x: 0, y: 0, width: v.width, height: v.height, scale: CUT.scale };
  const loop = (async () => {
    while (on) {
      const a = Date.now();
      try {
        const { data } = await cdp.send("Page.captureScreenshot", { format: "jpeg", quality: 90, clip });
        const t = ((a + Date.now()) / 2 - t0) / 1000;
        fs.writeFileSync(path.join(dir, `f${String(n++).padStart(5, "0")}_${t.toFixed(3)}.jpg`), Buffer.from(data, "base64"));
      } catch { break; }   // the page closed
      await new Promise((r) => setTimeout(r, Math.max(0, 100 - (Date.now() - a))));
    }
  })();
  return async () => { on = false; await loop; };
}

// A part of the window, as fractions of it (and its width in CSS pixels): the element's box, from `after`'s right edge
// when given, `height` tall from its top when given, else trimmed about its middle to `ratio` (width / height).
async function cropOf(page, sel, { after, ratio, height } = {}) {
  const v = page.viewportSize(), b = await page.locator(sel).first().boundingBox();
  let x0 = Math.max(0, b.x), y0 = Math.max(0, b.y), x1 = Math.min(v.width, b.x + b.width), y1 = Math.min(v.height, b.y + b.height);
  if (after) { const r = await page.locator(after).first().boundingBox(); x0 = r.x + r.width + 6; }
  if (height) y1 = Math.min(y1, y0 + height);
  else if (ratio) {
    const w = x1 - x0, h = y1 - y0;
    if (w / h > ratio) { const d = (w - h * ratio) / 2; x0 += d; x1 -= d; } else { const d = (h - w / ratio) / 2; y0 += d; y1 -= d; }
  }
  return { frac: [x0 / v.width, y0 / v.height, x1 / v.width, y1 / v.height].map((n) => n.toFixed(4)).join(","), width: x1 - x0 };
}

// Scroll the Clash panel so `sel` (the first match holding `text`, when given) sits at its top, as a person would.
async function scrollPanel(page, sel, text) {
  await page.evaluate(([sel, text]) => {
    const el = [...document.querySelectorAll(sel)].find((e) => !text || e.textContent?.includes(text));
    let box = document.querySelector('[data-tour="propose"]');
    while (box && !(box.scrollHeight > box.clientHeight && /auto|scroll/.test(getComputedStyle(box).overflowY))) box = box.parentElement;
    if (el && box) box.scrollTop += el.getBoundingClientRect().top - box.getBoundingClientRect().top - 8;
  }, [sel, text ?? ""]);
}

function encode(frames, out, badge, segments, crop) {
  // A part keeps its own pixels: never wider than it was recorded.
  const width = crop ? Math.min(CUT.width, Math.round(crop.width * CUT.scale)) : CUT.width;
  execFileSync("uv", ["run", "-q", "python", path.join(__dirname, "timelapse.py"), frames, out, String(width), String(FPS),
    ...segments.map(([a, b, s]) => `${a.toFixed(2)}:${b.toFixed(2)}:${s}`)],
    { cwd: path.join(ROOT, "server"), stdio: "inherit", env: { ...process.env, BADGE: badge, CROP: crop?.frac ?? "",
      BADGE_PX: LANDING ? String(Math.round(26 * width / 1000)) : "", STILL: LANDING ? out.replace(/\.webp$/, "-still.webp") : "" } });
}

async function record(browser, run, tmp) {
  const clips = LANDING ? run.landing : run.readme, workings = clips.some((c) => c.frames === "workings");
  const ctx = await browser.newContext({ viewport: run.check ? CUT.check : CUT.app, deviceScaleFactor: CUT.scale });
  const t0 = Date.now(), at = { run: run.name, crops: {} };
  const mark = (m) => { at[m] = (Date.now() - t0) / 1000; console.log(`  ${at[m].toFixed(1)} s ${m}`); };
  const page = await ctx.newPage();
  await page.goto(URL);

  if (run.check) {
    // Step 1: from the check to the list, named; the clip starts once the models are drawn (the check starts while
    // the loading card is still up). Its part: the list and the 3D view beside it, 4:3 from the top left.
    await page.waitForTimeout(1000);
    const stop = await snapshots(ctx, page, path.join(tmp, "app"), t0);
    await page.getByRole("button", { name: run.open }).first().click(); mark("open");
    await page.getByText("ORCA is checking the models").first().waitFor({ timeout: 180000 }); mark("check");
    await page.getByText(/Loading \d+ models/).first().waitFor({ state: "hidden", timeout: 180000 }); mark("drawn");
    const v = page.viewportSize(), right = (await page.locator("main.stage").first().boundingBox()) ?? { x: 0, width: 700 };
    const w = right.x + right.width, h = Math.min(v.height, Math.round(w * 3 / 4));
    at.crops.list = { frac: [0, 0, w / v.width, h / v.height].map((n) => n.toFixed(4)).join(","), width: w };
    await page.waitForSelector("button.clash-main", { timeout: 180000, state: "attached" }); mark("listed");
    await page.waitForTimeout(12000); mark("named");
    await stop(); await ctx.close();
    return at;
  }

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
    at.crops.stage = await cropOf(page, "main.stage", { after: "nav.rail", ratio: 16 / 10 });
    stop = await snapshots(ctx, page, path.join(tmp, "app"), t0);
    await page.waitForTimeout(1500);
    await page.keyboard.press("f");
  } else {
    stop = await screencast(ctx, page, path.join(tmp, "app"), t0);
    await page.waitForTimeout(500);
    await clash.click();
  }
  mark("clash"); await page.waitForTimeout(4000);
  if (LANDING) {
    // Step 2 watches the Clash panel, all of it that shows: its three pictures at the top, then (scrolled) Muse
    // Spark's reasoning, kept in view as it grows (a panel scrolled once stops at its end, leaving what comes next below).
    await scrollPanel(page, ".clash-panel");
    const box = await page.locator('[data-tour="propose"]').evaluateHandle((el) => {
      while (el && !(el.scrollHeight > el.clientHeight && /auto|scroll/.test(getComputedStyle(el).overflowY))) el = el.parentElement;
      return el;
    });
    const r = await box.asElement().boundingBox(), v = page.viewportSize();
    at.crops.panel = { frac: [r.x / v.width, r.y / v.height, (r.x + r.width) / v.width, Math.min(v.height, r.y + r.height) / v.height]
      .map((n) => n.toFixed(4)).join(","), width: r.width };
  }
  await page.locator('[data-tour="propose"]').click(); mark("propose");
  let follow;
  if (LANDING) {
    await page.waitForTimeout(6000); mark("reasoning");
    follow = setInterval(() => { scrollPanel(page, "h2", "Understanding").catch(() => {}); }, 1000);
  }
  await page.waitForSelector(".card-body.option", { timeout: 300000 });
  await page.waitForFunction(() => !document.querySelector('[data-tour="propose"]')?.textContent?.includes("Working"), null, { timeout: 300000 });
  clearInterval(follow);
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
  mark("end");
  console.log(`  ${count} verified option(s): ${(await options.locator(".opt-title").allInnerTexts()).join(" | ")}`);
  if (run.accept) {
    // Step 4: keep the first option. The server tries it again, edits the model and checks it.
    await page.locator('[data-tour="accept"]').first().click(); mark("accept");
    await page.getByText("Fix kept in the model").first().waitFor({ timeout: 120000 }); mark("kept");
    await page.waitForTimeout(5000);
  }
  await stop();

  if (workings) {
    const bottom = page.getByRole("button", { name: "Open the bottom bar" });
    if (await bottom.count()) { await bottom.first().click(); await page.waitForTimeout(800); }
    const [pop] = await Promise.all([ctx.waitForEvent("page"), page.getByRole("button", { name: "Open Activity in its own window" }).click()]);
    await pop.setViewportSize(CUT.workings);
    await pop.waitForTimeout(2500);
    const dir = path.join(tmp, "workings");
    if (LANDING) at.crops.graph = await cropOf(pop, ".wk-canvas");
    const stopPop = LANDING ? await snapshots(ctx, pop, dir, t0) : await screencast(ctx, pop, dir, t0);
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

function encodeRun(run, at, tmp) {
  for (const c of LANDING ? run.landing : run.readme) {
    const frames = c.frames ?? "app";
    if (!fs.existsSync(path.join(tmp, frames))) continue;
    encode(path.join(tmp, frames), path.join(CUT.out, `${c.name}.webp`), CUT.badges[c.crop ?? frames], PACE[c.pace](at),
      c.crop ? at.crops[c.crop] : undefined);
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
  for (const run of RUNS.filter((r) => (LANDING ? r.landing : r.readme) && (!ONLY || ONLY.split(",").includes(r.name)))) {
    console.log(run.check ? `${run.name}: open and check` : `${run.name}: clash #${run.clash}`);
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "orca-proposals-"));
    const at = await record(browser, run, tmp);
    fs.writeFileSync(path.join(tmp, "times.json"), JSON.stringify(at, null, 1));
    encodeRun(run, at, tmp);
    if (KEEP) console.log(`  frames and times kept in ${tmp} (--from to encode again)`);
    else fs.rmSync(tmp, { recursive: true, force: true });
  }
  await browser.close();
})();
