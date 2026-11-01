import assert from "node:assert/strict";
import test from "node:test";
import * as THREE from "three";
import { compiled } from "./app-host.mjs";

const three = import.meta.resolve("three");
const views = await compiled("../src/viewer/views.ts", { three });
const d = await import(await compiled("../src/viewer/drawing.ts", { three, "./views": views,
  "./origin": await compiled("../src/viewer/origin.ts", { three }) }));
const levels = [{ name: "Level 01", elevation_m: 0, height_m: 4 }, { name: "Level 02", elevation_m: 4, height_m: 4 }, { name: "Roof", elevation_m: 8, height_m: null }];
const model = new THREE.Box3(new THREE.Vector3(-10, -1, -8), new THREE.Vector3(10, 12, 8));
const rect = { x: 0, y: 0, w: 400, h: 300 };
// IFC (x, y, z) → three.js (x, z, −y)
const at = (x, y, z) => new THREE.Vector3(x, z, -y);

test("a plan keeps what is below its cut and above its bottom, both from its level", () => {
  const v = new d.DrawingView({ kind: "plan", level: 1, cut: 1.2, bottom: 0.5 });
  v.configure(v.spec, levels, model);
  assert.equal(v.planes.length, 2);
  assert.equal(v.cut, v.planes[0], "the cut is the plane that fills cut faces");
  assert.equal(v.keeps(at(0, 0, 5)), true);
  assert.equal(v.keeps(at(0, 0, 5.3)), false, "above the cut (+5.2)");
  assert.equal(v.keeps(at(0, 0, 4.4)), false, "below the bottom (+4.5)");
  v.configure({ kind: "plan", level: 1, cut: 1.2, bottom: null }, levels, model);
  assert.equal(v.planes.length, 1);
  assert.equal(v.keeps(at(0, 0, -50)), true);
});

test("a section keeps what lies ahead of its line, up to its far clip, inside its crop", () => {
  const spec = { kind: "section", origin: [2, 3], angle: 0, flip: false, far: 1.5, crop: { left: 2, right: 4, bottom: 0, top: 6 } };
  const v = new d.DrawingView(spec);
  v.configure(spec, levels, model);
  // Line along +x through (2, 3); it looks to its left, north (+y).
  assert.equal(v.keeps(at(3, 3.5, 2)), true);
  assert.equal(v.keeps(at(3, 2.5, 2)), false, "behind the line");
  assert.equal(v.keeps(at(3, 5, 2)), false, "beyond the far clip");
  assert.equal(v.keeps(at(-1, 3.5, 2)), false, "left of the crop (x < 0)");
  assert.equal(v.keeps(at(5.9, 3.5, 2)), true);
  assert.equal(v.keeps(at(3, 3.5, 7)), false, "above the crop");
  const flipped = { ...spec, flip: true, crop: null };
  v.configure(flipped, levels, model);
  assert.equal(v.keeps(at(3, 2.5, 2)), true, "flipped, it looks south");
  assert.ok(Math.abs(d.farBehind(spec, new THREE.Box3().setFromPoints([at(0, 3.4, 0), at(1, 3.2, 1)]), 2) - 2.4) < 1e-9);
});

test("an elevation's far clip runs from the model's face on its own side", () => {
  const v = new d.DrawingView({ kind: "elevation", facing: "south", far: 3 });
  v.configure(v.spec, levels, model);
  // Looking north from the south: the south face is IFC y = −8.
  assert.equal(v.keeps(at(0, -6, 2)), true);
  assert.equal(v.keeps(at(0, -4, 2)), false);
});

test("framing, panning and zooming: the point under the pointer stays put", () => {
  const v = new d.DrawingView({ kind: "plan", level: 0, cut: 1.2, bottom: 0 });
  v.configure(v.spec, levels, model);
  v.frame(new THREE.Box3().setFromPoints([at(-2, -1, 0), at(2, 1, 1)]), rect, 0);
  v.updateCamera(rect, 100);
  const c = v.toPane(at(0, 0, 1.2), rect);
  assert.ok(Math.abs(c.x - 200) < 1e-6 && Math.abs(c.y - 150) < 1e-6, "the framed box's middle is the pane's");
  assert.ok(Math.abs(v.scale - 0.01) < 1e-9, "4 m across 400 px");
  const north = v.toPane(at(0, 1, 1.2), rect);
  assert.ok(north.y < 150, "north is up the screen");
  const under = v.fromPane(300, 50, rect);
  v.zoomAt(0.5, 300, 50, rect);
  v.updateCamera(rect, 100);
  const after = v.fromPane(300, 50, rect);
  assert.ok(under.distanceTo(after) < 1e-9);
  const x0 = v.center.x;
  v.pan(10, 0);
  assert.ok(Math.abs(v.center.x - (x0 - 10 * v.scale)) < 1e-9, "dragging right moves the drawing right");
});

test("a drawing redraws when it turns: an elevation facing another way has another camera key", () => {
  const v = new d.DrawingView({ kind: "elevation", facing: "south", far: null });
  v.configure(v.spec, levels, model);
  v.updateCamera(rect, 100);
  const south = v.cameraKey(rect);
  v.configure({ kind: "elevation", facing: "north", far: null }, levels, model);
  v.updateCamera(rect, 100);
  assert.notEqual(v.cameraKey(rect), south);
});
