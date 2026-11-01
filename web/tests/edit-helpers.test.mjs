import assert from "node:assert/strict";
import test from "node:test";
import * as THREE from "three";
import { compiled } from "./app-host.mjs";

const edit = await import(await compiled("../src/viewer/edit.ts", { three: import.meta.resolve("three") }));

test("pushing a face out stretches the element along its normal and holds its far side", () => {
  // A 2 m long box along +x (three.js axes), its east face at x = 2: pushed 0.5 m out.
  const box = new THREE.Box3(new THREE.Vector3(0, 0, 0), new THREE.Vector3(2, 1, 1));
  const m = edit.pushMatrix(box, new THREE.Vector3(2, 0.5, 0.5), new THREE.Vector3(1, 0, 0), 0.5);
  const far = new THREE.Vector3(0, 0.3, 0.7).applyMatrix4(m), near = new THREE.Vector3(2, 0.3, 0.7).applyMatrix4(m);
  assert.ok(far.distanceTo(new THREE.Vector3(0, 0.3, 0.7)) < 1e-9, "the far side stays");
  assert.ok(near.distanceTo(new THREE.Vector3(2.5, 0.3, 0.7)) < 1e-9, "the face moves out by the push");
  assert.equal(edit.depthBehind(box, new THREE.Vector3(2, 0, 0), new THREE.Vector3(1, 0, 0)), 2);
  assert.equal(edit.pushMatrix(box, new THREE.Vector3(2, 0.5, 0.5), new THREE.Vector3(1, 0, 0), -2), null, "inside out: none");
  // Along a diagonal normal the stretch is still the face's distance, the cross directions untouched.
  const s = edit.stretchMatrix(new THREE.Vector3(), new THREE.Vector3(1, 1, 0).normalize(), 2);
  const across = new THREE.Vector3(1, -1, 0).applyMatrix4(s);
  assert.ok(across.distanceTo(new THREE.Vector3(1, -1, 0)) < 1e-9);
});

test("a face is the element's triangles that share its plane", () => {
  // A unit cube's six quads: the +x face is two triangles.
  const geo = new THREE.BoxGeometry(1, 1, 1).toNonIndexed();
  const n = geo.getAttribute("position").count;
  geo.setIndex([...Array(n).keys()]);
  const tris = edit.coplanar(geo.getAttribute("position"), geo.getIndex(), 0, n, new THREE.Vector3(1, 0, 0), new THREE.Vector3(0.5, 0, 0));
  assert.equal(tris.length, 2 * 9);
  assert.ok([...tris].filter((_, i) => i % 3 === 0).every((x) => Math.abs(x - 0.5) < 1e-9));
  assert.equal(edit.coplanar(geo.getAttribute("position"), geo.getIndex(), 0, n, new THREE.Vector3(1, 0, 0), new THREE.Vector3(0.2, 0, 0)).length, 0);
});

test("a drag is metres along the face, snapped; axes convert both ways", () => {
  assert.equal(edit.dragMetres(30, 40, { x: 0.6, y: 0.8 }, 100), 0.5);
  assert.equal(edit.snapTo(0.1234), 0.125);
  assert.equal(edit.snapTo(0.1234, 0.001), 0.123);
  assert.equal(edit.signedMm(0.15), "+150 mm"); assert.equal(edit.signedMm(-0.025), "−25 mm"); assert.equal(edit.signedMm(0), "0 mm");
  const v = edit.toThree([1, 2, 3]);
  assert.deepEqual([v.x, v.y, v.z], [1, 3, -2]); assert.deepEqual(edit.toIfcAxes(v), [1, 2, 3]);
});

test("the palette says what each tool can act on", () => {
  const ready = new Set(["push_pull", "align", "move"]);
  const flank = { allows: ["align", "void"], name: "sides" };
  assert.deepEqual(edit.toolState("push_pull", flank, ready), { ok: false, why: "Its sides cannot be pushed or pulled" });
  assert.deepEqual(edit.toolState("align", flank, ready), { ok: true, why: null });
  assert.deepEqual(edit.toolState("split", null, ready), { ok: false, why: "Not in this build yet" });
  assert.equal(edit.toolForKey("A"), "align"); assert.equal(edit.toolForKey("z"), null);
  assert.deepEqual(edit.EDIT_TOOLS.map((t) => t.id), ["push_pull", "align", "move", "void", "cut_by", "split", "remove_section", "clip", "delete"]);
});
