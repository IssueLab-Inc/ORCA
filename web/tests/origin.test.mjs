import assert from "node:assert/strict";
import test from "node:test";
import * as THREE from "three";
import { originModule } from "./app-host.mjs";

const o = await originModule();
const close = (a, b, e = 1e-9) => Math.abs(a - b) <= e;

test("a model near its origin is drawn where it is; a georeferenced one from its elements' median, to the metre", () => {
  assert.deepEqual(o.pickOrigin([-10, 2, 11], [3, -4, 6]), [0, 0], "Northbank: within metres of zero");
  assert.deepEqual(o.pickOrigin([], []), [0, 0]);
  // Snowdon Towers (Revit, survey coordinates): one element at the internal origin does not pull the median away.
  assert.deepEqual(o.pickOrigin([417615.4, 417590.2, 0, 417644.9, 417608.6], [78714.5, 78700.1, 0, 78730.3, 78711.2]), [417609, 78711]);
});

test("points cross between IFC and the viewer through the origin; heights never move", () => {
  o.setOrigin([417609, 78711]);
  try {
    const v = o.pointToThree(417615.25, 78714.5, 73.2);
    assert.ok(close(v.x, 6.25) && close(v.y, 73.2) && close(v.z, -3.5), "relative, three.js axes");
    const back = o.pointToIfc(v);
    assert.ok(close(back[0], 417615.25) && close(back[1], 78714.5) && close(back[2], 73.2));
    assert.deepEqual(o.origin(), [417609, 78711]);
    // Server triangles (IFC metres, Z up) come in relative to the origin.
    const verts = o.serverVerts([417610, 78712, 5, 417609, 78711, 0]);
    assert.ok(verts instanceof Float32Array);
    assert.deepEqual([...verts], [1, 5, -1, 0, 0, 0]);
    // A placement baked with the shift matches the point conversion.
    const placed = new THREE.Vector3(417615.25, 73.2, -78714.5).applyMatrix4(o.shiftFor([417609, 78711]));
    assert.ok(placed.distanceTo(v) < 1e-9);
  } finally { o.setOrigin(null); }
  assert.deepEqual(o.origin(), [0, 0]);
  const v = o.pointToThree(1, 2, 3);
  assert.deepEqual(v.toArray(), [1, 3, -2], "no origin: the plain axis swap");
});

test("relative to the origin a float32 keeps a millimetre's tenth; 418 km out it steps 31 mm", () => {
  const x = 417615.14;   // between float32's steps there (417615.125 and 417615.15625)
  const raw = Math.fround(x), rel = Math.fround(x - 417609) + 417609;
  assert.equal(Math.fround(417615.13), Math.fround(417615.14), "float32 cannot tell these apart");
  assert.ok(Math.abs(raw - x) > 0.01, `raw float32 is off by ${Math.abs(raw - x)}`);
  assert.ok(Math.abs(rel - x) < 1e-4);
});
