/**
 * Reads a Navisworks clash picture by colour. Navisworks draws the two elements flat red (A) and green (B) on black,
 * context grey, and where a see-through pair overlaps, a red-green blend (brown). So plain colour tells apart A, B and
 * the zone where they meet, exactly and instantly; no model call. (SAM 3.1 was tried: on these renders it found
 * nothing from text prompts and, from points, outlined less than colour does and never the overlap.)
 *
 * The zone is the blend plus the seam where red and green touch, which is all a solid view (image B) shows.
 */

export type Box = { x0: number; y0: number; x1: number; y1: number }  // fractions of the image, 0..1

export interface ClashRead {
  pair: Box | null;     // everything red, green or blended
  zone: Box | null;     // where the two meet
  /** Per-cell class on a `cols` x `rows` grid: 0 nothing, 1 A (red), 2 B (green), 3 where they meet. */
  cells: Uint8Array;
  cols: number;
  rows: number;
}

const GRID = 512;          // analysis resolution (the pictures are 1024 px): smooth outlines, ~10-20 ms to read
const SEAM = 3;            // cells: red and green this close count as touching

function classify(r: number, g: number, b: number): number {
  if (g > r + 40 && g > b + 40) return 2;
  if (r > g + 20 && r > b + 30) return g > 0.25 * r && b < 0.6 * g + 12 ? 3 : r > g + 40 ? 1 : 0;
  return 0;
}

const cache = new Map<string, Promise<ClashRead | null>>();

/** Read a picture once per URL (the list, the panel and the dialog share it). */
export function readClashImage(url: string): Promise<ClashRead | null> {
  let p = cache.get(url);
  if (!p) {
    p = load(url).then(analyse).catch(() => null);
    cache.set(url, p);
  }
  return p;
}

function load(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.decoding = "async";
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = url;
  });
}

function analyse(img: HTMLImageElement): ClashRead {
  const cols = GRID, rows = Math.max(1, Math.round((GRID * img.naturalHeight) / img.naturalWidth));
  const canvas = document.createElement("canvas");
  canvas.width = cols;
  canvas.height = rows;
  const ctx = canvas.getContext("2d", { willReadFrequently: true })!;
  ctx.imageSmoothingEnabled = false;  // keep flat colours flat: smoothing would blend red and green at every edge
  ctx.drawImage(img, 0, 0, cols, rows);
  const px = ctx.getImageData(0, 0, cols, rows).data;
  const cells = new Uint8Array(cols * rows);
  for (let i = 0; i < cells.length; i++) cells[i] = classify(px[i * 4], px[i * 4 + 1], px[i * 4 + 2]);

  // The seam: red cells with green within SEAM cells (and the other way round) are where a solid pair meets.
  const seam: number[] = [];
  for (let y = 0; y < rows; y++) {
    for (let x = 0; x < cols; x++) {
      const c = cells[y * cols + x];
      if (c !== 1 && c !== 2) continue;
      const want = c === 1 ? 2 : 1;
      search: for (let dy = -SEAM; dy <= SEAM; dy++) {
        for (let dx = -SEAM; dx <= SEAM; dx++) {
          const xx = x + dx, yy = y + dy;
          if (xx >= 0 && yy >= 0 && xx < cols && yy < rows && cells[yy * cols + xx] === want) { seam.push(y * cols + x); break search; }
        }
      }
    }
  }
  for (const i of seam) cells[i] = 3;

  const box = (test: (c: number) => boolean): Box | null => {
    let x0 = cols, y0 = rows, x1 = -1, y1 = -1;
    for (let y = 0; y < rows; y++) {
      for (let x = 0; x < cols; x++) {
        if (!test(cells[y * cols + x])) continue;
        if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
      }
    }
    return x1 < 0 ? null : { x0: x0 / cols, y0: y0 / rows, x1: (x1 + 1) / cols, y1: (y1 + 1) / rows };
  };
  return { pair: box((c) => c > 0), zone: box((c) => c === 3), cells, cols, rows };
}

/** A square around the zone (or the pair), with room round it, clamped to the picture: what a thumbnail shows. */
export function focusSquare(read: ClashRead, margin = 1.6, min = 0.18): Box | null {
  const b = read.zone ?? read.pair;
  if (!b) return null;
  const cx = (b.x0 + b.x1) / 2, cy = (b.y0 + b.y1) / 2;
  const side = Math.min(1, Math.max(min, Math.max(b.x1 - b.x0, b.y1 - b.y0) * margin));
  const x0 = Math.min(Math.max(cx - side / 2, 0), 1 - side), y0 = Math.min(Math.max(cy - side / 2, 0), 1 - side);
  return { x0, y0, x1: x0 + side, y1: y0 + side };
}

/** Outlines of A and B and the meeting zone, drawn on a canvas laid over the picture at its display size. */
export function drawOverlay(canvas: HTMLCanvasElement, read: ClashRead) {
  const w = canvas.clientWidth, h = canvas.clientHeight;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(h * dpr);
  const ctx = canvas.getContext("2d")!;
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);
  const { cells, cols, rows } = read;
  const sx = w / cols, sy = h / rows;
  const at = (x: number, y: number) => (x < 0 || y < 0 || x >= cols || y >= rows ? 0 : cells[y * cols + x]);
  const sides = (cls: number) => (c: number) => (cls === 3 ? c === 3 : c === cls || c === 3);  // A and B include the zone

  // Each class's boundary: cell edges between "in" and "out", as line segments.
  const outline = (inside: (c: number) => boolean, colour: string, width: number) => {
    ctx.beginPath();
    for (let y = 0; y <= rows; y++) {
      for (let x = 0; x <= cols; x++) {
        const here = inside(at(x, y));
        if (here !== inside(at(x - 1, y))) { ctx.moveTo(x * sx, y * sy); ctx.lineTo(x * sx, (y + 1) * sy); }
        if (here !== inside(at(x, y - 1))) { ctx.moveTo(x * sx, y * sy); ctx.lineTo((x + 1) * sx, y * sy); }
      }
    }
    ctx.strokeStyle = colour;
    ctx.lineWidth = width;
    ctx.shadowColor = colour;
    ctx.shadowBlur = 4;
    ctx.stroke();
  };
  outline(sides(1), "#ff6b6b", 1.5);
  outline(sides(2), "#5dff8a", 1.5);

  if (read.zone) {
    ctx.fillStyle = "rgba(255, 176, 0, 0.45)";
    for (let y = 0; y < rows; y++) for (let x = 0; x < cols; x++) if (cells[y * cols + x] === 3) ctx.fillRect(x * sx, y * sy, sx + 0.5, sy + 0.5);
    outline(sides(3), "#ffb000", 2);
    const z = read.zone;
    const cx = ((z.x0 + z.x1) / 2) * w, cy = ((z.y0 + z.y1) / 2) * h;
    const r = Math.max(((z.x1 - z.x0) * w) / 2, ((z.y1 - z.y0) * h) / 2) + 14;
    ctx.shadowBlur = 0;
    ctx.setLineDash([6, 5]);
    ctx.strokeStyle = "#ffb000";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.stroke();
    ctx.setLineDash([]);
  }
}
