import assert from "node:assert/strict";
import test from "node:test";
import * as THREE from "three";
import { viewerModule } from "./app-host.mjs";

/** Frames on demand (docs/architecture/13-3d-viewer.md, "Frames"): the viewer drew a 204 MB model sixty times a second
 * with nothing moving, which kept the page's thread busy (owner report, Nov 2: slow to move round Snowdon Towers). It
 * draws when something asks, for a moment after, and while anything still moves or waits to be drawn. */

const { Viewer } = await viewerModule();
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function viewer({ moving = () => false } = {}) {
  const v = Object.create(Viewer.prototype);
  Viewer.prototype.wakeOnCalls.call(v);
  const loop = { cb: null, starts: 0 };
  let frames = 0;
  Object.assign(v, {
    looping: false, awakeUntil: 0, inFrame: false, hush: 0, disposed: false, drawingPending: false, controlsHeld: false,
    cameraMoved: 0, flight: null, projection: "perspective",
    renderer: { setAnimationLoop(cb) { loop.cb = cb; if (cb) loop.starts++; } },
    camera: new THREE.PerspectiveCamera(),
    controls: { target: new THREE.Vector3(), autoRotate: false, update: moving },
    adjustClipRange() {}, drawFrame() { frames++; if (v.pendingDraws > 0) { v.pendingDraws--; v.drawingPending = true; } },
    pendingDraws: 0,
  });
  return { v, loop, frames: () => frames, tick: () => loop.cb?.() };
}

test("nothing asked for: no frames; a change draws for a moment, then the frames stop", async () => {
  const { v, loop, frames, tick } = viewer();
  assert.equal(loop.cb, null, "idle: no frame loop");
  v.setProjection("orthographic");   // any method of the viewer is a change
  assert.ok(loop.cb, "a change starts the frames");
  tick(); tick();
  assert.equal(frames(), 2);
  await wait(300);
  tick();
  assert.equal(loop.cb, null, "a moment after the last change, nothing moving: the frames stop");
  v.setProjection("perspective");
  assert.ok(loop.cb && loop.starts === 2, "the next change starts them again");
});

test("questions and pictures draw nothing, nor what they call on the way; a frame's own calls ask for none", () => {
  const { v, loop } = viewer();
  v.pose();
  assert.equal(loop.cb, null, "a question about the camera is not a change");
  v.hush++;   // inside a picture: it sets the mode and the camera, and puts them back
  v.setProjection("orthographic");
  v.hush--;
  assert.equal(loop.cb, null);
  v.inFrame = true;
  v.setProjection("perspective");
  v.inFrame = false;
  assert.equal(loop.cb, null, "called from inside a frame: already being drawn");
});

test("the frames go on while the camera glides, a flight runs or a drawing still waits for its picture", async () => {
  let gliding = true;
  const { v, loop, tick } = viewer({ moving: () => gliding });
  v.redraw();
  await wait(300);
  tick();
  assert.ok(loop.cb, "the controls' damping still moves the camera");
  assert.equal(v.moving, true, "and work that can wait (thumbnails) waits");
  gliding = false;
  v.pendingDraws = 1;
  await wait(300);
  tick();
  assert.ok(loop.cb, "a drawing pane drew nothing this frame: it is waiting for the gesture to rest");
  await wait(300);
  tick();
  assert.equal(loop.cb, null, "everything drawn and still: the frames stop");
  await wait(450);
  assert.equal(v.moving, false, "the camera has rested");
});

test("an async change draws again when it settles; a disposed viewer never draws", async () => {
  const { v, loop, tick } = viewer();
  let settle;
  const load = Viewer.prototype.load;
  v.load = undefined;   // the wrapper round the real load is what is under test: give it a load that waits
  Viewer.prototype.load = () => new Promise((resolve) => { settle = resolve; });
  try {
    Viewer.prototype.wakeOnCalls.call(v);
    Object.assign(v, { adjustClipRange() {}, drawFrame() {} });
    const work = v.load([]);
    await wait(300); tick();
    assert.equal(loop.cb, null, "parsing: nothing to draw yet");
    settle(); await work; await Promise.resolve();
    assert.ok(loop.cb, "the models are in: drawn");
  } finally { Viewer.prototype.load = load; }
  v.disposed = true; loop.cb = null;
  v.setProjection("orthographic");
  assert.equal(loop.cb, null);
});
