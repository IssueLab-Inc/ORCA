// Smooth shading for curved surfaces without rounding off real edges. web-ifc gives every facet a flat normal of its
// own, so a round duct or a Revit fitting shades as a ring of stripes and a see-through view shows every facet. Here
// each vertex takes the average of the facets that meet at its point and lie within `CREASE` of its own facet
// (weighted by the angle each makes there), so the facets of a curve blend into one surface and an edge sharper than
// the crease stays sharp. A vertex is split only where its triangles need different normals (a box welded at its
// corners); a vertex that belongs to one flat face, as web-ifc's do, keeps its place, so nothing grows.
import * as THREE from "three";

/** Facets meeting at less than this shade as one surface; at more, the edge stays sharp. A 12-sided round (30°) and
 * Revit's tessellated fittings (5–30°) shade smooth; a hexagon (60°) and the 85–90° edges of a building stay sharp.
 * The outlines use the same angle (Viewer.edgeGeometryOf), so a line is drawn exactly where the shading creases. */
export const CREASE = (40 * Math.PI) / 180;
export const CREASE_DEGREES = 40;

/** Points closer than this (in the geometry's own units) count as one point. */
const GRID = 1e-5;

export interface Creased { position: Float32Array; normal: Float32Array; index: Uint32Array }

/** Normals for triangles `index` (every three vertices when null) over `position`, smooth across facets within
 * `crease` radians of each other and sharp beyond. Returns the positions (with any split vertices appended), their
 * normals and the index. */
export function creaseNormals(position: ArrayLike<number>, index: ArrayLike<number> | null, crease = CREASE): Creased {
  const vertices = Math.floor(position.length / 3);
  let tri: Uint32Array;
  if (index) tri = index instanceof Uint32Array ? index : Uint32Array.from(index);
  else { tri = new Uint32Array(vertices - (vertices % 3)); for (let i = 0; i < tri.length; i++) tri[i] = i; }
  const corners = tri.length - (tri.length % 3), faces = corners / 3;

  // Each facet's unit normal (0 when it has no area) and the angle at each of its corners.
  const fn = new Float64Array(faces * 3), angle = new Float64Array(corners);
  for (let f = 0; f < faces; f++) {
    const a = tri[f * 3] * 3, b = tri[f * 3 + 1] * 3, c = tri[f * 3 + 2] * 3;
    const ux = position[b] - position[a], uy = position[b + 1] - position[a + 1], uz = position[b + 2] - position[a + 2];
    const wx = position[c] - position[a], wy = position[c + 1] - position[a + 1], wz = position[c + 2] - position[a + 2];
    const nx = uy * wz - uz * wy, ny = uz * wx - ux * wz, nz = ux * wy - uy * wx;
    const l = Math.hypot(nx, ny, nz);
    if (l < 1e-20) continue;
    fn[f * 3] = nx / l; fn[f * 3 + 1] = ny / l; fn[f * 3 + 2] = nz / l;
    for (let k = 0; k < 3; k++) {
      const p = tri[f * 3 + k] * 3, q = tri[f * 3 + (k + 1) % 3] * 3, r = tri[f * 3 + (k + 2) % 3] * 3;
      const ax = position[q] - position[p], ay = position[q + 1] - position[p + 1], az = position[q + 2] - position[p + 2];
      const bx = position[r] - position[p], by = position[r + 1] - position[p + 1], bz = position[r + 2] - position[p + 2];
      const cx = ay * bz - az * by, cy = az * bx - ax * bz, cz = ax * by - ay * bx;
      angle[f * 3 + k] = Math.atan2(Math.hypot(cx, cy, cz), ax * bx + ay * by + az * bz);
    }
  }

  // One id per point: vertices at the same place (to GRID) share it. Open addressing over the quantised coordinates.
  const point = pointIds(position, vertices);
  const points = point.count, at = point.ids;

  // The corners at each point (compressed rows).
  const start = new Uint32Array(points + 1);
  for (let k = 0; k < corners; k++) start[at[tri[k]] + 1]++;
  for (let i = 0; i < points; i++) start[i + 1] += start[i];
  const fill = start.slice(0, points), byPoint = new Uint32Array(corners);
  for (let k = 0; k < corners; k++) byPoint[fill[at[tri[k]]]++] = k;

  // Each output vertex: its source vertex and normal. A source vertex keeps its own slot for the first corner that
  // claims it; a corner whose normal differs takes a split (chained per source vertex, so equal ones are shared).
  const cosCrease = Math.cos(crease);
  let capacity = vertices + 16, count = vertices;
  let normal = new Float32Array(capacity * 3), source = new Uint32Array(capacity), next = new Int32Array(capacity).fill(-1);
  for (let i = 0; i < vertices; i++) source[i] = i;
  const claimed = new Uint8Array(vertices);
  const out = new Uint32Array(corners);
  for (let k = 0; k < corners; k++) {
    const f = (k / 3) | 0, v = tri[k];
    const fx = fn[f * 3], fy = fn[f * 3 + 1], fz = fn[f * 3 + 2];
    if (fx === 0 && fy === 0 && fz === 0) { out[k] = v; continue; }   // no area: draws nothing, any normal will do
    let sx = 0, sy = 0, sz = 0;
    const p = at[v];
    for (let j = start[p]; j < start[p + 1]; j++) {
      const g = ((byPoint[j] / 3) | 0) * 3;
      const gx = fn[g], gy = fn[g + 1], gz = fn[g + 2];
      if (fx * gx + fy * gy + fz * gz < cosCrease) continue;
      const w = angle[byPoint[j]];
      sx += gx * w; sy += gy * w; sz += gz * w;
    }
    const l = Math.hypot(sx, sy, sz);
    if (l > 1e-12) { sx /= l; sy /= l; sz /= l; } else { sx = fx; sy = fy; sz = fz; }
    if (!claimed[v]) {
      claimed[v] = 1; normal[v * 3] = sx; normal[v * 3 + 1] = sy; normal[v * 3 + 2] = sz; out[k] = v;
      continue;
    }
    let slot = v, found = -1;
    while (slot >= 0) {
      if (normal[slot * 3] * sx + normal[slot * 3 + 1] * sy + normal[slot * 3 + 2] * sz > 0.9999) { found = slot; break; }
      if (next[slot] < 0) break;
      slot = next[slot];
    }
    if (found < 0) {
      if (count === capacity) {
        capacity *= 2;
        const n2 = new Float32Array(capacity * 3); n2.set(normal); normal = n2;
        const s2 = new Uint32Array(capacity); s2.set(source); source = s2;
        const x2 = new Int32Array(capacity).fill(-1); x2.set(next); next = x2;
      }
      found = count++;
      source[found] = v; normal[found * 3] = sx; normal[found * 3 + 1] = sy; normal[found * 3 + 2] = sz;
      next[slot] = found;
    }
    out[k] = found;
  }

  const pos = new Float32Array(count * 3), nor = new Float32Array(count * 3);
  for (let i = 0; i < count; i++) {
    const s = source[i] * 3;
    pos[i * 3] = position[s]; pos[i * 3 + 1] = position[s + 1]; pos[i * 3 + 2] = position[s + 2];
    if (i < vertices && !claimed[i]) { nor[i * 3 + 1] = 1; continue; }   // used by no real triangle
    nor[i * 3] = normal[i * 3]; nor[i * 3 + 1] = normal[i * 3 + 1]; nor[i * 3 + 2] = normal[i * 3 + 2];
  }
  return { position: pos, normal: nor, index: out };
}

/** A geometry with creased normals from bare triangles. */
export function creased(position: ArrayLike<number>, index: ArrayLike<number> | null, crease = CREASE): THREE.BufferGeometry {
  const c = creaseNormals(position, index, crease);
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(c.position, 3));
  g.setAttribute("normal", new THREE.BufferAttribute(c.normal, 3));
  g.setIndex(new THREE.BufferAttribute(c.index, 1));
  return g;
}

/** An id per distinct point (to GRID), for each vertex. */
function pointIds(position: ArrayLike<number>, vertices: number): { ids: Uint32Array; count: number } {
  let size = 16;
  while (size < vertices * 2) size *= 2;
  const table = new Int32Array(size).fill(-1);   // slot → point id
  const keys = new Float64Array(vertices * 3);   // point id → its quantised coordinates
  const ids = new Uint32Array(vertices);
  let count = 0;
  for (let v = 0; v < vertices; v++) {
    const x = Math.round(position[v * 3] / GRID), y = Math.round(position[v * 3 + 1] / GRID), z = Math.round(position[v * 3 + 2] / GRID);
    let h = (Math.imul(x | 0, 73856093) ^ Math.imul(y | 0, 19349663) ^ Math.imul(z | 0, 83492791)) & (size - 1);
    for (;;) {
      const id = table[h];
      if (id < 0) {
        table[h] = count; keys[count * 3] = x; keys[count * 3 + 1] = y; keys[count * 3 + 2] = z;
        ids[v] = count++;
        break;
      }
      if (keys[id * 3] === x && keys[id * 3 + 1] === y && keys[id * 3 + 2] === z) { ids[v] = id; break; }
      h = (h + 1) & (size - 1);
    }
  }
  return { ids, count };
}
