import assert from "node:assert/strict";
import test from "node:test";
import { compiled } from "./app-host.mjs";

const northbank = await compiled("../src/landing/northbank.ts");
const scene = await import(northbank);
const check = await import(await compiled("../src/landing/check.ts", { "./northbank": northbank }));

const near = (a, b, tol = 1e-6) => Math.abs(a - b) <= tol;

test("the duct as modelled runs 300 mm into the girder's web: the clash list's -300 mm", () => {
  const c = check.checkRaise(0);
  assert.equal(c.clashGone, false);
  assert.ok(near(c.overlap, 0.3), `overlap ${c.overlap}`);
  assert.equal(c.verified, false);
  assert.deepEqual(c.newHits, []);
});

test("raised 400 mm the duct sits in the web opening with 50 mm all round: the recorded fix", () => {
  const c = check.checkRaise(0.4);
  assert.ok(c.clashGone && !c.newHits.length && c.verified);
  assert.ok(near(c.clearance, 0.05), `clearance ${c.clearance}`);
  assert.equal(c.nearest, "Transfer plate girder");
  assert.ok(check.checkRaise(0.4, 0.05).verified, "it meets a 50 mm requirement too");
});

test("part way up it still runs into the web, and at the opening's edge it only touches", () => {
  const half = check.checkRaise(0.2);
  assert.ok(!half.clashGone && near(half.overlap, 0.15), `overlap ${half.overlap}`);
  const touch = check.checkRaise(0.35);
  assert.ok(touch.clashGone && !touch.verified && near(touch.clearance, 0), "touching is no clash, but no room either");
});

test("only a 50 mm band passes at 25 mm of room, and only +400 mm at 50 mm", () => {
  const bands = check.passingBands(0.025);
  assert.equal(bands.length, 1);
  assert.ok(near(bands[0][0], 0.375) && near(bands[0][1], 0.425), JSON.stringify(bands));
  assert.deepEqual(check.passingBands(0.05).map(([a, b]) => [Math.round(a * 1000), Math.round(b * 1000)]), [[400, 400]]);
});

test("raised past the opening it hits the web again, then the slab: the clash can go while something new is hit", () => {
  const top = check.checkRaise(0.5);
  assert.ok(!top.clashGone && !top.verified);
  const flange = check.checkRaise(0.8);
  assert.ok(!flange.clashGone, "at +800 mm its bottom is still in the top flange");
  const slab = check.checkRaise(0.85);
  assert.ok(slab.clashGone, "clear of the girder");
  assert.deepEqual(slab.newHits, ["Level 03 floor slab"]);
  assert.equal(slab.verified, false);
});

test("lowered, it runs into the bottom flange and the web below the opening", () => {
  const c = check.checkRaise(-0.25);
  assert.ok(!c.clashGone && !c.verified);
});

test("millimetres read as the app writes them", () => {
  assert.equal(check.mm(0.4, true), "+400 mm");
  assert.equal(check.mm(-0.3, true), "-300 mm");
  assert.equal(check.mm(0.05), "50 mm");
  assert.equal(check.mm(-0.0001, true), "0 mm");
});

test("an offset's centreline rises through square-ish bends and comes back to the run's height", () => {
  const path = scene.offsetPath(0, 6, 7.18, [{ a: 2.8, b: 4.2, dz: 0.4, r: 0.15 }]);
  assert.deepEqual(path[0], [0, 7.18]);
  assert.deepEqual(path.at(-1), [6, 7.18]);
  const top = Math.max(...path.map((p) => p[1]));
  assert.ok(near(top, 7.58), `top ${top}`);
  for (let i = 1; i < path.length; i++) assert.ok(path[i][0] >= path[i - 1][0] - 1e-9, "x never goes back");
  // the raised stretch spans the risers' centres, 1.40 m apart
  const raised = path.filter((p) => near(p[1], 7.58));
  assert.ok(near(raised[0][0], 2.95) && near(raised.at(-1)[0], 4.05), JSON.stringify(raised));
});

test("an offset taken down mirrors one taken up", () => {
  const up = scene.offsetPath(0, 6, 1, [{ a: 2, b: 4, dz: 0.5, r: 0.1 }]);
  const down = scene.offsetPath(0, 6, 1, [{ a: 2, b: 4, dz: -0.5, r: 0.1 }]);
  assert.equal(up.length, down.length);
  up.forEach((p, i) => assert.ok(near(p[0], down[i][0]) && near(p[1] - 1, 1 - down[i][1]), `${p} vs ${down[i]}`));
});

test("a cut keeps the part of a run between two distances, on its level stretches", () => {
  const path = scene.offsetPath(-1, 8, 7.18, [{ a: 2.8, b: 4.2, dz: 0.4, r: 0.15 }]);
  const mid = scene.cutPath(path, 2.45, 4.55);
  assert.deepEqual(mid[0], [2.45, 7.18]);
  assert.deepEqual(mid.at(-1), [4.55, 7.18]);
  const left = scene.cutPath(path, -1, 2.45);
  assert.deepEqual(left, [[-1, 7.18], [2.45, 7.18]]);
});

test("a swept duct closes: its faces' normals point out, and a straight one is the box it should be", () => {
  const s = scene.sweep([[0, 0], [2, 0]], 0, scene.rect(0.6, 0.3));
  assert.equal(s.positions.length, (4 * 2 + 2 * 2) * 3 * 3, "four sides of two triangles, two caps of two");
  const xs = [], ys = [], zs = [];
  for (let i = 0; i < s.positions.length; i += 3) { xs.push(s.positions[i]); ys.push(s.positions[i + 1]); zs.push(s.positions[i + 2]); }
  assert.ok(near(Math.min(...ys), -0.3) && near(Math.max(...ys), 0.3) && near(Math.min(...zs), -0.15) && near(Math.max(...zs), 0.15));
  // every face's normal points away from the centreline
  for (let i = 0; i < s.positions.length; i += 9) {
    const c = [0, 1, 2].map((k) => (s.positions[i + k] + s.positions[i + 3 + k] + s.positions[i + 6 + k]) / 3);
    const n = [s.normals[i], s.normals[i + 1], s.normals[i + 2]];
    const cap = near(c[0], 0, 1e-5) ? -1 : near(c[0], 2, 1e-5) ? 1 : 0;
    const out = cap ? [cap, 0, 0] : [0, c[1], c[2]];
    assert.ok(n[0] * out[0] + n[1] * out[1] + n[2] * out[2] > 0, `face at ${c} faces in`);
  }
});

test("a mitred corner keeps the duct's full depth: an L of 300 mm duct has its corners where they should be", () => {
  const s = scene.sweep([[0, 0], [1, 0], [1, 1]], 0, scene.rect(0.6, 0.3), false, false);
  const xs = [], zs = [];
  for (let i = 0; i < s.positions.length; i += 3) { xs.push(s.positions[i]); zs.push(s.positions[i + 2]); }
  assert.ok(near(Math.max(...xs), 1.15, 1e-5) && near(Math.min(...zs), -0.15, 1e-5), `outer corner ${Math.max(...xs)}, ${Math.min(...zs)}`);
  assert.ok(near(Math.min(...xs.filter((x, i) => zs[i] > 0.9)), 0.85, 1e-5), "the upright leg is 300 mm deep");
});

test("the answer key's three runs each pass through their own web opening once fixed", () => {
  for (const run of scene.RUNS) {
    const open = scene.GIRDER.openings.find((o) => o.y[0] < run.y && o.y[1] > run.y && o.z[0] < run.z + run.fix.dz && o.z[1] > run.z + run.fix.dz);
    assert.ok(open, `${run.key} has an opening at its fixed height`);
    const ys = run.section.map((p) => run.y + p[0]), zs = run.section.map((p) => run.z + run.fix.dz + p[1]);
    const room = Math.min(Math.min(...ys) - open.y[0], open.y[1] - Math.max(...ys), Math.min(...zs) - open.z[0], open.z[1] - Math.max(...zs));
    assert.ok(near(room, run.clear, 0.0015), `${run.key}: ${room} against the recorded ${run.clear}`);
  }
});

const timeline = await import(await compiled("../src/landing/timeline.ts"));

test("the replay opens on the check, then pins the three answer-key clashes", () => {
  const start = timeline.heroAt(0.5);
  assert.equal(start.phase, "observe");
  assert.ok(start.scan >= 0, "the check sweeps across the scene");
  for (const k of ["duct", "tray", "cw"]) assert.equal(start.runs[k].pin, "hidden");
  const pinned = timeline.heroAt(3.4);
  for (const k of ["duct", "tray", "cw"]) assert.equal(pinned.runs[k].pin, "clash");
  assert.ok(pinned.girder > 0.9, "the girder shows as the clash's element B");
});

test("each fix is tried, passes the check, then is kept, in that order", () => {
  const T = timeline.T.duct;
  const trying = timeline.heroAt((T.lift[0] + T.lift[1]) / 2);
  assert.equal(trying.phase, "resolve");
  assert.ok(trying.runs.duct.ghost > 0.9 && trying.runs.duct.tone === "try" && trying.runs.duct.lift > 0 && trying.runs.duct.lift < 1);
  const checking = timeline.heroAt((T.check + T.pass) / 2);
  assert.equal(checking.phase, "check");
  assert.ok(checking.runs.duct.checking > 0);
  assert.equal(timeline.heroAt(T.pass + 0.1).runs.duct.tone, "pass");
  const kept = timeline.heroAt(T.keep + 1);
  assert.equal(kept.phase, "apply");
  assert.ok(kept.runs.duct.pin === "fixed" && kept.runs.duct.fixed === 1);
  assert.equal(kept.runs.tray.pin, "clash", "the next clash is still to come");
});

test("the tray's round: the whole lift fails on what it hits, then the round's offset passes", () => {
  const T = timeline.T.tray;
  const fail = timeline.heroAt(T.fail + 0.3);
  assert.ok(fail.whole.opacity > 0.9 && fail.whole.fail > 0.9 && fail.hits > 0, "the whole move shows what it hit");
  assert.equal(timeline.logAt(T.fail + 0.3).at(-1).tone, "fail");
  const gone = timeline.heroAt(T.idea + 0.2);
  assert.ok(gone.whole.opacity < 0.05 && gone.hits === 0, "the failed idea leaves before the next");
  assert.equal(timeline.heroAt(T.keep + 1).runs.tray.pin, "fixed");
});

test("the replay ends on 3 of 3 at the recorded heights, and loops", () => {
  const end = timeline.heroAt(timeline.STILL);
  for (const k of ["duct", "tray", "cw"]) assert.equal(end.runs[k].pin, "fixed");
  assert.equal(end.fade, 0, "the still frame is not dimmed");
  assert.match(timeline.logAt(timeline.STILL).at(-1).text, /3 of 3 .*\+400, \+250, \+280 mm/);
  assert.equal(timeline.heroAt(timeline.LOOP + 0.5).t, 0.5, "time wraps round the loop");
  assert.ok(timeline.heroAt(timeline.LOOP - 0.01).fade > 0.9 && timeline.heroAt(0).fade === 1, "dimmed at the turn");
  assert.equal(timeline.logAt(1).length, 1);
});

test("each chapter's still shows that chapter's kept fix", () => {
  const stills = [0, 1, 2, 3, 4].map(timeline.chapterStill);
  assert.deepEqual(stills.map((t) => timeline.heroAt(t).chapter), [0, 1, 2, 3, 4]);
  assert.equal(timeline.heroAt(stills[1]).runs.duct.pin, "fixed");
  assert.equal(timeline.heroAt(stills[2]).runs.tray.pin, "fixed");
  assert.equal(timeline.heroAt(stills[3]).runs.cw.pin, "fixed");
});

test("the log's numbers are the recorded ones", () => {
  const text = timeline.LOG.map((l) => l.text).join("\n");
  for (const n of ["464 clashes in 1,732 elements", "−300 mm", "−100 mm", "−77 mm", "+375 to +425 mm", "50 mm clear all round",
    "21 elements", "(5 elements)", "53 mm clear", "(15 elements)"]) assert.ok(text.includes(n), n);
  const runs = Object.fromEntries(scene.RUNS.map((r) => [r.key, r]));
  assert.deepEqual([runs.duct.fix.dz, runs.tray.fix.dz, runs.cw.fix.dz], [0.4, 0.25, 0.28]);
  assert.deepEqual([runs.duct.checked, runs.tray.checked, runs.cw.checked], [21, 5, 15]);
});

test("the band that clears the opening is the one ORCA tells Muse Spark: +375 to +425 mm at 25 mm", () => {
  // agent.py, from edits.passages: bottom + half the duct's depth + the clearance, top - the same, less the run's height
  const open = scene.GIRDER.openings.find((o) => o.y[0] < -2.45 && o.y[1] > -2.45 && o.z[0] > 7.3);
  const duct = scene.RUNS[0], half = 0.15 + 0.025;
  assert.ok(near(open.z[0] + half - duct.z, 0.375, 1e-9) && near(open.z[1] - half - duct.z, 0.425, 1e-9));
  const [band] = check.passingBands(0.025);
  assert.ok(near(band[0], 0.375) && near(band[1], 0.425), "the hands-on check agrees");
  assert.ok(timeline.LOG.some((l) => l.text.includes("+375 to +425 mm")), "and the replay says so");
});

const logos = await import(await compiled("../src/landing/logos.ts"));

test("every logo the landing shows is a file in web/public/logos, and the strip names each format once", async () => {
  const { existsSync } = await import("node:fs");
  const { fileURLToPath } = await import("node:url");
  for (const [key, src] of Object.entries(logos.LOGO)) {
    assert.match(src, /^\/logos\/[a-z]+\.(png|svg)$/, key);
    assert.ok(existsSync(fileURLToPath(new URL(`../public${src}`, import.meta.url))), `${key}: ${src} is missing`);
  }
  const keys = logos.FORMATS.map((f) => f.key);
  assert.deepEqual([...keys].sort(), Object.keys(logos.LOGO).sort());
  for (const f of logos.FORMATS) assert.match(f.what, /\b(in|out|plugged in)$/, `${f.name} says which way it goes`);
});
