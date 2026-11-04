import { GIRDER, RUNS, type Range } from "./northbank";

/**
 * The landing's "try the check yourself": Northbank #1 seen along the duct, at the girder. Raise the duct's middle
 * stretch and this says what ORCA's check would: is the clash gone, how much room is left, is anything new hit. It is
 * the check cut down to the one plane that decides it (every solid along the stretch the duct's offset spans, x 2.65
 * to 4.35, seen end on), with the models' own numbers: exact for this case, where the move is straight up. ORCA's real
 * check (server: verify.check) measures the whole edited model in 3D. At +400 mm it gives the recorded answer: 50 mm
 * all round, in the girder's web opening.
 */

/** A solid in that plane: y across (north), z up, metres. `girder` marks the clash's other element. */
export interface Solid { name: string; girder: boolean; y: Range; z: Range }

const DUCT = RUNS[0];
/** The duct's section as modelled: 600 wide, 300 high, centred at y -2.45, z 7.18. */
export const DUCT_AT: { y: Range; z: Range } = { y: [DUCT.y - 0.3, DUCT.y + 0.3], z: [DUCT.z - 0.15, DUCT.z + 0.15] };
/** The part of the plane the check looks at (and the picture shows). */
export const PLANE: { y: Range; z: Range } = { y: [-3.6, -1.15], z: [6.6, 8.05] };

/** The girder's web, cut into solid rectangles around its openings; then its flanges. */
function girderSolids(): Solid[] {
  const [y0, y1] = PLANE.y, web = GIRDER.web.z, name = "Transfer plate girder";
  const holes = GIRDER.openings.filter((o) => o.y[1] > y0 && o.y[0] < y1);
  const cuts = [...new Set([y0, y1, ...holes.flatMap((o) => o.y).filter((y) => y > y0 && y < y1)])].sort((a, b) => a - b);
  const out: Solid[] = [];
  for (let i = 0; i < cuts.length - 1; i++) {
    const a = cuts[i], b = cuts[i + 1], mid = (a + b) / 2;
    const gaps = holes.filter((o) => o.y[0] <= mid && o.y[1] >= mid).map((o) => o.z).sort((p, q) => p[0] - q[0]);
    let z = web[0];
    for (const g of gaps) {
      if (g[0] > z) out.push({ name, girder: true, y: [a, b], z: [z, g[0]] });
      z = Math.max(z, g[1]);
    }
    if (z < web[1]) out.push({ name, girder: true, y: [a, b], z: [z, web[1]] });
  }
  const f = GIRDER.flange;
  out.push({ name, girder: true, y: PLANE.y, z: [GIRDER.z[0], GIRDER.z[0] + f] });
  out.push({ name, girder: true, y: PLANE.y, z: [GIRDER.z[1] - f, GIRDER.z[1]] });
  return out;
}

/** Everything else along the stretch, as the models have it there. */
const OTHERS: Solid[] = [
  { name: "Level 03 floor slab", girder: false, y: PLANE.y, z: [7.85, 8.0] },
  { name: "Suspended ceiling", girder: false, y: PLANE.y, z: [6.7, 6.72] },
  { name: "LED ceiling panel", girder: false, y: [-3.398, -2.802], z: [6.7, 6.78] },
  { name: "LED ceiling panel", girder: false, y: [-1.598, -1.15], z: [6.7, 6.78] },
  { name: "Secondary beam UB 356", girder: false, y: [-3.0855, -2.9145], z: [7.499, 7.85] },
  { name: "Hot water main", girder: false, y: [-2.871, -2.829], z: [6.879, 7.201] },
  { name: "Cold water main", girder: false, y: [-3.077, -3.023], z: [6.873, 6.927] },
  { name: "Return air main", girder: false, y: [-1.95, -1.45], z: [7.08, 7.33] },
];

export const SOLIDS: Solid[] = [...girderSolids(), ...OTHERS];

export interface Check {
  raise: number;
  duct: { y: Range; z: Range };
  /** What the duct runs into, each with how deep (the overlap's smaller side, m). */
  hits: { name: string; girder: boolean; depth: number }[];
  /** The clash is gone: the duct no longer runs into the girder. */
  clashGone: boolean;
  /** Anything else it now runs into, by name. */
  newHits: string[];
  /** The deepest overlap, m (0 when it hits nothing). */
  overlap: number;
  /** The nearest gap when it hits nothing, m, and to what. */
  clearance: number | null;
  nearest: string | null;
  needed: number;
  /** Clash gone, nothing new hit, and at least the clearance needed. */
  verified: boolean;
}

const EPS = 1e-6;

/** The duct's middle stretch raised by `raise` metres (negative: lowered), checked with `needed` metres of room. */
export function checkRaise(raise: number, needed = 0.025): Check {
  const duct = { y: DUCT_AT.y, z: [DUCT_AT.z[0] + raise, DUCT_AT.z[1] + raise] as Range };
  const hits: Check["hits"] = [];
  let clearance: number | null = null, nearest: string | null = null;
  for (const s of SOLIDS) {
    const oy = Math.min(duct.y[1], s.y[1]) - Math.max(duct.y[0], s.y[0]);
    const oz = Math.min(duct.z[1], s.z[1]) - Math.max(duct.z[0], s.z[0]);
    if (oy > EPS && oz > EPS) {
      const depth = Math.min(oy, oz), had = hits.find((h) => h.name === s.name);
      if (had) had.depth = Math.max(had.depth, depth);
      else hits.push({ name: s.name, girder: s.girder, depth });
      continue;
    }
    const d = Math.hypot(Math.max(0, -oy), Math.max(0, -oz));
    if (clearance == null || d < clearance - EPS) { clearance = d; nearest = s.name; }
  }
  const clashGone = !hits.some((h) => h.girder);
  const newHits = hits.filter((h) => !h.girder).map((h) => h.name);
  const overlap = hits.reduce((m, h) => Math.max(m, h.depth), 0);
  const free = !hits.length;
  return {
    raise, duct, hits, clashGone, newHits, overlap,
    clearance: free ? clearance : null, nearest: free ? nearest : null, needed,
    verified: free && clearance != null && clearance >= needed - EPS,
  };
}

/** The raises that pass with `needed` of room, in `step` increments over [lo, hi] (the bands the slider lights). */
export function passingBands(needed = 0.025, lo = -0.3, hi = 0.9, step = 0.005): Range[] {
  const out: [number, number][] = [];
  for (let i = 0; lo + i * step <= hi + EPS; i++) {
    const r = Math.round((lo + i * step) * 1000) / 1000;
    if (!checkRaise(r, needed).verified) continue;
    const last = out[out.length - 1];
    if (last && Math.abs(last[1] + step - r) < EPS) last[1] = r;
    else out.push([r, r]);
  }
  return out;
}

/** Millimetres as people read them: "+400 mm", "-300 mm", "50 mm". */
export const mm = (m: number, signed = false) => {
  const v = Math.round(m * 1000) || 0;
  return `${signed && v > 0 ? "+" : ""}${v.toLocaleString("en-GB")} mm`;
};
