import { CircleCheck, CircleX, LoaderCircle, LocateFixed, Network, Trash2, Wand2 } from "lucide-react";
import type { Plan, PlanItem } from "./api";
import { mm } from "./ReportList";

/** A plan while it is being built: what each pair is doing. */
export interface PlanRun {
  kind: "batch" | "root_cause";
  started: number;
  phase: "cause" | "fixing" | "checking" | "done";
  rootCause: string;
  items: PlanItem[];
  status: Record<string, { state: "waiting" | "thinking" | "checking" | "done"; note?: string; ok?: boolean }>;
}

const editText = (i: PlanItem) => {
  const o = i.option;
  if (!o) return "";
  if (o.edit?.summary) return o.edit.summary;
  if (o.kind === "trim") return o.trim ? `trim one end ${Math.round(o.trim.by_m * 1000)} mm` : "trim at the joint";
  return o.kind === "offset" && o.split_m
    ? `offset ${(o.split_m[1] - o.split_m[0]).toFixed(2)} m of it ${o.delta_m[2] > 0 ? "up" : "down"} ${Math.abs(Math.round(o.delta_m[2] * 1000))} mm`
    : `move ${o.delta_m.map((v) => mm(v)).join(" · ")}`;
};

export function PlanPanel({ run, plan, now, busy, onAccept, onDiscard, onFocus, onAsDesigned, error }: {
  run: PlanRun | null; plan: Plan | null; now: number; busy: boolean; error?: string | null;
  onAccept: () => void; onDiscard: () => void; onFocus: (item: PlanItem) => void;
  onAsDesigned: (clashIds: string[], note: string) => void;
}) {
  if (!run && !plan) {
    return (
      <div className="plan-empty">
        <p className="hint">Tick several clashes in the list and choose <b>Fix together</b>, or pick a root cause: ORCA
          proposes a fix for each and checks them all together, so they do not collide.</p>
      </div>
    );
  }
  const items = plan?.items ?? run?.items ?? [];
  const working = !!run && run.phase !== "done";
  const seconds = Math.round((now - (run?.started ?? now)) / 1000);
  const ok = plan ? items.filter((i) => i.option && plan.check.items?.[i.key]?.passed).length : 0;
  const cause = plan?.root_cause || run?.rootCause;
  return (
    <section className="plan">
      <div className="row">
        <h2>{run?.kind === "root_cause" || plan?.kind === "root_cause" ? <><Network size={15} aria-hidden /> Root cause plan</> : <><Wand2 size={15} aria-hidden /> Fix together</>}</h2>
        {plan && plan.strategy !== "as_designed" && <span className={`chip ${plan.check.passed ? "ok" : "warn"}`}>{plan.check.passed ? "verified together" : `${ok} of ${items.length} verified`}</span>}
      </div>
      {working && <p className="live-line"><LoaderCircle size={14} className="spin" aria-hidden />{
        run!.phase === "cause" ? "Muse Spark is working out the cause…" : run!.phase === "checking" ? "Checking every fix together…"
          : `Finding a fix for each pair… ${seconds} s`}</p>}
      {cause && <div className="cause"><b>Cause</b><p>{cause}</p></div>}
      {error && !plan && <p className="bad" role="alert">The plan could not be built: {error}</p>}
      {plan?.strategy === "as_designed" && (
        <div className="advice">
          <b>No model change needed</b>
          <p>{plan.advice || "These clashes are how the parts are meant to go together."}</p>
          <div className="plan-actions">
            <button className="btn primary" onClick={() => onAsDesigned(plan.hub?.clash_ids ?? [], plan.advice)}>
              <CircleCheck size={15} aria-hidden /> Mark {plan.hub?.clash_ids.length ?? 0} clashes as by design</button>
            <button className="btn" onClick={onDiscard}><Trash2 size={15} aria-hidden /> Dismiss</button>
          </div>
        </div>
      )}

      <ol className="plan-items">
        {items.map((it) => {
          const st = run?.status[it.key];
          const res = plan?.check.items?.[it.key];
          const conflict = plan?.check.conflicts.find((c) => c.a === it.key || c.b === it.key);
          const state = plan ? (it.option ? (res?.passed ? "ok" : "fail") : "fail") : st?.state === "done" ? (st.ok ? "ok" : "fail") : "work";
          return (
            <li key={it.key} className={`plan-item ${state}`}>
              <span className="pi-icon" aria-hidden>{state === "ok" ? <CircleCheck size={16} /> : state === "fail" ? <CircleX size={16} /> : <LoaderCircle size={16} className="spin" />}</span>
              <div className="pi-body">
                <div className="pi-label">{it.label.replace(/Ifc/g, "")}</div>
                {!it.in_report && <span className="chip warn small">not in the report</span>}
                <div className="pi-fix">{it.option ? <><b>{it.option.title}</b> <span className="why">· {editText(it)}{res?.min_clearance_m != null ? ` · ${mm(res.min_clearance_m)} clear` : ""}</span></>
                  : it.error ? <ul className="pi-why">{it.error.split("\n").map((line, k) => <li key={k}>{line}</li>)}</ul>
                    : <span className="why">{st?.note ?? "waiting"}</span>}</div>
                {res && !res.passed && res.reason && <div className="bad small">{res.reason}</div>}
                {conflict && <div className="bad small">Collides with another fix in this plan ({conflict.detail})</div>}
              </div>
              <button className="ibtn" aria-label="Go to this clash" data-tip="Go to this clash" data-tip-side="left" onClick={() => onFocus(it)}>
                <LocateFixed size={16} aria-hidden /></button>
            </li>
          );
        })}
      </ol>

      {plan && plan.strategy !== "as_designed" && (
        <div className="plan-actions">
          <button className="btn primary" data-tour="accept-plan" disabled={busy || !items.some((i) => i.option)} onClick={onAccept}>
            <CircleCheck size={15} aria-hidden /> {!ok ? "Nothing to accept yet" : plan.check.passed ? "Accept the plan" : `Accept the ${ok} verified`}</button>
          <button className="btn" onClick={onDiscard}><Trash2 size={15} aria-hidden /> Discard</button>
          <span className="hint">{plan.seconds.toFixed(0)} s · checked as one, so the fixes do not collide</span>
        </div>
      )}
    </section>
  );
}
