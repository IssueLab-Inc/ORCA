// S0 for Show it built, step 2: ORCA's viewer renders each fix four ways (web/spikes/built.ts).
// Needs the server (8000) and `npx vite --port 5173` in web/. Usage: node capture.cjs OUT_DIR [radius ...]
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

(async () => {
  const out = process.argv[2];
  const radii = process.argv.slice(3).map(Number);
  const { cases } = JSON.parse(fs.readFileSync(path.join(out, "manifest.json"), "utf8"));
  const browser = await chromium.launch({ args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
  const page = await browser.newPage({ viewport: { width: 1024, height: 1024 } });
  page.on("console", (m) => { if (m.type() === "error") console.log("page:", m.text()); });
  await page.goto("http://localhost:5173/spikes/built.html");
  await page.waitForFunction(() => window.s0 && window.s0.ready, null, { timeout: 60000 });
  for (const c of cases) {
    for (const r of radii.length ? radii : [3]) {
      const t = Date.now();
      const p = await page.evaluate(([c, r]) => window.s0.passes(c, r), [c, r]);
      const dir = path.join(out, "passes", `${c.name}-R${r}`);
      fs.mkdirSync(dir, { recursive: true });
      for (const k of ["look", "ids", "normals", "depth", "fix"]) {
        fs.writeFileSync(path.join(dir, `${k}.png`), Buffer.from(p[k].split(",")[1], "base64"));
      }
      fs.writeFileSync(path.join(dir, "legend.json"), JSON.stringify({ legend: p.legend, near: p.near, far: p.far, views: p.views, best: p.best, cut: p.cut }));
      console.log(`${c.name} R${r}: ${((Date.now() - t) / 1000).toFixed(1)} s, view ${p.best} shows ${(p.views[p.best].shown * 100).toFixed(0)}% of the fix, ${p.cut.length} cut`);
    }
  }
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
