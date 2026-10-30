import { EyeOff, ListChecks, Workflow } from "lucide-react";
import type { Attempt } from "./api";
import { editText, kindLabel } from "./fixKinds";
import { Workings } from "./Workings";
import { aiName } from "./aiNames";

/** What the agent is doing now, while a proposal runs. */
export interface Progress {
  started: number;          // ms timestamp
  round: number;
  phase: "thinking" | "checking" | "done";
  thinkingSince: number;    // ms timestamp of the current model call
  modelSeconds: number[];   // per finished round
  ideas: number;            // candidates in the current round
  checking: { index: number; title: string; kind: string } | null;
  /** The model working now ("Muse Spark", or "Muse Wonder" on a second try). */
  model?: string;
  /** Ideas already in the table from an earlier try: a second try's own numbering starts after them. */
  offset?: number;
}

export { editText, KIND_LABEL } from "./fixKinds";

/** "collision with IfcWall (-200 mm), collision with …" → first finding, plus how many more. */
function firstReason(reason: string): [string, number] {
  const parts = reason.split(/, (?=collision|clearance|cannot)/);
  return [parts[0], parts.length - 1];
}

export function statusLine(p: Progress | null, now: number, attempts: Attempt[]): string {
  if (!p) return "";
  const total = Math.round((now - p.started) / 1000);
  const who = p.model || aiName("proposal");
  if (p.phase === "thinking") {
    return p.offset
      ? `${who}, round ${p.round}: reading the first try and the model around it… ${Math.round((now - p.thinkingSince) / 1000)} s`
      : `Round ${p.round}: ${who} is reading the clash and the model data… ${Math.round((now - p.thinkingSince) / 1000)} s`;
  }
  if (p.phase === "checking" && p.checking) {
    return `Round ${p.round}: checking ${p.offset ? `${who}'s ` : ""}idea ${(p.offset ?? 0) + p.checking.index + 1} (${p.checking.title}) against the whole model · ${total} s`;
  }
  const ok = attempts.filter((a) => a.passed).length;
  if (!attempts.length) return `Done in ${total} s: nothing was tried on the model`;  // a recommendation only (requirements)
  return `Done in ${total} s: ${ok} of ${attempts.length} ideas passed the geometry check`;
}

/** The Activity panel's two views: the table of ideas tried (Steps) and the run drawn as it happens (Workings). */
export type ActivityView = "steps" | "work";

/** Agent activity: the proposal's status line, then Steps or Workings (docs/workings.md). With `workings` off (phones,
 * tablets, or switched off) it is Steps alone, as before Workings. `inView`: the check the pilot shows in the viewer. */
export function Activity({ attempts, progress, now, workings = false, view = "steps", onView, onHide, inView = null }: {
  attempts: Attempt[]; progress: Progress | null; now: number;
  workings?: boolean; view?: ActivityView; onView?: (v: ActivityView) => void; onHide?: () => void; inView?: number | null;
}) {
  const drawing = workings && view === "work";
  const running = progress && progress.phase !== "done";
  const head = (progress || attempts.length || workings) && (
    <div className="activity-head">
      <b>Agent activity</b>
      {(progress || attempts.length > 0) && <span className={running ? "live" : "hint"}>{running && <i className="spinner" aria-hidden />}{statusLine(progress, now, attempts)}</span>}
      {progress && progress.modelSeconds.length > 0 &&
        <span className="hint mono">model {progress.modelSeconds.map((s) => `${s.toFixed(0)} s`).join(" + ")}</span>}
      {workings && <>
        <span className="spacer" />
        <span className="seg" role="tablist" aria-label="Activity view">
          <button type="button" role="tab" aria-selected={!drawing} className={drawing ? "" : "on"} onClick={() => onView?.("steps")}
            data-tip="The ideas tried, as a table"><ListChecks size={14} aria-hidden /> Steps</button>
          <button type="button" role="tab" aria-selected={drawing} className={drawing ? "on" : ""} onClick={() => onView?.("work")}
            data-tip="The run drawn as it happens (W)"><Workflow size={14} aria-hidden /> Workings</button>
        </span>
        {onHide && <button type="button" className="ibtn" aria-label="Turn Workings off" data-tip="Turn Workings off (Panels and layout turns it on again)"
          onClick={onHide}><EyeOff size={15} aria-hidden /></button>}
      </>}
    </div>
  );
  if (drawing) return <div className="activity">{head}<Workings inView={inView} /></div>;
  if (!progress && !attempts.length) {
    return <div className="activity">{head}<p className="hint">ORCA's steps appear here: each idea from {aiName("proposal")}, and what the geometry check found.</p></div>;
  }
  // Name the model on each idea only when two tried (a second try): one model needs no label.
  const first = aiName("proposal");
  const models = new Set(attempts.map((t) => t.model || first));
  const offset = progress?.offset ?? 0;
  return (
    <div className="activity">
      {head}
      <table className="steps">
        <thead><tr><th>#</th><th>Kind</th><th>Idea</th><th>Edit</th><th>Geometry check</th></tr></thead>
        <tbody>
          {attempts.map((t, i) => {
            const [first, more] = firstReason(t.reason);
            return (
              <tr key={i} className={t.passed ? "ok" : "fail"}>
                <td className="mono" data-label="#">{i + 1}</td>
                <td data-label="Kind"><span className={`badge ${t.kind}`}>{kindLabel(t.kind)}</span></td>
                <td data-label="Idea">{t.title}{models.size > 1 && <span className={`chip model ${t.model && t.model !== first ? "wonder" : ""}`}>{t.model || first}</span>}</td>
                <td className="mono" data-label="Edit">{editText(t)}</td>
                <td data-label="Check">{t.passed ? <span className="ok">✓ verified</span>
                  : <span className="bad" title={t.reason}>✗ {first}{more ? ` +${more} more` : ""}</span>}</td>
              </tr>
            );
          })}
          {progress?.phase === "checking" && progress.checking && offset + progress.checking.index >= attempts.length &&
            <tr className="pending"><td className="mono">{offset + progress.checking.index + 1}</td><td><span className={`badge ${progress.checking.kind}`}>{kindLabel(progress.checking.kind)}</span></td>
              <td>{progress.checking.title}</td><td /><td className="hint">checking…</td></tr>}
        </tbody>
      </table>
    </div>
  );
}
