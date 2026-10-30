import { ChevronDown, ChevronUp, Copy, Magnet, Trash2, X } from "lucide-react";
import { useRef, useState } from "react";
import { copyLine, copyText, measureText, type Measurement } from "./viewer/measure";

/** The Measure panel (docs/measure.md): snapping on or off, what to click next, and the measurements taken, each to
 * copy or delete; Copy all and Clear all. Beside the rail while the tool is on; its header drags it out of the way
 * (`at`, kept by the page) and folds it to one line. */
export function MeasurePanel({ measures, open, snap, coarse, at, onMove, onSnap, onCopy, onRemove, onClear, onClose }: {
  measures: readonly Measurement[]; open: boolean; snap: boolean; coarse: boolean; at: { x: number; y: number } | null;
  onMove: (at: { x: number; y: number }) => void; onSnap: (on: boolean) => void; onCopy: (text: string, what: string) => void;
  onRemove: (id: number) => void; onClear: () => void; onClose: () => void;
}) {
  const [folded, setFolded] = useState(false);
  const ref = useRef<HTMLElement>(null);
  const stop = (e: React.SyntheticEvent) => e.stopPropagation();
  const act = coarse ? "Tap" : "Click";
  const drag = (e: React.PointerEvent) => {
    const el = ref.current, host = el?.offsetParent as HTMLElement | null;
    if (coarse || !el || !host || (e.target as HTMLElement).closest("button")) return;
    e.preventDefault();
    const r = el.getBoundingClientRect(), h = host.getBoundingClientRect(), dx = e.clientX - r.left, dy = e.clientY - r.top;
    const clamp = (v: number, hi: number) => Math.max(0, Math.min(v, Math.max(hi, 0)));
    const move = (m: PointerEvent) => onMove({ x: clamp(m.clientX - h.left - dx, h.width - r.width), y: clamp(m.clientY - h.top - dy, h.height - 40) });
    // Capture phase: the panel stops pointer moves (no snapping under it), and React stops them before the window.
    const up = () => { for (const [k, f] of [["pointermove", move], ["pointerup", up], ["pointercancel", up]] as const) window.removeEventListener(k, f as EventListener, true); };
    window.addEventListener("pointermove", move, true);
    window.addEventListener("pointerup", up, true);
    window.addEventListener("pointercancel", up, true);
  };
  return (
    <section ref={ref} className={`measure-panel ${folded ? "folded" : ""}`} aria-label="Measure" style={at && !coarse ? { left: at.x, top: at.y } : undefined}
      onClick={stop} onDoubleClick={stop} onPointerDown={stop} onPointerMove={stop}>
      <header onPointerDown={drag} title={coarse ? undefined : "Drag to move"}>
        <b>Measure{measures.length ? <span className="count"> · {measures.length}</span> : null}</b>
        <button type="button" className={`btn small snap-toggle ${snap ? "on" : ""}`} aria-pressed={snap} onClick={() => onSnap(!snap)}
          data-tip="Snap to corners, midpoints and edges" data-tip-side="bottom"><Magnet size={13} aria-hidden /> Snap{coarse ? "" : <kbd>N</kbd>}</button>
        <button type="button" className="ibtn" aria-label={folded ? "Show the measurements" : "Fold the panel"} data-tip={folded ? "Show the measurements" : "Fold"} data-tip-side="bottom"
          onClick={() => setFolded((f) => !f)}>{folded ? <ChevronDown size={14} aria-hidden /> : <ChevronUp size={14} aria-hidden />}</button>
        <button type="button" className="ibtn" aria-label="Stop measuring" data-tip="Stop measuring (M)" data-tip-side="bottom" onClick={onClose}><X size={14} aria-hidden /></button>
      </header>
      {!folded && <><p className="hint">{open ? `${act} the second point${coarse ? "." : " · Esc drops the first."}` : `${act} a first point, in the 3D view or any drawing.`}</p>
      {measures.length > 0 && (<>
        <ol className="measure-list">
          {measures.map((m) => {
            const t = measureText(m);
            return (
              <li key={m.id}>
                <span className="measure-name"><b>M{m.id}</b> <span className="mono">{t.length}</span></span>
                <small>{m.view} · {t.parts}</small>
                <span className="measure-acts">
                  <button type="button" className="ibtn" aria-label={`Copy M${m.id}`} data-tip="Copy" data-tip-side="bottom" onClick={() => onCopy(copyLine(m), `M${m.id}`)}><Copy size={13} aria-hidden /></button>
                  <button type="button" className="ibtn" aria-label={`Delete M${m.id}`} data-tip="Delete" data-tip-side="bottom" onClick={() => onRemove(m.id)}><Trash2 size={13} aria-hidden /></button>
                </span>
              </li>);
          })}
        </ol>
        <footer>
          <button type="button" className="btn small" onClick={() => onCopy(copyText([...measures]), measures.length === 1 ? "the measurement" : `${measures.length} measurements`)}><Copy size={13} aria-hidden /> Copy all</button>
          <button type="button" className="btn small" onClick={onClear}><Trash2 size={13} aria-hidden /> Clear all</button>
        </footer>
      </>)}</>}
    </section>
  );
}
