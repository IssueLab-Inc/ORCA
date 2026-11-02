// Parsing an IFC into triangles, off the page's thread (viewer/ifcWorker.ts runs it; viewer/ifcLoader.ts asks it and
// builds the batches from what comes back) or on it when no worker starts. web-ifc reads the file and tessellates; each
// geometry gets creased normals once (viewer/normals.ts), and each placement is baked relative to the origin in double
// precision (viewer/origin.ts). What it returns is a few long typed arrays, so they cross to the page without copying.
import * as THREE from "three";
import type { IfcAPI } from "web-ifc";
import { creaseNormals, type Creased } from "./normals";
import { pickOrigin, shiftFor } from "./origin";

/** Sides of a circle (round ducts, pipes, bars). web-ifc's default, 12, drew a round duct as a dodecagon; 24 keeps a
 * 600 mm duct within 3 mm of round. Measured Nov 1: Snowdon Towers' MEP and architecture files and Northbank parse no
 * slower; Snowdon's structure parses about 2 s slower, nearly all of it 14 rebar sweeps. */
export const CIRCLE_SEGMENTS = 24;

/** One IFC's elements, each with every placement baked from `origin` and merged (three.js, Y up). Element `e`'s
 * vertices are `position`/`normal` from `vertexStart[e]` for `vertexCount[e]` (x, y, z each), its triangles `index`
 * from `indexStart[e]` for `indexCount[e]`, numbered from its own first vertex. */
export interface ParsedModel {
  expressIds: Uint32Array;
  globalIds: string[];
  /** r, g, b, a per element: its first placement's style. */
  colors: Float32Array;
  vertexStart: Uint32Array;
  vertexCount: Uint32Array;
  indexStart: Uint32Array;
  indexCount: Uint32Array;
  position: Float32Array;
  normal: Float32Array;
  index: Uint32Array;
  /** The IFC plan point [x, y] (metres) the elements were placed from. */
  origin: [number, number];
}

/** The buffers a parsed model is made of: handed over to the page, not copied. */
export function buffers(p: ParsedModel): ArrayBuffer[] {
  return [p.expressIds, p.colors, p.vertexStart, p.vertexCount, p.indexStart, p.indexCount, p.position, p.normal, p.index]
    .map((a) => a.buffer as ArrayBuffer);
}

/** Parse one IFC with an initialised web-ifc. `origin` (IFC plan metres): the point to place its elements from, so a
 * federation shares one; null picks it from this file's elements (`origin.pickOrigin`: zero near zero). */
export function parseIfc(ifc: IfcAPI, bytes: Uint8Array, origin: [number, number] | null): ParsedModel {
  // No COORDINATE_TO_ORIGIN: federated discipline files share coordinates, and shifting each by its own offset would
  // pull them apart. The viewer's own origin (below) is shared by every file of a load instead.
  const modelId = ifc.OpenModel(bytes, { COORDINATE_TO_ORIGIN: false, CIRCLE_SEGMENTS });
  try {
    type Placed = { shape: Creased; matrix: THREE.Matrix4 };
    // Placed first and baked once the origin is known: their placements decide it.
    const found: { expressId: number; placed: Placed[]; color: [number, number, number, number] }[] = [];
    // Each geometry's triangles with creased normals, in its own coordinates: a type placed many times (a fitting, a
    // window) is smoothed once. Kept for the parse only.
    const smoothed = new Map<number, Creased>();
    ifc.StreamAllMeshes(modelId, (flat) => {
      const placedHere: Placed[] = [];
      let color: [number, number, number, number] | null = null;
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
        color ??= [placed.color.x, placed.color.y, placed.color.z, placed.color.w];
      }
      if (placedHere.length) found.push({ expressId: flat.expressID, placed: placedHere, color: color ?? [0.8, 0.8, 0.8, 1] });
    });
    smoothed.clear();

    // Where to draw from: float32 vertices 418 km out step 31 mm, so each placement is taken relative to the origin in
    // double precision before its vertices are written (web-ifc's placements are Y up: IFC x is [12], IFC y is −[14]).
    const at = origin ?? pickOrigin(found.map((f) => f.placed[0].matrix.elements[12]), found.map((f) => -f.placed[0].matrix.elements[14]));
    const shift = shiftFor(at);
    const n = found.length;
    let vertices = 0, indices = 0;
    for (const f of found) for (const { shape } of f.placed) { vertices += shape.position.length / 3; indices += shape.index.length; }
    const out: ParsedModel = {
      expressIds: new Uint32Array(n), globalIds: new Array<string>(n), colors: new Float32Array(n * 4),
      vertexStart: new Uint32Array(n), vertexCount: new Uint32Array(n), indexStart: new Uint32Array(n), indexCount: new Uint32Array(n),
      position: new Float32Array(vertices * 3), normal: new Float32Array(vertices * 3), index: new Uint32Array(indices), origin: at,
    };
    const m = new THREE.Matrix4(), nm = new THREE.Matrix3(), v = new THREE.Vector3();
    let vAt = 0, iAt = 0;
    found.forEach((f, e) => {
      out.expressIds[e] = f.expressId;
      out.globalIds[e] = ifc.GetLine(modelId, f.expressId)?.GlobalId?.value ?? `#${f.expressId}`;
      out.colors.set(f.color, e * 4);
      out.vertexStart[e] = vAt; out.indexStart[e] = iAt;
      let base = 0;   // the element's own vertex count so far: a later placement's triangles are numbered after it
      for (const { shape, matrix } of f.placed) {
        // Bake the placement so each element's instance matrix starts as identity; previews are then deltas.
        m.multiplyMatrices(shift, matrix);
        nm.getNormalMatrix(m);
        const count = shape.position.length / 3;
        for (let k = 0; k < count; k++) {
          const o = (vAt + base + k) * 3;
          v.fromArray(shape.position, k * 3).applyMatrix4(m);
          out.position[o] = v.x; out.position[o + 1] = v.y; out.position[o + 2] = v.z;
          v.fromArray(shape.normal, k * 3).applyMatrix3(nm).normalize();
          out.normal[o] = v.x; out.normal[o + 1] = v.y; out.normal[o + 2] = v.z;
        }
        for (let k = 0; k < shape.index.length; k++) out.index[iAt + k] = shape.index[k] + base;
        iAt += shape.index.length;
        base += count;
      }
      out.vertexCount[e] = base;
      out.indexCount[e] = iAt - out.indexStart[e];
      vAt += base;
    });
    return out;
  } finally { ifc.CloseModel(modelId); }
}
