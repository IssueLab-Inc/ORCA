import assert from "node:assert/strict";
import test from "node:test";
import * as THREE from "three";
import { appHost, compiled, option } from "./app-host.mjs";

const { patchModel, makeRoom, toGeometry, removeElements } = await import(await compiled("../src/viewer/patch.ts", { three: import.meta.resolve("three") }));

/** A box as the server sends it: world metres, IFC Z up, unwelded (one quad of two triangles per face). */
function box(gid, [x, y, z], [sx, sy, sz] = [1, 1, 1], extra = {}) {
  const verts = [], faces = [], normals = [];
  const corner = (i, j, k) => [x + i * sx, y + j * sy, z + k * sz];
  const quads = [[[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, -1]], [[0, 0, 1], [0, 1, 1], [1, 1, 1], [1, 0, 1], [0, 0, 1]],
    [[0, 0, 0], [0, 0, 1], [1, 0, 1], [1, 0, 0], [0, -1, 0]], [[0, 1, 0], [1, 1, 0], [1, 1, 1], [0, 1, 1], [0, 1, 0]],
    [[0, 0, 0], [0, 1, 0], [0, 1, 1], [0, 0, 1], [-1, 0, 0]], [[1, 0, 0], [1, 0, 1], [1, 1, 1], [1, 1, 0], [1, 0, 0]]];
  for (const q of quads) {
    const n = verts.length / 3;
    for (const c of q.slice(0, 4)) { verts.push(...corner(...c)); normals.push(...q[4]); }
    faces.push(n, n + 1, n + 2, n, n + 2, n + 3);
  }
  return { global_id: gid, verts, faces, normals, color: [0.2, 0.4, 0.6, 1], file: 0, ...extra };
}

/** A model the way the loader builds it, with exactly the room its two elements need (none spare). */
function model() {
  const parts = [box("A", [0, 0, 0]), box("B", [3, 0, 0])].map((m) => ({ m, g: toGeometry(m) }));
  const v = parts.reduce((n, p) => n + p.g.getAttribute("position").count, 0);
  const i = parts.reduce((n, p) => n + p.g.getIndex().count, 0);
  const mesh = new THREE.BatchedMesh(parts.length, v, i, new THREE.MeshBasicMaterial());
  const byGlobalId = new Map(), byInstance = new Map();
  for (const { m, g } of parts) {
    const instanceId = mesh.addInstance(mesh.addGeometry(g));
    const el = { globalId: m.global_id, expressId: 1, instanceId, mesh, baseColor: new THREE.Color(0.9, 0.1, 0.1), baseAlpha: 1,
      baseMatrix: new THREE.Matrix4() };
    byGlobalId.set(m.global_id, el); byInstance.set(instanceId, el);
  }
  return { mesh, glass: null, byGlobalId, byInstance, glassByInstance: new Map(), stats: { elements: 2, triangles: 24, parseMs: 1 } };
}

test("a kept fix swaps an element's geometry on its own instance and adds new pieces past the batch's room", () => {
  const m = model();
  const a = m.byGlobalId.get("A"), instance = a.instanceId;
  const glass = [];
  const longer = { ...box("A", [0, 0, 0], [2, 1, 1]), color: null };  // the shortened original, any size: more vertices than room
  const bend = { ...box("P1", [2, 0, 0.5]), color: null };              // a new piece with no style of its own
  const opening = box("PfV", [5, 0, 0], [1, 1, 1], { color: [0.9, 0.5, 0.1, 0.35] });
  const r = patchModel(m, [longer, bend, box("P2", [2.5, 0, 1]), opening],
    () => { const g = new THREE.BatchedMesh(4, 256, 512, new THREE.MeshBasicMaterial()); glass.push(g); return g; },
    (gid) => (gid === "P1" ? { color: a.baseColor, alpha: 1 } : null));
  assert.deepEqual(r.changed, ["A"]); assert.deepEqual(r.added, ["P1", "P2", "PfV"]);
  // The original keeps its instance (colour, visibility, picking); its geometry is the new one, Z up → Y up.
  assert.equal(m.byGlobalId.get("A").instanceId, instance);
  const bounds = m.mesh.getBoundingBoxAt(m.mesh.getGeometryIdAt(instance), new THREE.Box3());
  assert.deepEqual([bounds.min.toArray(), bounds.max.toArray()].map((v) => v.map((c) => c + 0)), [[0, 0, -1], [2, 1, 0]]);
  // New pieces have their own instances, in the maps; a piece with no colour takes its origin's.
  const p1 = m.byGlobalId.get("P1");
  assert.equal(m.byInstance.get(p1.instanceId), p1); assert.equal(p1.baseColor, a.baseColor);
  // A see-through piece goes in a see-through batch, made for it when the model had none.
  assert.equal(glass.length, 1); assert.equal(m.glass, glass[0]);
  const pfv = m.byGlobalId.get("PfV");
  assert.equal(pfv.mesh, m.glass); assert.equal(pfv.baseAlpha, 0.35); assert.equal(m.glassByInstance.get(pfv.instanceId), pfv);
  assert.equal(m.stats.elements, 5);
  assert.equal(m.mesh.instanceCount, 4);  // A, B, P1, P2: nothing lost growing the batch
  assert.equal(m.mesh.boundingSphere, null);  // recomputed on the next frame, so new pieces are not culled
});

test("room is made by packing out what earlier patches freed before growing the batch", () => {
  const m = model();
  patchModel(m, [box("A", [0, 0, 0])], () => { throw new Error("no glass"); });  // frees A's first geometry
  const before = m.mesh.unusedVertexCount;
  makeRoom(m.mesh, 24, 36, 0);
  assert.ok(m.mesh.unusedVertexCount >= 24 && m.mesh.unusedVertexCount >= before);
});

test("accepting patches the model in place at this page's revision, and reloads what it missed when it missed an edit", async () => {
  // Revision 2 changed file 1 (an agent's fix the page never heard of), 3 and 4 file 0.
  for (const [known, patched, downloads] of [[3, 1, 0], [2, 0, 1], [1, 0, 2]]) {
    let fetched = 0;
    const kept = { files: [0], pieces: ["duct", "duct-2"], scene_id: "scene", revision_before: 3, revision: 4,
      meshes: [box("duct", [0, 0, 0]), box("duct-2", [1, 0, 0])], history: [[2, [1]], [3, [0]], [4, [0]]] };
    const host = await appHost({ api: { accept: async () => kept, file: async () => { fetched++; return new Uint8Array([1]); } } });
    const calls = [];
    host.viewer.patch = (meshes, origin) => { calls.push({ meshes, origin }); return true; };
    host.refs.sceneRevision.current = known;
    const work = host.button("Propose fixes").props.onClick(); host.render();
    host.requests.at(-1).resolve({ understanding: "A fix", options: [option], attempts: [] }); await work; host.render();
    await host.button("Accept this fix").props.onClick(); host.render();
    assert.equal(calls.length, patched, `revision ${known}`); assert.equal(fetched, downloads, `revision ${known}`);
    if (patched) assert.equal(calls[0].origin.get("duct-2"), "duct");
    assert.equal(host.refs.sceneRevision.current, 4);
    assert.equal(host.state.evidence.clash.status, "accepted");
    host.unmount();
  }
});

test("an opening the host's team must cut is recorded as requested, and the clash stays open", async () => {
  for (const cut of [true, false]) {
    const kept = { files: [1], pieces: [], scene_id: "scene", revision_before: 3, revision: 4,
      meshes: [box("pfv", [0, 0, 0], [1, 1, 1], { color: [0.96, 0.55, 0.12, 0.35] })],
      ...(cut ? {} : { cut: false, blocked_by: "Structure may not be edited: its team cuts the opening" }) };
    let sent = null, pair = null;
    const host = await appHost({ api: { accept: async (_, o, p) => { sent = o; pair = p; return kept; } } });
    host.viewer.patch = () => true;
    host.refs.sceneRevision.current = 3;
    const opening = { ...option, title: "Opening through the beam's wall", kind: "penetration", moved: ["beam"], delta_m: [0, 0, 0],
      edit: { service: "duct", host: "beam", summary: "Ø170 mm opening through Wall 'W1'", key: "beam|Ø170 mm" }, review: "architecture" };
    const work = host.button("Propose fixes").props.onClick(); host.render();
    host.requests.at(-1).resolve({ understanding: "An opening", options: [opening], attempts: [] }); await work; host.render();
    await host.button("Accept this fix").props.onClick(); host.render();
    assert.equal(sent.kind, "penetration");
    assert.deepEqual(pair, ["duct", "beam"]);   // the clash on screen: the server tries the fix again against it
    const ev = host.state.evidence.clash;
    assert.equal(ev.status, cut ? "accepted" : "recommended");
    assert.equal(ev.edit, "Ø170 mm opening through Wall 'W1'");
    assert.equal(!!host.state.fixes.clash, cut, `cut ${cut}`);
    if (!cut) assert.match(ev.blocked_by, /its team cuts the opening/);
    host.unmount();
  }
});

test("an edit that removes elements takes their instances out and the maps forget them (undo of what a fix made, a delete)", () => {
  const m = model();
  const b = m.byGlobalId.get("B");
  assert.deepEqual(removeElements(m, ["B", "nope"]), ["B"]);
  assert.equal(m.byGlobalId.has("B"), false); assert.equal(m.byInstance.has(b.instanceId), false);
  assert.equal(m.stats.elements, 1);
  assert.throws(() => m.mesh.getGeometryIdAt(b.instanceId));   // its instance went with its geometry
  const r = patchModel(m, [box("B", [3, 0, 0])], () => { throw new Error("no glass needed"); });
  assert.deepEqual(r.added, ["B"]);   // redo brings it back as a new instance
  assert.equal(m.stats.elements, 2);
});
