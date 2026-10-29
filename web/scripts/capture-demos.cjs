// The two demo pictures on the landing page and in the README, captured in Sightline's own viewer.
//
// Opens each demo the way a visitor does, waits for the check, picks a view, saves the canvas with the viewer's own
// Screenshot button, then crops it to 16:10 and writes WebP with Pillow (from the server's environment).
//
//   cd server && uv run uvicorn sightline.app:app --port 8765      (the demo models in samples/)
//   node web/scripts/capture-demos.cjs [--url http://localhost:8765]
//
// Writes web/public/demos/northbank.webp and cell.webp. Recapture after the viewer's look or the demo models change.
const { chromium } = require("playwright");
const { execFileSync } = require("child_process");
const path = require("path");
const fs = require("fs");
const os = require("os");

const arg = (name, fallback) => { const i = process.argv.indexOf(name); return i > 0 ? process.argv[i + 1] : fallback; };
const URL = arg("--url", "http://localhost:8765");
const ROOT = path.resolve(__dirname, "..", "..");
const OUT = path.join(ROOT, "web", "public", "demos");

// What to open, and the view: a preset key (1 top, 2 front, 3 right, 4 iso) and how far to dolly in after Fit
// (wheel steps over the middle of the canvas; negative zooms in).
const DEMOS = [
  { name: "northbank", open: /Open the Northbank demo/, view: "4", zoom: -4 },
  { name: "cell", open: /Open the machine cell/, view: "4", zoom: -2 },
];

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "sightline-demos-"));
  const browser = await chromium.launch({ args: ["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"] });
  for (const demo of DEMOS) {
    const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, acceptDownloads: true });
    await page.goto(URL);
    await page.getByRole("button", { name: demo.open }).first().click();
    await page.waitForSelector("button.clash-main", { timeout: 180000, state: "attached" });
    await page.waitForTimeout(3000);
    const canvas = page.locator("main.stage canvas").first();
    const box = await canvas.boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.keyboard.press("h");
    await page.keyboard.press(demo.view);
    await page.waitForTimeout(1500);
    for (let i = 0; i < Math.abs(demo.zoom); i++) { await page.mouse.wheel(0, Math.sign(demo.zoom) * 120); await page.waitForTimeout(120); }
    await page.waitForTimeout(1500);
    const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Save a screenshot" }).click()]);
    const png = path.join(tmp, `${demo.name}.png`);
    await download.saveAs(png);
    const webp = path.join(OUT, `${demo.name}.webp`);
    execFileSync("uv", ["run", "python", "-c", `
import sys
from PIL import Image
im = Image.open(sys.argv[1]).convert("RGB")
w, h = im.size
cw, ch = (w, round(w * 10 / 16)) if w * 10 / 16 <= h else (round(h * 16 / 10), h)
left, top = (w - cw) // 2, (h - ch) // 2
im.crop((left, top, left + cw, top + ch)).resize((1200, 750), Image.LANCZOS).save(sys.argv[2], "WEBP", quality=80, method=6)
`, png, webp], { cwd: path.join(ROOT, "server"), stdio: "inherit" });
    console.log(`${webp}: ${Math.round(fs.statSync(webp).size / 1024)} KB`);
    await page.close();
  }
  await browser.close();
  fs.rmSync(tmp, { recursive: true, force: true });
})();
