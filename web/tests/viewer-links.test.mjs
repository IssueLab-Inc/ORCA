import assert from "node:assert/strict";
import test from "node:test";
import * as THREE from "three";
import { compiled } from "./app-host.mjs";

const url = (js) => `data:text/javascript;base64,${Buffer.from(js).toString("base64")}`;
globalThis.ResizeObserver = class { observe() {} disconnect() {} };
const { Viewer } = await import(await compiled("../src/viewer/Viewer.ts", {
  three: import.meta.resolve("three"), "three/examples/jsm/controls/OrbitControls.js": import.meta.resolve("three/examples/jsm/controls/OrbitControls.js"),
  "three/examples/jsm/utils/BufferGeometryUtils.js": import.meta.resolve("three/examples/jsm/utils/BufferGeometryUtils.js"),
  "./ifcLoader": url("export const loadIfc=()=>null;"),
  "./patch": await compiled("../src/viewer/patch.ts", { three: import.meta.resolve("three") }) }));

test("the connection highlight never shows in a captured picture, and is back on screen afterwards", () => {
  const v = Object.create(Viewer.prototype);
  const seen = [];
  const box = (x) => new THREE.Box3(new THREE.Vector3(x, 0, 0), new THREE.Vector3(x + 1.1, 1, 1));
  Object.assign(v, {
    linkLayer: new THREE.Group(), marker: new THREE.Group(), focusMaterials: {}, mode: "xray", focus: null, flight: null,
    camera: new THREE.PerspectiveCamera(), controls: { target: new THREE.Vector3(), update() {} },
    renderer: { render() {} }, boxOf: ([g]) => box(g === "a" ? 0 : 1), setMode() {}, setFocus() {}, adjustClipRange() {},
    zoneCamera: () => [new THREE.Vector3(5, 5, 5), new THREE.Vector3()],
    png: () => { seen.push(v.linkLayer.visible); return "data:"; },
  });
  v.linkLayer.visible = true;
  const shots = v.posed("a", "b", (shot) => [shot("isolate", true, 512), shot("context", false, 512)]);
  assert.deepEqual(shots, ["data:", "data:"]);
  assert.deepEqual(seen, [false, false]);
  assert.equal(v.linkLayer.visible, true);
});
