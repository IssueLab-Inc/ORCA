// The Edit tool's pure parts (docs/manual-edits.md): the live push/pull preview's matrix, the triangles of a picked
// face, a drag in pixels as metres along a face, the tools and what each needs, and the ops the server takes.
// No renderer: tested on their own (tests/edit-helpers.test.mjs).
import * as THREE from "three";

/** IFC axes (metres, Z up) to three.js (Y up), and back: (x, y, z) ↔ (x, z, −y). */
export const toThree = (v: ArrayLike<number>) => new THREE.Vector3(v[0], v[2], -v[1]);
export const toIfcAxes = (v: THREE.Vector3): [number, number, number] => [v.x, -v.z, v.y];

/** A stretch along `axis` (unit) by factor `k`, holding the plane through `anchor` still: T(anchor)·(I + (k−1)aaᵀ)·T(−anchor).
 * A box-like element pushed or pulled at one face is exactly this, so the preview is one instance matrix. */
export function stretchMatrix(anchor: THREE.Vector3, axis: THREE.Vector3, k: number): THREE.Matrix4 {
  const a = axis.clone().normalize(), c = k - 1;
  const s = new THREE.Matrix4().set(
    1 + c * a.x * a.x, c * a.x * a.y, c * a.x * a.z, 0,
    c * a.y * a.x, 1 + c * a.y * a.y, c * a.y * a.z, 0,
    c * a.z * a.x, c * a.z * a.y, 1 + c * a.z * a.z, 0,
    0, 0, 0, 1);
  return new THREE.Matrix4().makeTranslation(anchor.x, anchor.y, anchor.z).multiply(s)
    .multiply(new THREE.Matrix4().makeTranslation(-anchor.x, -anchor.y, -anchor.z));
}

/** How far the element reaches behind a face, along its outward normal: the face's plane less the box's far side. */
export function depthBehind(box: THREE.Box3, point: THREE.Vector3, normal: THREE.Vector3): number {
  const n = normal.clone().normalize();
  let least = Infinity;
  for (const x of [box.min.x, box.max.x]) for (const y of [box.min.y, box.max.y]) for (const z of [box.min.z, box.max.z]) {
    least = Math.min(least, new THREE.Vector3(x, y, z).dot(n));
  }
  return point.dot(n) - least;
}

/** The live preview of pushing a face out `by` metres: the element stretched along the face's normal, its far side
 * still. Null when the push would turn it inside out (the server says why). */
export function pushMatrix(box: THREE.Box3, point: THREE.Vector3, normal: THREE.Vector3, by: number): THREE.Matrix4 | null {
  const n = normal.clone().normalize(), depth = depthBehind(box, point, n);
  if (depth <= 1e-6 || depth + by <= 1e-4) return null;
  const anchor = point.clone().addScaledVector(n, -depth);
  return stretchMatrix(anchor, n, (depth + by) / depth);
}

interface Attr { getX(i: number): number; getY(i: number): number; getZ(i: number): number; count: number }
interface Index { getX(i: number): number }

/** The triangles of one face of an element: those in its index range whose normal is within ~6° of `normal` and whose
 * plane passes within `tol` metres of `point` (all three.js axes). Flat, three floats a vertex, for an overlay. */
export function coplanar(pos: Attr, index: Index, start: number, count: number, normal: THREE.Vector3,
                         point: THREE.Vector3, cos = 0.995, tol = 0.003): Float32Array {
  const n = normal.clone().normalize(), d = n.dot(point);
  const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3(), e = new THREE.Vector3(), f = new THREE.Vector3();
  const out: number[] = [];
  for (let i = start; i + 2 < start + count; i += 3) {
    a.set(pos.getX(index.getX(i)), pos.getY(index.getX(i)), pos.getZ(index.getX(i)));
    b.set(pos.getX(index.getX(i + 1)), pos.getY(index.getX(i + 1)), pos.getZ(index.getX(i + 1)));
    c.set(pos.getX(index.getX(i + 2)), pos.getY(index.getX(i + 2)), pos.getZ(index.getX(i + 2)));
    const tn = e.subVectors(b, a).cross(f.subVectors(c, a));
    const len = tn.length();
    if (len < 1e-12 || tn.divideScalar(len).dot(n) < cos) continue;
    if (Math.abs(a.dot(n) - d) > tol) continue;
    out.push(a.x, a.y, a.z, b.x, b.y, b.z, c.x, c.y, c.z);
  }
  return new Float32Array(out);
}

/** A drag of (dx, dy) pixels as metres along a direction whose screen image is the unit `dir`, `ppm` pixels a metre. */
export const dragMetres = (dx: number, dy: number, dir: { x: number; y: number }, ppm: number) => (dx * dir.x + dy * dir.y) / ppm;

/** Metres to a step: 5 mm while dragging, 1 mm with Shift. */
export const snapTo = (m: number, step = 0.005) => Math.round(m / step) * step;

/** "+150 mm", "−25 mm", "0 mm". */
export function signedMm(m: number): string {
  const v = Math.round(m * 1000);
  return v === 0 ? "0 mm" : `${v > 0 ? "+" : "−"}${Math.abs(v).toLocaleString()} mm`;
}

export type EditToolId = "push_pull" | "align" | "move" | "void" | "cut_by" | "split" | "remove_section" | "clip" | "delete";

/** The edit tools in the palette's order: what each does, the key inside the tool, and what it needs picked. */
export const EDIT_TOOLS: { id: EditToolId; label: string; key: string; needs: "face" | "element"; hint: string }[] = [
  { id: "push_pull", label: "Push/pull a face", key: "p", needs: "face", hint: "Click a face, then drag it or type how far" },
  { id: "align", label: "Align a face to another", key: "a", needs: "face", hint: "Click the face to move, then the face to align it to" },
  { id: "move", label: "Move", key: "t", needs: "element", hint: "Click an element, then type the move or click two points" },
  { id: "void", label: "Cut a void", key: "o", needs: "face", hint: "Click a face, then place the opening" },
  { id: "cut_by", label: "Cut by another element's shape", key: "k", needs: "element", hint: "Click the element to cut, then the one whose shape cuts it" },
  { id: "split", label: "Split in two", key: "b", needs: "element", hint: "Click the element where it splits" },
  { id: "remove_section", label: "Remove a section", key: "r", needs: "element", hint: "Click where the section starts, then where it ends" },
  { id: "clip", label: "Clip an end to a face", key: "j", needs: "face", hint: "Click the end to clip, then the face to clip it to" },
  { id: "delete", label: "Delete", key: "d", needs: "element", hint: "Click the element to delete" },
];

/** Whether a tool can act on what is picked: a face's `allows` (from the server) for face tools, an element for the
 * rest. `ready` lists the tools this build has; the others say so. */
export function toolState(tool: EditToolId, picked: { allows: string[]; name: string } | null, ready: ReadonlySet<EditToolId>):
  { ok: boolean; why: string | null } {
  if (!ready.has(tool)) return { ok: false, why: "Not in this build yet" };
  const t = EDIT_TOOLS.find((x) => x.id === tool)!;
  if (t.needs === "element" || !picked) return { ok: true, why: null };
  if (tool === "void" || tool === "clip" || tool === "push_pull" || tool === "align") {
    return picked.allows.includes(tool) ? { ok: true, why: null } : { ok: false, why: `Its ${picked.name} cannot be ${tool === "push_pull" ? "pushed or pulled" : tool === "align" ? "aligned" : tool === "void" ? "cut" : "clipped"}` };
  }
  return { ok: true, why: null };
}

/** The tool for a key pressed while the Edit tool is on. */
export const toolForKey = (key: string): EditToolId | null => EDIT_TOOLS.find((t) => t.key === key.toLowerCase())?.id ?? null;
