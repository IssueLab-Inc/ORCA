/**
 * The demo video's cards (docs/demo-video.md, "Production notes"), set as the app sets its own words: IBM Plex Sans on
 * white cards with the notch's 14 px corners, saved as transparent PNGs at twice the pixels for the edit.
 *   - next-line.png: what's next, under the notch for the last 4 s;
 *   - chip-observe.png, chip-resolve.png, chip-check.png, chip-apply.png: the letter of ORCA each beat opens with.
 * Plex comes from Google Fonts, as in the app (index.html); the script stops rather than save a picture in a fallback
 * font.
 *
 *   node web/scripts/video-cards.cjs [--out docs/media/video]
 */
const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");

const SIZE = 32;   // CSS px: text about 32 px tall on a 1920 × 1080 frame once a 2× picture is placed at half size
const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");

const CARDS = {
  "next-line": `<div class="card"><b>Next:</b> ${esc("fixes that land in the designers’ own tools,")}<br>${esc("and checks against photos and scans of the site.")}</div>`,
  ...Object.fromEntries(["Observe", "Resolve", "Check", "Apply"].map((word) =>
    [`chip-${word.toLowerCase()}`, `<div class="card chip"><b>${word[0]}</b>${esc(word)}</div>`])),
};

const outArg = process.argv.indexOf("--out");
const outDir = path.resolve(outArg > 0 ? process.argv[outArg + 1] : path.join(__dirname, "..", "..", "docs", "media", "video"));

const page = (body) => `<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600&display=block">
<style>
  html, body { margin: 0; background: transparent; }
  .card { display: inline-block; margin: 8px; padding: 18px 30px 20px; background: #fff; border: 1px solid #dde3e7;
    border-radius: 14px; color: #11161b; font: 400 ${SIZE}px/1.35 "IBM Plex Sans"; text-align: center; }
  .card b { font-weight: 600; color: #052640; }
  .chip { display: inline-flex; align-items: center; gap: 16px; padding: 12px 26px 12px 14px; }
  .chip b { display: grid; place-items: center; width: 52px; height: 52px; border-radius: 10px; background: #052640;
    color: #fff; font-size: ${SIZE}px; line-height: 1; }
</style></head><body>${body}</body></html>`;

(async () => {
  const browser = await chromium.launch();
  try {
    const tab = await browser.newPage({ deviceScaleFactor: 2, viewport: { width: 1600, height: 400 } });
    fs.mkdirSync(outDir, { recursive: true });
    for (const [name, body] of Object.entries(CARDS)) {
      await tab.setContent(page(body), { waitUntil: "networkidle" });
      const loaded = await tab.evaluate(async (size) => {
        await document.fonts.ready;
        return ["400", "600"].every((w) => document.fonts.check(`${w} ${size}px "IBM Plex Sans"`)) &&
          [...document.fonts].some((f) => f.family.replace(/"/g, "") === "IBM Plex Sans" && f.status === "loaded");
      }, SIZE);
      if (!loaded) throw new Error("IBM Plex Sans did not load from Google Fonts: nothing more saved (a fallback font would not match the app)");
      const out = path.join(outDir, `${name}.png`);
      await tab.locator(".card").screenshot({ path: out, omitBackground: true });
      console.log(`saved ${path.relative(process.cwd(), out)}`);
    }
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error(e.message); process.exit(1); });
