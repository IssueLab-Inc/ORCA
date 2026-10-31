import assert from "node:assert/strict";
import test from "node:test";
import * as THREE from "three";
import { viewerModule } from "./app-host.mjs";

const { Viewer } = await viewerModule();

/** A viewer in the four-view layout on an 800 × 600 stage, drawing into a renderer that records what it is asked. */
function quad(models) {
  const v = Object.create(Viewer.prototype), drawn = [], camera = new THREE.PerspectiveCamera();
  const rect = (x, y) => ({ x, y, w: 400, h: 300 });
  const panes = [{ spec: { kind: "plan" }, rect: rect(0, 0), view: {} }, { spec: { kind: "3d" }, rect: rect(400, 0) },
    { spec: { kind: "section" }, rect: rect(0, 300), view: {} }, { spec: { kind: "elevation" }, rect: rect(400, 300), view: {} }];
  const renderer = { setScissorTest() {}, setViewport() {}, setScissor() {} };
  Object.assign(v, { models, panes, maximised: null, renderer, host: { clientWidth: 800, clientHeight: 600 }, projection: "perspective",
    marker: { visible: false }, markerLabel: null, grips: { children: [] }, cube: { render() {} },
    rect3d: () => rect(400, 0), activeCamera: () => camera, place() {}, drawMeasures() {}, annotatePane() {},
    render3d: (_, g) => drawn.push(["3d", g]), renderDrawing: (p, g) => drawn.push([p.spec.kind, g]) });
  return { v, drawn };
}

test("with nothing open the stage is one empty 3D view, not the layout's panes as patches of sky and paper", () => {
  const { v, drawn } = quad([]);
  v.drawFrame();
  assert.deepEqual(drawn, [["3d", { x: 0, y: 0, w: 800, h: 600 }]]);
  assert.equal(v.panes.length, 4, "the layout stays chosen");
});

test("with models open the four views draw, each in its own pane", () => {
  const { v, drawn } = quad([{}]);
  v.drawFrame();
  assert.deepEqual(drawn.map(([k]) => k), ["plan", "3d", "section", "elevation"]);
  assert.deepEqual(drawn[1][1], { x: 400, y: 300, w: 400, h: 300 }, "the 3D view top right (GL counts from the bottom)");
});
