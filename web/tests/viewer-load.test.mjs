import assert from "node:assert/strict";
import test from "node:test";
import { flush, originModule, viewerModule } from "./app-host.mjs";

async function stage({ glass = false, realAdopt = false } = {}) {
  const pending = [], removed = [], adopted = [], added = [];
  globalThis.__sightlineLoadIfc = () => new Promise((resolve, reject) => pending.push({ resolve, reject }));
  globalThis.ResizeObserver = class { observe() {} disconnect() {} };
  const { Viewer } = await viewerModule("export const loadIfc=(...a)=>globalThis.__sightlineLoadIfc(...a);");
  const batch = () => ({ layers: { enable() {} }, dispose() { this.disposed = true; } });
  const model = (id) => ({ id, mesh: batch(), glass: glass ? batch() : null, stats: { elements: 1, triangles: 2, parseMs: 3 } });
  const old = model("old"), v = Object.create(Viewer.prototype);
  Object.assign(v, { models: [old], names: ["old.ifc"], solid: {}, glass: {},
    scene: { remove: (...meshes) => removed.push(...meshes), add: (...meshes) => added.push(...meshes) },
    adopt: (m) => { adopted.push(m); return realAdopt ? Viewer.prototype.adopt.call(v, m) : m; },
    clearFocusCache() {}, applyMode() {}, fitAll() {}, preview() {}, hiddenModels: new Set(), pane3d: {}, history: { clear() {} }, panes: [], configureViews() {}, snapCache: new Map() });
  return { v, pending, old, model, removed, adopted, added };
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

test("dual-batch load failure disposes staged solid and glass while retaining both old batches", async () => {
  const s = await stage({ glass: true, realAdopt: true });
  const work = s.v.load([new Uint8Array([1]), new Uint8Array([2])], ["one", "two"]);
  const first = s.model("first"); s.pending[0].resolve(first); await flush();
  assert.deepEqual(s.v.models, [s.old]); assert.deepEqual(s.added, []); assert.deepEqual(s.removed, []);
  s.pending[1].reject(new Error("Invalid IFC")); await assert.rejects(work, /Invalid IFC/);
  assert.equal(first.mesh.disposed, true); assert.equal(first.glass.disposed, true);
  assert.equal(s.old.mesh.disposed, undefined); assert.equal(s.old.glass.disposed, undefined);
});

test("dual-batch superseded load disposes both abandoned batches without changing newer adoption", async () => {
  const s = await stage({ glass: true, realAdopt: true }); let current = 1;
  const abandoned = s.v.load([new Uint8Array([1])], ["abandoned"], () => current === 1);
  current = 2; const work = s.v.load([new Uint8Array([2])], ["current"], () => current === 2);
  const next = s.model("next"), stale = s.model("stale");
  s.pending[1].resolve(next); await work; s.pending[0].resolve(stale); await abandoned;
  assert.deepEqual(s.v.models, [next]); assert.deepEqual(s.v.names, ["current"]);
  assert.deepEqual(s.added, [next.mesh, next.glass]);
  assert.equal(stale.mesh.disposed, true); assert.equal(stale.glass.disposed, true);
});

test("dual-batch successful federation load stages every file then adopts glass materials and removes both old batches", async () => {
  const s = await stage({ glass: true, realAdopt: true });
  const work = s.v.load([new Uint8Array([1]), new Uint8Array([2])], ["one", "two"]);
  const first = s.model("first"), second = s.model("second");
  s.pending[0].resolve(first); await flush();
  assert.deepEqual(s.added, []); assert.deepEqual(s.removed, []); assert.equal(s.old.glass.disposed, undefined);
  s.pending[1].resolve(second); const stats = await work;
  assert.deepEqual(s.v.models, [first, second]); assert.deepEqual(s.v.names, ["one", "two"]);
  assert.deepEqual(s.removed, [s.old.mesh, s.old.glass]);
  assert.equal(s.old.mesh.disposed, true); assert.equal(s.old.glass.disposed, true);
  assert.deepEqual(s.added, [first.mesh, first.glass, second.mesh, second.glass]);
  for (const m of [first, second]) { assert.equal(m.mesh.material, s.v.solid); assert.equal(m.glass.material, s.v.glass); }
  assert.deepEqual(stats, { elements: 2, triangles: 4, parseMs: 6 });
});

test("dual-batch stale replacement disposes both parsed batches and leaves the current model intact", async () => {
  const s = await stage({ glass: true, realAdopt: true }); let current = true;
  const work = s.v.replace(0, new Uint8Array([1]), () => current);
  current = false; const stale = s.model("stale"); s.pending[0].resolve(stale); await work;
  assert.deepEqual(s.v.models, [s.old]); assert.deepEqual(s.added, []); assert.deepEqual(s.removed, []);
  assert.equal(stale.mesh.disposed, true); assert.equal(stale.glass.disposed, true);
  assert.equal(s.old.mesh.disposed, undefined); assert.equal(s.old.glass.disposed, undefined);
});

test("dual-batch successful replacement adopts both new batches and removes and disposes both old batches", async () => {
  const s = await stage({ glass: true, realAdopt: true });
  const work = s.v.replace(0, new Uint8Array([1])); const next = s.model("next");
  s.pending[0].resolve(next); await work;
  assert.deepEqual(s.v.models, [next]); assert.deepEqual(s.added, [next.mesh, next.glass]);
  assert.deepEqual(s.removed, [s.old.mesh, s.old.glass]);
  assert.equal(s.old.mesh.disposed, true); assert.equal(s.old.glass.disposed, true);
  assert.equal(next.mesh.material, s.v.solid); assert.equal(next.glass.material, s.v.glass);
});

test("every file of a load is placed from the first file's origin, and the viewer takes it with the models", async () => {
  const o = await originModule(); o.setOrigin(null);
  const s = await stage(), calls = [];
  globalThis.__sightlineLoadIfc = (...a) => new Promise((resolve, reject) => { calls.push(a); s.pending.push({ resolve, reject }); });
  const work = s.v.load([new Uint8Array([1]), new Uint8Array([2])], ["one", "two"]);
  s.pending[0].resolve({ ...s.model("first"), origin: [417609, 78711] }); await flush();
  assert.equal(calls[0][1], null, "the first file picks its own");
  assert.deepEqual(calls[1][1], [417609, 78711], "the second is placed from the first's, so they stay aligned");
  assert.deepEqual(o.origin(), [0, 0], "the models on screen keep theirs until the new ones are adopted");
  s.pending[1].resolve({ ...s.model("second"), origin: [417609, 78711] }); await work;
  assert.deepEqual(o.origin(), [417609, 78711]);
  // A superseded load never touches it.
  let current = 1; const stale = s.v.load([new Uint8Array([3])], ["stale"], () => current === 1); current = 2;
  s.pending[2].resolve({ ...s.model("stale"), origin: [5000, 5000] }); await stale;
  assert.deepEqual(o.origin(), [417609, 78711]);
  o.setOrigin(null);
});
