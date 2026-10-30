import assert from "node:assert/strict";
import test from "node:test";
import * as THREE from "three";
import { compiled } from "./app-host.mjs";

const v = await import(await compiled("../src/viewer/views.ts", { three: import.meta.resolve("three") }));
const levels = [
  { name: "Foundations", elevation_m: -1.2, height_m: 1.2 }, { name: "Level 01", elevation_m: 0, height_m: 4 },
  { name: "Level 02", elevation_m: 4, height_m: 4 }, { name: "Roof", elevation_m: 8, height_m: null },
];

test("layouts split the stage into one, two or four panes that tile it", () => {
  assert.deepEqual(v.paneRects("single", 800, 600), [{ x: 0, y: 0, w: 800, h: 600 }]);
  assert.deepEqual(v.paneRects("two", 800, 600), [{ x: 0, y: 0, w: 400, h: 600 }, { x: 400, y: 0, w: 400, h: 600 }]);
  const quad = v.paneRects("quad", 801, 601, { x: 0.25, y: 0.5 });
  assert.equal(quad.length, 4);
  assert.equal(quad.reduce((n, r) => n + r.w * r.h, 0), 801 * 601);
  assert.deepEqual(v.paneRects("two", 1000, 500, { x: 0.05, y: 0.5 })[0].w, 200, "a split never leaves a pane under a fifth");
  assert.deepEqual(v.defaultKinds("quad"), ["plan", "3d", "section", "elevation"]);
});

test("a plan's view range follows its level and keeps the cut above the bottom", () => {
  assert.deepEqual(v.planRange(levels, { kind: "plan", level: 2, cut: 1.2, bottom: 0 }).cutZ, 5.2);
  const r = v.planRange(levels, { kind: "plan", level: 1, cut: 0.5, bottom: 0.8 });
  assert.equal(r.bottomZ, 0.8);
  assert.ok(Math.abs(r.cutZ - 0.81) < 1e-9, "the cut stays 10 mm above the bottom");
  assert.equal(v.planRange(levels, { kind: "plan", level: 1, cut: 1.2, bottom: null }).bottomZ, null);
});

test("plan presets: floor plan, ceiling void and whole storey; none needing a next level on the top one", () => {
  assert.deepEqual(v.planPreset(levels, 1, "floor"), { cut: 1.2, bottom: 0 });
  const ceiling = v.planPreset(levels, 1, "ceiling");
  assert.ok(Math.abs(ceiling.cut - 3.95) < 1e-9 && ceiling.bottom === 2.4);
  assert.ok(Math.abs(v.planPreset(levels, 1, "storey").cut - 3.95) < 1e-9);
  assert.equal(v.planPreset(levels, 3, "ceiling"), null);
  assert.deepEqual(v.planPreset(levels, 3, "floor"), { cut: 1.2, bottom: 0 });
});

test("a clash sets the plan's level and a cut through it, between 0.3 m and the storey less 50 mm", () => {
  const spec = { kind: "plan", level: 0, cut: 1.2, bottom: 0 };
  assert.deepEqual(v.planThrough(levels, 3.5, spec), { kind: "plan", level: 1, cut: 3.5, bottom: 0 });
  assert.ok(Math.abs(v.planThrough(levels, 7.99, spec).cut - 3.95) < 1e-9);
  assert.equal(v.planThrough(levels, 4.05, spec).cut, 0.3);
  assert.equal(v.planThrough(levels, 2, { ...spec, bottom: null }).bottom, null, "a bottom the user turned off stays off");
  assert.equal(v.levelAt(levels, -5), 0);
  assert.deepEqual(v.levelsOrModel([], 0.1, 2.1), [{ name: "Model", elevation_m: 0.1, height_m: 2 }]);
});

test("sections look to the line's left, flip to its right, and run along the longer side of the moving run", () => {
  const f = v.sectionFrame({ angle: 0, flip: false });
  assert.deepEqual(f.along.map(Math.round), [1, 0]);
  assert.deepEqual(f.look.map((x) => Math.round(x) + 0), [0, 1]);
  assert.deepEqual(v.sectionFrame({ angle: 0, flip: true }).look.map((x) => Math.round(x) + 0), [0, -1]);
  const spec = { kind: "section", origin: [0, 0], angle: 1, flip: false, far: 2, crop: { left: 1, right: 1, bottom: -1, top: 9 } };
  const along = v.sectionThrough([3, 4, 3.5], { min: [0, 3.7, 3.2], max: [16, 4.3, 3.8] }, spec);
  assert.equal(along.angle, 0);
  assert.deepEqual(along.origin, [3, 4]);
  assert.equal(along.crop.left, 8, "half the run, at most 6 m, plus 2 m");
  assert.equal(v.sectionThrough([0, 0, 0], { min: [0, 0, 0], max: [1, 9, 1] }, spec).angle, Math.PI / 2);
});

test("elevations: which one looks the same way, and which grid axes they show", () => {
  assert.equal(v.facingFor([0, 1]), "south");
  assert.equal(v.facingFor([-1, 0.2]), "east");
  assert.deepEqual(v.facingLook("west"), [1, 0]);
  const axis = { tag: "1", grid: "G", start: [0, -8, 0], end: [0, 8, 0] };
  assert.equal(v.gridShows(axis, [0, 1]), true);
  assert.equal(v.gridShows(axis, [1, 0]), false);
});

test("the nearest standard scale and a round scale bar", () => {
  assert.equal(v.nearestScale(0.0254 / 96 * 100), 100);
  assert.equal(v.nearestScale(0.0254 / 96 * 130), 100);
  assert.equal(v.nearestScale(0.0254 / 96 * 180), 200);
  const bar = v.scaleBar(0.05, 100);
  assert.equal(bar.metres, 5);
  assert.equal(Math.round(bar.pixels), 100);
  assert.equal(v.level3(4), "+4.000");
  assert.equal(v.level3(-1.2), "−1.200");
});

test("the view cube: faces, edges and corners give 26 directions with their names", () => {
  assert.deepEqual(v.cubeRegion(new THREE.Vector3(0.1, 1, -0.2)).toArray(), [0, 1, 0]);
  assert.deepEqual(v.cubeRegion(new THREE.Vector3(0.9, 1, 0)).toArray(), [1, 1, 0]);
  assert.deepEqual(v.cubeRegion(new THREE.Vector3(0.8, 1, 0.9)).toArray(), [1, 1, 1]);
  assert.equal(v.cubeName(new THREE.Vector3(0, 0, 1)), "Front");
  assert.equal(v.cubeName(new THREE.Vector3(1, 1, -1)), "Top Back Right");
});

test("camera history: back and forward through jumps, a new jump clears the way forward", () => {
  const h = new v.CameraHistory(3);
  const p = (x) => ({ position: [x, 0, 0], target: [0, 0, 0] });
  assert.equal(h.canBack, false);
  h.push(p(1)); h.push(p(1)); h.push(p(2));
  assert.deepEqual(h.goBack(p(3)), p(2));
  assert.deepEqual(h.goBack(p(2)), p(1));
  assert.equal(h.goBack(p(1)), null);
  assert.deepEqual(h.goForward(p(1)), p(2));
  h.push(p(9));
  assert.equal(h.canForward, false);
  for (let i = 0; i < 10; i++) h.push(p(10 + i));
  let n = 0; while (h.goBack(p(0))) n++;
  assert.equal(n, 3, "at most `max` jumps are kept");
});

test("visibility: hidden for now, isolated, class and level filters", () => {
  const f = { classes: ["IfcSlab"], levels: ["Roof"] }, none = { hidden: [], isolated: null };
  assert.equal(v.shownBy("w", "IfcWall", "Level 01", f, none), true);
  assert.equal(v.shownBy("s", "IfcSlab", "Level 01", f, none), false);
  assert.equal(v.shownBy("r", "IfcWall", "Roof", f, none), false);
  assert.equal(v.shownBy("w", "IfcWall", "Level 01", f, { hidden: ["w"], isolated: null }), false);
  assert.equal(v.shownBy("w", "IfcWall", "Level 01", f, { hidden: [], isolated: ["x"] }), false);
  assert.equal(v.shownBy("x", undefined, undefined, f, { hidden: [], isolated: ["x"] }), true);
});

test("Esc clears one thing at a time and never leaves a clash ORCA is working on", () => {
  const s = { measuring: false, lightbox: false, selection: false, clash: true, working: false };
  assert.equal(v.escStep({ ...s, measuring: true, selection: true }), "measure");
  assert.equal(v.escStep({ ...s, lightbox: true, selection: true }), "lightbox");
  assert.equal(v.escStep({ ...s, selection: true }), "selection");
  assert.equal(v.escStep(s), "clash");
  assert.equal(v.escStep({ ...s, working: true }), null);
  assert.equal(v.escStep({ ...s, clash: false }), null);
});
