/**
 * The landing's picture of Northbank's answer key, built from the demo models' own geometry: the Level 02 transfer
 * girder TB-L02-01 (`samples/Northbank-Structure.ifc`), the three services that run into it and their neighbours
 * (`Northbank-MEP.ifc`), read with IfcOpenShell on Nov 4. Every number is in metres, in the models' own frame (x east,
 * y north, z up), as the files have them. The fixes are the recorded ones (README, "See it work"): the duct's middle
 * 1.40 m up 400 mm, the tray up 250 mm, the cold water main up 280 mm, each through its own web opening. Pure data and
 * arithmetic: nothing here draws (heroScene.ts does), so the check in check.ts and the tests can read it.
 */

export type Range = readonly [number, number];
/** A point on a run's centreline in its vertical plane: (distance along the run, height). */
export type P2 = readonly [number, number];

export interface Opening { y: Range; z: Range }

/** Transfer plate girder 1000 deep - grid 3: two 400 x 40 flanges and a 20 mm web with six openings, 12 m long. */
export const GIRDER = {
  name: "Transfer plate girder 1000 deep - grid 3",
  tag: "TB-L02-01",
  x: [3.3, 3.7] as Range,
  y: [-6, 6] as Range,
  z: [6.85, 7.85] as Range,
  flange: 0.04,
  web: { x: [3.49, 3.51] as Range, z: [6.89, 7.81] as Range },
  /** The web's openings (IfcArbitraryProfileDefWithVoids), each as the y and z it spans. */
  openings: [
    { y: [2.25, 2.95], z: [6.98, 7.38] },
    { y: [-2.0, -1.4], z: [7.03, 7.38] },        // the return air main, already through it
    { y: [-2.921, -2.779], z: [7.109, 7.251] },  // the hot water main, already through it
    { y: [-2.8, -2.1], z: [7.38, 7.78] },        // #1: the supply air main's, 700 x 400
    { y: [-1.2, -0.8], z: [7.05, 7.25] },        // #2: the cable tray's
    { y: [-3.13, -2.97], z: [7.10, 7.26] },      // #3: the cold water main's
  ] as Opening[],
  /** Bearing stiffeners either side of the web under column B3. */
  stiffeners: [{ x: [3.3, 3.49] as Range }, { x: [3.51, 3.7] as Range }],
  stiffenerY: [-0.01, 0.01] as Range,
};

/** A cross-section in a run's own frame: u across it (horizontal), v up it (in the run's vertical plane). */
export type Section = readonly P2[];
export const rect = (w: number, h: number): Section => [[-w / 2, -h / 2], [w / 2, -h / 2], [w / 2, h / 2], [-w / 2, h / 2]];
/** A cable tray: an open channel, `t` thick. */
export const channel = (w: number, h: number, t = 0.008): Section => [
  [-w / 2, -h / 2], [w / 2, -h / 2], [w / 2, h / 2], [w / 2 - t, h / 2], [w / 2 - t, -h / 2 + t], [-w / 2 + t, -h / 2 + t],
  [-w / 2 + t, h / 2], [-w / 2, h / 2]];
export const circle = (r: number, n = 18): Section => Array.from({ length: n }, (_, i) => {
  const a = (i / n) * Math.PI * 2;
  return [Math.cos(a) * r, Math.sin(a) * r] as const;
});

/** A raised stretch of a run: risers at `a` and `b` (along the run), `dz` up, bends of radius `r`. */
export interface Offset { a: number; b: number; dz: number; r: number }

/** A straight horizontal run (a duct, tray or pipe) along x at a fixed y, as the services here all are. */
export interface Run {
  key: "duct" | "tray" | "cw";
  name: string;
  short: string;
  number: number;
  y: number;
  z: number;              // centreline height
  x: Range;               // the run as drawn (the models' runs are longer; the ends fade out)
  section: Section;
  smooth?: boolean;       // round: smooth normals
  fix: Offset;            // the recorded fix
  split: Range;           // where the fixed stretch is cut from the run for the swap (outside the bends)
  overlap: number;        // the clash list's depth, m (negative: overlapping)
  clear: number;          // the fix's clearance, m
  checked: number;        // elements the fix was checked against
}

/** The three answer-key clashes and their recorded fixes. */
export const RUNS: Run[] = [
  { key: "duct", number: 1, name: "Supply air main L02 600x300", short: "Supply air main", y: -2.45, z: 7.18, x: [-1.4, 7.8],
    section: rect(0.6, 0.3), fix: { a: 2.8, b: 4.2, dz: 0.4, r: 0.18 }, split: [2.45, 4.55], overlap: -0.3, clear: 0.05, checked: 21 },
  { key: "tray", number: 2, name: "Cable tray L02 300x100", short: "Cable tray", y: -1.0, z: 6.9, x: [-2.4, 9.4],
    section: channel(0.3, 0.1), fix: { a: 2.75, b: 4.25, dz: 0.25, r: 0.1 }, split: [2.5, 4.5], overlap: -0.1, clear: 0.05, checked: 5 },
  { key: "cw", number: 3, name: "Cold water main L02 DN54", short: "Cold water main", y: -3.05, z: 6.9, x: [-2.4, 9.9],
    section: circle(0.027), smooth: true, fix: { a: 2.75, b: 4.25, dz: 0.28, r: 0.06 }, split: [2.55, 4.45], overlap: -0.077, clear: 0.053, checked: 15 },
];

/** The return air spigots (D250) that leave the return main north over the tray, then drop to their grilles: along
 * y from -1.45 to -0.56 at z 7.205, then down to 6.95. A whole-run move of the tray up 250 mm runs into all three
 * (its z 7.10 to 7.20 inside theirs, 7.08 to 7.33): moving a long run whole fails on what lies along it (CLAUDE.md,
 * Oct 27). */
export const SPIGOT_X = [2.2, 5.0, 7.0];
export const SPIGOT = { r: 0.125, y: [-1.45, -0.5625] as Range, z: 7.205, drop: [6.95, 7.205] as Range };

/** Neighbours drawn for context: boxes (min, max) and runs that already pass the girder through their own openings. */
export interface ContextBox { name: string; min: readonly [number, number, number]; max: readonly [number, number, number]; kind: "structure" | "services" | "ceiling" | "slab" }
export const CONTEXT_BOXES: ContextBox[] = [
  { name: "Composite floor slab 150 - Level 03", kind: "slab", min: [-2.6, -5.4, 7.85], max: [9.6, 1.6, 8.0] },
  // UB 356x171x45 secondary beams framing into the girder at y -3 (flanges and web), and UB 457 on grid B at y 0
  ...iBeam("UB 356x171x45 - secondary", -3.0, [7.499, 7.85], 0.171, 0.0097, 0.007),
  ...iBeam("UB 457x191x67 - grid B", 0.0, [7.393, 7.85], 0.19, 0.0127, 0.0085),
  // supply air main tees and the branches to the diffusers
  { name: "Supply air main L02 tee", kind: "services", min: [1.4, -2.8, 7.03], max: [1.8, -2.15, 7.33] },
  { name: "Supply air main L02 tee", kind: "services", min: [5.4, -2.8, 7.03], max: [5.8, -2.15, 7.33] },
  { name: "Supply branch L02 300x200", kind: "services", min: [1.45, -4.1, 7.08], max: [1.75, -2.8, 7.28] },
  { name: "Supply branch L02 300x200", kind: "services", min: [5.45, -4.1, 7.08], max: [5.75, -2.8, 7.28] },
  { name: "Supply branch L02 bend", kind: "services", min: [1.45, -4.4, 6.95], max: [1.75, -4.1, 7.28] },
  { name: "Supply branch L02 bend", kind: "services", min: [5.45, -4.4, 6.95], max: [5.75, -4.1, 7.28] },
  { name: "Supply diffuser 600x600", kind: "services", min: [1.303, -4.598, 6.7], max: [1.898, -4.002, 6.95] },
  { name: "Supply diffuser 600x600", kind: "services", min: [5.302, -4.598, 6.7], max: [5.898, -4.002, 6.95] },
  // the return grilles at the end of the spigots (SPIGOTS)
  ...SPIGOT_X.map((x) => ({ name: "Return grille 600x600", kind: "services" as const, min: [x - 0.298, -0.798, 6.7] as const, max: [x + 0.298, -0.202, 6.95] as const })),
  // the suspended ceiling's light panels
  ...[0, 1.8, 3.6, 5.4, 7.2].flatMap((x) => [-3.1, -1.3, 0.9].map((y) => ({
    name: "LED recessed panel 600x600", kind: "ceiling" as const, min: [x - 0.298, y - 0.298, 6.7] as const, max: [x + 0.298, y + 0.298, 6.78] as const }))),
];

/** Runs drawn for context: the return air main through opening 2, the hot water main through opening 3 with the
 * designer's own offset (the shape the fixes take). */
export const CONTEXT_RUNS: { name: string; y: number; z: number; x: Range; section: Section; smooth?: boolean; offset?: Offset }[] = [
  { name: "Return air main L02 500x250", y: -1.7, z: 7.205, x: [-1.2, 8.6], section: rect(0.5, 0.25) },
  { name: "Hot water main L02 DN42", y: -2.85, z: 6.9, x: [-2.4, 9.9], section: circle(0.021), smooth: true,
    offset: { a: 2.7, b: 4.3, dz: 0.28, r: 0.042 } },
];

function iBeam(name: string, y: number, z: Range, b: number, tf: number, tw: number): ContextBox[] {
  const spans: Range[] = [[-2.6, GIRDER.x[0]], [GIRDER.x[1], 9.6]];
  return spans.flatMap(([x0, x1]) => [
    { name, kind: "structure" as const, min: [x0, y - b / 2, z[1] - tf] as const, max: [x1, y + b / 2, z[1]] as const },
    { name, kind: "structure" as const, min: [x0, y - b / 2, z[0]] as const, max: [x1, y + b / 2, z[0] + tf] as const },
    { name, kind: "structure" as const, min: [x0, y - tw / 2, z[0] + tf] as const, max: [x1, y + tw / 2, z[1] - tf] as const },
  ]);
}

/**
 * A run's centreline from x0 to x1 at height z, with raised stretches: straight, a bend up at `a`, a short riser, a
 * bend over, the raised stretch, and the same down at `b`. Each bend is a quarter circle of radius r in `steps` pieces.
 */
export function offsetPath(x0: number, x1: number, z: number, offsets: Offset[] = [], steps = 6): P2[] {
  const out: P2[] = [[x0, z]];
  let radius = 0;
  const arc = (cx: number, cz: number, from: number, to: number) => {
    const r = radius;
    for (let i = 1; i <= steps; i++) {
      const t = from + ((to - from) * i) / steps;
      out.push([cx + Math.cos(t) * r, cz + Math.sin(t) * r]);
    }
  };
  const H = Math.PI / 2;
  for (const o of [...offsets].sort((p, q) => p.a - q.a)) {
    const { a, b, dz, r } = o, top = z + dz, up = dz > 0 ? 1 : -1, rr = Math.min(r, Math.abs(dz) / 2);
    // Each bend's centre and its start and end angles, for a stretch taken up (or down): into the riser at a, out of it
    // onto the raised stretch, into the riser at b, and back onto the run.
    const bends: [number, number, number, number][] = up > 0
      ? [[a - rr, z + rr, -H, 0], [a + rr, top - rr, Math.PI, H], [b - rr, top - rr, H, 0], [b + rr, z + rr, Math.PI, 3 * H]]
      : [[a - rr, z - rr, H, 0], [a + rr, top + rr, Math.PI, 3 * H], [b - rr, top + rr, -H, 0], [b + rr, z - rr, Math.PI, H]];
    const riser = Math.abs(dz) > 2 * rr + 1e-9;
    radius = rr;
    out.push([a - rr, z]);
    arc(...bends[0]);
    if (riser) out.push([a, top - up * rr]);
    arc(...bends[1]);
    out.push([b - rr, top]);
    arc(...bends[2]);
    if (riser) out.push([b, z + up * rr]);
    arc(...bends[3]);
  }
  out.push([x1, z]);
  return dedupe(out);
}

function dedupe(points: P2[]): P2[] {
  return points.filter((p, i) => i === 0 || Math.hypot(p[0] - points[i - 1][0], p[1] - points[i - 1][1]) > 1e-6);
}

/** The part of a path between two distances along the run. A run's x never goes back (risers are vertical), and the
 * cuts fall on level stretches, outside the bends. */
export function cutPath(path: P2[], from: number, to: number): P2[] {
  const out: P2[] = [];
  const at = (p: P2, q: P2, x: number): P2 => [x, p[1] + ((q[1] - p[1]) * (x - p[0])) / (q[0] - p[0] || 1)];
  for (let i = 0; i < path.length - 1; i++) {
    const p = path[i], q = path[i + 1];
    if (q[0] < from || p[0] > to) continue;
    if (!out.length) out.push(p[0] < from ? at(p, q, from) : p);
    if (q[0] > to) { out.push(at(p, q, to)); break; }
    out.push(q);
  }
  return dedupe(out);
}

/** A swept solid: triangles in the models' frame, with a normal per vertex and the height of the centreline each
 * vertex was swept from (to grow a raised stretch out of the run it replaces). */
export interface Swept { positions: Float32Array; normals: Float32Array; heights: Float32Array }

/**
 * Sweeps a cross-section along a run's centreline (in the vertical plane through `y`, running along +x), with mitred
 * joints at every vertex, so a raised stretch's bends close exactly. Section points are (u, v): u along +y, v along
 * the centreline's upward normal; a counter-clockwise section gives outward faces. Convex sections are capped.
 */
export function sweep(path: P2[], y: number, section: Section, smooth = false, caps = true): Swept {
  const n = path.length, m = section.length;
  const tan = (i: number): P2 => {
    const p = path[Math.max(0, i - 1)], q = path[Math.min(n - 1, i === 0 ? 1 : i)];
    const d = Math.hypot(q[0] - p[0], q[1] - p[1]) || 1;
    return [(q[0] - p[0]) / d, (q[1] - p[1]) / d];
  };
  // the mitre at each vertex: the bisector of the normals in and out, stretched so the section keeps its depth
  const rings: { x: number; z: number; nx: number; nz: number; s: number }[] = path.map((p, i) => {
    const tin = tan(i), tout = i < n - 1 ? tan(i + 1) : tin;
    const nin: P2 = [-tin[1], tin[0]], nout: P2 = [-tout[1], tout[0]];
    let nx = nin[0] + nout[0], nz = nin[1] + nout[1];
    const len = Math.hypot(nx, nz) || 1;
    nx /= len; nz /= len;
    const s = 1 / Math.max(0.2, nx * nin[0] + nz * nin[1]);
    return { x: p[0], z: p[1], nx, nz, s };
  });
  const corner = (i: number, k: number): [number, number, number] => {
    const r = rings[i], [u, v] = section[k];
    return [r.x + r.nx * v * r.s, y + u, r.z + r.nz * v * r.s];
  };
  const pos: number[] = [], nor: number[] = [], hts: number[] = [];
  /** One vertex: swept from ring i, at point p, facing q. */
  const push = (i: number, p: number[], q: number[]) => { pos.push(...p); nor.push(...q); hts.push(rings[i].z); };
  const radial = (i: number, k: number): number[] => {
    const r = rings[i], [u, v] = section[k], l = Math.hypot(u, v) || 1;
    return [r.nx * v / l, u / l, r.nz * v / l];
  };
  for (let i = 0; i < n - 1; i++) {
    for (let k = 0; k < m; k++) {
      const k1 = (k + 1) % m, j = i + 1;
      const A = corner(i, k), B = corner(i, k1), C = corner(j, k1), D = corner(j, k);
      // two triangles, A B D and B C D; a round section faces each vertex out from the centreline, a flat one per face
      // (a bend whose inner radius is nil folds a side to a point: its empty triangles are left out)
      if (area(A, B, D) > 1e-12) {
        const f = smooth ? null : faceNormal(A, B, D);
        push(i, A, f ?? radial(i, k)); push(i, B, f ?? radial(i, k1)); push(j, D, f ?? radial(j, k));
      }
      if (area(B, C, D) > 1e-12) {
        const f = smooth ? null : faceNormal(B, C, D);
        push(i, B, f ?? radial(i, k1)); push(j, C, f ?? radial(j, k1)); push(j, D, f ?? radial(j, k));
      }
    }
  }
  if (caps && convex(section)) {
    for (const [i, sign] of [[0, -1], [n - 1, 1]] as const) {
      const t = tan(i === 0 ? 0 : n - 1), f = [t[0] * sign, 0, t[1] * sign];
      for (let k = 1; k < m - 1; k++) {
        const tri = sign > 0 ? [corner(i, 0), corner(i, k), corner(i, k + 1)] : [corner(i, 0), corner(i, k + 1), corner(i, k)];
        for (const c of tri) push(i, c, f);
      }
    }
  }
  return { positions: new Float32Array(pos), normals: new Float32Array(nor), heights: new Float32Array(hts) };
}

function area(a: number[], b: number[], d: number[]): number {
  const u = [b[0] - a[0], b[1] - a[1], b[2] - a[2]], v = [d[0] - a[0], d[1] - a[1], d[2] - a[2]];
  return Math.hypot(u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]) / 2;
}

function faceNormal(a: number[], b: number[], d: number[]): number[] {
  const u = [b[0] - a[0], b[1] - a[1], b[2] - a[2]], v = [d[0] - a[0], d[1] - a[1], d[2] - a[2]];
  const c = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
  const l = Math.hypot(c[0], c[1], c[2]) || 1;
  return [c[0] / l, c[1] / l, c[2] / l];
}

function convex(section: Section): boolean {
  let sign = 0;
  for (let i = 0; i < section.length; i++) {
    const a = section[i], b = section[(i + 1) % section.length], c = section[(i + 2) % section.length];
    const cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]);
    if (Math.abs(cross) < 1e-12) continue;
    if (sign && Math.sign(cross) !== sign) return false;
    sign = Math.sign(cross);
  }
  return true;
}
