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
    linkLayer: new THREE.Group(), marker: new THREE.Group(), grips: new THREE.Group(), sectionBox: null, focusMaterials: {}, mode: "xray", focus: null, flight: null,
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
