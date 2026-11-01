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

// Adding and removing models in an open scene (docs/add-and-remove-models.md).
async function opened(...ids) {
  const s = await stage({ realAdopt: true });
  const els = (id) => new Map([[`${id}-1`, {}], [`${id}-2`, {}]]);
  const make = (id) => ({ ...s.model(id), byGlobalId: els(id) });
  const models = ids.map(make);
  Object.assign(s.v, { models, names: ids.map((id) => `${id}.ifc`), moved: new Map(), hidden: new Set(), info: new Map(),
    paints: new Map(), focus: { a: null, b: null }, selection: null, measures: [{ id: 1 }], measureStamp: 0, draft: null, hover: { point: null } });
  return { ...s, make, models };
}

test("files added are parsed from the models' own origin, all before any is shown, then appended", async () => {
  const o = await originModule(); o.setOrigin([417609, 78711]);
  const s = await opened("S", "M"), calls = [];
  globalThis.__sightlineLoadIfc = (...a) => new Promise((resolve, reject) => { calls.push(a); s.pending.push({ resolve, reject }); });
  let fitted = 0; s.v.fitAll = () => { fitted++; };
  const work = s.v.add([new Uint8Array([1]), new Uint8Array([2])], ["A.ifc", "B.ifc"]);
  const a = s.make("A"); s.pending[0].resolve(a); await flush();
  assert.deepEqual(s.v.models, s.models, "nothing shows until every new file is parsed");
  const b = s.make("B"); s.pending[1].resolve(b); const stats = await work;
  assert.deepEqual(calls.map((c) => c[1]), [[417609, 78711], [417609, 78711]]);
  assert.deepEqual(s.v.models, [...s.models, a, b]); assert.deepEqual(s.v.names, ["S.ifc", "M.ifc", "A.ifc", "B.ifc"]);
  assert.deepEqual(s.added, [a.mesh, b.mesh]); assert.equal(a.mesh.material, s.v.solid);
  assert.deepEqual(stats, { elements: 4, triangles: 8, parseMs: 12 }); assert.equal(fitted, 1, "framed so the new model shows");
  assert.deepEqual(s.v.measures, [{ id: 1 }], "measurements on the other models stay");
  o.setOrigin(null);
});

test("an add that fails or is superseded leaves the open models as they were and disposes what it parsed", async () => {
  const s = await opened("S");
  const failing = s.v.add([new Uint8Array([1]), new Uint8Array([2])], ["A.ifc", "B.ifc"]);
  const a = s.make("A"); s.pending[0].resolve(a); await flush();
  s.pending[1].reject(new Error("Invalid IFC")); await assert.rejects(failing, /Invalid IFC/);
  assert.equal(a.mesh.disposed, true); assert.deepEqual(s.v.models, s.models);
  let current = true; const stale = s.v.add([new Uint8Array([3])], ["C.ifc"], () => current); current = false;
  const c = s.make("C"); s.pending[2].resolve(c);
  assert.equal(await stale, null); assert.equal(c.mesh.disposed, true); assert.deepEqual(s.v.names, ["S.ifc"]);
});

test("a model removed is disposed, the later ones move down, and what pointed into it goes", async () => {
  const s = await opened("S", "M", "A");
  const [structure, mep, arch] = s.models;
  s.v.hiddenModels = new Set([1, 2]);
  s.v.moved.set("S-1", {}); s.v.hidden.add("S-2"); s.v.info.set("S-1", {}); s.v.info.set("M-1", {});
  s.v.focus = { a: "S-1", b: "M-1", group: { "S-2": "a", "M-2": "b" } }; s.v.selection = "S-2";
  const stats = s.v.remove(0);
  assert.deepEqual(s.v.models, [mep, arch]); assert.deepEqual(s.v.names, ["M.ifc", "A.ifc"]);
  assert.deepEqual(s.removed, [structure.mesh]); assert.equal(structure.mesh.disposed, true); assert.equal(mep.mesh.disposed, undefined);
  assert.deepEqual([...s.v.hiddenModels].sort(), [0, 1], "the hidden marks follow their models down");
  assert.equal(s.v.moved.has("S-1") || s.v.hidden.has("S-2") || s.v.info.has("S-1"), false);
  assert.equal(s.v.info.has("M-1"), true);
  assert.deepEqual(s.v.focus, { a: null, b: "M-1", group: { "M-2": "b" } }); assert.equal(s.v.selection, null);
  assert.deepEqual(s.v.measures, [], "measurements may have been on it"); assert.equal(s.v.hover, null);
  assert.deepEqual(stats, { elements: 2, triangles: 4, parseMs: 6 });
  assert.equal(s.v.remove(5), null, "a position it does not have changes nothing");
  assert.deepEqual(s.v.models, [mep, arch]);
});
