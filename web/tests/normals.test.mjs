import assert from "node:assert/strict";
import test from "node:test";
import * as THREE from "three";
import { compiled } from "./app-host.mjs";

const n = await import(await compiled("../src/viewer/normals.ts", { three: import.meta.resolve("three") }));

/** A prism of `sides` round the y axis (radius 1, height 1), built the way web-ifc builds one: each side facet and each
 * cap its own vertices, so every vertex belongs to one flat face. */
function prism(sides) {
  const pos = [], idx = [];
  const ring = (i, y) => [Math.cos((2 * Math.PI * i) / sides), y, Math.sin((2 * Math.PI * i) / sides)];
  for (let i = 0; i < sides; i++) {
    const v = pos.length / 3;
    pos.push(...ring(i, 0), ...ring(i + 1, 0), ...ring(i + 1, 1), ...ring(i, 1));
    idx.push(v, v + 2, v + 1, v, v + 3, v + 2);
  }
  for (const y of [0, 1]) {
    const v = pos.length / 3;
    for (let i = 0; i < sides; i++) pos.push(...ring(i, y));
    for (let i = 1; i < sides - 1; i++) idx.push(...(y ? [v, v + i, v + i + 1] : [v, v + i + 1, v + i]));
  }
  return { pos: new Float32Array(pos), idx: new Uint32Array(idx) };
}

/** A unit box with its 8 corners shared by every face that meets there (welded, as IfcOpenShell sends a preview). */
function weldedBox() {
  const pos = new Float32Array([0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0, 0, 0, 1, 1, 0, 1, 1, 1, 1, 0, 1, 1]);
  const idx = new Uint32Array([0, 2, 1, 0, 3, 2, 4, 5, 6, 4, 6, 7, 0, 1, 5, 0, 5, 4, 3, 7, 6, 3, 6, 2, 0, 4, 7, 0, 7, 3, 1, 2, 6, 1, 6, 5]);
  return { pos, idx };
}

const at = (a, i) => [a[i * 3], a[i * 3 + 1], a[i * 3 + 2]];
const len = (v) => Math.hypot(...v);
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];

test("a 24-sided round shades smooth: every side vertex's normal points straight out from the axis", () => {
  const { pos, idx } = prism(24);
  const out = n.creaseNormals(pos, idx);
  assert.equal(out.position.length, pos.length, "no vertex split: each already belongs to one face");
  assert.deepEqual([...out.index], [...idx]);
  for (let v = 0; v < 24 * 4; v++) {
    const p = at(out.position, v), nm = at(out.normal, v);
    const radial = [p[0], 0, p[2]].map((c) => c / Math.hypot(p[0], p[2]));
    assert.ok(dot(nm, radial) > 0.9999, `side vertex ${v} is radial`);
  }
});

test("a round's caps stay flat and its rim stays a sharp edge", () => {
  const { pos, idx } = prism(24);
  const out = n.creaseNormals(pos, idx);
  for (let v = 24 * 4; v < pos.length / 3; v++) {
    const nm = at(out.normal, v);
    assert.ok(Math.abs(Math.abs(nm[1]) - 1) < 1e-6, `cap vertex ${v} points along the axis`);
  }
});

test("facets 30° apart (a 12-sided round) smooth at the crease; 60° apart (a hexagon) stay sharp", () => {
  const twelve = n.creaseNormals(prism(12).pos, prism(12).idx);
  const p0 = at(twelve.position, 0), n0 = at(twelve.normal, 0);
  assert.ok(dot(n0, [p0[0], 0, p0[2]]) > 0.9999, "12 sides: radial");
  const { pos, idx } = prism(6);
  const six = n.creaseNormals(pos, idx);
  // vertex 0 is on the first facet, whose own normal is half way between its two corners
  const flat = [Math.cos(Math.PI / 6), 0, Math.sin(Math.PI / 6)];
  assert.ok(dot(at(six.normal, 0), flat) > 0.9999, "6 sides: the facet's own normal");
  assert.ok(n.CREASE > (30 * Math.PI) / 180 && n.CREASE < (55 * Math.PI) / 180);
});

test("a welded box splits its corners: each face keeps its own flat normal", () => {
  const { pos, idx } = weldedBox();
  const out = n.creaseNormals(pos, idx);
  assert.equal(out.position.length / 3, 24, "8 corners × 3 faces");
  assert.equal(out.index.length, idx.length);
  for (let t = 0; t < out.index.length; t += 3) {
    const [a, b, c] = [out.index[t], out.index[t + 1], out.index[t + 2]].map((v) => at(out.position, v));
    const u = [b[0] - a[0], b[1] - a[1], b[2] - a[2]], w = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
    const face = [u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0]];
    const f = face.map((x) => x / len(face));
    for (let k = 0; k < 3; k++) assert.ok(dot(at(out.normal, out.index[t + k]), f) > 0.9999, `triangle ${t / 3} is flat`);
  }
});

test("without an index, every three vertices are a triangle", () => {
  const { pos, idx } = prism(24);
  const soup = new Float32Array(idx.length * 3);
  idx.forEach((v, i) => soup.set(at(pos, v), i * 3));
  const out = n.creaseNormals(soup, null);
  assert.equal(out.index.length, idx.length);
  const p = at(out.position, out.index[0]), nm = at(out.normal, out.index[0]);
  assert.ok(dot(nm, [p[0], 0, p[2]].map((c) => c / Math.hypot(p[0], p[2]))) > 0.9999);
});

test("degenerate triangles and lone vertices give no NaN", () => {
  const pos = new Float32Array([0, 0, 0, 1, 0, 0, 2, 0, 0, 0, 1, 0, 5, 5, 5]);
  const idx = new Uint32Array([0, 1, 2, 0, 1, 3]);   // the first is a line
  const out = n.creaseNormals(pos, idx);
  for (const x of out.normal) assert.ok(Number.isFinite(x));
  assert.ok(Math.abs(Math.abs(out.normal[2]) - 1) < 1e-6, "vertex 0 takes the real triangle's normal");
});

test("creased builds a geometry three.js can draw", () => {
  const { pos, idx } = prism(24);
  const g = n.creased(pos, idx);
  assert.ok(g instanceof THREE.BufferGeometry);
  assert.equal(g.getAttribute("normal").count, g.getAttribute("position").count);
  assert.equal(g.getIndex().count, idx.length);
});
