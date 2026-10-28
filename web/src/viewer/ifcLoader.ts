// Loads an IFC with web-ifc into ONE BatchedMesh: one draw call, but every element keeps its own
// transform, colour and visibility. That is what makes "preview option 2" a single matrix update.
// See-through elements (a robot's safety zone, mesh guards, glazing) go in a second batch drawn after the solid one
// without writing depth, so what is inside them still shows.
import * as THREE from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { IfcAPI } from "web-ifc";

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

export async function loadIfc(bytes: Uint8Array): Promise<LoadedModel> {
  const t0 = performance.now();
  const ifc = await ifcApi();
  // No COORDINATE_TO_ORIGIN: federated discipline files share coordinates, and shifting each by its own
  // offset would pull them apart.
  const modelId = ifc.OpenModel(bytes, { COORDINATE_TO_ORIGIN: false });

  type Part = { expressId: number; geometry: THREE.BufferGeometry; color: THREE.Color; alpha: number };
  const parts: Part[] = [];
  ifc.StreamAllMeshes(modelId, (flat) => {
    const pieces: THREE.BufferGeometry[] = [];
    let color: THREE.Color | null = null;
    let alpha = 1;
    for (let i = 0; i < flat.geometries.size(); i++) {
      const placed = flat.geometries.get(i);
      const g = ifc.GetGeometry(modelId, placed.geometryExpressID);
      // Interleaved x, y, z, nx, ny, nz
      const verts = ifc.GetVertexArray(g.GetVertexData(), g.GetVertexDataSize());
      const index = ifc.GetIndexArray(g.GetIndexData(), g.GetIndexDataSize());
      const buf = new THREE.InterleavedBuffer(new Float32Array(verts), 6);
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.InterleavedBufferAttribute(buf, 3, 0));
      geo.setAttribute("normal", new THREE.InterleavedBufferAttribute(buf, 3, 3));
      geo.setIndex(new THREE.BufferAttribute(new Uint32Array(index), 1));
      // Bake the placement so each element's instance matrix starts as identity; previews are then deltas.
      geo.applyMatrix4(new THREE.Matrix4().fromArray(placed.flatTransformation));
      pieces.push(deinterleave(geo));
      if (!color) {
        color = new THREE.Color(placed.color.x, placed.color.y, placed.color.z);
        alpha = placed.color.w;
      }
      g.delete();
    }
    if (pieces.length) {
      const merged = pieces.length === 1 ? pieces[0] : mergeGeometries(pieces, false);
      if (merged) parts.push({ expressId: flat.expressID, geometry: merged, color: color ?? new THREE.Color(0.8, 0.8, 0.8), alpha });
    }
  });

  const byGlobalId = new Map<string, LoadedElement>();
  const batch = (list: Part[], byInstance: Map<number, LoadedElement>) => {
    let vertexCount = 0;
    let indexCount = 0;
    for (const p of list) {
      vertexCount += p.geometry.getAttribute("position").count;
      indexCount += p.geometry.getIndex()?.count ?? 0;
    }
    const material = new THREE.MeshStandardMaterial({ metalness: 0, roughness: 0.85, side: THREE.DoubleSide });
    const mesh = new THREE.BatchedMesh(list.length, vertexCount, indexCount, material);
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
  };
}

function deinterleave(geo: THREE.BufferGeometry): THREE.BufferGeometry {
  const out = new THREE.BufferGeometry();
  for (const name of ["position", "normal"]) {
    const a = geo.getAttribute(name);
    const arr = new Float32Array(a.count * 3);
    for (let i = 0; i < a.count; i++) {
      arr[i * 3] = a.getX(i);
      arr[i * 3 + 1] = a.getY(i);
      arr[i * 3 + 2] = a.getZ(i);
    }
    out.setAttribute(name, new THREE.BufferAttribute(arr, 3));
  }
  out.setIndex(geo.getIndex());
  return out;
}
