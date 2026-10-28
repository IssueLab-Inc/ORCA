import assert from "node:assert/strict";
import test from "node:test";
import { compiled, flush } from "./app-host.mjs";

const url = (js) => `data:text/javascript;base64,${Buffer.from(js).toString("base64")}`;
async function stage() {
  const pending = [], removed = [], adopted = [];
  globalThis.__sightlineLoadIfc = () => new Promise((resolve, reject) => pending.push({ resolve, reject }));
  globalThis.ResizeObserver = class { observe() {} disconnect() {} };
  const { Viewer } = await import(await compiled("../src/viewer/Viewer.ts", {
    three: import.meta.resolve("three"), "three/examples/jsm/controls/OrbitControls.js": import.meta.resolve("three/examples/jsm/controls/OrbitControls.js"),
    "./ifcLoader": url("export const loadIfc=(...a)=>globalThis.__sightlineLoadIfc(...a);") }));
  const model = (id) => ({ id, mesh: { dispose() { this.disposed = true; } }, stats: { elements: 1, triangles: 2, parseMs: 3 } });
  const old = model("old"), v = Object.create(Viewer.prototype);
  Object.assign(v, { models: [old], names: ["old.ifc"], scene: { remove: (mesh) => removed.push(mesh) },
    adopt: (m) => { adopted.push(m); return m; }, clearFocusCache() {}, applyMode() {}, fitAll() {}, preview() {}, hiddenModels: new Set() });
  return { v, pending, old, model, removed, adopted };
}

test("actual Viewer.load stages all parses before replacing a usable federation and disposes partial failure", async () => {
  const s = await stage(); const work = s.v.load([new Uint8Array([1]), new Uint8Array([2])], ["one", "two"]);
  const first = s.model("first"); s.pending[0].resolve(first); await flush();
  assert.deepEqual(s.v.models, [s.old]); assert.deepEqual(s.v.names, ["old.ifc"]); assert.deepEqual(s.removed, []);
  s.pending[1].reject(new Error("Invalid IFC")); await assert.rejects(work, /Invalid IFC/);
  assert.deepEqual(s.v.models, [s.old]); assert.equal(first.mesh.disposed, true); assert.equal(s.old.mesh.disposed, undefined);
});

test("actual Viewer.load discards an obsolete parse after a newer load adopted geometry", async () => {
  const s = await stage(); let current = 1;
  const oldWork = s.v.load([new Uint8Array([1])], ["abandoned"], () => current === 1);
  current = 2; const newWork = s.v.load([new Uint8Array([2])], ["current"], () => current === 2);
  const newer = s.model("newer"), stale = s.model("stale");
  s.pending[1].resolve(newer); await newWork; s.pending[0].resolve(stale); await oldWork;
  assert.deepEqual(s.v.models, [newer]); assert.deepEqual(s.v.names, ["current"]); assert.deepEqual(s.adopted, [newer]);
  assert.equal(stale.mesh.disposed, true);
});
