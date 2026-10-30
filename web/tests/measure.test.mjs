import assert from "node:assert/strict";
import test from "node:test";
import * as THREE from "three";
import { compiled } from "./app-host.mjs";

const m = await import(await compiled("../src/viewer/measure.ts", { three: import.meta.resolve("three") }));
const v = (x, y, z) => new THREE.Vector3(x, y, z);
const close = (a, b, e = 1e-6) => Math.abs(a - b) < e;

test("a plane through a box cuts its four sides, and the cut joins into four straight runs", () => {
  const box = new THREE.BoxGeometry(2, 1, 1).toNonIndexed();   // 12 triangles: each side's diagonal splits the cut
  const pieces = m.cutSegments(box.getAttribute("position").array, new THREE.Plane(new THREE.Vector3(0, 1, 0), 0));
  assert.equal(pieces.length, 8, "two pieces a side, one either side of its diagonal");
  const runs = m.mergeRuns(pieces);
  assert.equal(runs.length, 4);
  const lengths = runs.map(([a, b]) => a.distanceTo(b)).sort();
  assert.ok(close(lengths[0], 1) && close(lengths[1], 1) && close(lengths[2], 2) && close(lengths[3], 2));
  const c = m.candidatesOf(runs);
  assert.equal(c.ends.length, 4, "the four corners, once each");
  assert.ok(c.mids.some((p) => close(p.x, 0) && close(Math.abs(p.z), 0.5)), "a long side's middle");
});

test("collinear runs with a gap stay two runs", () => {
  const runs = m.mergeRuns([[v(0, 0, 0), v(1, 0, 0)], [v(1, 0, 0), v(2, 0, 0)], [v(3, 0, 0), v(4, 0, 0)]]);
  assert.equal(runs.length, 2);
  assert.ok(close(runs[0][0].distanceTo(runs[0][1]), 2));
});

test("an edge is clipped to what a view's planes keep", () => {
  const keepBelow = new THREE.Plane(new THREE.Vector3(0, -1, 0), 1);   // keeps y ≤ 1
  const s = m.clipSegment(v(0, 0, 0), v(0, 2, 0), [keepBelow]);
  assert.ok(s && close(s[1].y, 1) && close(s[0].y, 0));
  assert.equal(m.clipSegment(v(0, 2, 0), v(0, 3, 0), [keepBelow]), null);
});

test("snapping: an end first, then a midpoint, then the nearest point on an edge, each within its pixels", () => {
  const c = m.candidatesOf([[v(0, 0, 0), v(100, 0, 0)]]);
  const project = (p) => new THREE.Vector2(p.x, p.y);   // world = pixels, to read the cases
  assert.equal(m.pickSnap(new THREE.Vector2(5, 3), c, project).kind, "end");
  assert.equal(m.pickSnap(new THREE.Vector2(47, 6), c, project).kind, "mid");
  const edge = m.pickSnap(new THREE.Vector2(30, 5), c, project);
  assert.equal(edge.kind, "edge");
  assert.ok(close(edge.point.x, 30) && close(edge.point.y, 0));
  assert.equal(m.pickSnap(new THREE.Vector2(30, 20), c, project), null, "too far from anything");
});

test("in perspective an edge point is where the pointer's ray passes closest to the edge", () => {
  const c = m.candidatesOf([[v(-5, 0, -10), v(5, 0, -10)]]);
  const ray = new THREE.Ray(v(0, 0, 0), v(0.1, 0, -1).normalize());
  const project = (p) => new THREE.Vector2(p.x / -p.z * 100, p.y / -p.z * 100);   // a pinhole looking down −z
  const s = m.pickSnap(new THREE.Vector2(10, 0), c, project, ray, { end: 0, mid: 0, edge: 8 });
  assert.equal(s.kind, "edge");
  assert.ok(close(s.point.x, 1, 1e-6) && close(s.point.z, -10));
});

test("a measurement in words and as a line to paste, in model axes (IFC x, y, z from three's x, −z, y)", () => {
  const meas = { id: 3, a: v(1, 2, -3), b: v(2, 2, -3.5), pane: 0, view: "Level 02 · Plan" };
  assert.deepEqual(m.measureText(meas), { length: "1118 mm", parts: "Δx 1000 · Δy 500 · Δz 0" });
  assert.equal(m.copyLine(meas), "M3  1118 mm  (Δx 1000 · Δy 500 · Δz 0)  Level 02 · Plan  from (1.000, 3.000, 2.000) to (2.000, 3.500, 2.000) m");
  assert.equal(m.copyText([meas, { ...meas, id: 4 }]).split("\n").length, 2);
});
