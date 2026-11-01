// Accepting a fix used to download and re-parse the whole IFC file it changed. The server now sends the changed and
// new elements' triangles instead (server: Workspace.patch), and this swaps them into the model's batches in place:
// an element keeps its instance (id, colour, visibility), new pieces get their own. Pure over the LoadedModel, so it
// is tested without a renderer; the Viewer redraws afterwards.
import * as THREE from "three";
import type { LoadedElement, LoadedModel } from "./ifcLoader";

/** One element's triangles from the server: world metres, IFC Z up, unwelded, with normals and its style's colour. */
export interface ElementMesh {
  global_id: string; verts: number[]; faces: number[]; normals?: number[]; color?: number[] | null; file?: number;
}

const SEE_THROUGH = 0.99;

/** Spare space in each batch for what kept fixes add (the loader reserves it; makeRoom grows past it when needed). */
export const ROOM = { instances: 64, vertices: 16384, indices: 49152 };

/** Server triangles as a batch-ready geometry: IFC Z up → three.js Y up, (x, y, z) → (x, z, −y), normals likewise. */
export function toGeometry(m: ElementMesh): THREE.BufferGeometry {
  const flip = (src: number[]) => {
    const out = new Float32Array(src.length);
    for (let i = 0; i < src.length; i += 3) { out[i] = src[i]; out[i + 1] = src[i + 2]; out[i + 2] = -src[i + 1]; }
    return out;
  };
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(flip(m.verts), 3));
  g.setIndex(new THREE.BufferAttribute(new Uint32Array(m.faces), 1));
  if (m.normals && m.normals.length === m.verts.length) g.setAttribute("normal", new THREE.BufferAttribute(flip(m.normals), 3));
  else g.computeVertexNormals();
  return g;
}

/** Make sure `batch` has room for `vertices`, `indices` and `instances` more: first by packing out what earlier patches
 * freed, then by growing to twice what is needed. Growing replaces the batch's geometry buffers, so anything sharing
 * them (the viewer's focus geometry) must be rebuilt afterwards. Returns whether the buffers were replaced. */
export function makeRoom(batch: THREE.BatchedMesh, vertices: number, indices: number, instances: number): boolean {
  let replaced = false;
  if (batch.unusedVertexCount < vertices || batch.unusedIndexCount < indices) {
    batch.optimize();
    replaced = true;  // ranges moved
  }
  if (batch.unusedVertexCount < vertices || batch.unusedIndexCount < indices) {
    // three r186 keeps the buffer sizes private; unusedVertexCount and unusedIndexCount are measured against them.
    const size = batch as unknown as { _maxVertexCount: number; _maxIndexCount: number };
    batch.setGeometrySize(size._maxVertexCount + 2 * vertices, size._maxIndexCount + 2 * indices);
  }
  if (batch.instanceCount + instances > batch.maxInstanceCount) {
    batch.setInstanceCount(batch.maxInstanceCount + 2 * instances);
  }
  return replaced;
}

/** Swap `meshes` into `model`. An element already drawn gets the new geometry on its own instance; a new one (a split
 * run's pieces, a bend) is added, coloured from its mesh, else from `colourOf` (the element it came from), and drawn
 * see-through when its alpha says so (`glassFor` makes the model's see-through batch when it has none). */
export function patchModel(model: LoadedModel, meshes: ElementMesh[], glassFor: () => THREE.BatchedMesh,
  colourOf: (globalId: string) => { color: THREE.Color; alpha: number } | null = () => null): { added: string[]; changed: string[] } {
  const prepared = meshes.map((m) => {
    const old = model.byGlobalId.get(m.global_id);
    const c = m.color;
    const known = c ? { color: new THREE.Color(c[0], c[1], c[2]), alpha: c[3] ?? 1 }
      : old ? { color: old.baseColor, alpha: old.baseAlpha } : colourOf(m.global_id) ?? { color: new THREE.Color(0.75, 0.75, 0.75), alpha: 1 };
    return { m, old, geometry: toGeometry(m), ...known, seeThrough: known.alpha < SEE_THROUGH };
  });
  // Room first, per batch, all at once: an element that changes batch (its opacity changed) counts as new there.
  const batchFor = (p: (typeof prepared)[number]) => (p.seeThrough ? (model.glass ??= glassFor()) : model.mesh);
  const need = new Map<THREE.BatchedMesh, { v: number; i: number; n: number }>();
  for (const p of prepared) {
    const b = batchFor(p);
    const r = need.get(b) ?? { v: 0, i: 0, n: 0 };
    r.v += p.geometry.getAttribute("position").count;
    r.i += p.geometry.getIndex()!.count;
    if (!p.old || p.old.mesh !== b) r.n += 1;
    need.set(b, r);
  }
  for (const [b, r] of need) makeRoom(b, r.v, r.i, r.n);

  const added: string[] = [], changed: string[] = [];
  for (const p of prepared) {
    const b = batchFor(p);
    const instances = (mesh: THREE.BatchedMesh) => (mesh === model.mesh ? model.byInstance : model.glassByInstance);
    if (p.old && p.old.mesh === b) {
      // Same instance, new geometry: add first, point the instance at it, then drop the old (dropping first would
      // drop the instance with it).
      const fresh = b.addGeometry(p.geometry);
      const stale = b.getGeometryIdAt(p.old.instanceId);
      b.setGeometryIdAt(p.old.instanceId, fresh);
      b.deleteGeometry(stale);
      p.old.baseColor = p.color; p.old.baseAlpha = p.alpha;
      b.setColorAt(p.old.instanceId, new THREE.Vector4(p.color.r, p.color.g, p.color.b, p.alpha));
      changed.push(p.m.global_id);
    } else {
      if (p.old) {   // it changed batch: leave the old one
        p.old.mesh.deleteGeometry(p.old.mesh.getGeometryIdAt(p.old.instanceId));
        instances(p.old.mesh).delete(p.old.instanceId);
      }
      const instanceId = b.addInstance(b.addGeometry(p.geometry));
      b.setColorAt(instanceId, new THREE.Vector4(p.color.r, p.color.g, p.color.b, p.alpha));
      b.setMatrixAt(instanceId, new THREE.Matrix4());
      const el: LoadedElement = { globalId: p.m.global_id, expressId: p.old?.expressId ?? -1, instanceId, mesh: b,
        baseColor: p.color, baseAlpha: p.alpha, baseMatrix: new THREE.Matrix4() };
      model.byGlobalId.set(p.m.global_id, el);
      instances(b).set(instanceId, el);   // an id freed earlier may come back: this replaces its stale entry
      if (!p.old) { added.push(p.m.global_id); model.stats.elements += 1; }
      else changed.push(p.m.global_id);
    }
    model.stats.triangles += p.geometry.getIndex()!.count / 3;
    p.geometry.dispose();
  }
  for (const b of need.keys()) { b.boundingBox = null; b.boundingSphere = null; }
  return { added, changed };
}

/** Take elements out of `model` (an edit removed them, or undo took back what it made): their instance and geometry
 * go, and the maps forget them. Returns the GlobalIds it held. */
export function removeElements(model: LoadedModel, globalIds: Iterable<string>): string[] {
  const gone: string[] = [];
  for (const gid of globalIds) {
    const el = model.byGlobalId.get(gid);
    if (!el) continue;
    // Deleting the geometry deletes the instances drawing it (one per element here).
    el.mesh.deleteGeometry(el.mesh.getGeometryIdAt(el.instanceId));
    (el.mesh === model.mesh ? model.byInstance : model.glassByInstance).delete(el.instanceId);
    model.byGlobalId.delete(gid);
    model.stats.elements -= 1;
    el.mesh.boundingBox = null; el.mesh.boundingSphere = null;
    gone.push(gid);
  }
  return gone;
}
