// A drawing's annotation layer (docs/views.md, "Annotations"): a 2D canvas over its pane with what a drawing carries
// besides the model: grids with bubbles, levels with heads, the clash in a revision cloud, the other views' marks (a
// section's line and depth in plan, a plan's cut and bottom in a section or elevation, elevation markers, the 3D
// camera), the title, scale bar and north arrow. It also says where the marks a user can drag are (`Handle`).
import * as THREE from "three";
import type { DrawingView } from "./drawing";
import { COMPASS_NAME, facingLook, gridShows, level3, nearestScale, planRange, scaleBar, sectionFrame, toThree, type DrawingSpec,
  type GridAxis, type Level, type Rect } from "./views";

const INK = "#1d2530", GRID = "#2f6aa3", CLOUD = "#d0342c", MUTED = "#5d6a7a", MARK = "#7a3db8";

/** Something on a drawing a user can drag: a section's line, end, far clip or crop side; a plan's cut or bottom; a
 * crop's top or bottom. `pane` is the pane whose view it changes; the points are pane pixels. */
export interface Handle {
  kind: "section-line" | "section-end" | "section-far" | "section-side" | "plan-cut" | "plan-bottom" | "crop-top" | "crop-bottom";
  pane: number; a: THREE.Vector2; b: THREE.Vector2; end?: "left" | "right";
}

export interface AnnotateInput {
  view: DrawingView; rect: Rect; index: number; title: string;
  /** Room kept free at the left (the viewer's tool rail over a pane at the stage's left edge). */
  left: number;
  levels: Level[]; grids: GridAxis[]; model: THREE.Box3;
  clash: { zone: THREE.Box3; label: string } | null;
  others: { index: number; spec: DrawingSpec; title: string }[];
  camera3d: { position: THREE.Vector3; target: THREE.Vector3; fov: number } | null;
}

/** Draw a drawing's annotations; returns what can be dragged on it. */
export function annotate(g: CanvasRenderingContext2D, dpr: number, a: AnnotateInput): Handle[] {
  const { view, rect } = a;
  g.setTransform(1, 0, 0, 1, 0, 0);
  g.clearRect(0, 0, g.canvas.width, g.canvas.height);
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.lineCap = "round"; g.lineJoin = "round";
  const px = (p: THREE.Vector3) => view.toPane(p, rect);
  const handles: Handle[] = [];
  const spec = view.spec;
  const font = (size: number, weight = 500) => `${weight} ${size}px "IBM Plex Sans", system-ui, sans-serif`;

  if (spec.kind === "plan") {
    // Grids: dash-dot centre lines, a bubble at each end.
    for (const ax of a.grids) {
      const p0 = px(toThree(ax.start[0], ax.start[1], 0)), p1 = px(toThree(ax.end[0], ax.end[1], 0));
      gridLine(g, p0, p1, ax.tag, true);
    }
    // Sections: the line, look heads and name; the far clip and the crop's sides.
    for (const o of a.others) {
      if (o.spec.kind === "section") {
        const s = o.spec, { along, look } = sectionFrame(s);
        const o3 = (u: number, v = 0) => toThree(s.origin[0] + along[0] * u + look[0] * v, s.origin[1] + along[1] * u + look[1] * v, 0);
        const left = s.crop?.left ?? 6, right = s.crop?.right ?? 6;
        const A = px(o3(-left)), B = px(o3(right));
        g.save(); g.strokeStyle = MARK; g.lineWidth = 2.2; g.setLineDash([18, 5, 3, 5]); line(g, A, B); g.restore();
        const n = px(o3(0, 1)).sub(px(o3(0))).normalize();
        for (const [P, end] of [[A, "left"], [B, "right"]] as const) {
          head(g, P, n, "A");
          handles.push({ kind: "section-end", pane: o.index, a: P.clone(), b: P.clone(), end });
        }
        handles.push({ kind: "section-line", pane: o.index, a: A, b: B });
        if (s.far != null) {
          const F0 = px(o3(-left, s.far)), F1 = px(o3(right, s.far));
          g.save(); g.strokeStyle = MARK; g.lineWidth = 1; g.setLineDash([6, 4]); line(g, F0, F1); line(g, A, F0); line(g, B, F1); g.restore();
          handles.push({ kind: "section-far", pane: o.index, a: F0, b: F1 });
        }
        handles.push({ kind: "section-side", pane: o.index, a: A, b: A.clone().addScaledVector(n, 30), end: "left" });
        handles.push({ kind: "section-side", pane: o.index, a: B, b: B.clone().addScaledVector(n, 30), end: "right" });
      } else if (o.spec.kind === "elevation" && !a.model.isEmpty()) {
        // An elevation's marker outside the model, on the side it looks from.
        const lk = facingLook(o.spec.facing), d = toThree(lk[0], lk[1], 0).normalize();
        const c = a.model.getCenter(new THREE.Vector3()), size = a.model.getSize(new THREE.Vector3());
        const reachOut = Math.abs(d.x) * size.x / 2 + Math.abs(d.z) * size.z / 2 + Math.max(size.x, size.z) * 0.08;
        const at = c.clone().addScaledVector(d, -reachOut), P = px(at), Q = px(at.clone().addScaledVector(d, 1));
        const dir = Q.sub(P).normalize();
        elevationMark(g, P, dir, COMPASS_NAME[o.spec.facing][0]);
      }
    }
    // The 3D camera: where it stands and what it sees.
    if (a.camera3d) {
      const c = a.camera3d, P = px(c.position), T = px(c.target);
      const d = T.clone().sub(P);
      if (d.length() > 2) {
        // A fixed size: the 3D view's orbit point moves to what is under the pointer at each press, and a mark as long as
        // the distance to it jumped about while the camera itself barely moved.
        const len = 48, ang = Math.atan2(d.y, d.x), half = THREE.MathUtils.degToRad(c.fov) * 0.6;
        g.save(); g.strokeStyle = "#2f8fdf"; g.fillStyle = "rgba(47,143,223,.12)"; g.lineWidth = 1.2;
        g.beginPath(); g.moveTo(P.x, P.y); g.lineTo(P.x + Math.cos(ang - half) * len, P.y + Math.sin(ang - half) * len);
        g.lineTo(P.x + Math.cos(ang + half) * len, P.y + Math.sin(ang + half) * len); g.closePath(); g.fill(); g.stroke();
        g.fillStyle = "#2f8fdf"; g.beginPath(); g.arc(P.x, P.y, 4, 0, Math.PI * 2); g.fill(); g.restore();
      }
    }
    north(g, rect.w - 34, 68);
  } else {
    const look = spec.kind === "section" ? sectionFrame(spec).look : facingLook(spec.facing);
    // Levels: a line across, its head at the right.
    for (const lv of a.levels) {
      const y = px(new THREE.Vector3(view.center.x, lv.elevation_m, view.center.z)).y;
      if (y < -20 || y > rect.h + 20) continue;
      g.save(); g.strokeStyle = MUTED; g.lineWidth = 0.8; g.setLineDash([10, 3, 2, 3]); line(g, new THREE.Vector2(0, y), new THREE.Vector2(rect.w - 120, y)); g.restore();
      levelHead(g, rect.w - 120, y, lv.name, level3(lv.elevation_m));
    }
    // Grid axes that run along the view's look: a vertical line with its bubble on top.
    for (const ax of a.grids) {
      if (!gridShows(ax, look)) continue;
      const mid = toThree((ax.start[0] + ax.end[0]) / 2, (ax.start[1] + ax.end[1]) / 2, 0);
      const x = px(mid).x;
      if (x < -10 || x > rect.w + 10) continue;
      gridLine(g, new THREE.Vector2(x, rect.h - 8), new THREE.Vector2(x, 70), ax.tag, false);
    }
    // Plans' cut and bottom, to drag.
    for (const o of a.others) {
      if (o.spec.kind !== "plan") continue;
      const { cutZ, bottomZ, level } = planRange(a.levels, o.spec);
      const yc = px(new THREE.Vector3(view.center.x, cutZ, view.center.z)).y;
      g.save(); g.strokeStyle = MARK; g.lineWidth = 1.4; g.setLineDash([9, 5]); line(g, new THREE.Vector2(0, yc), new THREE.Vector2(rect.w, yc)); g.restore();
      tag(g, a.left + 10, yc - 4, `${o.title} · cut ${level3(cutZ - level.elevation_m)}`, MARK, font(11, 600));
      handles.push({ kind: "plan-cut", pane: o.index, a: new THREE.Vector2(0, yc), b: new THREE.Vector2(rect.w, yc) });
      if (bottomZ != null) {
        const yb = px(new THREE.Vector3(view.center.x, bottomZ, view.center.z)).y;
        g.save(); g.strokeStyle = MARK; g.lineWidth = 1; g.setLineDash([2, 4]); line(g, new THREE.Vector2(0, yb), new THREE.Vector2(rect.w, yb)); g.restore();
        tag(g, a.left + 10, yb - 4, `bottom ${level3(bottomZ - level.elevation_m)}`, MARK, font(10.5));
        handles.push({ kind: "plan-bottom", pane: o.index, a: new THREE.Vector2(0, yb), b: new THREE.Vector2(rect.w, yb) });
      }
    }
    // The crop's border, its top and bottom to drag.
    if (view.crop) {
      const q = view.crop.map(px);
      g.save(); g.strokeStyle = INK; g.lineWidth = 0.8; g.beginPath(); q.forEach((p, i) => (i ? g.lineTo(p.x, p.y) : g.moveTo(p.x, p.y))); g.closePath(); g.stroke(); g.restore();
      handles.push({ kind: "crop-bottom", pane: a.index, a: q[0], b: q[1] }, { kind: "crop-top", pane: a.index, a: q[3], b: q[2] });
    }
  }

  // The clash, in a revision cloud.
  if (a.clash && !a.clash.zone.isEmpty()) {
    const pts = cornersOf(a.clash.zone).map(px);
    const x0 = Math.min(...pts.map((p) => p.x)) - 12, x1 = Math.max(...pts.map((p) => p.x)) + 12;
    const y0 = Math.min(...pts.map((p) => p.y)) - 12, y1 = Math.max(...pts.map((p) => p.y)) + 12;
    if (x1 > 0 && x0 < rect.w && y1 > 0 && y0 < rect.h) {
      cloud(g, Math.max(x0, -20), Math.max(y0, -20), Math.min(x1, rect.w + 20), Math.min(y1, rect.h + 20));
      tag(g, Math.min(Math.max(x1 + 4, 4), rect.w - 40), Math.max(y0, 14), a.clash.label, CLOUD, font(11.5, 700), true);
    }
  }

  // Title, scale and scale bar.
  const sc = nearestScale(view.scale), bar = scaleBar(view.scale, 90);
  const detail = spec.kind === "plan" ? (() => { const r = planRange(a.levels, spec); const l = r.level.elevation_m;
    return `cut ${level3(r.cutZ - l)}${r.bottomZ == null ? "" : ` · bottom ${level3(r.bottomZ - l)}`}`; })()
    : spec.far != null ? `far clip ${spec.far.toFixed(2)} m` : "no far clip";
  const by = rect.h - 14;
  const tx = a.left + 16;
  const title = a.title.toUpperCase(), sub = `${detail}  ·  ≈ 1:${sc}`;
  // The title block as wide as its words, within the pane; the scale bar beside it, or above it when the pane is too
  // narrow for both on one line.
  g.font = font(12.5, 700); const tw = g.measureText(title).width;
  g.font = font(11); const sw = g.measureText(sub).width;
  const boxW = Math.max(Math.min(Math.max(tw, sw) + 16, rect.w - tx - 8), 60);
  const bx = rect.w - 18 - bar.pixels;
  const sy = tx - 8 + boxW > bx - 16 ? by - 44 : by;
  g.fillStyle = "rgba(251,251,248,.86)"; g.fillRect(tx - 8, by - 32, boxW, 38);
  g.fillStyle = INK; g.font = font(12.5, 700); g.textBaseline = "alphabetic"; g.textAlign = "left";
  g.fillText(fit(g, title, boxW - 16), tx, by - 14);
  g.fillStyle = MUTED; g.font = font(11); g.fillText(fit(g, sub, boxW - 16), tx, by);
  g.fillStyle = "rgba(251,251,248,.86)"; g.fillRect(bx - 8, sy - 22, bar.pixels + 18, 28);
  for (let i = 0; i < 4; i++) { g.fillStyle = i % 2 ? "#fff" : INK; g.fillRect(bx + (bar.pixels / 4) * i, sy - 6, bar.pixels / 4, 4); }
  g.strokeStyle = INK; g.lineWidth = 0.8; g.strokeRect(bx, sy - 6, bar.pixels, 4);
  g.fillStyle = INK; g.font = font(10.5); g.textAlign = "left"; g.fillText("0", bx - 2, sy - 10);
  g.textAlign = "right"; g.fillText(`${bar.metres >= 1 ? bar.metres : bar.metres * 1000}${bar.metres >= 1 ? " m" : " mm"}`, bx + bar.pixels + 4, sy - 10);
  g.textAlign = "left";
  return handles;
}

/** Text cut with an ellipsis to `w` pixels in the current font. */
function fit(g: CanvasRenderingContext2D, text: string, w: number): string {
  if (g.measureText(text).width <= w) return text;
  let t = text;
  while (t.length > 1 && g.measureText(`${t}…`).width > w) t = t.slice(0, -1);
  return `${t.trimEnd()}…`;
}

function line(g: CanvasRenderingContext2D, a: THREE.Vector2, b: THREE.Vector2) { g.beginPath(); g.moveTo(a.x, a.y); g.lineTo(b.x, b.y); g.stroke(); }

/** A grid axis: dash-dot from a to b, a bubble beyond each end (or only beyond `b`, its top, in a section). */
function gridLine(g: CanvasRenderingContext2D, a: THREE.Vector2, b: THREE.Vector2, tag: string, both: boolean) {
  const d = b.clone().sub(a);
  if (d.length() < 1) return;
  d.normalize();
  const r = 10;
  g.save(); g.strokeStyle = GRID; g.lineWidth = 0.9; g.setLineDash([16, 4, 2, 4]); line(g, a, b); g.restore();
  for (const [p, s] of (both ? [[a, -1], [b, 1]] : [[b, 1]]) as [THREE.Vector2, number][]) {
    const c = p.clone().addScaledVector(d, s * r);
    g.save(); g.fillStyle = "#fff"; g.strokeStyle = GRID; g.lineWidth = 1.2;
    g.beginPath(); g.arc(c.x, c.y, r, 0, Math.PI * 2); g.fill(); g.stroke();
    g.fillStyle = GRID; g.font = `700 11px "IBM Plex Sans", system-ui, sans-serif`; g.textAlign = "center"; g.textBaseline = "middle";
    g.fillText(tag, c.x, c.y + 0.5); g.restore();
  }
}

/** A section's head: a filled half-disc pointing the way it looks, with its name. */
function head(g: CanvasRenderingContext2D, p: THREE.Vector2, n: THREE.Vector2, name: string) {
  const ang = Math.atan2(n.y, n.x);
  g.save(); g.fillStyle = MARK; g.strokeStyle = MARK; g.lineWidth = 1.2;
  g.beginPath(); g.arc(p.x, p.y, 11, ang - Math.PI / 2, ang + Math.PI / 2); g.closePath(); g.fill();
  g.beginPath(); g.arc(p.x, p.y, 11, 0, Math.PI * 2); g.stroke();
  g.fillStyle = "#fff"; g.font = `700 10px "IBM Plex Sans", system-ui, sans-serif`; g.textAlign = "center"; g.textBaseline = "middle";
  g.fillText(name, p.x + Math.cos(ang) * 4.5, p.y + Math.sin(ang) * 4.5 + 0.5); g.restore();
}

function elevationMark(g: CanvasRenderingContext2D, p: THREE.Vector2, dir: THREE.Vector2, name: string) {
  const ang = Math.atan2(dir.y, dir.x);
  g.save(); g.translate(p.x, p.y); g.rotate(ang);
  g.fillStyle = MARK; g.beginPath(); g.moveTo(16, 0); g.lineTo(-6, -11); g.lineTo(-6, 11); g.closePath(); g.fill();
  g.rotate(-ang); g.fillStyle = "#fff"; g.font = `700 10px "IBM Plex Sans", system-ui, sans-serif`; g.textAlign = "center"; g.textBaseline = "middle";
  g.fillText(name, 0, 0.5); g.restore();
}

function levelHead(g: CanvasRenderingContext2D, x: number, y: number, name: string, value: string) {
  g.save(); g.fillStyle = INK; g.strokeStyle = INK; g.lineWidth = 1;
  g.beginPath(); g.moveTo(x, y); g.lineTo(x + 7, y - 7); g.lineTo(x + 14, y); g.closePath(); g.fill();
  g.beginPath(); g.moveTo(x, y); g.lineTo(x + 112, y); g.stroke();
  g.font = `600 11px "IBM Plex Sans", system-ui, sans-serif`; g.textAlign = "left"; g.textBaseline = "alphabetic";
  g.fillText(name, x + 18, y - 4);
  g.font = `11px "IBM Plex Mono", ui-monospace, monospace`; g.fillStyle = MUTED; g.fillText(value, x + 18, y + 12); g.restore();
}

function north(g: CanvasRenderingContext2D, x: number, y: number) {
  g.save(); g.strokeStyle = INK; g.fillStyle = "rgba(255,255,255,.9)"; g.lineWidth = 1;
  g.beginPath(); g.arc(x, y, 16, 0, Math.PI * 2); g.fill(); g.stroke();
  g.fillStyle = INK; g.beginPath(); g.moveTo(x, y - 13); g.lineTo(x + 6, y + 8); g.lineTo(x, y + 3); g.closePath(); g.fill();
  g.fillStyle = "#fff"; g.strokeStyle = INK; g.beginPath(); g.moveTo(x, y - 13); g.lineTo(x - 6, y + 8); g.lineTo(x, y + 3); g.closePath(); g.fill(); g.stroke();
  g.fillStyle = INK; g.font = `700 10px "IBM Plex Sans", system-ui, sans-serif`; g.textAlign = "center"; g.fillText("N", x, y - 20); g.restore();
}

/** A revision cloud round a rectangle: scallops along each side. */
function cloud(g: CanvasRenderingContext2D, x0: number, y0: number, x1: number, y1: number) {
  const r = 7;
  g.save(); g.strokeStyle = CLOUD; g.lineWidth = 1.6; g.beginPath();
  const edge = (ax: number, ay: number, bx: number, by: number) => {
    const len = Math.hypot(bx - ax, by - ay), n = Math.max(1, Math.round(len / (2 * r)));
    const ang = Math.atan2(by - ay, bx - ax);
    for (let i = 0; i < n; i++) {
      const cx = ax + ((bx - ax) * (i + 0.5)) / n, cy = ay + ((by - ay) * (i + 0.5)) / n, rr = len / n / 2;
      g.arc(cx, cy, rr, ang + Math.PI, ang + 2 * Math.PI);
    }
  };
  edge(x0, y0, x1, y0); edge(x1, y0, x1, y1); edge(x1, y1, x0, y1); edge(x0, y1, x0, y0);
  g.stroke(); g.restore();
}

function tag(g: CanvasRenderingContext2D, x: number, y: number, text: string, colour: string, f: string, filled = false) {
  g.save(); g.font = f; g.textBaseline = "alphabetic"; g.textAlign = "left";
  const w = g.measureText(text).width;
  g.fillStyle = filled ? colour : "rgba(251,251,248,.9)"; g.fillRect(x - 3, y - 12, w + 6, 16);
  g.fillStyle = filled ? "#fff" : colour; g.fillText(text, x, y); g.restore();
}

function cornersOf(b: THREE.Box3): THREE.Vector3[] {
  const out: THREE.Vector3[] = [];
  for (const x of [b.min.x, b.max.x]) for (const y of [b.min.y, b.max.y]) for (const z of [b.min.z, b.max.z]) out.push(new THREE.Vector3(x, y, z));
  return out;
}
