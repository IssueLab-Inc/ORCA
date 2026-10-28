import { Brain, CircleCheck, Flag, RotateCcw, ScanSearch } from "lucide-react";
import type { TriageKind, TriageModel, TriageVerdict } from "./api";

export const TRIAGE: Record<TriageKind, { label: string; cls: string; tip: string; colour: string; long: string }> = {
  real_clash: { label: "real", cls: "bad", tip: "A real clash: something has to move", colour: "var(--fail)", long: "Real problem" },
  modelling_error: { label: "model error", cls: "warn", tip: "A modelling mistake for the model's author", colour: "#d49a1c", long: "Model error" },
  by_design: { label: "by design", cls: "", tip: "How the parts are meant to go together", colour: "#7d8fa6", long: "By design" },
  non_physical: { label: "not physical", cls: "muted", tip: "A space, port or opening: not a physical clash", colour: "#c3ccd8", long: "Not physical" },
  unknown: { label: "no answer", cls: "muted", tip: "The triage model did not answer", colour: "#e3e7ec", long: "No answer" },
};
const WHY: Record<TriageKind, string> = {
  real_clash: "Something has to move",
  modelling_error: "For the model's author to clean up",
  by_design: "Parts that meet on purpose",
  non_physical: "Spaces, ports, openings",
  unknown: "Ask again, or open it",
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

/** Bulk triage of the whole report, the first step: run it, watch it land, filter by verdict, set the noise aside. */
export function TriageCard({ run, results, now, filter, onFilter, onRun, onSetAside, onFlag, live = [], onOpen, resolved = () => false, total }: {
  run: TriageRun | null; results: Record<string, TriageVerdict>; now: number; total: number;
  live?: { id: string; name: string; text: string }[]; onOpen?: (id: string) => void;
  filter: TriageKind | null; onFilter: (k: TriageKind | null) => void; onRun: (rerun: boolean) => void;
  onSetAside: (ids: string[]) => void; onFlag: (ids: string[]) => void;
  resolved?: (id: string) => boolean;  // fixed, set aside or flagged already
  open?: number;
}) {
  const ids = Object.keys(results);
  const counts = Object.fromEntries(ORDER.map((k) => [k, ids.filter((id) => results[id].verdict === k).length])) as Record<TriageKind, number>;
  const noise = ids.filter((id) => ["by_design", "non_physical"].includes(results[id].verdict));
  const errors = ids.filter((id) => results[id].verdict === "modelling_error");
  const noiseOpen = noise.filter((id) => !resolved(id));
  const errorsOpen = errors.filter((id) => !resolved(id));
  const byRule = ids.filter((id) => results[id].source === "rule").length;
  const n = run?.total || total;
  const seconds = run ? Math.round(run.done ? run.seconds ?? 0 : Math.max(0, now - run.started) / 1000) : 0;
  const model = run?.model ? (run.open_weights ? "Muse Spark Open" : "Muse Spark") : "";
  const state = !run ? "idle" : run.done ? "done" : "running";

  // One bar for the whole report: a segment per verdict (click to filter), the rest still to come.
  const bar = (
    <div className="triage-bar" role="group" aria-label="Clashes by verdict">
      {ORDER.filter((k) => counts[k]).map((k) => (
        <button key={k} className={filter === k ? "on" : ""} style={{ flexGrow: counts[k], background: TRIAGE[k].colour }}
          aria-label={`${counts[k]} ${TRIAGE[k].long.toLowerCase()}`} data-tip={`${counts[k]} ${TRIAGE[k].long.toLowerCase()}`} data-tip-side="bottom"
          onClick={() => onFilter(filter === k ? null : k)} />))}
      {n > ids.length && <span className="rest" style={{ flexGrow: n - ids.length }} />}
    </div>
  );

  return (
    <section className={`triage ${state}`} data-tour="triage">
      <div className="triage-head">
        <span className="triage-icon"><ScanSearch size={15} aria-hidden /></span>
        <div>
          <h3>Triage</h3>
          <span className="triage-sub">{state === "idle" ? "Step 1 · sort the report" : state === "running" ? "Sorting the report…" : "Every clash has a verdict"}</span>
        </div>
        {run?.done && <button className="ibtn" aria-label="Triage again" data-tip="Triage again" data-tip-side="left" onClick={() => onRun(true)}>
          <RotateCcw size={14} aria-hidden /></button>}
      </div>

      {state === "idle" && <>
        <p className="triage-lead">Most clash results are noise. Triage gives all <b>{n}</b> a verdict, so you only open the few that need a fix.</p>
        <button className="btn primary triage-go" onClick={() => onRun(false)}>
          <ScanSearch size={15} aria-hidden /> Triage all {n} clashes</button>
        <p className="hint">Sure cases (spaces, ports, touches) are settled by rule at once; Muse Spark Open, an open-weights
          model, reads the rest, eight at a time. About three minutes.</p>
      </>}

      {state === "running" && run && <>
        <div className="triage-count"><b>{ids.length}</b> of {n} sorted <span className="hint">· {seconds} s{byRule ? ` · ${byRule} by rule` : ""}</span></div>
        {bar}
        {live.length > 0 && (
          <div className="triage-live" aria-live="off">
            <span className="triage-live-head"><Brain size={12} aria-hidden /> {model || "The model"} is reading {live.length} now</span>
            {live.slice(-4).map((l) => (
              <button key={l.id} className="triage-live-row" onClick={() => onOpen?.(l.id)} title={`Open ${l.name}`}>
                <b>{l.name}</b><span>{tail(l.text)}</span>
              </button>))}
          </div>)}
      </>}

      {state === "done" && <>
        <div className="triage-count">
          <b className={counts.real_clash ? "bad" : "ok"}>{counts.real_clash}</b>
          {counts.real_clash === 1 ? " needs a fix" : " need a fix"} <span className="hint">of {n} clashes</span>
        </div>
        {bar}
      </>}

      {state !== "idle" && ids.length > 0 && (
        <div className="triage-rows">
          {ORDER.filter((k) => counts[k]).map((k) => (
            <button key={k} className={`triage-row ${filter === k ? "on" : ""}`} aria-pressed={filter === k}
              data-tour={k === "real_clash" ? "triage-real" : undefined}
              data-tip={filter === k ? "Show every clash again" : `Show only these in the list`} data-tip-side="right"
              onClick={() => onFilter(filter === k ? null : k)}>
              <i style={{ background: TRIAGE[k].colour }} />
              <span className="lbl">{TRIAGE[k].long}<small>{WHY[k]}</small></span>
              <b>{counts[k]}</b>
            </button>))}
        </div>)}

      {state === "done" && (noise.length > 0 || errors.length > 0) && (
        <div className="triage-actions">
          {noise.length > 0 && (noiseOpen.length
            ? <button className="btn small" onClick={() => onSetAside(noiseOpen)} data-tip="Mark the by-design and not-physical clashes as reviewed" data-tip-side="top">
              <CircleCheck size={13} aria-hidden /> Set aside {noiseOpen.length} as noise</button>
            : <span className="chip ok"><CircleCheck size={12} aria-hidden /> {noise.length} set aside</span>)}
          {errors.length > 0 && (errorsOpen.length
            ? <button className="btn small" onClick={() => onFlag(errorsOpen)} data-tip="Flag the model errors for their author" data-tip-side="top">
              <Flag size={13} aria-hidden /> Flag {errorsOpen.length} for their authors</button>
            : <span className="chip warn"><Flag size={12} aria-hidden /> {errors.length} flagged</span>)}
        </div>)}

      {run && (run.note || run.error) && <p className={run.error ? "bad small" : "hint small"}>{run.error || run.note}</p>}
      {run && state !== "idle" && (
        <p className="triage-meta">
          {state === "done" && <>{seconds} s · {byRule} by rule · </>}
          {run.model
            ? <><span className={`chip small ${run.open_weights ? "ok" : ""}`} title={run.note}>{run.open_weights ? "open weights" : "fallback"}</span> {model}</>
            : "starting…"}
        </p>)}
    </section>
  );
}
