import assert from "node:assert/strict";
import test from "node:test";
import * as THREE from "three";
import { viewerModule } from "./app-host.mjs";

globalThis.ResizeObserver = class { observe() {} disconnect() {} };
const { Viewer } = await viewerModule();

/** A model of three elements in one batch, as the loader builds it. */
function model() {
  const mesh = new THREE.BatchedMesh(3, 96, 128, new THREE.MeshBasicMaterial());
  const byGlobalId = new Map(), byInstance = new Map();
  for (const [k, gid] of ["a", "b", "c"].entries()) {
    const g = new THREE.BoxGeometry(1, 1, 1).translate(k * 2, 0, 0);
    const instanceId = mesh.addInstance(mesh.addGeometry(g));
    const el = { globalId: gid, expressId: k + 1, instanceId, mesh, baseColor: new THREE.Color("#808080"), baseAlpha: 1, baseMatrix: new THREE.Matrix4() };
    byGlobalId.set(gid, el); byInstance.set(instanceId, el);
  }
  return { mesh, glass: null, byGlobalId, byInstance, glassByInstance: new Map(), stats: { elements: 3, triangles: 36, parseMs: 1 } };
}

function viewer() {
  const v = Object.create(Viewer.prototype), m = model(), mat = new THREE.MeshBasicMaterial();
  Object.assign(v, {
    models: [m], hidden: new Set(), hiddenModels: new Set(), panes: [], filters: { classes: [], levels: [] },
    temp: { hidden: [], isolated: null }, info: new Map(), rules: null, paints: new Map(), scratch: new THREE.Vector4(),
    linkGroups: [], lifted: false, style: "shaded", mode: "shaded", greyContext: true, version: 0, drawVis: [],
    solid: mat, ghost: mat, xrayAll: mat, consistent: mat, glass: mat, moved: new Map(), focus: { a: null, b: null },
    selection: null, drawFocus() {}, drawSelection() {}, onChange: null,
  });
  return { v, m };
}
const hex = (m, gid) => `#${m.mesh.getColorAt(m.byGlobalId.get(gid).instanceId, new THREE.Color()).getHexString()}`;
const visible = (m, gid) => m.mesh.getVisibleAt(m.byGlobalId.get(gid).instanceId);

test("the filters hide, isolate and colour elements on their batch, and grey the rest when asked", () => {
  const { v, m } = viewer();
  v.setRules({ hide: new Set(["a"]), only: null, paint: new Map([["b", "#318181"]]), greyRest: true });
  assert.equal(visible(m, "a"), false);
  assert.equal(visible(m, "b"), true);
  assert.equal(hex(m, "b"), "#318181");
  assert.equal(hex(m, "c"), "#b9c2cc", "grey for what no filter colours");
  assert.equal(v.isShown("a"), false); assert.equal(v.isShown("b"), true);
  v.setRules({ hide: null, only: new Set(["c"]), paint: null, greyRest: false });
  assert.deepEqual(["a", "b", "c"].map((g) => visible(m, g)), [false, false, true]);
  assert.equal(hex(m, "b"), "#808080", "colours go with their filter");
  v.setRules(null);
  assert.deepEqual(["a", "b", "c"].map((g) => visible(m, g)), [true, true, true]);
});

test("a captured picture never sees the filters, and they are back afterwards", () => {
  const { v, m } = viewer();
  v.setRules({ hide: new Set(["a"]), only: null, paint: new Map([["b", "#318181"]]), greyRest: false });
  v.lifted = true; v.applyMode();
  assert.equal(visible(m, "a"), true); assert.equal(hex(m, "b"), "#808080");
  v.lifted = false; v.applyMode();
  assert.equal(visible(m, "a"), false); assert.equal(hex(m, "b"), "#318181");
});

test("lit links leave out what a filter takes off screen", () => {
  const { v } = viewer();
  Object.assign(v, { linkLayer: new THREE.Group(), linkMaterials: new Map(), geometryOf: () => new THREE.BoxGeometry(),
    edgeGeometryOf: () => new THREE.BufferGeometry(), find: (gid) => ({ model: v.models[0], el: v.models[0].byGlobalId.get(gid) }) });
  v.setLinks([{ color: "#2563eb", ids: ["a", "b"] }]);
  const lit = () => v.linkLayer.children.filter((o) => o.isMesh).length;
  assert.equal(lit(), 2);
  v.setRules({ hide: new Set(["a"]), only: null, paint: null, greyRest: false });
  assert.equal(lit(), 1);
});
