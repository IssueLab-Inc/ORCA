// The viewer's views beside the 3D one (docs/views.md): plans, sections and elevations, and the pure rules they
// follow: where each pane sits, what a plan's view range is, where a clash puts each view, the nearest drawing scale,
// what the view cube's regions mean and the camera's history. No WebGL here, so it is tested on its own.
import * as THREE from "three";

/** Side by side, one view, or four (owner, Oct 29). */
export type Layout = "single" | "two" | "quad";
export type Compass = "north" | "south" | "east" | "west";

/** A level as the server reads it (IfcBuildingStorey): world metres, IFC Z up. */
export interface Level { name: string; elevation_m: number; height_m: number | null }
/** One grid axis, IFC axes (metres, Z up). */
export interface GridAxis { tag: string; grid: string; start: number[]; end: number[] }
export interface Datums { levels: Level[]; grids: GridAxis[]; storeys: Record<string, string>; sources: { grids: string | null } }

/** A plan's view range: both planes are offsets from its level (metres), so they follow the level. */
export interface PlanSpec { kind: "plan"; level: number; cut: number; bottom: number | null }
/** A section: a vertical plane through `origin` (IFC x, y) along `angle` (radians, IFC plan), looking to its left
 * (or right, flipped); far clip behind the line and a crop, both optional (metres). */
export interface SectionSpec {
  kind: "section"; origin: [number, number]; angle: number; flip: boolean; far: number | null;
  crop: { left: number; right: number; bottom: number; top: number } | null;
}
/** An elevation shows a façade: "south" looks from the south, northwards. */
export interface ElevationSpec { kind: "elevation"; facing: Compass; far: number | null }
export type ViewSpec = { kind: "3d" } | PlanSpec | SectionSpec | ElevationSpec;
export type DrawingSpec = PlanSpec | SectionSpec | ElevationSpec;

export interface Rect { x: number; y: number; w: number; h: number }

/** The panes of a layout inside a stage `w` × `h` (CSS pixels, top-left origin), split at `split` (shares). */
export function paneRects(layout: Layout, w: number, h: number, split = { x: 0.5, y: 0.5 }): Rect[] {
  const sx = Math.round(w * clamp(split.x, 0.2, 0.8)), sy = Math.round(h * clamp(split.y, 0.2, 0.8));
  if (layout === "single") return [{ x: 0, y: 0, w, h }];
  if (layout === "two") return [{ x: 0, y: 0, w: sx, h }, { x: sx, y: 0, w: w - sx, h }];
  return [{ x: 0, y: 0, w: sx, h: sy }, { x: sx, y: 0, w: w - sx, h: sy },
    { x: 0, y: sy, w: sx, h: h - sy }, { x: sx, y: sy, w: w - sx, h: h - sy }];
}

/** What each pane shows when a layout is first picked: plan beside 3D, then a section and an elevation below. */
export function defaultKinds(layout: Layout): ViewSpec["kind"][] {
  return layout === "single" ? ["3d"] : layout === "two" ? ["plan", "3d"] : ["plan", "3d", "section", "elevation"];
}

export const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi);

// ---------------------------------------------------------------- plan view range

/** Least gap between a plan's cut and its bottom, metres. */
export const MIN_RANGE = 0.01;

/** The plan's cut and bottom as world heights (IFC z), the cut kept above the bottom. `levels` must be sorted. */
export function planRange(levels: Level[], spec: PlanSpec): { level: Level; cutZ: number; bottomZ: number | null } {
  const level = levels[clamp(spec.level, 0, levels.length - 1)];
  const bottomZ = spec.bottom == null ? null : level.elevation_m + spec.bottom;
  const cutZ = level.elevation_m + spec.cut;
  return { level, cutZ: bottomZ == null ? cutZ : Math.max(cutZ, bottomZ + MIN_RANGE), bottomZ };
}

/** The next level above level `i`: one at the same height (another file's name for the same floor) is not above it. */
export function nextAbove(levels: Level[], i: number): Level | null {
  const z = levels[i]?.elevation_m ?? 0;
  return levels.slice(i + 1).find((l) => l.elevation_m > z + 1e-6) ?? null;
}

/** The storey's height: to the next level up, or what the server says, else 4 m. */
export function storeyHeight(levels: Level[], i: number): number {
  const next = nextAbove(levels, i);
  return next ? next.elevation_m - levels[i].elevation_m : levels[i].height_m ?? 4;
}

export type PlanPreset = "floor" | "ceiling" | "storey";
/** The plan presets (docs/views.md, "Plan: view range"): Floor plan, Ceiling void (beams and services, no floor),
 * Whole storey. Null when the preset needs a next level and there is none. */
export function planPreset(levels: Level[], i: number, preset: PlanPreset): { cut: number; bottom: number | null } | null {
  const h = storeyHeight(levels, i), hasNext = !!nextAbove(levels, i);
  if (preset === "floor") return { cut: Math.min(1.2, h - 0.05), bottom: 0 };
  if (!hasNext) return null;
  const underNext = h - 0.05;
  if (preset === "ceiling") return { cut: underNext, bottom: Math.min(2.4, underNext - MIN_RANGE) };
  return { cut: underNext, bottom: 0 };
}

/** The level a height stands in: the highest at or below it, else the lowest. */
export function levelAt(levels: Level[], z: number): number {
  let best = 0;
  levels.forEach((l, i) => { if (l.elevation_m <= z + 1e-6) best = i; });
  return best;
}

/** A plan through a point (the clash default): its level, and the cut through the point, kept between 0.3 m and the
 * storey height less 50 mm. The bottom stays as the user set it. */
export function planThrough(levels: Level[], z: number, spec: PlanSpec): PlanSpec {
  const level = levelAt(levels, z);
  const h = storeyHeight(levels, level);
  const cut = clamp(z - levels[level].elevation_m, 0.3, Math.max(0.3, h - 0.05));
  const bottom = spec.bottom == null ? null : Math.min(spec.bottom, cut - MIN_RANGE);
  return { ...spec, level, cut, bottom };
}

/** Levels for a model with none (a machine cell): one, at the bottom of the model, as tall as the model. */
export function levelsOrModel(levels: Level[], zMin: number, zMax: number): Level[] {
  if (levels.length) return [...levels].sort((p, q) => p.elevation_m - q.elevation_m);
  return [{ name: "Model", elevation_m: zMin, height_m: Math.max(zMax - zMin, 1e-3) }];
}

// ---------------------------------------------------------------- sections and elevations (IFC plan axes)

/** IFC (x, y, z) → three.js (x, z, −y). */
export const toThree = (x: number, y: number, z: number) => new THREE.Vector3(x, z, -y);

/** A section's frame in IFC plan axes: `along` the line (screen right), `look` the way it looks (into the drawing). */
export function sectionFrame(spec: Pick<SectionSpec, "angle" | "flip">) {
  const u = [Math.cos(spec.angle), Math.sin(spec.angle)];
  let look = [-u[1], u[0]];          // the line's left: looking that way, the line runs left to right
  let along = u;
  if (spec.flip) { look = [-look[0], -look[1]]; along = [-u[0], -u[1]]; }
  return { along: along as [number, number], look: look as [number, number] };
}

/** Where an elevation looks from and to: "south" stands south and looks north. */
export function facingLook(facing: Compass): [number, number] {
  return facing === "south" ? [0, 1] : facing === "north" ? [0, -1] : facing === "west" ? [1, 0] : [-1, 0];
}

/** The elevation that looks the same way as a direction in plan (the one that faces a section's look). */
export function facingFor(look: [number, number]): Compass {
  const [x, y] = look;
  if (Math.abs(y) >= Math.abs(x)) return y >= 0 ? "south" : "north";
  return x >= 0 ? "west" : "east";
}

export const COMPASS_NAME: Record<Compass, string> = { north: "North", south: "South", east: "East", west: "West" };

/** A view's name, as its title block and header read it ("Level 01 · Plan"). */
export function viewTitle(levels: Level[], spec: ViewSpec): string {
  if (spec.kind === "3d") return "3D";
  if (spec.kind === "plan") return `${levels[spec.level]?.name ?? "Model"} · Plan`;
  if (spec.kind === "section") return "Section A–A";
  return `${COMPASS_NAME[spec.facing]} elevation`;
}

/** A section through a clash, along the run that moves: the longer horizontal side of its box (IFC metres). */
export function sectionThrough(point: [number, number, number], runBox: { min: number[]; max: number[] } | null,
  spec: SectionSpec, margin = 2): SectionSpec {
  let angle = spec.angle;
  if (runBox) {
    const dx = runBox.max[0] - runBox.min[0], dy = runBox.max[1] - runBox.min[1];
    angle = dx >= dy ? 0 : Math.PI / 2;
  }
  const half = runBox ? Math.max(runBox.max[0] - runBox.min[0], runBox.max[1] - runBox.min[1]) / 2 : 4;
  const crop = spec.crop ? { ...spec.crop, left: Math.min(half, 6) + margin, right: Math.min(half, 6) + margin } : null;
  return { ...spec, origin: [point[0], point[1]], angle, crop };
}

/** Does a grid axis show in a section or elevation looking along `look`? Only one running within 25° of it. */
export function gridShows(axis: GridAxis, look: [number, number]): boolean {
  const dx = axis.end[0] - axis.start[0], dy = axis.end[1] - axis.start[1];
  const len = Math.hypot(dx, dy);
  if (len < 1e-9) return false;
  return Math.abs((dx * look[0] + dy * look[1]) / len) >= Math.cos(THREE.MathUtils.degToRad(25));
}

// ---------------------------------------------------------------- scale

const STANDARD = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000];
/** The nearest standard drawing scale for `metresPerPixel` on a 96 dpi screen ("1:100"). */
export function nearestScale(metresPerPixel: number): number {
  const ratio = metresPerPixel / (0.0254 / 96);
  return STANDARD.reduce((best, s) => (Math.abs(Math.log(s / ratio)) < Math.abs(Math.log(best / ratio)) ? s : best), STANDARD[0]);
}

/** A scale bar about `px` pixels long: a round length in metres (1, 2 or 5 × 10ⁿ) and its pixels. */
export function scaleBar(metresPerPixel: number, px = 100): { metres: number; pixels: number } {
  const want = metresPerPixel * px;
  const p = Math.pow(10, Math.floor(Math.log10(want)));
  const metres = [1, 2, 5, 10].map((k) => k * p).reduce((b, m) => (Math.abs(m - want) < Math.abs(b - want) ? m : b));
  return { metres, pixels: metres / metresPerPixel };
}

/** Metres to the millimetre with a sign: +1.200. */
export const level3 = (m: number) => `${m >= 0 ? "+" : "−"}${Math.abs(m).toFixed(3)}`;

// ---------------------------------------------------------------- view cube

/** A point on the view cube's surface (−1..1 per axis, three.js axes) → the direction to look from: a face, an edge
 * or a corner (26 in all). */
export function cubeRegion(p: THREE.Vector3, edge = 0.55): THREE.Vector3 {
  const s = (v: number) => (Math.abs(v) >= edge ? Math.sign(v) : 0);
  const d = new THREE.Vector3(s(p.x), s(p.y), s(p.z));
  if (!d.lengthSq()) {    // the middle of a face: its axis
    const a = Math.max(Math.abs(p.x), Math.abs(p.y), Math.abs(p.z));
    d.set(Math.abs(p.x) === a ? Math.sign(p.x) : 0, Math.abs(p.y) === a ? Math.sign(p.y) : 0, Math.abs(p.z) === a ? Math.sign(p.z) : 0);
  }
  return d;
}

/** The name of a view cube direction: Top, Front, Front Right, Top Front Right… (Front looks north, from the south.) */
export function cubeName(d: THREE.Vector3): string {
  const parts = [d.y > 0 ? "Top" : d.y < 0 ? "Bottom" : "", d.z > 0 ? "Front" : d.z < 0 ? "Back" : "",
    d.x > 0 ? "Right" : d.x < 0 ? "Left" : ""].filter(Boolean);
  return parts.join(" ");
}

// ---------------------------------------------------------------- camera history

export interface Pose { position: [number, number, number]; target: [number, number, number] }

/** Back and forward through camera jumps. A jump pushes where the camera was; going back pushes where it is. */
export class CameraHistory {
  private back: Pose[] = [];
  private ahead: Pose[] = [];
  constructor(private max = 50) {}
  /** Before a jump: remember where the camera is (not if it is where the last entry already is). */
  push(p: Pose) {
    const last = this.back[this.back.length - 1];
    if (last && near(last, p)) return;
    this.back.push(p);
    if (this.back.length > this.max) this.back.shift();
    this.ahead = [];
  }
  goBack(now: Pose): Pose | null {
    const p = this.back.pop();
    if (!p) return null;
    this.ahead.push(now);
    return p;
  }
  goForward(now: Pose): Pose | null {
    const p = this.ahead.pop();
    if (!p) return null;
    this.back.push(now);
    return p;
  }
  get canBack() { return this.back.length > 0; }
  get canForward() { return this.ahead.length > 0; }
  clear() { this.back = []; this.ahead = []; }
}
const near = (a: Pose, b: Pose) => a.position.every((v, i) => Math.abs(v - b.position[i]) < 1e-3)
  && a.target.every((v, i) => Math.abs(v - b.target[i]) < 1e-3);

// ---------------------------------------------------------------- visibility

/** Visibility filters (docs/views.md, "Visibility"): hidden classes and levels, and for now hidden or isolated
 * elements. Viewing only: the check, triage and fixes never see them. */
export interface Filters { classes: string[]; levels: string[] }
/** What the drawing views show (docs/filters.md, "Drawings"): what the filters and hides leave (the default; the mode
 * round the focus is the 3D view's), exactly what the 3D view shows, or the whole model (only hidden models stay
 * hidden; no filter colours). */
export type DrawingsShow = "filtered" | "follow" | "whole";
export interface Temporary { hidden: string[]; isolated: string[] | null }

/** Is an element shown by the filters and the temporary hide / isolate? (The model's own visibility and "round the
 * focus" come after; the pair, previews and trials always show.) */
export function shownBy(gid: string, cls: string | undefined, level: string | undefined, f: Filters, t: Temporary,
  hiddenClasses = new Set(f.classes), hiddenLevels = new Set(f.levels), hidden = new Set(t.hidden),
  isolated = t.isolated ? new Set(t.isolated) : null): boolean {
  if (hidden.has(gid)) return false;
  if (isolated && !isolated.has(gid)) return false;
  if (cls && hiddenClasses.has(cls)) return false;
  if (level && hiddenLevels.has(level)) return false;
  return true;
}

/** What Esc clears, one thing at a time (docs/views.md): the measure, the image dialog, the selected element (and its
 * card), then the clash. Null when nothing is left, or the clash can't be left while ORCA works on it. */
export type EscStep = "measure" | "lightbox" | "selection" | "clash";
export function escStep(s: { measuring: boolean; lightbox: boolean; selection: boolean; clash: boolean; working: boolean }): EscStep | null {
  if (s.measuring) return "measure";
  if (s.lightbox) return "lightbox";
  if (s.selection) return "selection";
  if (s.clash && !s.working) return "clash";
  return null;
}
