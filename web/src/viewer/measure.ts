// Measuring (docs/measure.md): the pure parts. Where a plane cuts an element's triangles and how the cut joins into the
// outline's straight runs, clipping an edge to a view's planes, choosing what the pointer snaps to, and the words.
import * as THREE from "three";
import { pointToIfc } from "./origin";

export type SnapKind = "end" | "mid" | "edge" | "face" | "free";
export type Segment = [THREE.Vector3, THREE.Vector3];
/** What a pointer can snap to, in world space: ends (corners, an edge's ends), midpoints and segments. */
export interface Candidates { ends: THREE.Vector3[]; mids: THREE.Vector3[]; segs: Segment[] }
/** One measurement: two points in the model (three.js world), and the view it was taken in (`pane` null: 3D). */
export interface Measurement { id: number; a: THREE.Vector3; b: THREE.Vector3; pane: number | null; view: string }

const EPS = 1e-12;

/** Where `plane` cuts triangles (`pos`: x, y, z of each corner, three corners a triangle): the pieces of the cut. */
export function cutSegments(pos: ArrayLike<number>, plane: THREE.Plane): Segment[] {
  const out: Segment[] = [];
  const p = [new THREE.Vector3(), new THREE.Vector3(), new THREE.Vector3()];
  const d = [0, 0, 0];
  for (let i = 0; i + 8 < pos.length; i += 9) {
    for (let k = 0; k < 3; k++) {
      p[k].set(pos[i + 3 * k], pos[i + 3 * k + 1], pos[i + 3 * k + 2]);
      d[k] = plane.distanceToPoint(p[k]);
    }
    const pts: THREE.Vector3[] = [];
    for (let k = 0; k < 3; k++) {
      const j = (k + 1) % 3;
      if (d[k] === 0) pts.push(p[k].clone());   // a corner on the plane
      if ((d[k] < 0 && d[j] > 0) || (d[k] > 0 && d[j] < 0)) pts.push(p[k].clone().lerp(p[j], d[k] / (d[k] - d[j])));
    }
    const u = pts.filter((q, n) => pts.findIndex((r) => r.distanceToSquared(q) < EPS) === n);
    if (u.length === 2) out.push([u[0], u[1]]);   // a triangle lying in the plane (three points) adds nothing
  }
  return out;
}

/** Join collinear pieces that touch or overlap into straight runs: a face split into two triangles cuts as one line,
 * with one midpoint. `tol` in metres. */
export function mergeRuns(segs: Segment[], tol = 1e-3): Segment[] {
  const lines: { o: THREE.Vector3; dir: THREE.Vector3; spans: [number, number][] }[] = [];
  const off = (p: THREE.Vector3, l: { o: THREE.Vector3; dir: THREE.Vector3 }) => p.clone().sub(l.o).cross(l.dir).length();
  for (const [a, b] of segs) {
    const dir = b.clone().sub(a);
    const len = dir.length();
    if (len < tol) continue;
    dir.divideScalar(len);
    let line = lines.find((l) => Math.abs(Math.abs(l.dir.dot(dir)) - 1) < 1e-6 && off(a, l) < tol && off(b, l) < tol);
    if (!line) { line = { o: a.clone(), dir, spans: [] }; lines.push(line); }
    const s = line.dir.dot(a.clone().sub(line.o)), t = line.dir.dot(b.clone().sub(line.o));
    line.spans.push([Math.min(s, t), Math.max(s, t)]);
  }
  const out: Segment[] = [];
  for (const l of lines) {
    l.spans.sort((x, y) => x[0] - y[0]);
    let [s, e] = l.spans[0];
    for (const [s2, e2] of l.spans.slice(1)) {
      if (s2 <= e + tol) e = Math.max(e, e2);
      else { out.push([l.o.clone().addScaledVector(l.dir, s), l.o.clone().addScaledVector(l.dir, e)]); [s, e] = [s2, e2]; }
    }
    out.push([l.o.clone().addScaledVector(l.dir, s), l.o.clone().addScaledVector(l.dir, e)]);
  }
  return out;
}

/** The part of a segment every plane keeps (its positive side), or null. */
export function clipSegment(a: THREE.Vector3, b: THREE.Vector3, planes: THREE.Plane[]): Segment | null {
  const p = a.clone(), q = b.clone();
  for (const pl of planes) {
    const dp = pl.distanceToPoint(p), dq = pl.distanceToPoint(q);
    if (dp < 0 && dq < 0) return null;
    if (dp < 0) p.lerp(q, dp / (dp - dq));
    else if (dq < 0) q.lerp(p, dq / (dq - dp));
  }
  return p.distanceToSquared(q) > EPS ? [p, q] : null;
}

/** Ends, midpoints and segments for snapping, from segments (duplicate ends dropped). */
export function candidatesOf(segs: Segment[]): Candidates {
  const ends: THREE.Vector3[] = [];
  const add = (p: THREE.Vector3) => { if (!ends.some((q) => q.distanceToSquared(p) < 1e-10)) ends.push(p); };
  for (const [a, b] of segs) { add(a); add(b); }
  return { ends, mids: segs.map(([a, b]) => a.clone().add(b).multiplyScalar(0.5)), segs };
}

export const SNAP_PX = { end: 12, mid: 12, edge: 8 };

/** What the pointer snaps to: the nearest end within `tol.end` pixels, else the nearest midpoint, else the nearest
 * point on a segment. `project` maps a world point to pane pixels (null when it is behind the camera). With `ray` (a
 * perspective view), an edge point is where the pointer's ray passes closest to the edge, exact in depth. */
export function pickSnap(cursor: THREE.Vector2, c: Candidates, project: (p: THREE.Vector3) => THREE.Vector2 | null,
  ray: THREE.Ray | null = null, tol = SNAP_PX): { point: THREE.Vector3; kind: "end" | "mid" | "edge"; px: THREE.Vector2 } | null {
  const nearest = (pts: THREE.Vector3[], kind: "end" | "mid", within: number) => {
    let best: { point: THREE.Vector3; kind: "end" | "mid"; px: THREE.Vector2 } | null = null, bd = within;
    for (const p of pts) {
      const s = project(p);
      if (!s) continue;
      const d = s.distanceTo(cursor);
      if (d <= bd) { bd = d; best = { point: p.clone(), kind, px: s }; }
    }
    return best;
  };
  const end = nearest(c.ends, "end", tol.end);
  if (end) return end;
  const mid = nearest(c.mids, "mid", tol.mid);
  if (mid) return mid;
  let best: { point: THREE.Vector3; kind: "edge"; px: THREE.Vector2 } | null = null, bd = tol.edge;
  for (const [a, b] of c.segs) {
    const sa = project(a), sb = project(b);
    if (!sa || !sb) continue;
    const ab = sb.clone().sub(sa), len = ab.lengthSq();
    if (len < 1e-9) continue;
    const t = THREE.MathUtils.clamp(cursor.clone().sub(sa).dot(ab) / len, 0, 1);
    const s = sa.clone().addScaledVector(ab, t), d = s.distanceTo(cursor);
    if (d > bd) continue;
    bd = d;
    let point = a.clone().lerp(b, t);
    if (ray) { const on = new THREE.Vector3(); ray.distanceSqToSegment(a, b, undefined, on); point = on; }
    best = { point, kind: "edge", px: project(point) ?? s };
  }
  return best;
}

/** IFC axes (x, y, z) from three.js (x, y, z): (x, −z, y). */
const ifc = (v: THREE.Vector3): [number, number, number] => [v.x, -v.z, v.y];
const mm = (m: number) => `${Math.round(m * 1000)}`;

/** A measurement's length and its components along the IFC axes, in millimetres. */
export function measureText(m: Pick<Measurement, "a" | "b">): { length: string; parts: string } {
  const [ax, ay, az] = ifc(m.a), [bx, by, bz] = ifc(m.b);
  return { length: `${mm(m.a.distanceTo(m.b))} mm`, parts: `Δx ${mm(Math.abs(bx - ax))} · Δy ${mm(Math.abs(by - ay))} · Δz ${mm(Math.abs(bz - az))}` };
}

/** One measurement as a line to paste: number, length, components, the view, and both ends in model coordinates. */
export function copyLine(m: Measurement): string {
  const t = measureText(m);
  const at = (v: THREE.Vector3) => `(${pointToIfc(v).map((x) => x.toFixed(3)).join(", ")})`;   // where it is in the model
  return `M${m.id}  ${t.length}  (${t.parts})  ${m.view}  from ${at(m.a)} to ${at(m.b)} m`;
}

export function copyText(ms: Measurement[]): string { return ms.map(copyLine).join("\n"); }
