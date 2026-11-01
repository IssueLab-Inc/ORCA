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

/** Faces whose plane only a pick on them says (an I-section's inner faces, a mesh's face, a round side, a face ORCA
 * does not edit): an op names them by the pick, never by id. */
export const PICKED_KINDS: ReadonlySet<string> = new Set(["other", "flank", "plane", "radial"]);

/** How an op names a face: its id, or the pick on it (`PICKED_KINDS`). */
export function faceRef(f: { id: string; kind: string }, p: { point: number[]; normal: number[] }):
  string | { point: number[]; normal: number[] } {
  return PICKED_KINDS.has(f.kind) ? { point: [...p.point], normal: [...p.normal] } : f.id;
}

/** How far face A (a point and outward normal on it) moves along its normal to sit `gap` metres off face B: the
 * server's align, for the preview before its check. Null when the faces are more than 1° from parallel. */
export function alignDistance(pa: ArrayLike<number>, na: ArrayLike<number>, pb: ArrayLike<number>, nb: ArrayLike<number>,
                              gap = 0): number | null {
  const unit = (v: ArrayLike<number>) => { const l = Math.hypot(v[0], v[1], v[2]) || 1; return [v[0] / l, v[1] / l, v[2] / l]; };
  const a = unit(na), b = unit(nb), cos = a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  if (Math.abs(cos) < Math.cos(Math.PI / 180)) return null;
  return ((pb[0] - pa[0]) * b[0] + (pb[1] - pa[1]) * b[1] + (pb[2] - pa[2]) * b[2]) / cos - gap;
}

/** How far face A moves along its normal so its plane passes through point P, the gap short of it (a corner, an
 * edge's midpoint, a point on an edge as the target). */
export function pointDistance(pa: ArrayLike<number>, na: ArrayLike<number>, p: ArrayLike<number>, gap = 0): number {
  const l = Math.hypot(na[0], na[1], na[2]) || 1;
  const t = ((p[0] - pa[0]) * na[0] + (p[1] - pa[1]) * na[1] + (p[2] - pa[2]) * na[2]) / l;
  return t - gap * (t >= 0 ? 1 : -1);
}

/** The keep button's words for a check: "Keep", or what it is kept with ("Keep with 1 clash · 1 open joint"). */
export function keepLabel(c: { clashes: number; joints?: unknown[] | null }, deleting = false): string {
  const n = c.clashes, j = c.joints?.length ?? 0;
  if (!n && !j) return deleting ? "Delete it" : "Keep";
  const parts = [n ? `${n} clash${n === 1 ? "" : "es"}` : "", j ? `${j} open joint${j === 1 ? "" : "s"}` : ""].filter(Boolean);
  return `Keep with ${parts.join(" · ")}`;
}

/** A check's summary as the edit and then each thing it brings along, one per line ("…; its type FT-BOX too"). */
export function effects(summary: string): { lead: string; rest: string[] } {
  const [lead, ...rest] = summary.split("; ").map((s) => s.trim()).filter(Boolean);
  return { lead: lead ?? "", rest };
}

/** The other elements an edit changes, by why, a few names each and how many more: what to look at before keeping it. */
export function alsoGroups(also: { element: string; name: string; why: string }[], show = 3):
  { why: string; names: string[]; more: number; elements: string[] }[] {
  const by = new Map<string, { element: string; name: string }[]>();
  for (const a of also) by.set(a.why, [...(by.get(a.why) ?? []), a]);
  return [...by].map(([why, list]) => ({ why, names: list.slice(0, show).map((a) => a.name), more: Math.max(0, list.length - show),
    elements: list.map((a) => a.element) }));
}

/** The Edit tool's "Apply to the type" choice in words: which type, and how many other elements it would change. */
export function typeChoice(t: { name: string; others: number } | null | undefined): string {
  if (!t) return "Apply to the type";
  return `Apply to type ${t.name}` + (t.others ? ` · ${t.others} other${t.others === 1 ? "" : "s"}` : "");
}

/** The ways an offset can take a section between two points along a run (IFC axes, Z up): up, down, and the two sides
 * square to the run in plan, named by compass. The run must be level (the server refuses the rest). */
export function offsetWays(from: number[], to: number[]): { label: string; toward: [number, number, number] }[] {
  const dx = to[0] - from[0], dy = to[1] - from[1], l = Math.hypot(dx, dy) || 1;
  const side: [number, number, number] = [-dy / l, dx / l, 0];   // cross(Z, run)
  const compass = (v: number[]) => (Math.abs(v[0]) >= Math.abs(v[1]) ? (v[0] > 0 ? "East" : "West") : (v[1] > 0 ? "North" : "South"));
  const r = (v: number) => Math.round(v * 1e6) / 1e6 || 0;
  return [{ label: "Up", toward: [0, 0, 1] }, { label: "Down", toward: [0, 0, -1] },
    { label: compass(side), toward: [r(side[0]), r(side[1]), 0] }, { label: compass(side.map((c) => -c)), toward: [r(-side[0]), r(-side[1]), 0] }];
}

/** A snapped point as an align target, in words. */
export const SNAP_WORDS: Record<string, string> = { end: "corner", mid: "midpoint of an edge", edge: "edge" };

/** Short words for a tool offered on a face the current tool cannot take ("Align it"). */
export const OFFER: Record<EditToolId, string> = { push_pull: "Push/pull it", align: "Align it", move: "Move it", void: "Cut a void",
  cut_by: "Cut it by a shape", split: "Split it", remove_section: "Remove a section", clip: "Clip it", delete: "Delete it",
  offset: "Offset a section", join: "Join it", disconnect: "Disconnect it" };

export type EditToolId = "push_pull" | "align" | "move" | "void" | "cut_by" | "split" | "remove_section" | "clip" | "delete"
  | "offset" | "join" | "disconnect";

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
  { id: "offset", label: "Offset a section (duct, pipe, tray)", key: "f", needs: "element", hint: "Click where the offset starts, then where it ends" },
  { id: "join", label: "Join two ends (in line, or with a bend)", key: "n", needs: "element", hint: "Click a segment, then the one to join it to" },
  { id: "disconnect", label: "Disconnect a joint", key: "x", needs: "element", hint: "Click an element near the joint to open" },
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
