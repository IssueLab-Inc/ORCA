import { Check, Network, RefreshCw, Trash2 } from "lucide-react";
import type { ContextEvent, ContextObjective, ContextProposal, ContextResult } from "./api";
import { mm } from "./ReportList";

/** Kept separately from batch plans: a context edit can change a previously unclashing element. */
export interface ContextRun {
  objective: ContextObjective | null;
  started: number;
  phase: "inspecting" | "thinking" | "checking" | "blocked" | "done";
  messages: string[];
  result: ContextResult | null;
  error: string | null;
  stale: boolean;
  accepted?: boolean;
}

export function contextStep(run: ContextRun, event: ContextEvent): ContextRun {
  if (event.type === "error") return { ...run, phase: "done", error: event.detail };
  if (event.type === "context_result") return { ...run, phase: "done", result: event,
    objective: event.proposals[0]?.objective ?? run.objective };
  return { ...run, phase: event.phase, messages: [...run.messages, event.message] };
}

export function ContextPlan({ run, names, chosen, acknowledged, busy, now, onChoose, onAcknowledge, onAccept, onRegenerate, onDiscard }: {
  names: Record<string, Record<string, unknown>>;
  run: ContextRun; chosen: string | null; acknowledged: string[]; busy: boolean; now: number;
  onChoose: (id: string) => void; onAcknowledge: (id: string, checked: boolean) => void;
  onAccept: () => void; onRegenerate: () => void; onDiscard: () => void;
}) {
  const working = run.phase !== "done";
  const proposals = run.result?.proposals ?? [];
  const current = proposals.find((p) => p.id === chosen);
  const ready = current?.passed && current.checks.geometry.passed && current.checks.integrity.passed
    && current.review_conditions.every((c) => acknowledged.includes(c.id));
  return <section className="plan context-plan" aria-label="Wider fix review">
    <div className="row"><h2><Network size={15} aria-hidden /> Explore wider fix</h2>
      {!working && <button className="btn small" aria-label="Dismiss wider fix" disabled={busy} onClick={onDiscard}><Trash2 size={14} /></button>}</div>
    <p className="hint">Inspect surrounding elements and check each complete arrangement. Accepting keeps every dependent edit together.</p>
    {run.objective && <details className="context-objective"><summary>Original objective</summary>
      <p className="mono">{run.objective.element_a}<br />{run.objective.element_b}</p></details>}
    {working && <p className="live-line" role="status"><i className="spinner" aria-hidden />
      {run.messages.at(-1) ?? "Inspecting the clash and its surroundings…"} · {Math.max(0, Math.round((now - run.started) / 1000))} s</p>}
    {run.messages.length > 0 && <details className="context-activity"><summary>Inspection and checks · {run.messages.length} steps</summary>
      <ol>{run.messages.map((message, i) => <li key={i}>{message}</li>)}</ol></details>}
    {run.result && <p>{run.result.message}</p>}
    {run.result && <p className="hint">{run.result.trials} trials · {run.result.model_calls} model calls · {run.result.seconds.toFixed(1)} s</p>}
    {run.error && <p className="bad" role="alert">{run.error}</p>}
    {run.stale && <p className="context-warning" role="status">The model has changed or fresh checks could not confirm this proposal. Regenerate for the original objective before accepting.</p>}
    {run.accepted && <p className="ok" role="status">Complete proposal kept in the open model. Export IFC to download all edited files.</p>}
    {proposals.map((p, i) => <div className={`card context-card ${chosen === p.id ? "pick" : ""}`} key={p.id}>
      <button className="card-body" aria-pressed={chosen === p.id} disabled={busy || run.accepted} onClick={() => onChoose(p.id)}>
        <span className="row"><b>{i + 1} · {p.title}</b><span className="chip ok">checks passed</span></span>
        <span className="hint">{p.edits.length} coordinated edit{p.edits.length === 1 ? "" : "s"}</span>
      </button>
      {chosen === p.id && <ContextEvidence proposal={p} names={names} />}
    </div>)}
    {current && !run.accepted && <div className="context-conditions">
      <h3>Designer review conditions</h3>
      <p className="hint">Geometry and model checks passed with these conditions. Review each before keeping the complete proposal.</p>
      {current.review_conditions.map((c) => <label className="context-condition" key={c.id}>
        <input type="checkbox" checked={acknowledged.includes(c.id)} disabled={busy || run.stale} onChange={(e) => onAcknowledge(c.id, e.target.checked)} />
        <span>{c.message}</span></label>)}
      {!current.review_conditions.length && <p className="hint">No additional conditions were returned by the model checks.</p>}
      <button className="btn primary" disabled={busy || working || run.stale || !ready} onClick={onAccept}>
        <Check size={15} aria-hidden /> Accept complete proposal</button>
    </div>}
    {!working && !run.accepted && <button className="btn" disabled={busy || !run.objective} onClick={onRegenerate}>
      <RefreshCw size={14} aria-hidden /> Regenerate for original objective</button>}
  </section>;
}

function ContextEvidence({ proposal: p, names }: { proposal: ContextProposal; names: Record<string, Record<string, unknown>> }) {
  const g = p.checks.geometry, integrity = p.checks.integrity;
  return <div className="context-evidence">
    <ol className="context-edits">{p.edits.map((edit, i) => <li key={`${edit.element}-${i}`}>
      <b>{edit.kind === "offset" ? "Local offset" : edit.kind === "trim" ? "Trim" : "Move run"} · {elementLabel(names[edit.element])}</b>
      <p><b>Why:</b> {edit.reason}</p>
      {edit.label !== edit.reason && <p>{edit.label}</p>}
      <p className="mono">{edit.kind === "trim" ? `${edit.end} end · ${mm(edit.by_m)}`
        : `Δx ${mm(edit.delta_m?.[0])} · Δy ${mm(edit.delta_m?.[1])} · Δz ${mm(edit.delta_m?.[2])}`}
        {edit.split_m && ` · split ${edit.split_m.map((v) => `${v.toFixed(2)} m`).join(" – ")}`}</p>
      <p className="hint">{edit.moved.length} source element{edit.moved.length === 1 ? "" : "s"} · {edit.pieces.length} resulting pieces</p>
      <details><summary>Model identity and affected sources</summary><p className="mono">{edit.element}</p><p>Model revision: {p.scene_revision}</p>
        {names[edit.element]?.source != null && <p>File: {String(names[edit.element].source)}</p>}
        <ul>{edit.moved.map((gid) => <li className="mono" key={gid}>{gid}</li>)}</ul></details>
    </li>)}</ol>
    <p className={g.passed ? "ok" : "bad"}>Geometry: {g.target_resolved ? "original clash resolved" : "original clash remains"}
      {g.min_clearance_m != null && ` · nearest ${mm(g.min_clearance_m)}`}</p>
    <p className={integrity.passed ? "ok" : "bad"}>Model integrity checks {integrity.passed ? "passed" : "failed"}</p>
    {integrity.warnings.map((w, i) => <p className="context-warning" key={i}>{w}</p>)}
    {integrity.errors.map((e, i) => <p className="bad" key={i}>{e}</p>)}
    {g.existing_conflicts.length > 0 && <details><summary>{g.existing_conflicts.length} unchanged baseline conflicts remain</summary>
      <ul>{g.existing_conflicts.map((h, i) => <li key={i}>{h.element} / {h.other} · {h.kind} · {mm(h.distance_m)}</li>)}</ul></details>}
    {g.hits.length > 0 && <ul>{g.hits.map((h, i) => <li className="bad" key={i}>{h.element} / {h.other} · {h.kind} · {mm(h.distance_m)}</li>)}</ul>}
    <p className="hint">These checks do not establish engineering adequacy or full IFC conformance. Retained authored frame warnings require the stated designer review.</p>
  </div>;
}

function elementLabel(info?: Record<string, unknown>) {
  if (!info) return "Loading element…";
  const parts = [info.name, typeof info.ifc_class === "string" ? info.ifc_class.replace(/^Ifc/, "") : null, info.tag]
    .filter((v) => typeof v === "string" && v.length > 0);
  return parts.length ? [...new Set(parts)].join(" · ") : "Model element (identity below)";
}
