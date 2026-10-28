import { CircleCheck, Flag, Filter, LoaderCircle, RotateCcw, ScanSearch, Brain } from "lucide-react";
import type { TriageKind, TriageModel, TriageVerdict } from "./api";

export const TRIAGE: Record<TriageKind, { label: string; cls: string; tip: string }> = {
  real_clash: { label: "real", cls: "bad", tip: "A real clash: something has to move" },
  modelling_error: { label: "model error", cls: "warn", tip: "A modelling mistake for the model's author" },
  by_design: { label: "by design", cls: "", tip: "How the parts are meant to go together" },
  non_physical: { label: "not physical", cls: "muted", tip: "A space, port or opening: not a physical clash" },
  unknown: { label: "no answer", cls: "muted", tip: "The triage model did not answer" },
};
/** The end of what the model is writing, from a word boundary, on one or two lines. */
function tail(text: string) {
  const t = text.replace(/\s+/g, " ").trim();
  if (t.length <= 170) return t;
  const cut = t.slice(-170);
  return "…" + cut.slice(cut.indexOf(" ") + 1);
}

const ORDER: TriageKind[] = ["real_clash", "modelling_error", "by_design", "non_physical", "unknown"];

export interface TriageRun extends TriageModel { total: number; started: number; done: boolean; seconds?: number; error?: string }

/** Bulk triage of the whole report: run it, watch it land, filter by verdict, set the noise aside in one click. */
export function TriageCard({ run, results, now, filter, onFilter, onRun, onSetAside, onFlag, open, live = [], onOpen }: {
  run: TriageRun | null; results: Record<string, TriageVerdict>; now: number; open: number;
  live?: { id: string; name: string; text: string }[]; onOpen?: (id: string) => void;
  filter: TriageKind | null; onFilter: (k: TriageKind | null) => void; onRun: (rerun: boolean) => void;
  onSetAside: (ids: string[]) => void; onFlag: (ids: string[]) => void;
}) {
  const ids = Object.keys(results);
  const counts = Object.fromEntries(ORDER.map((k) => [k, ids.filter((id) => results[id].verdict === k).length])) as Record<TriageKind, number>;
  const noise = ids.filter((id) => ["by_design", "non_physical"].includes(results[id].verdict));
  const errors = ids.filter((id) => results[id].verdict === "modelling_error");
  const byRule = ids.filter((id) => results[id].source === "rule").length;
  const who = run ? `${run.open_weights ? "Muse Spark Open" : "Muse Spark"} · ${run.model}` : "";
  return (
    <section className="triage" data-tour="triage">
      <div className="row">
        <h3><ScanSearch size={14} aria-hidden /> Triage</h3>
        {run?.done
          ? <button className="ibtn" aria-label="Triage again" data-tip="Triage again" data-tip-side="left" onClick={() => onRun(true)}><RotateCcw size={14} aria-hidden /></button>
          : !run && <button className="btn small primary" onClick={() => onRun(false)} data-tip="A verdict on every clash: real, by design, not physical or a model error" data-tip-side="left">
            <ScanSearch size={13} aria-hidden /> Triage all</button>}
      </div>
      {!run && <p className="hint">Sort every clash before opening one. Sure cases (spaces, ports, touches) are settled by rule; the rest go to the open-weights model, many at a time.</p>}
      {run && <>
        <div className="triage-progress" role="progressbar" aria-valuemin={0} aria-valuemax={run.total} aria-valuenow={ids.length}>
          <span style={{ width: `${run.total ? (100 * ids.length) / run.total : 0}%` }} /></div>
        <p className="hint">
          {!run.done && <LoaderCircle size={12} className="spin" aria-hidden />} {ids.length} of {run.total}
          {run.done ? ` in ${Math.round(run.seconds ?? Math.max(0, now - run.started) / 1000)} s` : ` · ${Math.round(Math.max(0, now - run.started) / 1000)} s`}
          {byRule > 0 && ` · ${byRule} by rule`}
          <br />{run.model
            ? <><span className={`chip small ${run.open_weights ? "ok" : ""}`} title={run.note}>{run.open_weights ? "open weights" : "fallback"}</span> {who}</>
            : "starting…"}
        </p>
        {!run.done && live.length > 0 && (
          <div className="triage-live" aria-live="off">
            <span className="triage-live-head"><Brain size={12} aria-hidden /> {run.open_weights ? "Muse Spark Open" : "Muse Spark"} is reading {live.length} now</span>
            {live.slice(-4).map((l) => (
              <button key={l.id} className="triage-live-row" onClick={() => onOpen?.(l.id)} title={`Open ${l.name}`}>
                <b>{l.name}</b><span>{tail(l.text)}</span>
              </button>))}
          </div>)}
        {run.note && <p className="hint small">{run.note}</p>}
        {run.error && <p className="bad small">{run.error}</p>}
        <div className="triage-chips">
          {ORDER.filter((k) => counts[k]).map((k) => (
            <button key={k} className={`chip ${TRIAGE[k].cls} ${filter === k ? "on" : ""}`} aria-pressed={filter === k}
              data-tour={k === "real_clash" ? "triage-real" : undefined}
              data-tip={filter === k ? "Show every clash" : `Show only: ${TRIAGE[k].tip.toLowerCase()}`} data-tip-side="bottom"
              onClick={() => onFilter(filter === k ? null : k)}>{filter === k && <Filter size={11} aria-hidden />} {counts[k]} {TRIAGE[k].label}</button>
          ))}
        </div>
        {run.done && (noise.length > 0 || errors.length > 0) && open > 0 && (
          <div className="plan-actions">
            {noise.length > 0 && <button className="btn small" onClick={() => onSetAside(noise)}
              data-tip="Mark the by-design and non-physical clashes as reviewed" data-tip-side="top">
              <CircleCheck size={13} aria-hidden /> Set aside {noise.length}</button>}
            {errors.length > 0 && <button className="btn small" onClick={() => onFlag(errors)} data-tip="Flag the model errors for their author" data-tip-side="top">
              <Flag size={13} aria-hidden /> Flag {errors.length}</button>}
          </div>
        )}
      </>}
    </section>
  );
}
