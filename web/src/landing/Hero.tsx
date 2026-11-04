import { ArrowDown, Check, Download, Pause, Play, Upload, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { HeroScene, webglAvailable } from "./heroScene";
import { CHAPTERS, LOOP, PHASES, STILL, chapterStill, heroAt, logAt, type HeroFrame, type LogLine, type Phase } from "./timeline";
import { RUNS } from "./northbank";
import { mm } from "./check";

/** What the hero's buttons do (from About's `start`). */
export interface HeroActions {
  disabled: boolean;
  onGolden?: () => void;
  onBlank?: () => void;
  onDemos: () => void;
}

/** The labels a frame shows, as a string that only changes when one does (so React redraws them rarely). */
function labelState(f: HeroFrame): string {
  const pins = RUNS.map((r) => `${r.key}:${f.runs[r.key].pin}:${f.runs[r.key].clearance > 0.05 ? 1 : 0}`).join(",");
  return `${pins}|focus:${f.focus}|hits:${f.hits > 0 ? 1 : 0}|girder:${f.t < 4.4 || f.finale > 0 ? 1 : 0}|exp:${f.exports}`;
}

/**
 * The landing's first screen: the promise and the way in on the left; on the right (behind, on a wide screen) the
 * live 3D replay of ORCA fixing Northbank's three girder clashes, with its phase, its log and chapter buttons. The
 * replay pauses off screen; people who ask for less motion get its last frame, and the chapters as stills. Without
 * WebGL it shows a recorded frame of the real app instead.
 */
export function Hero({ actions, reduce, resume }: { actions: HeroActions; reduce: boolean; resume?: ReactNode }) {
  const stage = useRef<HTMLDivElement>(null);
  const glHost = useRef<HTMLDivElement>(null);
  const win = useRef<HTMLDivElement>(null);
  const labels = useRef<Map<string, HTMLElement>>(new Map());
  const bar = useRef<HTMLElement | null>(null);
  const [gl] = useState(() => typeof document !== "undefined" && webglAvailable());
  const [failed, setFailed] = useState(false);
  const [playing, setPlaying] = useState(!reduce);
  const [frame, setFrame] = useState<{ phase: Phase; chapter: number; log: LogLine[]; labels: string; f: HeroFrame }>(() => {
    const f = heroAt(reduce ? STILL : 0);
    return { phase: f.phase, chapter: f.chapter, log: logAt(f.t), labels: labelState(f), f };
  });
  const ctl = useRef({ t: reduce ? STILL : 0, drift: 0, playing: !reduce, visible: true, kick: () => {}, scene: null as HeroScene | null });

  useEffect(() => { ctl.current.playing = playing; ctl.current.kick(); }, [playing]);
  useEffect(() => { if (reduce) setPlaying(false); }, [reduce]);

  useEffect(() => {
    const host = stage.current, holder = glHost.current;
    if (!gl || !host || !holder) return;
    // A canvas of its own each time: a context given back on unmount (forceContextLoss) stays lost on its canvas.
    const el = document.createElement("canvas");
    el.setAttribute("aria-hidden", "true");
    holder.appendChild(el);
    let scene: HeroScene;
    try { scene = new HeroScene(el); } catch { el.remove(); setFailed(true); return; }
    const c = ctl.current;
    c.scene = scene;
    let raf = 0, last = performance.now(), shown = "";
    // The subject is framed in the HUD's empty window, wherever the layout puts it.
    const resize = () => {
      const s = host.getBoundingClientRect(), w = win.current?.getBoundingClientRect();
      const box = w && w.width > 0 && w.height > 0 && s.width > 0 && s.height > 0
        ? { x: (w.left + w.width / 2 - s.left) / s.width, y: (w.top + w.height / 2 - s.top) / s.height, w: w.width / s.width, h: w.height / s.height }
        : undefined;
      scene.setSize(s.width, s.height, box);
      draw(0);
    };
    const place = (f: HeroFrame) => {
      for (const a of scene.anchors(f)) {
        const node = labels.current.get(a.id);
        if (!node) continue;
        const p = scene.project(a.at);
        node.style.transform = p ? `translate(${p.x.toFixed(1)}px, ${p.y.toFixed(1)}px)` : "translate(-9999px, 0)";
      }
    };
    const draw = (dt: number) => {
      const f = heroAt(c.t);
      scene.render(f, dt, c.drift);
      holder.style.opacity = String(1 - f.fade);
      place(f);
      const sig = `${f.phase}|${f.chapter}|${logAt(f.t).length}:${logAt(f.t).at(-1)?.at}|${labelState(f)}`;
      if (sig !== shown) { shown = sig; setFrame({ phase: f.phase, chapter: f.chapter, log: logAt(f.t), labels: labelState(f), f }); }
      if (bar.current) {
        const ch = CHAPTERS[f.chapter], next = CHAPTERS[f.chapter + 1]?.at ?? LOOP;
        bar.current.style.setProperty("--p", String(Math.min(1, (f.t - ch.at) / (next - ch.at))));
      }
    };
    const tick = (now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      if (c.playing) { c.t = (c.t + dt) % LOOP; c.drift += dt; }
      draw(dt);
      raf = c.playing && c.visible ? requestAnimationFrame(tick) : 0;
    };
    c.kick = () => {
      if (!raf && c.playing && c.visible) { last = performance.now(); raf = requestAnimationFrame(tick); }
      else if (!c.playing) draw(0.016);
    };
    const ro = new ResizeObserver(resize);
    ro.observe(host);
    if (win.current) ro.observe(win.current);
    const io = typeof IntersectionObserver !== "undefined"
      ? new IntersectionObserver(([e]) => { c.visible = e.isIntersecting; c.kick(); }, { threshold: 0.02 }) : null;
    io?.observe(host);
    const vis = () => { c.visible = document.visibilityState === "visible"; c.kick(); };
    document.addEventListener("visibilitychange", vis);
    resize();
    c.kick();
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect(); io?.disconnect();
      document.removeEventListener("visibilitychange", vis);
      c.scene = null; c.kick = () => {};
      scene.dispose();
      el.remove();
    };
  }, [gl]);

  // Drag to look round; a vertical swipe still scrolls the page (touch-action: pan-y).
  const drag = useRef<{ x: number; y: number; id: number } | null>(null);
  const onDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    drag.current = { x: e.clientX, y: e.clientY, id: e.pointerId };
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };
  const onMove = (e: React.PointerEvent) => {
    const d = drag.current, s = ctl.current.scene;
    if (!d || d.id !== e.pointerId || !s) return;
    s.orbit.yaw = Math.max(-1.1, Math.min(1.1, s.orbit.yaw - (e.clientX - d.x) * 0.006));
    s.orbit.pitch = Math.max(-0.3, Math.min(0.55, s.orbit.pitch + (e.clientY - d.y) * (e.pointerType === "touch" ? 0 : 0.004)));
    d.x = e.clientX; d.y = e.clientY;
    if (!ctl.current.playing) ctl.current.kick();
  };
  const onUp = () => { drag.current = null; };

  const jump = (i: number) => {
    const c = ctl.current;
    c.t = reduce || !playing ? chapterStill(i) : CHAPTERS[i].at;
    c.kick();
  };

  const { f } = frame;
  const label = (id: string, node: ReactNode, cls: string, show: boolean) => (
    <div key={id} className={`lp-tag ${cls}${show ? " on" : ""}`} ref={(el) => { if (el) labels.current.set(id, el); else labels.current.delete(id); }}>
      <div className="lp-tag-in">{node}</div>
    </div>
  );
  const live = gl && !failed;
  return (
    <section className="lp-hero" data-tone="dark" aria-labelledby="lp-hero-title">
      <div className={`lp-hero-stage${live ? "" : " still"}`} ref={stage} onPointerDown={live ? onDown : undefined}
        onPointerMove={live ? onMove : undefined} onPointerUp={onUp} onPointerCancel={onUp}>
        {live ? <div className="lp-hero-gl" ref={glHost} /> : (
          <img className="lp-hero-fallback" src="/demos/fix-northbank-still.webp" width={1000} height={625}
            alt="ORCA's viewer on Northbank's clash #1: the supply air duct raised 400 mm through the transfer girder's web opening, clear by 50 mm." />
        )}
        {live && <div className="lp-tags" aria-hidden>
          {RUNS.map((r) => {
            const s = f.runs[r.key], quiet = f.focus !== "all" && f.focus !== r.key;
            // a kept fix's pin says how far it moved and, while its chapter lasts, the room the check measured; the pins
            // of the clashes not being told stay short, and each opens away from its neighbours (the tray's, north of
            // the duct, to the right; the others to the left), so none covers another
            return label(`pin-${r.key}`, s.pin === "fixed"
              ? <><Check size={12} strokeWidth={3} aria-hidden />#{r.number} <b>{mm(r.fix.dz, true)}</b>
                {s.clearance > 0.05 && <em>{mm(r.clear)} {r.key === "duct" ? "all round" : "clear"}</em>}</>
              : <><i className="lp-ping" />#{r.number} <b>{mm(r.overlap, true)}</b></>,
              `pin ${s.pin} ${r.key === "tray" ? "r" : "l"}${quiet ? " quiet" : ""}`, s.pin !== "hidden");
          })}
          {[0, 1, 2].map((i) => label(`hit-${i}`, <X size={12} strokeWidth={3} aria-hidden />, "hit", f.hits > 0))}
          {label("girder", <>TB-L02-01 · transfer girder, 1000 deep</>, "note", f.t < 4.4 || f.finale > 0)}
        </div>}
      </div>
      <div className="lp-hero-scrim" aria-hidden />

      <div className="lp-hero-inner">
        <div className="lp-hero-copy">
          {resume}
          <p className="lp-eyebrow">ORCA · AI design coordination</p>
          <h1 id="lp-hero-title">Fixes, not just findings.<span>Every fix proven before you see it.</span></h1>
          <p className="lp-hero-lede">
            For the design coordinator, who makes every team's 3D design fit together. Where two designs conflict, ORCA
            proposes a fix as a real edit to the model, and proves it with geometry before anyone sees it.
          </p>
          <div className="lp-cta">
            {actions.onGolden && <button className="lp-btn primary" data-tour="golden" disabled={actions.disabled} onClick={actions.onGolden}>
              <Play size={16} aria-hidden /> Watch ORCA fix a clash</button>}
            {actions.onBlank && <button className="lp-btn glass" data-tour="blank" onClick={actions.onBlank}>
              <Upload size={16} aria-hidden /> Use your own models</button>}
            <a className="lp-link" href="#demos" onClick={(e) => { e.preventDefault(); actions.onDemos(); }}>
              Pick a demo <ArrowDown size={15} aria-hidden /></a>
          </div>
          <p className="lp-hero-meta"><span>Buildings and machines</span><span>IFC and STEP in</span><span>Edited IFC and STEP, PDF and BCF out</span></p>
        </div>

        <div className="lp-hud" aria-hidden={!live}>
          {live && <div className="lp-hud-top">
              <ol className="lp-phases" aria-label="Observe, Resolve, Check, Apply">
                {PHASES.map((p) => <li key={p.id} className={frame.phase === p.id ? "on" : ""}><b>{p.word[0]}</b>{p.word.slice(1)}</li>)}
              </ol>
              <span className={`lp-export${f.exports ? " on" : ""}`}><Download size={13} aria-hidden /> Export IFC
                {f.exports > 0 && <em key={f.exports}><Check size={10} strokeWidth={3} aria-hidden />{f.exports}</em>}</span>
          </div>}
          <div className="lp-hud-window" ref={win} aria-hidden />
          {live && <>
            <ol className="lp-log" aria-live="off">
              {frame.log.map((l, i) => (
                <li key={l.at} className={`${l.tone}${i === frame.log.length - 1 ? " new" : ""}`}>
                  <span className="lp-log-tag">{l.phase}</span><span className="lp-log-text">{l.text}</span>
                </li>
              ))}
            </ol>
            <div className="lp-hud-foot">
              <div className="lp-chapters" ref={(el) => { bar.current = el; }}>
                <button type="button" className="lp-play" onClick={() => setPlaying((p) => !p)} aria-label={playing ? "Pause the replay" : "Play the replay"}>
                  {playing ? <Pause size={14} aria-hidden /> : <Play size={14} aria-hidden />}</button>
                {CHAPTERS.map((c, i) => (
                  <button key={c.label} type="button" className={frame.chapter === i ? "on" : ""} onClick={() => jump(i)}>
                    {c.label}{frame.chapter === i && playing && <i aria-hidden />}</button>
                ))}
              </div>
              <p className="lp-hud-note">Replay, sped up, drawn from Northbank's own geometry. Drag to look round.</p>
            </div>
          </>}
        </div>
      </div>
      <p className="lp-sr">
        A replay of ORCA on Northbank, a demo office building: the check finds 464 clashes in 1,732 elements; three real
        ones are on one Level 02 transfer girder. Muse Spark proposes raising the supply air duct 400 mm through the
        girder's web opening; the geometry check finds it clear by 50 mm all round, and it is kept. Moving the whole
        cable tray fails on the return air spigots, so the stretch at the girder is offset 250 mm instead; the cold water
        main is offset 280 mm. All three land at the designer's own heights.
      </p>
    </section>
  );
}
