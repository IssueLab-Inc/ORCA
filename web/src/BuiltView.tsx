import { useState } from "react";
import { Building2, Info, PenLine, RotateCcw } from "lucide-react";
import type { BuiltEvent, BuiltResult } from "./api";

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
      : e.round === 1 ? "Muse Image is drawing two pictures from ORCA's view…" : "Drawing two more, told what the judges found…";
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

const verdictText = (r: BuiltResult) => (r.verdicts ?? []).map((v) => v.verdict.replace("_", " ")).join(" and ");

/** The picture over ORCA's view with a wipe between them, the model's lines on top when asked, and what checked it.
 * `reopen`: the server let go of the models, so a failed picture offers to open them again instead of trying again. */
export function BuiltView({ run, onRetry, reopen }: { run: BuiltRun; onRetry?: () => void; reopen?: { label: string; onClick: () => void } }) {
  const [wipe, setWipe] = useState(100);
  const [lines, setLines] = useState(false);
  const r = run.result;
  if (run.status === "working") return (
    <div className="built working" role="status">
      {run.look && <img className="built-look" src={run.look} alt="ORCA's view of the fix, being restyled" />}
      <p><i className="spinner" aria-hidden /> {run.step}</p>
      <p className="hint">About a minute: two pictures are drawn, each checked against the model's outline and by the judges.</p>
    </div>);
  if (run.status === "failed" || !r || r.status !== "done" || !r.image_url) return (
    <div className="built failed" role="status">
      <p><b>No built view.</b> {run.error ?? r?.why ?? "Muse Image couldn't keep to the model here."}</p>
      <p className="hint">ORCA's own views of the fix stand; the model is the record.</p>
      {reopen ? <button className="btn small" onClick={reopen.onClick}><RotateCcw size={13} aria-hidden /> {reopen.label}</button>
        : onRetry && <button className="btn small" onClick={onRetry}><RotateCcw size={13} aria-hidden /> Try again</button>}
    </div>);
  const judge = r.judge ?? "Muse Wonder";
  const check = `Checked against the model: outline match ${r.gate ? r.gate.f.toFixed(2) : "?"}${verdictText(r) ? `; ${judge} judges: ${verdictText(r)}` : ""}`
    + `${judge !== "Muse Wonder" ? " (the lighter check: today's Muse Wonder budget was spent)" : ""}${r.cached ? " (drawn before)" : ""}.`;
  return (
    <figure className="built done">
      <div className="built-stage">
        {run.look && <img className="built-under" src={run.look} alt="ORCA's view of the fix" />}
        <img className="built-pic" src={r.image_url} alt="The fix as it could look built: an illustration"
          style={{ clipPath: `inset(0 ${100 - wipe}% 0 0)` }} />
        {lines && r.lines_url && <img className="built-lines" src={r.lines_url} alt="" aria-hidden />}
        {run.look && wipe > 0 && wipe < 100 && <span className="built-wipe" style={{ left: `${wipe}%` }} aria-hidden />}
      </div>
      <div className="built-tools">
        {run.look && <label className="built-slider"><span>ORCA's view</span>
          <input type="range" min={0} max={100} value={wipe} onChange={(e) => setWipe(Number(e.target.value))}
            aria-label="Wipe between ORCA's view and the illustration" /><span>Built</span></label>}
        {r.lines_url && <button className={`btn small ${lines ? "on" : ""}`} aria-pressed={lines} onClick={() => setLines(!lines)}
          data-tip="Draw the model's own outline over the picture, to see that it matches"><PenLine size={13} aria-hidden /> Lines from the model</button>}
        <span className="ibtn" tabIndex={0} aria-label={check} data-tip={check}><Info size={14} aria-hidden /></span>
      </div>
      <figcaption>
        <Building2 size={13} aria-hidden /> Illustration by Muse Image from ORCA's model view. The model is the record.
        {run.cut && <span className="hint"> {run.cut}</span>}
      </figcaption>
    </figure>);
}
