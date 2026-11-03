/**
 * The demo video's "what's next" card (docs/demo-video.md, the last shot): the line set as the app sets its own
 * words, IBM Plex Sans on a white card with the notch's 14 px corners, saved as a transparent PNG at twice the pixels
 * for the edit. Plex comes from Google Fonts, as in the app (index.html); the script stops rather than save a picture
 * in a fallback font.
 *
 *   node web/scripts/video-next-line.cjs [--out docs/media/video/next-line.png]
 */
const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");

const LEAD = "Next:";
const LINES = ["fixes that land in the designers’ own tools,", "and checks against photos and scans of the site."];
const SIZE = 32;   // CSS px: text about 32 px tall on a 1920 × 1080 frame once the 2× picture is placed at half size

const outArg = process.argv.indexOf("--out");
const out = path.resolve(outArg > 0 ? process.argv[outArg + 1] : path.join(__dirname, "..", "..", "docs", "media", "video", "next-line.png"));

const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");
const page = `<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600&display=block">
<style>
  html, body { margin: 0; background: transparent; }
  .card { display: inline-block; margin: 8px; padding: 18px 30px 20px; background: #fff; border: 1px solid #dde3e7;
    border-radius: 14px; color: #11161b; font: 400 ${SIZE}px/1.35 "IBM Plex Sans"; text-align: center; }
  .card b { font-weight: 600; color: #052640; }
</style></head><body><div class="card"><b>${esc(LEAD)}</b> ${LINES.map(esc).join("<br>")}</div></body></html>`;

(async () => {
  const browser = await chromium.launch();
  try {
    const tab = await browser.newPage({ deviceScaleFactor: 2, viewport: { width: 1600, height: 400 } });
    await tab.setContent(page, { waitUntil: "networkidle" });
    const loaded = await tab.evaluate(async (size) => {
      await document.fonts.ready;
      return ["400", "600"].every((w) => document.fonts.check(`${w} ${size}px "IBM Plex Sans"`)) &&
        [...document.fonts].some((f) => f.family.replace(/"/g, "") === "IBM Plex Sans" && f.status === "loaded");
    }, SIZE);
    if (!loaded) throw new Error("IBM Plex Sans did not load from Google Fonts: nothing saved (a fallback font would not match the app)");
    fs.mkdirSync(path.dirname(out), { recursive: true });
    await tab.locator(".card").screenshot({ path: out, omitBackground: true });
    console.log(`saved ${path.relative(process.cwd(), out)}`);
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error(e.message); process.exit(1); });
