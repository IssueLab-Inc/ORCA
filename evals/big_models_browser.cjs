// The browser half of evals/big_models.py: upload a model through "Use your own models" the way a visitor does, and
// time each stage the page reports (packing, uploading, the server opening it, drawing), then the JS heap.
//
//   cd server && SIGHTLINE_MODEL_UPLOAD_MAX_MB=600 uv run uvicorn sightline.app:app --port 8000   (web built)
//   node ../evals/big_models_browser.cjs http://localhost:8000 /tmp/big-150.ifc
const { chromium } = require("playwright");

const [url = "http://localhost:8000", file] = process.argv.slice(2);
(async () => {
  const browser = await chromium.launch({ args: ["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist",
    "--enable-precise-memory-info"] });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 300)));
  page.on("console", (m) => { if ((m.type() === "error" || m.type() === "warning") && !m.text().includes("GL Driver")) errors.push(m.text().slice(0, 300)); });
  page.on("crash", () => errors.push("the page crashed (out of memory?)"));
  await page.goto(url);
  await page.locator('[data-tour="blank"]').first().click();
  const t0 = Date.now();
  const at = () => ((Date.now() - t0) / 1000).toFixed(1);
  const stages = [];
  let last = "";
  const watch = setInterval(async () => {
    const text = await page.locator(".overlay.live").first().innerText().catch(() => "");
    const stage = text.replace(/[\d.,]+%.*|\d[\d,]* of [\d,]+.*/, "").trim();   // one row per stage, not per percent
    if (text && stage !== last) { last = stage; stages.push([at(), text.trim()]); console.log(`${at()} s  ${text.trim()}`); }
  }, 250);
  await page.locator('input[type="file"]').first().setInputFiles(file);
  const opened = await page.waitForFunction(() => /[\d,]+ elements/.test(document.querySelector(".stat.mono")?.textContent ?? "")
    || !!document.querySelector(".overlay.error"), null, { timeout: 30 * 60 * 1000, polling: 500 }).then(() => true, () => false);
  clearInterval(watch);
  const shown = await page.locator(".stat.mono").first().innerText().catch(() => "");
  const heap = await page.evaluate(() => performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1e6) : null);
  const failure = await page.locator(".overlay.error").first().innerText().catch(() => "");
  console.log(JSON.stringify({ opened: opened && !!shown, seconds: Number(at()), shown, js_heap_mb: heap,
    failure: failure.slice(0, 300) || null, errors: errors.slice(0, 5) }));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
