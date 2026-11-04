import { useEffect, useRef, useState, type ReactNode } from "react";
import { loadClip } from "../stepClips";
import { useScrollProgress } from "./motion";

/**
 * Two of the landing's sections that move with the scroll: the three teams' models coming together until they clash
 * (Collide), and the loop told step by step beside one frame playing that step's recorded run (Loop).
 */

/** Where the sheets cross: a service through a beam or a wall (drawn on the top sheet once they meet). */
const HITS: [number, number][] = [[118, 96], [262, 96], [190, 150], [118, 196], [262, 196], [334, 150], [62, 150]];

/** Three teams' models as sheets of one plan, apart, then together, with their clashes lit where they meet. */
export function Collide({ reduce }: { reduce: boolean }) {
  const box = useRef<HTMLDivElement>(null);
  const p = useScrollProgress(box, 0.5);
  const t = reduce ? 1 : Math.min(1, p * 1.15);
  const gap = (1 - t) * 92;
  const met = t > 0.9;
  return (
    <div className={`lp-collide${met ? " met" : ""}`} ref={box} style={{ ["--gap" as string]: `${gap}px` }} aria-hidden>
      <div className="lp-sheets">
        <Sheet i={0} name="Architecture" cls="arch">
          <path d="M30 40H370V260H30Z M30 120H150 M190 120H260 M300 120H370 M200 40V95 M200 145V260 M110 180H200" />
        </Sheet>
        <Sheet i={1} name="Services (MEP)" cls="mep">
          <path className="duct" d="M20 96H380 M20 196H380" />
          <path className="pipe" d="M190 30V270 M62 30V270 M334 30V270" />
        </Sheet>
        <Sheet i={2} name="Structure" cls="str">
          <path className="beam" d="M118 30V270 M262 30V270 M40 150H360" />
          {[[118, 60], [262, 60], [118, 240], [262, 240], [40, 150], [360, 150]].map(([x, y]) => <rect key={`${x}-${y}`} x={x - 9} y={y - 9} width="18" height="18" />)}
        </Sheet>
        <div className="lp-sheet hits" style={{ ["--i" as string]: 3 }}>
          <svg viewBox="0 0 400 300">{HITS.map(([x, y], k) => <g key={k} style={{ ["--k" as string]: k }}><circle cx={x} cy={y} r="13" /><circle cx={x} cy={y} r="4.5" /></g>)}</svg>
        </div>
      </div>
    </div>
  );
}

function Sheet({ i, name, cls, children }: { i: number; name: string; cls: string; children: ReactNode }) {
  return (
    <div className={`lp-sheet ${cls}`} style={{ ["--i" as string]: i }}>
      <svg viewBox="0 0 400 300"><rect className="lp-sheet-bg" x="2" y="2" width="396" height="296" rx="10" />{children}</svg>
      <span className="lp-sheet-name">{name}</span>
    </div>
  );
}

export interface LoopStep {
  letter: string; word: string; title: string; points: ReactNode[];
  clip: { src: string; alt: string; caption: ReactNode; tall?: boolean };
}

/**
 * The loop in one screen (owner feedback, Nov 2: one frame, one screen high, not a clip beside each step): the four
 * steps as tabs beside one frame playing the chosen step's recorded run. It moves on as each clip ends (its length read
 * from the file, stepClips.ts), until the visitor picks a step. Nothing is fetched before the section nears the view,
 * then only the clip on screen and the next; each plays from a fresh object URL, so it starts from its first frame.
 * Less motion: each clip's last frame, and no moving on.
 */
export function Loop({ steps, reduce }: { steps: LoopStep[]; reduce: boolean }) {
  const [active, setActive] = useState(0);
  const [auto, setAuto] = useState(true);
  const [near, setNear] = useState(false);
  const [playing, setPlaying] = useState<{ src: string; url: string; ms: number | null } | null>(null);
  const [started, setStarted] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);
  const step = steps[active], count = steps.length;
  const src = step.clip.src, next = steps[(active + 1) % count].clip.src;

  useEffect(() => {
    const el = wrap.current;
    if (!el || near) return;
    if (typeof IntersectionObserver === "undefined") { setNear(true); return; }
    const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) setNear(true); },
      { root: el.closest(".lp-page"), rootMargin: "0px 0px -20% 0px", threshold: 0.2 });
    io.observe(el);
    return () => io.disconnect();
  }, [near]);

  useEffect(() => {
    if (!near || reduce) return;
    let live = true, made: string | null = null;
    setStarted(false);
    void loadClip(`${src}.webp`).then((c) => {
      if (!live) return;
      made = c ? URL.createObjectURL(c.blob) : null;
      setPlaying({ src, url: made ?? `${src}.webp`, ms: c?.ms ?? null });
      void loadClip(`${next}.webp`);
    });
    return () => { live = false; if (made) { const m = made; window.setTimeout(() => URL.revokeObjectURL(m), 1500); } };
  }, [near, reduce, src, next]);

  useEffect(() => {
    if (!auto || reduce || !started || !playing?.ms || playing.src !== src) return;
    const t = window.setTimeout(() => setActive((i) => (i + 1) % count), playing.ms);
    return () => window.clearTimeout(t);
  }, [auto, reduce, started, playing, src, count]);

  const pick = (i: number, focus = false) => { setAuto(false); setActive(i); if (focus) tabs.current[i]?.focus(); };
  const onKey = (e: React.KeyboardEvent) => {
    const d = ["ArrowDown", "ArrowRight"].includes(e.key) ? 1 : ["ArrowUp", "ArrowLeft"].includes(e.key) ? -1 : 0;
    if (!d) return;
    e.preventDefault();
    pick((active + d + count) % count, true);
  };
  const live = !reduce && playing?.src === src ? playing : null;
  return (
    <div className="lp-loop" ref={wrap}>
      <div className="lp-loop-tabs" role="tablist" aria-label="Observe, Resolve, Check, Apply" aria-orientation="vertical" onKeyDown={onKey}>
        {steps.map((s, i) => {
          const on = i === active;
          return (
            <div key={s.word} className={`lp-loop-step${on ? " on" : ""}`}>
              <button type="button" role="tab" id={`lp-loop-tab-${i}`} aria-selected={on} aria-controls="lp-loop-panel" tabIndex={on ? 0 : -1}
                ref={(el) => { tabs.current[i] = el; }} onClick={() => pick(i)}>
                <span className="lp-loop-letter" aria-hidden>{s.letter}</span>
                <span className="lp-loop-head"><b>{s.word}</b><span>{s.title}</span></span>
              </button>
              {on && <ul className="lp-loop-points">{s.points.map((x, k) => <li key={k}>{x}</li>)}</ul>}
              {on && auto && live?.ms && started && <span className="lp-loop-progress" aria-hidden><i key={live.url} style={{ animationDuration: `${live.ms}ms` }} /></span>}
            </div>
          );
        })}
      </div>
      <figure className="lp-loop-frame" role="tabpanel" id="lp-loop-panel" aria-labelledby={`lp-loop-tab-${active}`}>
        <div className={`lp-frame${step.clip.tall ? " tall" : ""}`}>
          <div className="lp-frame-bar" aria-hidden><i /><i /><i /><span>ORCA · Northbank</span><em>{step.word}</em></div>
          <div className="lp-frame-screen">
            {live
              ? <img key={live.url} src={live.url} alt={step.clip.alt} onLoad={() => setStarted(true)} />
              : <img key={step.clip.src} src={`${step.clip.src}-still.webp`} alt={step.clip.alt} loading="lazy" decoding="async" />}
          </div>
        </div>
        <figcaption key={active}>{step.clip.caption}</figcaption>
      </figure>
    </div>
  );
}
