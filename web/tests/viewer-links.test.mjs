import assert from "node:assert/strict";
import test from "node:test";
import * as THREE from "three";
import { viewerModule } from "./app-host.mjs";

globalThis.ResizeObserver = class { observe() {} disconnect() {} };
const { Viewer } = await viewerModule();

test("the connection highlight never shows in a captured picture, and is back on screen afterwards", () => {
  const v = Object.create(Viewer.prototype);
  const seen = [];
  const box = (x) => new THREE.Box3(new THREE.Vector3(x, 0, 0), new THREE.Vector3(x + 1.1, 1, 1));
  Object.assign(v, {
    linkLayer: new THREE.Group(), marker: new THREE.Group(), grips: new THREE.Group(), overlay: new THREE.Group(), hitLayer: new THREE.Group(),
    hidden: new Set(), moved: new Map(), sectionBox: null, focusMaterials: {}, mode: "xray", focus: null, flight: null,
    camera: new THREE.PerspectiveCamera(), controls: { target: new THREE.Vector3(), update() {} },
    renderer: { render() {} }, boxOf: ([g]) => box(g === "a" ? 0 : 1), setMode() {}, setFocus() {}, adjustClipRange() {},
    zoneCamera: () => [new THREE.Vector3(5, 5, 5), new THREE.Vector3()],
    png: () => { seen.push(v.linkLayer.visible); return "data:"; }, fullCanvas: (take) => take(), drawFrame() {},
  });
  v.linkLayer.visible = true;
  const shots = v.posed("a", "b", (shot) => [shot("isolate", true, 512), shot("context", false, 512)]);
  assert.deepEqual(shots, ["data:", "data:"]);
  assert.deepEqual(seen, [false, false]);
  assert.equal(v.linkLayer.visible, true);
});

test("a preview on screen (the idea ORCA is trying, what it hit) never shows in a captured picture, and is back afterwards", () => {
  // A list thumbnail drawn while ORCA works on another clash: the model as it is, not the trial in place.
  const v = Object.create(Viewer.prototype);
  const seen = [];
  const box = (x) => new THREE.Box3(new THREE.Vector3(x, 0, 0), new THREE.Vector3(x + 1.1, 1, 1));
  const hidden = new Set(["duct"]), moved = new Map([["duct", new THREE.Matrix4().makeTranslation(0, 0.4, 0)]]);
  Object.assign(v, {
    linkLayer: new THREE.Group(), marker: new THREE.Group(), grips: new THREE.Group(), overlay: new THREE.Group(), hitLayer: new THREE.Group(),
    hidden, moved, sectionBox: null, focusMaterials: {}, mode: "xray", focus: null, flight: null,
    camera: new THREE.PerspectiveCamera(), controls: { target: new THREE.Vector3(), update() {} },
    renderer: { render() {} }, boxOf: ([g]) => box(g === "a" ? 0 : 1), setFocus() {}, adjustClipRange() {},
    setMode() { seen.push({ mode: true, hidden: v.hidden.size, moved: v.moved.size }); },
    zoneCamera: () => [new THREE.Vector3(5, 5, 5), new THREE.Vector3()],
    png: () => { seen.push({ overlay: v.overlay.visible, hits: v.hitLayer.visible, hidden: v.hidden.size, moved: v.moved.size }); return "data:"; },
    fullCanvas: (take) => take(), drawFrame() {},
  });
  v.posed("a", "b", (shot) => shot("isolate", true, 192));
  const shots = seen.filter((x) => !x.mode);
  assert.deepEqual(shots, [{ overlay: false, hits: false, hidden: 0, moved: 0 }]);
  assert.deepEqual(seen.at(-1), { mode: true, hidden: 1, moved: 1 }, "the view is drawn again with the preview back");
  assert.equal(v.hidden, hidden); assert.equal(v.moved, moved);
  assert.equal(v.overlay.visible, true); assert.equal(v.hitLayer.visible, true);
});

test("a picture frames the pair where it is in the model, not where a previewed move has put one of them", () => {
  const v = Object.create(Viewer.prototype);
  const framed = [];
  const at = (x) => new THREE.Box3(new THREE.Vector3(x, 0, 0), new THREE.Vector3(x + 1.1, 1, 1));
  const moved = new Map([["a", new THREE.Matrix4().makeTranslation(0, 5, 0)]]);   // the idea ORCA is trying moves "a" up 5 m
  Object.assign(v, {
    linkLayer: new THREE.Group(), marker: new THREE.Group(), grips: new THREE.Group(), overlay: new THREE.Group(), hitLayer: new THREE.Group(),
    hidden: new Set(), moved, sectionBox: null, focusMaterials: {}, mode: "xray", focus: null, flight: null,
    camera: new THREE.PerspectiveCamera(), controls: { target: new THREE.Vector3(), update() {} },
    renderer: { render() {} }, setMode() {}, setFocus() {}, adjustClipRange() {},
    boxOf: ([g]) => { const b = at(g === "a" ? 0 : 1); return v.moved.has(g) ? b.translate(new THREE.Vector3(0, 5, 0)) : b; },
    zoneCamera: (zone) => { framed.push(zone.clone()); return [new THREE.Vector3(5, 5, 5), new THREE.Vector3()]; },
    png: () => "data:", fullCanvas: (take) => take(), drawFrame() {},
  });
  const shot = v.posed("a", "b", (shot) => shot("isolate", true, 192));
  assert.equal(shot, "data:", "moved apart in the preview, they still meet in the model: there is a picture");
  assert.deepEqual([framed[0].min.y, framed[0].max.y], [0, 1], "framed where they meet in the model");
  assert.equal(v.moved, moved, "the preview is back afterwards");
});
