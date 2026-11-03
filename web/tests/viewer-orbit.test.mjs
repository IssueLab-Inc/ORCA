import assert from "node:assert/strict";
import test from "node:test";
import * as THREE from "three";
import { viewerModule } from "./app-host.mjs";

const { Viewer } = await viewerModule();

function viewer() {
  const v = Object.create(Viewer.prototype);
  const camera = new THREE.PerspectiveCamera(45, 1.5, 0.05, 5000);
  camera.position.set(10, 6, 10);
  const controls = { target: new THREE.Vector3(0, 0, 0), rotateSpeed: 1, update() { camera.lookAt(this.target); camera.updateMatrixWorld(); } };
  controls.update();
  Object.assign(v, { camera, controls, pane3d: { clientHeight: 600 } });
  return v;
}

test("orbiting round a pivot (the selection, the clash) keeps it where it is on screen and as far away", () => {
  const v = viewer(), pivot = new THREE.Vector3(3, 1, -2);
  const before = pivot.clone().project(v.camera), far = v.camera.position.distanceTo(pivot), was = v.camera.position.clone();
  v.orbitAround(pivot, 120, -40);
  const after = pivot.clone().project(v.camera);
  assert.ok(Math.abs(after.x - before.x) < 1e-6 && Math.abs(after.y - before.y) < 1e-6, "the pivot does not move on screen");
  assert.ok(Math.abs(v.camera.position.distanceTo(pivot) - far) < 1e-6);
  assert.ok(v.camera.position.distanceTo(was) > 1, "the camera went round");
  assert.ok(Math.abs(v.camera.up.y - 1) < 1e-9, "no roll: up stays up");
});

test("a drag across turns round the vertical; a long drag down stops short of looking straight down", () => {
  const v = viewer(), pivot = new THREE.Vector3(0, 0, 0);
  const height = v.camera.position.y;
  v.orbitAround(pivot, 200, 0);
  assert.ok(Math.abs(v.camera.position.y - height) < 1e-9, "a sideways drag keeps the camera's height");
  v.orbitAround(pivot, 0, 5000);
  const offset = v.camera.position.clone().sub(v.controls.target);
  assert.ok(offset.angleTo(new THREE.Vector3(0, 1, 0)) >= 0.0099, "never past straight down");
});

/** A viewer ready for a press in the 3D view: models open, a clash in focus round (2, 2, 2), nothing selected. */
function pressable({ orbitClash, flight = null }) {
  const v = viewer(), picked = [];
  Object.assign(v, { models: [{}], cube: { el: { contains: () => false } }, gripAt: () => null, selection: null,
    lastClash: { ids: [], zone: new THREE.Box3(new THREE.Vector3(1, 1, 1), new THREE.Vector3(3, 3, 3)), point: null },
    orbitClash, flight, projection: "perspective", pickAt: () => { picked.push(true); return null; } });
  v.controls.enableRotate = true;
  return { v, picked };
}
const press = (v) => v.press({ button: 0, pointerId: 1, clientX: 10, clientY: 20, pointerType: "mouse", target: null });

test("a clash in focus with nothing selected is what a drag orbits round, also while the camera is still flying", () => {
  const flying = { from: [], to: [], t0: 0, ms: 650 };
  const { v, picked } = pressable({ orbitClash: true, flight: flying });
  press(v);
  assert.deepEqual(v.spin.pivot.toArray(), [2, 2, 2]);
  assert.equal(v.flight, null, "the user takes the view: the flight stops");
  assert.equal(v.controls.enableRotate, false, "the controls do not turn for this drag");
  assert.equal(picked.length, 0);
});

test("with no clash in focus and nothing selected, a drag turns about what is under the pointer", () => {
  const { v, picked } = pressable({ orbitClash: false });
  press(v);
  assert.ok(!v.spin, "no pivot of its own");
  assert.equal(picked.length, 1, "it looks under the pointer");
});

/** A viewer with a clash round (2, 2, 2) on screen, for the pilot's slow turn. */
function turning() {
  const v = viewer();
  const flights = [];
  Object.assign(v, { models: [], focus: { a: null, b: null, group: {} }, flight: null, reach: () => 0.01,
    lastClash: { ids: [], zone: new THREE.Box3(new THREE.Vector3(1, 1, 1), new THREE.Vector3(3, 3, 3)), point: null } });
  v.controls.autoRotate = false;
  const fly = Viewer.prototype.flyTo;
  v.flyTo = function (position, target, animate, record) { flights.push({ position: position.clone(), target: target.clone() }); fly.call(this, position, target, false, record); };
  return { v, flights };
}

test("the pilot's turn starts by gliding sideways to the clash, keeping the camera's angle and distance", () => {
  const { v, flights } = turning();
  const offset = v.camera.position.clone().sub(v.controls.target);
  v.orbit(true);
  assert.equal(v.controls.autoRotate, true);
  assert.equal(flights.length, 1);
  assert.deepEqual(flights[0].target.toArray(), [2, 2, 2]);
  assert.ok(flights[0].position.clone().sub(flights[0].target).distanceTo(offset) < 1e-9, "the same angle and distance");
});

test("a proposal started while the camera still flies to its clash turns round the clash framed, not the model", () => {
  // The golden path: its check picks the clash (a flight from the whole model in to the clash, 650 ms) and the
  // proposal starts a moment later. The turn used to glide sideways from where the flight set out, cutting it off.
  const { v, flights } = turning();
  v.camera.position.set(200, 150, 200);   // the whole model in view
  v.controls.target.set(0, 0, 0);
  const framed = [new THREE.Vector3(5, 4, 5), new THREE.Vector3(2, 2, 2)];
  v.flight = { from: [v.camera.position.clone(), v.controls.target.clone()], to: framed, t0: performance.now(), ms: 650 };
  v.orbit(true);
  assert.equal(flights.length, 0, "the flight to the clash goes on");
  assert.equal(v.flight.to, framed);
  assert.equal(v.controls.autoRotate, true);
  // A flight elsewhere: the glide starts from where it lands.
  v.controls.autoRotate = false;
  v.flight = { from: [v.camera.position.clone(), v.controls.target.clone()], to: [new THREE.Vector3(10, 10, 10), new THREE.Vector3(8, 8, 8)], t0: 0, ms: 650 };
  v.orbit(true);
  assert.equal(flights.length, 1);
  assert.deepEqual(flights[0].target.toArray(), [2, 2, 2]);
  assert.deepEqual(flights[0].position.toArray(), [4, 4, 4], "the flight's own angle and distance");
});
