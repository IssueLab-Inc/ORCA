// The point the viewer draws from. Vertices on the GPU are float32, which 418 km from zero (Autodesk's Snowdon Towers,
// a Revit export in survey coordinates) steps 31 mm: a 200 mm duct's vertices snap to that grid and its round end
// comes out square. So the loader places every element relative to this point, in double precision, and every IFC
// point crossing into or out of the viewer goes through here. Only plan x and y move: heights stay as they are, so
// levels, plan cuts and the server's elevations need nothing. Saved views (camera poses in viewer coordinates) stay
// valid because the same files give the same origin.
import * as THREE from "three";

/** Within this many metres of zero a model is drawn where it is (float32 still steps under a tenth of a millimetre
 * there), so Northbank and the machine cell are drawn exactly as before. */
export const NEAR_M = 1000;

let ox = 0, oy = 0;

/** The origin of the models on screen, IFC metres [x, y]. */
export function origin(): [number, number] { return [ox, oy]; }

/** Set when models are adopted (`Viewer.load`); null or nothing: zero. */
export function setOrigin(o: readonly number[] | null | undefined) { ox = o?.[0] ?? 0; oy = o?.[1] ?? 0; }

/** The origin for a model whose elements stand at these IFC plan positions: their median (one stray element at the
 * internal origin does not pull it away), to the metre, or zero when that is near. */
export function pickOrigin(xs: number[], ys: number[]): [number, number] {
  if (!xs.length || !ys.length) return [0, 0];
  const mid = (a: number[]) => [...a].sort((p, q) => p - q)[a.length >> 1];
  const x = mid(xs), y = mid(ys);
  return Math.hypot(x, y) < NEAR_M ? [0, 0] : [Math.round(x), Math.round(y)];
}

/** The translation that takes a three.js position placed in IFC world coordinates to one relative to `o`. */
export function shiftFor(o: readonly number[]): THREE.Matrix4 { return new THREE.Matrix4().makeTranslation(-o[0], 0, o[1]); }

/** An IFC point (metres, Z up) in the viewer (three.js, Y up, relative to the origin). */
export function pointToThree(x: number, y: number, z: number): THREE.Vector3 { return new THREE.Vector3(x - ox, z, oy - y); }

/** A viewer point in IFC metres. */
export function pointToIfc(v: THREE.Vector3): [number, number, number] { return [v.x + ox, oy - v.z, v.y]; }

/** Server triangles' vertices (IFC metres, Z up, flat x, y, z…) as viewer positions. */
export function serverVerts(verts: ArrayLike<number>): Float32Array {
  const out = new Float32Array(verts.length);
  for (let i = 0; i < verts.length; i += 3) {
    out[i] = verts[i] - ox; out[i + 1] = verts[i + 2]; out[i + 2] = oy - verts[i + 1];
  }
  return out;
}
