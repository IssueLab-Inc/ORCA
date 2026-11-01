// Loads an IFC with web-ifc into ONE BatchedMesh: one draw call, but every element keeps its own
// transform, colour and visibility. That is what makes "preview option 2" a single matrix update.
// Curves are drawn with 24 sides and shaded smooth across facets within the crease (viewer/normals.ts).
// See-through elements (a robot's safety zone, mesh guards, glazing) go in a second batch drawn after the solid one
// without writing depth, so what is inside them still shows.
import * as THREE from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { IfcAPI } from "web-ifc";
import { creaseNormals, type Creased } from "./normals";
import { pickOrigin, shiftFor } from "./origin";
import { ROOM } from "./patch";

export interface LoadedElement {
  globalId: string;
  expressId: number;
  instanceId: number;
  /** The batch it is drawn in: the model's solid `mesh`, or its see-through `glass`. */
  mesh: THREE.BatchedMesh;
  baseColor: THREE.Color;
  /** 1 for solid elements; the IFC style's opacity for see-through ones. */
  baseAlpha: number;
  baseMatrix: THREE.Matrix4;
}

export interface LoadedModel {
  mesh: THREE.BatchedMesh;
  glass: THREE.BatchedMesh | null;
  byGlobalId: Map<string, LoadedElement>;
  byInstance: Map<number, LoadedElement>;
  glassByInstance: Map<number, LoadedElement>;
  stats: { elements: number; triangles: number; parseMs: number };
  /** The IFC plan point [x, y] (metres) its elements were placed from (viewer/origin.ts). */
  origin: [number, number];
}

let api: IfcAPI | null = null;

async function ifcApi(): Promise<IfcAPI> {
  if (!api) {
    api = new IfcAPI();
    api.SetWasmPath("/wasm/");
    await api.Init();
  }
  return api;
}

/** Sides of a circle (round ducts, pipes, bars). web-ifc's default, 12, drew a round duct as a dodecagon; 24 keeps a
 * 600 mm duct within 3 mm of round. Measured Nov 1: Snowdon Towers' MEP and architecture files and Northbank parse no
 * slower; Snowdon's structure parses about 2 s slower, nearly all of it 14 rebar sweeps. */
export const CIRCLE_SEGMENTS = 24;

/** Parse one IFC. `origin` (IFC plan metres): the point to place its elements from, so a federation shares one; null
 * picks it from this file's elements (`origin.pickOrigin`: zero near zero). */
export async function loadIfc(bytes: Uint8Array, origin: [number, number] | null = null): Promise<LoadedModel> {
  const t0 = performance.now();
  const ifc = await ifcApi();
  // No COORDINATE_TO_ORIGIN: federated discipline files share coordinates, and shifting each by its own
  // offset would pull them apart. The viewer's own origin (below) is shared by every file of a load instead.
  const modelId = ifc.OpenModel(bytes, { COORDINATE_TO_ORIGIN: false, CIRCLE_SEGMENTS });

  type Part = { expressId: number; geometry: THREE.BufferGeometry; color: THREE.Color; alpha: number };
  type Placed = { shape: Creased; matrix: THREE.Matrix4 };
  // Placed first and baked once the origin is known: their placements decide it.
  const found: { expressId: number; placed: Placed[]; color: THREE.Color; alpha: number }[] = [];
  // Each geometry's triangles with creased normals, in its own coordinates: a type placed many times (a fitting, a
  // window) is smoothed once. Kept for the parse only.
  const smoothed = new Map<number, Creased>();
  ifc.StreamAllMeshes(modelId, (flat) => {
    const placedHere: Placed[] = [];
    let color: THREE.Color | null = null;
    let alpha = 1;
    for (let i = 0; i < flat.geometries.size(); i++) {
      const placed = flat.geometries.get(i);
      let shape = smoothed.get(placed.geometryExpressID);
      if (!shape) {
        const g = ifc.GetGeometry(modelId, placed.geometryExpressID);
        // Interleaved x, y, z, nx, ny, nz; web-ifc's normals are flat per facet, so only the positions are kept.
        const verts = ifc.GetVertexArray(g.GetVertexData(), g.GetVertexDataSize());
        const index = ifc.GetIndexArray(g.GetIndexData(), g.GetIndexDataSize());
        const position = new Float32Array(verts.length / 2);
        for (let k = 0, j = 0; k < verts.length; k += 6, j += 3) {
          position[j] = verts[k]; position[j + 1] = verts[k + 1]; position[j + 2] = verts[k + 2];
        }
        g.delete();
        shape = creaseNormals(position, index);
        smoothed.set(placed.geometryExpressID, shape);
      }
      placedHere.push({ shape, matrix: new THREE.Matrix4().fromArray(placed.flatTransformation) });
      if (!color) {
        color = new THREE.Color(placed.color.x, placed.color.y, placed.color.z);
        alpha = placed.color.w;
      }
    }
    if (placedHere.length) found.push({ expressId: flat.expressID, placed: placedHere, color: color ?? new THREE.Color(0.8, 0.8, 0.8), alpha });
  });
  smoothed.clear();

  // Where to draw from: float32 vertices 418 km out step 31 mm, so each placement is taken relative to the origin in
  // double precision before its vertices are written (web-ifc's placements are Y up: IFC x is [12], IFC y is −[14]).
  const at = origin ?? pickOrigin(found.map((f) => f.placed[0].matrix.elements[12]), found.map((f) => -f.placed[0].matrix.elements[14]));
  const shift = shiftFor(at);
  const parts: Part[] = [];
  for (const f of found) {
    const pieces = f.placed.map(({ shape, matrix }) => {
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.BufferAttribute(shape.position.slice(), 3));
      geo.setAttribute("normal", new THREE.BufferAttribute(shape.normal.slice(), 3));
      geo.setIndex(new THREE.BufferAttribute(shape.index, 1));   // never changed: shared by every placement
      // Bake the placement so each element's instance matrix starts as identity; previews are then deltas.
      geo.applyMatrix4(shift.clone().multiply(matrix));
      return geo;
    });
    const merged = pieces.length === 1 ? pieces[0] : mergeGeometries(pieces, false);
    if (merged) parts.push({ expressId: f.expressId, geometry: merged, color: f.color, alpha: f.alpha });
  }
  found.length = 0;

  const byGlobalId = new Map<string, LoadedElement>();
  const batch = (list: Part[], byInstance: Map<number, LoadedElement>) => {
    let vertexCount = 0;
    let indexCount = 0;
    for (const p of list) {
      vertexCount += p.geometry.getAttribute("position").count;
      indexCount += p.geometry.getIndex()?.count ?? 0;
    }
    const material = new THREE.MeshStandardMaterial({ metalness: 0, roughness: 0.85, side: THREE.DoubleSide });
    // Room for the pieces a kept fix adds (offset and route pieces, bends), so accepting one patches the batch in place
    // (viewer/patch.ts) instead of regrowing it the first time.
    const mesh = new THREE.BatchedMesh(list.length + ROOM.instances, vertexCount + ROOM.vertices, indexCount + ROOM.indices, material);
    for (const p of list) {
      const instanceId = mesh.addInstance(mesh.addGeometry(p.geometry));
      mesh.setColorAt(instanceId, new THREE.Vector4(p.color.r, p.color.g, p.color.b, p.alpha));
      const globalId: string = ifc.GetLine(modelId, p.expressId)?.GlobalId?.value ?? `#${p.expressId}`;
      const el = { globalId, expressId: p.expressId, instanceId, mesh, baseColor: p.color, baseAlpha: p.alpha,
        baseMatrix: new THREE.Matrix4() };
      byGlobalId.set(globalId, el);
      byInstance.set(instanceId, el);
      p.geometry.dispose();
    }
    return { mesh, triangles: indexCount / 3 };
  };
  const SEE_THROUGH = 0.99;
  const byInstance = new Map<number, LoadedElement>();
  const glassByInstance = new Map<number, LoadedElement>();
  const solid = batch(parts.filter((p) => p.alpha >= SEE_THROUGH), byInstance);
  const seeThrough = parts.filter((p) => p.alpha < SEE_THROUGH);
  const glass = seeThrough.length ? batch(seeThrough, glassByInstance) : null;
  ifc.CloseModel(modelId);
  return {
    mesh: solid.mesh, glass: glass?.mesh ?? null, byGlobalId, byInstance, glassByInstance,
    stats: { elements: parts.length, triangles: solid.triangles + (glass?.triangles ?? 0),
      parseMs: Math.round(performance.now() - t0) },
    origin: at,
  };
}
