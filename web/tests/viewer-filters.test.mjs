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

test("what a preview moves shows through an isolated clash, the Isolate and Context modes and a filter, lit as joined", () => {
  // Snowdon #20 isolated: the drain tilts and its bend goes down with it. The bend is the model's own element, shifted;
  // hidden, the tilted arm ended in mid-air (views.shownBy: the pair, previews and trials always show).
  const { v, m } = viewer();
  Object.assign(v, { linkLayer: new THREE.Group(), linkMaterials: new Map(), geometryOf: () => new THREE.BoxGeometry(),
    edgeGeometryOf: () => new THREE.BufferGeometry(), find: (gid) => ({ model: v.models[0], el: v.models[0].byGlobalId.get(gid) }) });
  const shown = () => ["a", "b", "c"].map((g) => visible(m, g));
  const lit = () => v.linkLayer.children.filter((o) => o.isMesh).length;
  v.setTemporary({ hidden: [], isolated: ["a"] });   // a clash row's Isolate: only its pair
  v.setLinks([{ color: "#2563eb", ids: ["b"] }]);    // what the option carries, lit as joined
  assert.deepEqual(shown(), [true, false, false]);
  assert.equal(lit(), 0);
  v.moved.set("b", new THREE.Matrix4().makeTranslation(0, -0.07, 0)); v.applyMode();   // the option carries b down
  assert.deepEqual(shown(), [true, true, false], "the carried part shows where the fix puts it; nothing else comes back");
  assert.equal(lit(), 1);
  v.setTemporary({ hidden: [], isolated: null });
  v.focus = { a: "a", b: null, group: {} };
  v.setMode("isolate");
  assert.deepEqual(shown(), [false, true, false], "Isolate: the pair is drawn by the focus layer, the carried part on its batch");
  v.nearFocus = () => new Set();
  v.setMode("context");
  assert.deepEqual(shown(), [false, true, false], "Context: shown however far it is");
  v.setMode("shaded");
  v.setRules({ hide: new Set(["b", "c"]), only: null, paint: null, greyRest: false });
  assert.deepEqual(shown(), [false, true, false], "a part a filter hides shows while a preview moves it");
  v.moved.clear(); v.applyMode();   // the preview goes: the filter has it again
  assert.deepEqual(shown(), [false, false, false]);
  assert.equal(lit(), 0);
});

test("drawings show what the filters leave, what the 3D view shows, or the whole model", () => {
  const { v, m } = viewer();
  v.panes = [{}, {}];
  v.setRules({ hide: new Set(["a"]), only: null, paint: null, greyRest: false });
  const drawn = () => Object.fromEntries(v.drawVis.map((d) => [d.el.globalId, d.vDraw]));
  assert.deepEqual(drawn(), {}, "filtered (the default): the drawings show what the 3D view does here");
  v.setDrawingsShow("whole");
  assert.deepEqual(drawn(), { a: true }, "the whole model: what a filter hides is drawn");
  v.setDrawingsShow("follow");
  assert.deepEqual(drawn(), {});
  assert.equal(visible(m, "a"), false, "the 3D view keeps the filter whatever the drawings show");
});

test("a drawing's fill pass takes the filters' colours on paper, the rest its file's tint, and gives the 3D colours back", () => {
  const { v, m } = viewer();
  v.setRules({ hide: null, only: null, paint: new Map([["b", "#318181"]]), greyRest: false });
  const paper = new THREE.Color("#fbfbf8"), tint = new THREE.Color("#eceef0");
  v.drawStyle = { tint: () => tint, onPaper: (hex) => new THREE.Color(hex).lerp(paper, 0.25) };
  const back = v.useDrawingPaint(v.rules.paint);
  assert.equal(hex(m, "b"), `#${new THREE.Color("#318181").lerp(paper, 0.25).getHexString()}`);
  assert.equal(hex(m, "a"), "#eceef0");
  back();
  assert.equal(hex(m, "b"), "#318181"); assert.equal(hex(m, "a"), "#808080");
});

test("framing for a filter takes the 3D view and every unpinned drawing to the elements, not a pinned one", () => {
  const { v } = viewer();
  const framed = [], flown = [];
  const pane = (pinned) => ({ pinned, rect: { x: 0, y: 0, w: 100, h: 100 }, view: { frame: (box) => framed.push([pinned, box.clone()]) } });
  Object.assign(v, { panes: [{ view: null }, pane(false), pane(true)], flyToBox: (box) => flown.push(box.clone()),
    boxOf: (ids) => new THREE.Box3(new THREE.Vector3(0, 0, 0), new THREE.Vector3(ids.length, 1, 1)) });
  v.frameEverywhere(["a", "b"]);
  assert.equal(flown.length, 1);
  assert.deepEqual(framed.map(([pinned]) => pinned), [false], "the pinned drawing stays");
  assert.equal(framed[0][1].max.x, 2);
  v.boxOf = () => new THREE.Box3();
  v.frameEverywhere([]);
  assert.equal(flown.length, 1, "nothing to frame: nothing moves");
});

test("a level's elements come from the viewer's own storeys, and what is shown is tested once per change", () => {
  const { v } = viewer();
  v.info = new Map([["a", { level: "Level 01" }], ["b", { level: "Level 02" }], ["c", { level: "Level 02" }]]);
  assert.deepEqual(v.ofLevel("Level 02"), ["b", "c"]);
  assert.deepEqual(v.ofLevel("Roof"), []);
  let built = 0;
  const real = v.filterTest.bind(v);
  v.filterTest = () => { built++; return real(); };
  v.setRules({ hide: new Set(["a"]), only: null, paint: null, greyRest: false });
  built = 0;
  assert.deepEqual(["a", "b", "c"].map((g) => v.isShown(g)), [false, true, true]);
  assert.equal(built, 1, "one test for many elements");
  v.setRules({ hide: new Set(["b"]), only: null, paint: null, greyRest: false });
  assert.deepEqual(["a", "b"].map((g) => v.isShown(g)), [true, false], "a change makes a new test");
});
