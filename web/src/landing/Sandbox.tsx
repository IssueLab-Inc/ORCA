import { Check, RotateCcw, Sparkles, X as Cross } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { DUCT_AT, PLANE, SOLIDS, checkRaise, mm, passingBands, type Solid } from "./check";
import { GIRDER } from "./northbank";

const LO = -0.3, HI = 0.9, STEP = 0.005, ANSWER = 0.4;
/** Plane metres to the drawing's millimetres: y across from the left edge, z down from the top. */
const X = (y: number) => (y - PLANE.y[0]) * 1000;
const Y = (z: number) => (PLANE.z[1] - z) * 1000;
const W = X(PLANE.y[1]), H = Y(PLANE.z[0]);
const snap = (v: number) => Math.round(Math.min(HI, Math.max(LO, v)) / STEP) * STEP;

/** The gaps round the duct to what is straight above, below and beside it (for the dimension lines). */
function gaps(duct: { y: readonly [number, number]; z: readonly [number, number] }) {
  const over = (a: readonly [number, number], b: readonly [number, number]) => Math.min(a[1], b[1]) - Math.max(a[0], b[0]) > 1e-6;
  let up = Infinity, down = Infinity, left = Infinity, right = Infinity;
  for (const s of SOLIDS) {
    if (over(s.y, duct.y)) {
      if (s.z[0] >= duct.z[1] - 1e-6) up = Math.min(up, s.z[0] - duct.z[1]);
      if (s.z[1] <= duct.z[0] + 1e-6) down = Math.min(down, duct.z[0] - s.z[1]);
    }
    if (over(s.z, duct.z)) {
      if (s.y[1] <= duct.y[0] + 1e-6) left = Math.min(left, duct.y[0] - s.y[1]);
      if (s.y[0] >= duct.y[1] - 1e-6) right = Math.min(right, s.y[0] - duct.y[1]);
    }
  }
  return { up, down, left, right };
}

/**
 * "Try the check yourself": Northbank #1 seen along the duct, at the girder, drawn from the models (check.ts). Drag
 * the duct (or use the slider) and the check answers as ORCA's would: clash gone, nothing new hit, room to spare.
 */
export function Sandbox({ reduce }: { reduce: boolean }) {
  const [raise, setRaise] = useState(0);
  const [needed, setNeeded] = useState(0.025);
  const [moved, setMoved] = useState(false);
  const c = useMemo(() => checkRaise(raise, needed), [raise, needed]);
  const bands = useMemo(() => passingBands(needed, LO, HI, STEP), [needed]);
  const tween = useRef(0);
  const svg = useRef<SVGSVGElement>(null);
  const drag = useRef<{ y: number; from: number; id: number } | null>(null);

  useEffect(() => () => cancelAnimationFrame(tween.current), []);
  const go = (to: number) => {
    cancelAnimationFrame(tween.current);
    setMoved(true);
    if (reduce) { setRaise(to); return; }
    const from = raise, t0 = performance.now(), ms = 900;
    const step = (now: number) => {
      const x = Math.min(1, (now - t0) / ms), e = x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
      setRaise(snap(from + (to - from) * e));
      if (x < 1) tween.current = requestAnimationFrame(step);
    };
    tween.current = requestAnimationFrame(step);
  };
  const onDown = (e: React.PointerEvent<SVGSVGElement>) => {
    cancelAnimationFrame(tween.current);
    drag.current = { y: e.clientY, from: raise, id: e.pointerId };
    e.currentTarget.setPointerCapture(e.pointerId);
    setMoved(true);
  };
  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const d = drag.current, el = svg.current;
    if (!d || d.id !== e.pointerId || !el) return;
    const perM = el.getBoundingClientRect().height / (PLANE.z[1] - PLANE.z[0]);
    setRaise(snap(d.from + (d.y - e.clientY) / perM));
  };
  const onUp = () => { drag.current = null; };

  const duct = c.duct, g = gaps(duct);
  const state = c.verified ? "ok" : c.hits.length ? "bad" : "near";
  const girderHit = c.hits.find((h) => h.girder);
  const pct = (v: number) => `${((v - LO) / (HI - LO)) * 100}%`;
  const dim = (x1: number, y1: number, x2: number, y2: number, text: string, side: "v" | "h") => (
    <g className="lp-sb-dim">
      <line x1={x1} y1={y1} x2={x2} y2={y2} />
      {side === "v"
        ? <><line x1={x1 - 22} y1={y1} x2={x1 + 22} y2={y1} /><line x1={x2 - 22} y1={y2} x2={x2 + 22} y2={y2} />
          <text x={x1 + 34} y={(y1 + y2) / 2 + 15}>{text}</text></>
        : <><line x1={x1} y1={y1 - 22} x2={x1} y2={y1 + 22} /><line x1={x2} y1={y2 - 22} x2={x2} y2={y2 + 22} />
          <text x={(x1 + x2) / 2} y={y1 - 34} textAnchor="middle">{text}</text></>}
    </g>
  );
  const web = GIRDER.web.z;
  const holes = GIRDER.openings.filter((o) => o.y[1] > PLANE.y[0] && o.y[0] < PLANE.y[1]);
  const webPath = `M${X(PLANE.y[0])} ${Y(web[1])}H${X(PLANE.y[1])}V${Y(web[0])}H${X(PLANE.y[0])}Z`
    + holes.map((o) => `M${X(o.y[0])} ${Y(o.z[1])}H${X(o.y[1])}V${Y(o.z[0])}H${X(o.y[0])}Z`).join("");
  const box = (s: Pick<Solid, "y" | "z">) => ({ x: X(s.y[0]), y: Y(s.z[1]), width: X(s.y[1]) - X(s.y[0]), height: Y(s.z[0]) - Y(s.z[1]) });
  const clearText = c.hits.length ? "it overlaps" : `${mm(c.clearance ?? 0)} clear, ${mm(needed)} needed`;

  return (
    <div className="lp-sb">
      <figure className="lp-sb-figure">
        <svg ref={svg} viewBox={`-60 -40 ${W + 120} ${H + 80}`} role="img" className={`lp-sb-svg ${state}`}
          aria-label={`Northbank clash 1 seen along the duct: the duct raised ${mm(raise, true)}. ${c.verified ? "It passes the check." : "It fails the check."}`}
          onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}>
          <defs>
            <pattern id="lp-sb-grid" width="100" height="100" patternUnits="userSpaceOnUse"><path d="M100 0H0V100" className="lp-sb-gridline" /></pattern>
            <pattern id="lp-sb-hatch" width="40" height="40" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="40" className="lp-sb-hatchline" /></pattern>
          </defs>
          <rect x={0} y={0} width={W} height={H} fill="url(#lp-sb-grid)" />
          {/* the slab above and the ceiling below */}
          <rect {...box({ y: PLANE.y, z: [7.85, 8.0] })} className="lp-sb-slab" />
          <rect {...box({ y: PLANE.y, z: [7.85, 8.0] })} fill="url(#lp-sb-hatch)" />
          <rect {...box({ y: PLANE.y, z: [6.7, 6.72] })} className="lp-sb-ceiling" />
          {[[-3.398, -2.802], [-1.598, -1.15]].map(([a, b]) => <rect key={a} {...box({ y: [a, b], z: [6.7, 6.78] })} className="lp-sb-lamp" />)}
          {/* the girder: its web with the openings, and its flanges, seen face on */}
          <path d={webPath} className="lp-sb-web" fillRule="evenodd" />
          <rect {...box({ y: PLANE.y, z: [GIRDER.z[1] - GIRDER.flange, GIRDER.z[1]] })} className="lp-sb-flange" />
          <rect {...box({ y: PLANE.y, z: [GIRDER.z[0], GIRDER.z[0] + GIRDER.flange] })} className="lp-sb-flange" />
          {/* the secondary beam end on, and the services already through their own openings */}
          <path className="lp-sb-beam" d={`M${X(-3.0855)} ${Y(7.85)}H${X(-2.9145)}V${Y(7.8403)}H${X(-2.9965)}V${Y(7.5087)}H${X(-2.9145)}V${Y(7.499)}H${X(-3.0855)}V${Y(7.5087)}H${X(-3.0035)}V${Y(7.8403)}H${X(-3.0855)}Z`} />
          <rect {...box({ y: [-1.95, -1.45], z: [7.08, 7.33] })} className="lp-sb-other" rx={6} />
          <circle cx={X(-2.85)} cy={Y(7.18)} r={21} className="lp-sb-other" />
          <circle cx={X(-3.05)} cy={Y(6.9)} r={27} className="lp-sb-other" />
          <text x={X(-1.7)} y={Y(7.205) + 14} className="lp-sb-small" textAnchor="middle">return air</text>
          {/* the duct as modelled, and where it is now */}
          <rect {...box(DUCT_AT)} className="lp-sb-was" rx={8} />
          <g className={`lp-sb-duct ${state}`}>
            <rect {...box(duct)} rx={8} />
            <path d={`M${X(-2.45) - 60} ${Y(duct.z[0] + 0.15)}h120M${X(-2.45)} ${Y(duct.z[0] + 0.15) - 60}v120`} className="lp-sb-cross" />
          </g>
          {/* the room left round it */}
          {!c.hits.length && <>
            {g.up < 1 && dim(X(-2.45) + 150, Y(duct.z[1] + g.up), X(-2.45) + 150, Y(duct.z[1]), mm(g.up), "v")}
            {g.down < 1 && dim(X(-2.45) - 150, Y(duct.z[0]), X(-2.45) - 150, Y(duct.z[0] - g.down), mm(g.down), "v")}
            {g.left < 0.3 && dim(X(duct.y[0] - g.left), Y(duct.z[1]) + 70, X(duct.y[0]), Y(duct.z[1]) + 70, mm(g.left), "h")}
            {g.right < 0.3 && dim(X(duct.y[1]), Y(duct.z[1]) + 70, X(duct.y[1] + g.right), Y(duct.z[1]) + 70, mm(g.right), "h")}
          </>}
          {c.hits.length > 0 && <text x={X(-2.45)} y={Y(duct.z[1]) - 30} className="lp-sb-hitnote" textAnchor="middle">
            {girderHit ? `into the girder ${mm(-girderHit.depth, true)}` : `hits the ${c.newHits[0]?.toLowerCase()}`}</text>}
          <text x={W - 10} y={Y(7.925) + 14} className="lp-sb-label" textAnchor="end">Level 03 slab</text>
          <text x={W - 10} y={Y(6.72) - 18} className="lp-sb-label" textAnchor="end">Suspended ceiling</text>
          <text x={X(-2.45)} y={Y(7.81) + 52} className="lp-sb-label" textAnchor="middle">girder web opening, 700 × 400</text>
          <text x={10} y={Y(6.89) - 22} className="lp-sb-label">Transfer girder: its 20 mm web, face on</text>
        </svg>
        <figcaption>Seen along the duct, at the girder. Drag the duct up or down.</figcaption>
      </figure>

      <div className="lp-sb-panel">
        <div className="lp-sb-raise">
          <span>Raise the duct's middle</span>
          <b className="mono">{mm(raise, true)}</b>
        </div>
        <div className="lp-sb-range">
          <div className="lp-sb-track" aria-hidden>
            {bands.map(([a, b]) => <i key={a} className="band" style={{ left: pct(a), width: `calc(${pct(b)} - ${pct(a)} + 2px)` }} />)}
            <i className="answer" style={{ left: pct(ANSWER) }}><span>ORCA</span></i>
            <i className="zero" style={{ left: pct(0) }} />
          </div>
          <input type="range" min={LO} max={HI} step={STEP} value={raise} aria-label="Raise the duct's middle stretch"
            aria-valuetext={mm(raise, true)} onChange={(e) => { cancelAnimationFrame(tween.current); setMoved(true); setRaise(snap(Number(e.target.value))); }} />
          <div className="lp-sb-scale" aria-hidden><span>{mm(LO, true)}</span><span>0</span><span>{mm(HI, true)}</span></div>
        </div>
        <ul className="lp-sb-checks" aria-live="polite">
          <li className={c.clashGone ? "ok" : "bad"}>{c.clashGone ? <Check size={15} aria-hidden /> : <Cross size={15} aria-hidden />}
            <span><b>{c.clashGone ? "Clash gone" : "Clash still there"}</b>{girderHit ? ` · in the girder ${mm(-girderHit.depth, true)}` : " · clear of the girder"}</span></li>
          <li className={c.newHits.length ? "bad" : "ok"}>{c.newHits.length ? <Cross size={15} aria-hidden /> : <Check size={15} aria-hidden />}
            <span><b>{c.newHits.length ? "Something new hit" : "Nothing new hit"}</b>{c.newHits.length ? ` · ${c.newHits.join(", ")}` : ""}</span></li>
          <li className={c.verified ? "ok" : "bad"}>{c.verified ? <Check size={15} aria-hidden /> : <Cross size={15} aria-hidden />}
            <span><b>{c.hits.length ? "No room" : c.verified ? "Room to spare" : "Too close"}</b> · {clearText}</span></li>
        </ul>
        <div className={`lp-sb-verdict ${c.verified ? "ok" : "bad"}`} role="status">
          <b>{c.verified ? "Verified" : "Not verified"}</b>
          <span>{c.verified
            ? Math.abs(raise - ANSWER) < 1e-6 ? "ORCA's recorded fix: 1.40 m of duct up 400 mm, 50 mm clear all round." : "A fix like this would reach you, ranked with the others."
            : moved ? "It goes back to Muse Spark with why, and what it hit." : "As modelled: the duct runs through the girder's web."}</span>
        </div>
        <div className="lp-sb-actions">
          <button type="button" className="lp-btn small primary" onClick={() => go(ANSWER)}><Sparkles size={14} aria-hidden /> Show ORCA's fix</button>
          <button type="button" className="lp-btn small glass" onClick={() => go(0)}><RotateCcw size={14} aria-hidden /> As modelled</button>
        </div>
        <div className="lp-sb-need" role="group" aria-label="Clearance the requirements ask for">
          <span>Clearance needed</span>
          {[[0.025, "25 mm · default"], [0.05, "50 mm · strict"]].map(([v, l]) => (
            <button key={l} type="button" className={needed === v ? "on" : ""} aria-pressed={needed === v} onClick={() => setNeeded(v as number)}>{l}</button>
          ))}
        </div>
      </div>
    </div>
  );
}
