import { useEffect, useRef } from "react";
import { nearestSnap, nextSnap, type Snap } from "./layout";

/** The phone's bottom sheet bar (docs/mobile.md): a handle, a line saying what is happening with its next action,
 * and the Clashes / Fix / Chat tabs. Drag the bar (or flick it) to peek, half or full; tap the handle to step through
 * them. The panels below it are App's own panes, so nothing remounts when the sheet moves or the layout changes. */
export function SheetBar({ snap, onSnap, children }: { snap: Snap; onSnap: (s: Snap) => void; children: React.ReactNode }) {
  const bar = useRef<HTMLDivElement>(null);
  const drag = useRef<{ y: number; h: number; moved: boolean; samples: { y: number; t: number }[] } | null>(null);

  // The bar's own height is the sheet's peek height; the viewer sits above it (CSS --peek-h).
  useEffect(() => {
    const el = bar.current, app = el?.closest<HTMLElement>(".app");
    if (!el || !app) return;
    const ro = new ResizeObserver(() => app.style.setProperty("--peek-h", `${el.offsetHeight}px`));
    ro.observe(el);
    return () => { ro.disconnect(); app.style.removeProperty("--peek-h"); };
  }, []);

  // The sheet is the bar plus the open panel under it, down to the window's bottom; its height is CSS's --sheet-h, or
  // --sheet-drag while a finger moves it (both on .app, the bar's parent).
  const sheet = () => bar.current?.parentElement ?? null;
  const shown = () => window.innerHeight - (bar.current?.getBoundingClientRect().top ?? window.innerHeight);
  const heights = () => {
    const top = document.querySelector(".bar")?.getBoundingClientRect().bottom ?? 52;
    return { peek: bar.current?.offsetHeight ?? 120, half: window.innerHeight * 0.55, full: window.innerHeight - top - 8 };
  };

  function down(e: React.PointerEvent) {
    if (e.button > 0) return;
    drag.current = { y: e.clientY, h: shown(), moved: false, samples: [{ y: e.clientY, t: e.timeStamp }] };
  }
  function move(e: React.PointerEvent) {
    const d = drag.current, el = sheet();
    if (!d || !el) return;
    if (!d.moved) {
      if (Math.abs(e.clientY - d.y) < 8) return;
      d.moved = true;
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
      el.classList.add("dragging");
    }
    const hs = heights();
    const h = Math.max(hs.peek, Math.min(hs.full, d.h + d.y - e.clientY));
    el.style.setProperty("--sheet-drag", `${h}px`);
    d.samples = [...d.samples.slice(-4), { y: e.clientY, t: e.timeStamp }];
  }
  function up(e: React.PointerEvent) {
    const d = drag.current, el = sheet();
    drag.current = null;
    if (!d?.moved || !el) return;
    const first = d.samples[0], last = d.samples[d.samples.length - 1];
    const velocity = last.t > first.t ? (first.y - last.y) / (last.t - first.t) : 0;  // px/ms, up is positive
    const h = shown();
    el.classList.remove("dragging");
    el.style.removeProperty("--sheet-drag");
    onSnap(nearestSnap(h, velocity, heights(), snap));
    // A drag that started on a tab is not a tap on it.
    const target = e.currentTarget as HTMLElement;
    const swallow = (c: Event) => { c.stopPropagation(); c.preventDefault(); };
    target.addEventListener("click", swallow, { capture: true, once: true });
    setTimeout(() => target.removeEventListener("click", swallow, { capture: true }), 350);
  }

  const label = snap === "full" ? "Collapse the panel" : "Expand the panel";
  return (
    <div className="sheet-bar" ref={bar} onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up}>
      <button type="button" className="sheet-handle" aria-label={label} title={label} onClick={() => onSnap(nextSnap(snap))}
        onKeyDown={(e) => {
          if (e.key === "ArrowUp" && snap !== "full") { e.preventDefault(); onSnap(snap === "peek" ? "half" : "full"); }
          if (e.key === "ArrowDown" && snap !== "peek") { e.preventDefault(); onSnap(snap === "full" ? "half" : "peek"); }
        }}><span aria-hidden /></button>
      {children}
    </div>
  );
}
