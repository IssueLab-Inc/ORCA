import { Bot, CircleDot, Crosshair, Eye, Image as ImageIcon, Maximize, MessageSquare, Minus, Pause, Play, Plus, Radio, RotateCcw, Sparkles, Tags, User, type LucideIcon } from "lucide-react";
import { Component, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { kindLabel } from "./fixKinds";
import { runs, type Run } from "./runlog";
import { graphOf, sec, type Actor, type Edge, type Graph, type Part, type Peek, type Side, type Step } from "./workingsGraph";

/*
 * Workings (docs/workings.md): the Activity panel's drawing of a run as it happens. The graph comes from `workingsGraph.ts`;
 * this draws it on a canvas that pans and zooms, follows the newest step, and replays a finished run from its events.
 *
 * The panel can float or open in a window of its own (docs/panels.md) without remounting, so whatever needs a window
 * (timers, sizes, pointer capture) takes the one the canvas is in now, never the page's.
 */

const LABELS = 126, LABELS_NARROW = 84, FAR = 0.6, MIN_K = 0.22, MAX_K = 1.6, GX = 18;
const SPEEDS = [1, 2, 4, 8];
const ACTOR: Record<Actor, { label: string; icon: LucideIcon; color: string }> = {
  you: { label: "You", icon: User, color: "#8592a3" }, orca: { label: "ORCA", icon: CircleDot, color: "#2f5d8a" },
  spark: { label: "Muse Spark", icon: Sparkles, color: "#4b4fb3" }, wonder: { label: "Muse Wonder", icon: Sparkles, color: "#5b3c99" },
  image: { label: "Muse Image", icon: ImageIcon, color: "#9c3a6b" },
};
const ORIGIN_ICON: Record<Run["origin"], LucideIcon> = { you: User, chat: MessageSquare, agent: Bot, replay: RotateCcw };
const KIND_NAME: Record<Run["kind"], string> = { propose: "Fixes", plan: "Plan", triage: "Triage", built: "Show it built", detect: "Check" };

type Rect = { x: number; y: number; w: number; h: number };
type View = { k: number; tx: number; ty: number };
const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));
const winOf = (el: Element | null | undefined): Window => el?.ownerDocument.defaultView ?? window;

function anchor(r: Rect, side: Side): [number, number, number, number] {
  switch (side) {
    case "r": return [r.x + r.w, r.y + r.h / 2, 1, 0];
    case "l": return [r.x, r.y + r.h / 2, -1, 0];
    case "t": return [r.x + r.w / 2, r.y, 0, -1];
    case "tr": return [r.x + r.w - 34, r.y, 0, -1];
    default: return [r.x + r.w / 2, r.y + r.h, 0, 1];
  }
}
function sides(a: Rect, b: Rect): [Side, Side] {
  if (b.x >= a.x + a.w - 4) return ["r", "l"];
  if (b.x + b.w <= a.x + 4) return ["l", "r"];
  return b.y >= a.y + a.h ? ["b", "t"] : ["t", "b"];
}
/** An edge's curve: out of one step's side and into the other's, bent in proportion to how far apart they are. */
export function curve(a: Rect, b: Rect, fa?: Side, ta?: Side): number[][] {
  const [sa, sb] = fa && ta ? [fa, ta] : sides(a, b);
  const p0 = anchor(a, sa), p3 = anchor(b, sb), d = clamp(Math.hypot(p3[0] - p0[0], p3[1] - p0[1]) * 0.42, 26, 150);
  return [[p0[0], p0[1]], [p0[0] + p0[2] * d, p0[1] + p0[3] * d], [p3[0] + p3[2] * d, p3[1] + p3[3] * d], [p3[0] + p3[2] * 3, p3[1] + p3[3] * 3]];
}
const bez = (p: number[][], u: number) => { const m = 1 - u; return [0, 1].map((k) => m * m * m * p[0][k] + 3 * m * m * u * p[1][k] + 3 * m * u * u * p[2][k] + u * u * u * p[3][k]); };
const pathOf = (p: number[][]) => `M${p[0].map((v) => v.toFixed(1))} C${p[1].map((v) => v.toFixed(1))} ${p[2].map((v) => v.toFixed(1))} ${p[3].map((v) => v.toFixed(1))}`;

/** How an edge looks now: the step it leads to decides (running, failed), a finished run lights its kept path. */
function edgeClass(e: Edge, to: Step | undefined, done: boolean) {
  if (e.kind === "ghost" || e.kind === "feedback") return e.kind;
  if (to?.status === "run") return "live";
  if (to?.status === "fail") return "fail";
  if (e.win && done && to?.status !== "ghost") return "ok";
  return e.kind === "seq" ? "seq" : "base";
}

/** The runs kept, re-read a few times a second at most (a triage sends many events a second). */
function useRuns(host: React.RefObject<HTMLElement | null>) {
  const [list, setList] = useState(() => runs.runs());
  useEffect(() => {
    let timer = 0, w: Window | null = null;
    const off = runs.subscribe(() => {
      if (timer) return;
      w = winOf(host.current);
      timer = w.setTimeout(() => { timer = 0; setList(runs.runs()); }, 80);
    });
    return () => { off(); if (timer && w) w.clearTimeout(timer); };
  }, [host]);
  return list;
}

function PartView({ p }: { p: Part }): ReactNode {
  switch (p.kind) {
    case "text": return <div className={`wk-t ${p.tone ?? ""} ${p.strong ? "strong" : ""} ${p.mono ? "mono" : ""} ${p.live ? "pulse" : ""}`}>{p.text}</div>;
    case "fix": return <div className="wk-t"><span className={`badge ${p.fix}`}>{kindLabel(p.fix)}</span> {p.text}</div>;
    case "thoughts": return <ul className="wk-thoughts">{p.items.map((t, i) => <li key={i}>{t}</li>)}</ul>;
    case "quote": return <p className="wk-quote">“{p.text}”</p>;
    case "chips": return <span className="chips">{p.items.map((c, i) => <span key={i} className={`chip ${c.tone ?? ""}`}>{c.text}</span>)}</span>;
    case "list": return <ul className="wk-list">{p.items.map((it, i) => <li key={i} className={it.tone ?? ""}>{it.mark && <b>{it.mark}</b>}<span>{it.text}{it.note && <i> {it.note}</i>}</span></li>)}</ul>;
    case "progress": return <div className="wk-progress"><span className="wk-prog"><i style={{ width: `${(p.total ? p.done / p.total : 0) * 100}%` }} /></span><span className="wk-t muted">{p.text}</span></div>;
    case "bars": return <div className="wk-bars">{p.rows.map((r) => <div key={r.label} className={`wk-bar ${r.tone}`}><span>{r.label}</span><span className="track"><i style={{ width: `${(p.max ? r.n / p.max : 0) * 100}%` }} /></span><b>{r.n}</b></div>)}</div>;
    case "slots": return <div className="wk-slots">{p.rows.map((r) => <div key={r.n} className={`wk-slot ${r.title ? "" : "idle"}`}><span>{r.n}</span><div><b>{r.title || "idle"}</b> <i>{r.note}</i></div></div>)}</div>;
    case "image": return <img className="wk-img" src={p.src} alt={p.alt} />;
  }
}

function StepView({ s, x, y, w, inView, pinned, peeking, you }: { s: Step; x: number; y: number; w: number; inView: boolean; pinned: boolean; peeking: boolean; you: string }) {
  const a = ACTOR[s.actor], Icon = a.icon;
  return (
    <div className={`wk-step a-${s.actor} st-${s.status}${pinned ? " pinned" : ""}${s.peek ? " has-peek" : ""}${peeking ? " peeking" : ""}`} data-id={s.id}
      style={{ left: x, top: y, width: w }} data-tip={s.peek && !pinned ? "In the viewer while you point at it; click to keep it there" : undefined}>
      <div className="wk-head">
        <span className="wk-actor"><Icon size={13} aria-hidden />{s.actor === "you" ? you : s.model ?? a.label}</span>
        {inView && <span className="wk-eye"><Eye size={11} aria-hidden />in view</span>}
        <span className="wk-time">{s.time}</span>
      </div>
      <div className="wk-title">{s.fix && <span className={`badge ${s.fix}`}>{kindLabel(s.fix)}</span>}{s.fix ? " " : ""}{s.title}</div>
      {s.body.length > 0 && <div className="wk-body">{s.body.map((p, i) => <PartView key={i} p={p} />)}</div>}
      {s.detail.length > 0 && <div className="wk-detail">{s.detail.map((p, i) => <PartView key={i} p={p} />)}</div>}
      <div className="wk-ev">{s.ev}{s.newEv && <b>{s.newEv}</b>}</div>
    </div>
  );
}

/** The timeline under the canvas: who was busy when, and where the drawing stands. Drag to replay. */
function Strip({ graph, at, onSeek, clock }: { graph: Graph; at: number; onSeek: (t: number) => void; clock: string }) {
  const dur = Math.max(graph.duration, 0.5), X = (v: number) => (v / dur) * 1000;
  // Lanes in pixels: a bar 8 px tall (or a row per item), 4 px apart.
  let y = 3;
  const pos: Record<string, { y: number; h: number }> = {};
  const rows = graph.rows.map((r) => { const h = r.subs ? r.subs * 3 + 2 : 8; pos[r.id] = { y, h }; y += h + 4; return { ...r, h }; });
  const step = dur <= 25 ? 5 : dur <= 70 ? 10 : dur <= 160 ? 20 : 60;
  const ticks: number[] = []; for (let s = 0; s <= dur; s += step) ticks.push(s);
  const seek = (e: React.PointerEvent<HTMLDivElement>) => { const b = e.currentTarget.getBoundingClientRect(); onSeek(clamp((e.clientX - b.left) / b.width, 0, 1) * dur); };
  return (
    <div className="wk-strip">
      {/* Each label sits on its own lane's bars: the same top and height, in pixels */}
      <div className="wk-rows" style={{ height: y }}>{rows.map((r) => <span key={r.id} style={{ top: pos[r.id].y - 2, height: r.h + 4 }}>{r.label}</span>)}</div>
      <div className="wk-track" onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); seek(e); }}
        onPointerMove={(e) => { if (e.buttons) seek(e); }} role="slider" aria-label="Replay the run" aria-valuemin={0}
        aria-valuemax={Math.round(dur)} aria-valuenow={Math.round(at)} tabIndex={0}
        onKeyDown={(e) => { const d = e.key === "ArrowLeft" ? -1 : e.key === "ArrowRight" ? 1 : 0; if (d) { e.preventDefault(); onSeek(clamp(at + d * step / 5, 0, dur)); } }}>
        <svg viewBox={`0 0 1000 ${y}`} preserveAspectRatio="none" style={{ height: y }}>
          {graph.bars.map((b, i) => { const p = pos[b.lane]; if (!p) return null; const yy = b.sub != null ? p.y + b.sub * 3 : p.y;
            return <rect key={i} className={`g-${b.tone}`} x={X(b.a)} y={yy} width={Math.max(3, X(b.b) - X(b.a))} height={b.sub != null ? 2.2 : p.h} rx={1} />; })}
          {graph.ticks.map((k, i) => { const p = pos[k.lane]; return p ? <rect key={`t${i}`} className={`g-${k.tone}`} x={X(k.at) - 2} y={p.y - 1} width={4} height={p.h + 2} rx={1} /> : null; })}
        </svg>
        {/* The first tick starts at the track's left edge and the last ends at its right, so none hangs outside it */}
        <div className="wk-ticks">{ticks.map((s) => <span key={s} style={{ left: `${(s / dur) * 100}%`,
          transform: `translateX(${s === 0 ? 0 : s / dur > 0.94 ? -100 : -50}%)` }}>{s} s</span>)}</div>
        <div className="wk-head-line" style={{ left: `${(clamp(at, 0, dur) / dur) * 100}%` }} />
      </div>
      <span className="wk-clock mono">{clock}</span>
    </div>
  );
}

/** A run Workings can't draw says so in place; the rest of the page carries on (there is no boundary above it). */
class Boundary extends Component<{ children: ReactNode }, { error: string | null }> {
  state = { error: null as string | null };
  static getDerivedStateFromError(e: unknown) { return { error: e instanceof Error ? e.message : String(e) }; }
  render() {
    if (!this.state.error) return this.props.children;
    return <div className="workings empty"><p className="hint">Workings couldn't draw this run ({this.state.error}). Steps still lists it.</p>
      <button type="button" className="btn small" onClick={() => this.setState({ error: null })}>Try again</button></div>;
  }
}

/** Workings: the run picked (the newest by default), drawn as it stands. `inView`: the check the 3D viewer's pilot
 *  is showing (its step number), marked on the drawing. */
export function Workings(props: { inView?: number | null; onPeek?: (peek: Peek | null, pin: boolean) => void }) {
  return <Boundary><WorkingsView {...props} /></Boundary>;
}

function WorkingsView({ inView = null, onPeek }: { inView?: number | null; onPeek?: (peek: Peek | null, pin: boolean) => void }) {
  const host = useRef<HTMLDivElement>(null), canvas = useRef<HTMLDivElement>(null), layer = useRef<HTMLDivElement>(null);
  const labels = useRef<HTMLDivElement>(null), mini = useRef<SVGSVGElement>(null), zoomText = useRef<HTMLSpanElement>(null);
  const list = useRuns(host);
  // A run picked from the list stays until a newer run starts (or the newest is picked): new work always shows.
  const [pick, setPick] = useState<number | null>(null);
  const newest = list[list.length - 1]?.id ?? null;
  useEffect(() => { setPick(null); }, [newest]);
  const run = (pick != null ? list.find((r) => r.id === pick) : undefined) ?? list[list.length - 1] ?? null;
  const [replay, setReplay] = useState<{ at: number; playing: boolean } | null>(null);
  const [speed, setSpeed] = useState(1);
  const [now, setNow] = useState(() => Date.now());
  const [showEv, setShowEv] = useState(false);
  const [follow, setFollow] = useState(true);
  const [pinned, setPinned] = useState<string | null>(null);
  const [far, setFar] = useState(false);
  const view = useRef<View>({ k: 0.85, tx: LABELS, ty: 0 });
  const followId = useRef<string | null>(null), autoFit = useRef(true), seenRun = useRef<number | null>(null);
  // Follow is read by handlers between renders: a ref beside the state the button shows.
  const following = useRef(true);
  const setFollowing = (on: boolean) => { following.current = on; setFollow(on); };
  const rects = useRef(new Map<string, Rect>()), size = useRef({ w: 0, h: 0 }), curves = useRef(new Map<string, number[][]>());
  const dots = useRef<SVGGElement>(null);
  const glideTimer = useRef<{ w: Window; id: number } | null>(null);
  const live = !!run && run.ended === null;
  const at = !run ? 0 : replay ? replay.at : run.ended ?? Math.max(0, (now - run.started) / 1000);
  const graph = useMemo(() => (run ? graphOf(run, at) : null), [run, run?.version, at]);   // eslint-disable-line react-hooks/exhaustive-deps
  // A finished run's timeline shows all of it while the drawing replays a part.
  const whole = useMemo(() => (run && run.ended !== null ? graphOf(run) : null), [run, run?.version]);   // eslint-disable-line react-hooks/exhaustive-deps

  const runId = run?.id ?? null;
  useEffect(() => { setReplay(null); setPinned(null); }, [runId]);

  // A check hovered, or pinned with a click, shows its trial in the viewer (the page decides when it may: not while
  // the pilot is driving, unless pinned). The hovered one wins while the pointer is on it; the pinned one stays.
  const [hovered, setHovered] = useState<string | null>(null);
  const peekOf = (id: string | null) => (id ? graph?.steps.find((s) => s.id === id)?.peek ?? null : null);
  const hoverPeek = peekOf(hovered), pinPeek = peekOf(pinned), shown = hoverPeek ?? pinPeek;
  const shownKey = shown ? `${shown.key}|${shown.passed}|${shown === pinPeek && !hoverPeek ? "pin" : "hover"}` : "";
  const tell = useRef(onPeek); tell.current = onPeek;
  useEffect(() => { tell.current?.(shown, !!shown && shown === pinPeek && !hoverPeek); }, [shownKey]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => { tell.current?.(null, false); }, []);

  // The clock, while the run is live or replaying: from the window the canvas is in now.
  const ticking = live || !!replay?.playing;
  useEffect(() => {
    if (!ticking) return;
    let stop = false, timer = 0, last = Date.now(), w = winOf(host.current);
    const tick = () => {
      if (stop) return;
      const t = Date.now(), dt = (t - last) / 1000; last = t;
      setNow(t);
      setReplay((r) => {
        if (!r?.playing || !run) return r;
        const end = run.ended ?? (t - run.started) / 1000, next = r.at + dt * speed;
        return next >= end ? (run.ended !== null ? null : { at: end, playing: false }) : { ...r, at: next };
      });
      w = winOf(host.current); timer = w.setTimeout(tick, 100);
    };
    timer = w.setTimeout(tick, 100);
    return () => { stop = true; w.clearTimeout(timer); };
  }, [ticking, speed, run]);

  /** Where the drawing sits in the canvas: pans, zoom, lane labels, the overview's frame. `glide`: true eases there
   *  (its timer ends the easing), false jumps (the person is dragging or zooming), unset leaves an easing running. */
  function apply(glide?: boolean) {
    const c = canvas.current, L = layer.current, g = graph;
    if (!c || !L || !g) return;
    const v = view.current, lw = c.clientWidth < 560 ? LABELS_NARROW : LABELS;
    if (glide != null) { L.classList.toggle("glide", glide); labels.current?.classList.toggle("glide", glide); }
    c.classList.toggle("narrow", c.clientWidth < 560);
    c.classList.toggle("short", c.clientHeight < 280);
    L.style.transform = `translate(${v.tx}px, ${v.ty}px) scale(${v.k})`;
    c.style.backgroundPosition = `${v.tx}px ${v.ty}px`; c.style.backgroundSize = `${20 * v.k}px ${20 * v.k}px`;
    if (labels.current) {
      labels.current.style.width = `${lw}px`; labels.current.classList.toggle("narrow", lw === LABELS_NARROW);
      let y = 0;
      for (const [i, el] of [...labels.current.children].entries()) {
        const lane = g.lanes[i]; if (!lane) continue;
        (el as HTMLElement).style.transform = `translateY(${v.ty + y * v.k}px)`; (el as HTMLElement).style.height = `${lane.h * v.k}px`;
        el.classList.toggle("small", lane.h * v.k < 46); y += lane.h;
      }
    }
    if (zoomText.current) zoomText.current.textContent = `${Math.round(v.k * 100)}%`;
    const vp = mini.current?.querySelector(".vp");
    if (vp) { vp.setAttribute("x", `${-v.tx / v.k}`); vp.setAttribute("y", `${-v.ty / v.k}`); vp.setAttribute("width", `${c.clientWidth / v.k}`); vp.setAttribute("height", `${c.clientHeight / v.k}`); }
    if ((v.k < FAR) !== far) setFar(v.k < FAR);
    // One easing at a time: a newer glide restarts the clock, so an older one's timer never cuts it short.
    if (glide != null && glideTimer.current) { glideTimer.current.w.clearTimeout(glideTimer.current.id); glideTimer.current = null; }
    if (glide) { const w = winOf(c); glideTimer.current = { w, id: w.setTimeout(() => { glideTimer.current = null; L.classList.remove("glide"); labels.current?.classList.remove("glide"); }, 650) }; }
  }
  const labelsWidth = () => ((canvas.current?.clientWidth ?? 800) < 560 ? LABELS_NARROW : LABELS);
  function fit() {
    const c = canvas.current, g = graph; if (!c || !g || !c.clientWidth) return;
    const W = GX + g.cols.reduce((a, b) => a + b, 0) + 20, H = g.lanes.reduce((a, l) => a + l.h, 0), lw = labelsWidth();
    const k = clamp(Math.min((c.clientWidth - lw - 16) / W, (c.clientHeight - 16) / H), MIN_K, 1.1);
    view.current = { k, tx: lw + (c.clientWidth - lw - W * k) / 2, ty: (c.clientHeight - H * k) / 2 }; apply(true);
  }
  function glideTo(r: Rect | undefined) {
    const c = canvas.current, g = graph; if (!c || !r || !g) return;
    const H = g.lanes.reduce((a, l) => a + l.h, 0), v = view.current, lw = labelsWidth(), ch = c.clientHeight;
    const tx = lw + (c.clientWidth - lw) * 0.6 - (r.x + r.w / 2) * v.k;
    const ty = H * v.k <= ch ? (ch - H * v.k) / 2 : clamp(ch / 2 - (r.y + r.h / 2) * v.k, ch - H * v.k - 10, 10);
    view.current = { k: v.k, tx, ty }; apply(true);
  }
  function zoomAt(f: number, px: number, py: number) {
    const v = view.current, k = clamp(v.k * f, MIN_K, MAX_K), r = k / v.k;
    view.current = { k, tx: px - (px - v.tx) * r, ty: py - (py - v.ty) * r }; apply(false);
  }
  function handOver() { autoFit.current = false; if (following.current) setFollowing(false); }
  /** The zoom to follow at: the lanes' height where the canvas allows, never so small the titles can't be read. */
  function followZoom() {
    const c = canvas.current, H = graph ? graph.lanes.reduce((a, l) => a + l.h, 0) : 400;
    return clamp(((c?.clientHeight ?? 300) - 16) / H, 0.5, 0.85);
  }

  // What handlers and long-lived effects call: the latest of each (they read this render's graph).
  const act = useRef({ apply, fit, glideTo, zoomAt, handOver });
  act.current = { apply, fit, glideTo, zoomAt, handOver };
  const miniKey = useRef("");

  // After each new drawing: measure the steps, draw the edges between them, follow the newest step.
  useLayoutEffect(() => {
    const L = layer.current, g = graph; if (!L || !g) return;
    const map = new Map<string, Rect>();
    for (const el of L.querySelectorAll<HTMLElement>(".wk-step")) map.set(el.dataset.id!, { x: el.offsetLeft, y: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight });
    rects.current = map;
    for (const p of L.querySelectorAll<SVGPathElement>("path[data-edge]")) {
      const e = g.edges[Number(p.dataset.edge)], a = map.get(e.from), b = map.get(e.to);
      if (!a || !b) continue;
      const c = curve(a, b, e.fa, e.ta); p.setAttribute("d", pathOf(c)); curves.current.set(`${e.from}>${e.to}`, c);
      const label = L.querySelector<SVGTextElement>(`text[data-edge="${p.dataset.edge}"]`);
      if (label) { const m = bez(c, 0.5); label.setAttribute("x", m[0].toFixed(1)); label.setAttribute("y", (m[1] - 6).toFixed(1)); }
    }
    const key = [...map].map(([id, r]) => `${id}:${r.x},${r.y},${r.w},${r.h}`).join("|") + g.steps.map((s) => s.status).join("");
    if (mini.current && key !== miniKey.current) {
      miniKey.current = key;
      const W = GX + g.cols.reduce((x, y) => x + y, 0) + 20, H = g.lanes.reduce((x, l) => x + l.h, 0);
      mini.current.setAttribute("viewBox", `0 0 ${W} ${H}`);
      const byId = new Map(g.steps.map((s) => [s.id, s]));
      let o = "";
      for (const [id, r] of map) { const s = byId.get(id); if (s) o += `<rect x="${r.x}" y="${r.y}" width="${r.w}" height="${r.h}" rx="10" fill="${ACTOR[s.actor].color}" opacity="${s.status === "ghost" ? 0.25 : 0.7}"/>`; }
      mini.current.innerHTML = o + `<rect class="vp" vector-effect="non-scaling-stroke"/>`;
    }
    // Another run: a live one is followed from its start, a finished one shown whole.
    if (seenRun.current !== runId && canvas.current?.clientWidth) {
      seenRun.current = runId; followId.current = null; autoFit.current = true;
      if (live) { view.current.k = followZoom(); if (!following.current) setFollowing(true); }
      else { if (following.current) setFollowing(false); fit(); return; }
    }
    if (following.current) {
      let best: Step | null = null;
      for (const s of g.steps) if (s.status !== "ghost" && (!best || (s.status === "run" ? 1e6 : 0) + s.t0 >= (best.status === "run" ? 1e6 : 0) + best.t0)) best = s;
      if (best && best.id !== followId.current) { followId.current = best.id; glideTo(map.get(best.id)); }
      else apply();
    } else apply();
  }, [graph, far, showEv, pinned, follow, runId, live]);   // eslint-disable-line react-hooks/exhaustive-deps

  // The canvas's size, checked a few times a second from its own window: it changes when the panel floats, pops out,
  // is resized or comes back from behind another tab.
  useEffect(() => {
    let stop = false, timer = 0, w = winOf(host.current);
    const check = () => {
      if (stop) return;
      const c = canvas.current;
      if (c && c.clientWidth && (c.clientWidth !== size.current.w || c.clientHeight !== size.current.h)) {
        size.current = { w: c.clientWidth, h: c.clientHeight };
        if (following.current) { followId.current = null; const r = rects.current.get([...rects.current.keys()].pop() ?? ""); if (r) act.current.glideTo(r); }
        else if (autoFit.current) act.current.fit(); else act.current.apply();
      }
      w = winOf(host.current); timer = w.setTimeout(check, 300);
    };
    check();
    return () => { stop = true; w.clearTimeout(timer); };
  }, []);

  // Dots carried along the busy edges (triage's clashes on their way to a verdict), while the run is live or replaying.
  const flowing = !!graph && graph.flows.some((f) => at >= f.a && at < f.b) && (live || !!replay?.playing);
  const now$ = useRef({ graph, at });
  now$.current = { graph, at };
  useEffect(() => {
    const g = dots.current;
    if (!g) return;
    if (!flowing) { g.innerHTML = ""; return; }
    let stop = false, frame = 0, w = winOf(host.current);
    const draw = (ms: number) => {
      if (stop) return;
      let o = "";
      const { graph: gr, at: t } = now$.current;
      for (const f of gr?.flows ?? []) {
        const c = curves.current.get(`${f.from}>${f.to}`);
        if (!c || t < f.a || t >= f.b) continue;
        for (let i = 0; i < f.n; i++) { const p = bez(c, (ms / 1800 + i / f.n) % 1); o += `<circle class="${f.tone ?? ""}" cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="3.4"/>`; }
      }
      g.innerHTML = o;
      w = winOf(host.current); frame = w.requestAnimationFrame(draw);
    };
    frame = w.requestAnimationFrame(draw);
    return () => { stop = true; w.cancelAnimationFrame(frame); };
  }, [flowing]);

  // Zooming with the wheel takes the page's scroll there: a listener that may prevent it (React's is passive).
  const drawn = !!run && !!graph;
  useEffect(() => {
    const c = canvas.current; if (!c) return;
    const wheel = (e: WheelEvent) => { e.preventDefault(); act.current.handOver(); const b = c.getBoundingClientRect(); act.current.zoomAt(Math.exp(-e.deltaY * 0.0015), e.clientX - b.left, e.clientY - b.top); };
    c.addEventListener("wheel", wheel, { passive: false });
    return () => c.removeEventListener("wheel", wheel);
  }, [drawn]);

  // Dragging pans, two fingers zoom, a click on a step pins it open (and a click elsewhere lets it go).
  const pointers = useRef(new Map<number, [number, number]>());
  const drag = useRef<{ x: number; y: number; tx: number; ty: number; moved: boolean; step: string | null } | null>(null);
  const pinch = useRef<{ d: number; k: number } | null>(null);
  const down = (e: React.PointerEvent<HTMLDivElement>) => {
    if ((e.target as Element).closest(".wk-tools, .wk-mini")) return;
    e.currentTarget.setPointerCapture(e.pointerId); pointers.current.set(e.pointerId, [e.clientX, e.clientY]);
    if (pointers.current.size === 1) drag.current = { x: e.clientX, y: e.clientY, tx: view.current.tx, ty: view.current.ty, moved: false, step: (e.target as Element).closest<HTMLElement>(".wk-step")?.dataset.id ?? null };
    if (pointers.current.size === 2) { const [a, b] = [...pointers.current.values()]; pinch.current = { d: Math.hypot(a[0] - b[0], a[1] - b[1]), k: view.current.k }; drag.current = null; }
  };
  const move = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!pointers.current.has(e.pointerId)) return;
    pointers.current.set(e.pointerId, [e.clientX, e.clientY]);
    if (pinch.current && pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()], box = e.currentTarget.getBoundingClientRect();
      handOver(); zoomAt((pinch.current.k * Math.hypot(a[0] - b[0], a[1] - b[1]) / pinch.current.d) / view.current.k, (a[0] + b[0]) / 2 - box.left, (a[1] + b[1]) / 2 - box.top);
      return;
    }
    const d = drag.current; if (!d) return;
    if (!d.moved && Math.hypot(e.clientX - d.x, e.clientY - d.y) > 4) { d.moved = true; e.currentTarget.classList.add("dragging"); handOver(); }
    if (d.moved) { view.current.tx = d.tx + e.clientX - d.x; view.current.ty = d.ty + e.clientY - d.y; apply(false); }
  };
  const up = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!pointers.current.delete(e.pointerId)) return;
    if (pointers.current.size < 2) pinch.current = null;
    const d = drag.current;
    if (d && !d.moved && pointers.current.size === 0) setPinned((p) => (d.step && p !== d.step ? d.step : null));
    if (pointers.current.size === 0) { drag.current = null; e.currentTarget.classList.remove("dragging"); }
  };

  if (!run || !graph) {
    return <div className="workings empty" ref={host}><p className="hint">ORCA's work appears here as it happens: each idea from Muse, each
      geometry check, and what ORCA kept. Propose fixes for a clash to see it.</p></div>;
  }
  const W = GX + graph.cols.reduce((a, b) => a + b, 0) + 20, H = graph.lanes.reduce((a, l) => a + l.h, 0);
  const laneTop: Record<string, number> = {}; { let y = 0; for (const l of graph.lanes) { laneTop[l.id] = y; y += l.h; } }
  const colX: number[] = []; { let x = GX; for (const w of graph.cols) { colX.push(x); x += w; } }
  const byId = new Map(graph.steps.map((s) => [s.id, s]));
  const inViewId = inView != null && live ? graph.steps.find((s) => s.seq === inView)?.id ?? null : null;
  const finishedRun = run.ended !== null;
  const playing = !!replay?.playing;
  const OriginIcon = ORIGIN_ICON[run.origin];
  const you = graph.lanes[0]?.label ?? "You";
  const play = () => {
    if (playing) { setReplay((r) => r && { ...r, playing: false }); return; }
    const end = run.ended ?? at;
    setReplay((r) => ({ at: r && r.at < end - 0.05 ? r.at : 0, playing: true }));
    followId.current = null; setFollowing(true); autoFit.current = false;
  };
  return (
    <div className="workings" ref={host}>
      <div className={`wk-canvas${far ? " far" : ""}${showEv ? " show-ev" : ""}`} ref={canvas} onPointerDown={down} onPointerMove={move}
        onPointerUp={up} onPointerCancel={up} aria-label="Workings: the run as a graph" role="figure"
        onPointerOver={(e) => { if (e.pointerType !== "touch") setHovered((e.target as Element).closest<HTMLElement>(".wk-step")?.dataset.id ?? null); }}
        onPointerLeave={() => setHovered(null)}>
        <div className="wk-layer" ref={layer} style={{ width: W, height: H }}>
          {graph.lanes.map((l, i) => <div key={l.id} className={`wk-lane${i % 2 ? " alt" : ""}`} style={{ top: laneTop[l.id], height: l.h, width: W + 8000 }} />)}
          <svg className="wk-edges" width={W} height={H}>
            <defs>{(["base", "live", "ok", "fail", "ghost", "feedback"] as const).map((m) => (
              <marker key={m} id={`wk-ar-${m}`} viewBox="0 0 8 8" refX="7" refY="4" markerUnits="userSpaceOnUse" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
                <path d="M0,0.5 L8,4 L0,7.5 z" className={`wk-ar ${m}`} /></marker>))}</defs>
            {graph.edges.map((e, i) => {
              if (!byId.has(e.from) || !byId.has(e.to)) return null;
              const cls = edgeClass(e, byId.get(e.to), graph.done);
              return <path key={`${e.from}>${e.to}`} data-edge={i} className={`e ${cls}`} markerEnd={`url(#wk-ar-${cls === "seq" ? "base" : cls})`} />;
            })}
            {graph.edges.map((e, i) => e.label && byId.has(e.from) && byId.has(e.to)
              ? <text key={`l${e.from}>${e.to}`} data-edge={i} textAnchor="middle">{e.label}</text> : null)}
            <g ref={dots} />
          </svg>
          {graph.steps.map((s) => <StepView key={s.id} s={s} x={colX[s.col]} y={laneTop[s.lane] + (s.dy ?? 14)} w={graph.cols[s.col] - 40}
            inView={inViewId === s.id} pinned={pinned === s.id} peeking={!!onPeek && !!shown && s.peek?.key === shown.key} you={you} />)}
        </div>
        <div className="wk-labels" ref={labels} aria-hidden>
          {graph.lanes.map((l) => <div key={l.id} className="wk-ll" style={{ ["--c" as string]: ACTOR[l.actor].color }}>
            <div><b><i className="sw" />{l.label}</b><span>{l.sub}</span></div></div>)}
        </div>
        <div className="wk-tools">
          <button type="button" className={`wk-tbtn ${follow ? "on" : ""}`} aria-pressed={follow} data-tip="Keep the newest step in view"
            onClick={() => { const on = !follow; setFollowing(on); if (on) { followId.current = null; autoFit.current = false; if (view.current.k < FAR) view.current.k = followZoom(); } }}>
            <Crosshair size={14} aria-hidden /> Follow</button>
          <span className="wk-tgroup">
            <button type="button" aria-label="Zoom out" onClick={() => { handOver(); const c = canvas.current!; zoomAt(0.8, c.clientWidth / 2, c.clientHeight / 2); }}><Minus size={14} aria-hidden /></button>
            <span className="wk-zv" ref={zoomText}>85%</span>
            <button type="button" aria-label="Zoom in" onClick={() => { handOver(); const c = canvas.current!; zoomAt(1.25, c.clientWidth / 2, c.clientHeight / 2); }}><Plus size={14} aria-hidden /></button>
          </span>
          <button type="button" className="wk-tbtn" data-tip="Show the whole run" onClick={() => { handOver(); fit(); }}><Maximize size={14} aria-hidden /> Fit</button>
          <button type="button" className={`wk-tbtn ${showEv ? "on" : ""}`} aria-pressed={showEv} data-tip="Label each step with the stream event behind it"
            onClick={() => setShowEv((s) => !s)}><Tags size={14} aria-hidden /> Events</button>
        </div>
        <svg className="wk-mini" ref={mini} preserveAspectRatio="xMidYMid meet" aria-hidden onPointerDown={(e) => {
          const c = canvas.current!, b = e.currentTarget.getBoundingClientRect(), s = Math.min(b.width / W, b.height / H);
          const gx = (e.clientX - b.left - (b.width - W * s) / 2) / s, gy = (e.clientY - b.top - (b.height - H * s) / 2) / s;
          handOver(); view.current = { k: view.current.k, tx: c.clientWidth / 2 - gx * view.current.k, ty: c.clientHeight / 2 - gy * view.current.k }; apply(true);
        }} />
      </div>
      <div className="wk-foot">
        <label className="wk-run"><OriginIcon size={14} aria-hidden />
          <select value={run.id} onChange={(e) => { const id = Number(e.target.value); setPick(id === newest ? null : id); }} aria-label="Run">
            {[...list].reverse().map((r) => <option key={r.id} value={r.id}>
              {KIND_NAME[r.kind]}{r.title ? `: ${r.title}` : ""}{r.ended === null ? " (running)" : r.error ? " (stopped)" : ""}</option>)}
          </select></label>
        {finishedRun
          ? <button type="button" className="btn small primary" onClick={play}>{playing ? <Pause size={13} aria-hidden /> : <Play size={13} aria-hidden />}
            {playing ? " Pause" : replay ? " Play" : " Replay"}</button>
          : replay ? <button type="button" className="btn small primary" onClick={() => setReplay(null)}><Radio size={13} aria-hidden /> Back to live</button>
            : <span className="chip accent"><Radio size={12} aria-hidden /> Live</span>}
        {finishedRun && <span className="seg wk-speeds" aria-label="Replay speed">{SPEEDS.map((s) =>
          <button key={s} type="button" className={s === speed ? "on" : ""} onClick={() => setSpeed(s)}>{s}×</button>)}</span>}
        <Strip graph={whole ?? graph} at={at} onSeek={(t) => { setReplay({ at: t, playing: false }); }}
          clock={`${sec(at)}${finishedRun ? ` / ${sec(run.ended!)}` : ""}`} />
      </div>
    </div>
  );
}
