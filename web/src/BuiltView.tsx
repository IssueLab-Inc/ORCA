import { useRef, useState } from "react";
import { Building2, ChevronsLeftRight, Info, PenLine, RotateCcw, ShieldCheck } from "lucide-react";
import type { BuiltEvent, BuiltResult } from "./api";
import { aiName } from "./aiNames";

/** Show it built (docs/show-it-built.md): one fix's picture, while it is drawn and checked, then beside ORCA's view. */
export interface BuiltRun {
  status: "working" | "done" | "failed";
  step: string;          // what is happening now, in words
  look: string;          // ORCA's own view of the fix (a data URL): what the picture is checked against
  cut: string;           // what the cutaway took away for the view, in words ("" when nothing)
  result?: BuiltResult;
  error?: string;        // the request failed (switched off, capped, the server)
}

/** A stream event in words, for the status line. */
export function builtStep(e: BuiltEvent): string {
  switch (e.type) {
    case "drawing": return e.shared ? "This view is already being drawn: waiting for that picture…"
      : e.round === 1 ? `${aiName("image")} is drawing two pictures from ORCA's view…` : "Drawing two more, told what the judges found…";
    case "gate": return e.passed ? `Picture ${e.picture} keeps to the model's outline; the judges look next…`
      : e.error ? `Picture ${e.picture} failed: ${e.error}` : `Picture ${e.picture} strayed from the model's outline: dropped`;
    case "judging": return `The judges are comparing picture ${e.picture} with the model view…`;
    case "judged": return `Picture ${e.picture}: ${e.verdicts.every((v) => v === "faithful" || v === "minor_differences")
      ? "every judge calls it faithful" : "a judge found a change, so it is dropped"}`;
    case "retry": return `The judges found: ${e.why}. Drawing again…`;
    default: return "Working…";
  }
}

/** What a cutaway took away, by kind: "2 coverings and a slab (cut at)". */
export function cutText(cut: string[], sectioned: string[], classOf: (gid: string) => string | undefined): string {
  const count = (ids: string[]) => {
    const n = new Map<string, number>();
    for (const g of ids) { const k = (classOf(g) ?? "element").replace(/^Ifc/, "").replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase(); n.set(k, (n.get(k) ?? 0) + 1); }
    return [...n].map(([k, v]) => v === 1 ? `a ${k}` : `${v} ${k}s`);
  };
  const parts = [...count(cut.filter((g) => !sectioned.includes(g)))];
  if (sectioned.length) parts.push(`${count(sectioned).join(", ")} (cut through by the section)`);
  return parts.length ? `Taken away for the view: ${parts.join(", ")}.` : "";
}

/** Where a pointer at `x` puts the wipe on a picture from `left`, `width` wide: a share of it from the left, 0 to 100. */
export function wipeAt(x: number, left: number, width: number): number {
  return width > 0 ? Math.min(100, Math.max(0, ((x - left) / width) * 100)) : 50;
}

const verdictText = (r: BuiltResult) => (r.verdicts ?? []).map((v) => v.verdict.replace("_", " ")).join(" and ");

/** The picture over ORCA's view with a wipe between them, the model's lines on top when asked, and what checked it.
 * `reopen`: the server let go of the models, so a failed picture offers to open them again instead of trying again. */
export function BuiltView({ run, onRetry, reopen }: { run: BuiltRun; onRetry?: () => void; reopen?: { label: string; onClick: () => void } }) {
  const [wipe, setWipe] = useState(50);   // both sides at once: what is drawn beside what the model has
  const [lines, setLines] = useState(false);
  const [dragging, setDragging] = useState(false);
  const pressed = useRef(50);   // the wipe when the press began
  const r = run.result;
  if (run.status === "working") return (
    <div className="built working" role="status">
      {run.look && <img className="built-look" src={run.look} alt="ORCA's view of the fix, being restyled" />}
      <p><i className="spinner" aria-hidden /> {run.step}</p>
      <p className="hint">About a minute: two pictures are drawn, each checked against the model's outline and by the judges.</p>
    </div>);
  if (run.status === "failed" || !r || r.status !== "done" || !r.image_url) return (
    <div className="built failed" role="status">
      <p><b>No built view.</b> {run.error ?? r?.why ?? `${aiName("image")} couldn't keep to the model here.`}</p>
      <p className="hint">ORCA's own views of the fix stand; the model is the record.</p>
      {reopen ? <button className="btn small" onClick={reopen.onClick}><RotateCcw size={13} aria-hidden /> {reopen.label}</button>
        : onRetry && <button className="btn small" onClick={onRetry}><RotateCcw size={13} aria-hidden /> Try again</button>}
    </div>);
  const judge = r.judge ?? aiName("escalation");
  const check = `Checked against the model: outline match ${r.gate ? r.gate.f.toFixed(2) : "?"}${verdictText(r) ? `; ${judge} judges: ${verdictText(r)}` : ""}`
    + `${judge !== aiName("escalation") ? ` (the lighter check: today's ${aiName("escalation")} budget was spent)` : ""}${r.cached ? " (drawn before)" : ""}.`;
  // The picture is left of the wipe, ORCA's view right of it, each side with its name cut at the wipe like the picture.
  // Drag on the picture (or click) to move the wipe; the handle says it moves; a focused picture takes the arrow keys.
  // The check is a labelled chip (its numbers in the tip), the label one block beside its icon: in a narrow panel nothing
  // wraps onto a line of its own.
  const wiping = !!run.look;
  const wipeTo = (e: React.PointerEvent<HTMLDivElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    setWipe(wipeAt(e.clientX, box.left, box.width));
  };
  const keys: Record<string, (w: number) => number> = { ArrowLeft: (w) => w - 5, ArrowRight: (w) => w + 5, ArrowDown: (w) => w - 5,
    ArrowUp: (w) => w + 5, PageDown: (w) => w - 20, PageUp: (w) => w + 20, Home: () => 0, End: () => 100 };
  const left = `inset(0 ${100 - wipe}% 0 0)`, right = `inset(0 0 0 ${wipe}%)`;
  return (
    <figure className="built done">
      <div className={`built-stage ${wiping ? "wiping" : ""} ${dragging ? "dragging" : ""}`}
        {...(wiping ? {
          role: "slider", tabIndex: 0, "aria-label": "Drag to compare the illustration (left) with ORCA's view (right)",
          "aria-valuemin": 0, "aria-valuemax": 100, "aria-valuenow": Math.round(wipe),
          "aria-valuetext": `${Math.round(wipe)}% illustration, ${Math.round(100 - wipe)}% ORCA's view`,
          // A mouse or pen moves the wipe where it presses; a finger only once it moves, and a swipe the browser takes
          // as a scroll (pan-y: up and down) puts the wipe back where it was.
          onPointerDown: (e: React.PointerEvent<HTMLDivElement>) => {
            if (e.button !== 0) return;
            try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* the drag still follows over the picture */ }
            pressed.current = wipe;
            setDragging(true);
            if (e.pointerType !== "touch") { wipeTo(e); e.preventDefault(); }
          },
          onPointerMove: (e: React.PointerEvent<HTMLDivElement>) => { if (dragging) wipeTo(e); },
          onPointerUp: () => setDragging(false),
          onPointerCancel: () => { setDragging(false); setWipe(pressed.current); },
          onKeyDown: (e: React.KeyboardEvent<HTMLDivElement>) => {
            const step = keys[e.key];
            if (step) { e.preventDefault(); setWipe((w) => Math.min(100, Math.max(0, step(w)))); }
          },
        } : {})}>
        {wiping && <div className="built-side" style={{ clipPath: right }}>
          <img className="built-under" src={run.look} alt="ORCA's view of the fix" draggable={false} />
          <span className="built-tag right" aria-hidden>ORCA's view</span>
        </div>}
        <div className="built-side" style={wiping ? { clipPath: left } : undefined}>
          <img className="built-pic" src={r.image_url} alt="The fix as it could look built: an illustration" draggable={false} />
          {wiping && <span className="built-tag left" aria-hidden>Built</span>}
        </div>
        {lines && r.lines_url && <img className="built-lines" src={r.lines_url} alt="" aria-hidden draggable={false} />}
        {wiping && <span className="built-wipe" style={{ left: `${wipe}%` }} aria-hidden>
          <span className="built-knob"><ChevronsLeftRight size={14} /></span></span>}
      </div>
      <div className="built-tools">
        {r.lines_url && <button className={`btn small ${lines ? "on" : ""}`} aria-pressed={lines} onClick={() => setLines(!lines)}
          data-tip="Draw the model's own outline over the picture, to see that it matches"><PenLine size={13} aria-hidden /> Lines from the model</button>}
        <span className="built-check" tabIndex={0} aria-label={check} data-tip={check}>
          <ShieldCheck size={13} aria-hidden /> Checked against the model <Info size={12} aria-hidden /></span>
      </div>
      <figcaption>
        <Building2 size={13} aria-hidden />
        <div>
          <p>Illustration by {aiName("image")} from ORCA's model view. The model is the record.</p>
          {run.cut && <p className="hint">{run.cut}</p>}
        </div>
      </figcaption>
    </figure>);
}
