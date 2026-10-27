import { ChevronDown, ChevronUp, CircleCheck, Flag, ListChecks, Network, Repeat2, Sparkles, Wand2 } from "lucide-react";
import { useState } from "react";
import type { Pattern, PatternVerdict, RootCause } from "./api";

const short = (c: string) => c.replace(/^Ifc/, "");
const VERDICT: Record<PatternVerdict["verdict"], { label: string; cls: string }> = {
  by_design: { label: "by design", cls: "" }, modelling_error: { label: "model error", cls: "warn" }, real_problem: { label: "real problem", cls: "bad" },
};

/** What Sightline sees across the report: elements behind several clashes, and clashes that repeat the same way. */
export function Insights({ rootCauses, patterns, verdicts, explaining, busy, onFixRoot, onExplain, onSelect, onReview, onFixAll }: {
  rootCauses: RootCause[] | null; patterns: Pattern[] | null; verdicts: Record<string, PatternVerdict> | null;
  explaining: boolean; busy: boolean;
  onFixRoot: (hub: string) => void; onExplain: () => void; onSelect: (ids: string[]) => void;
  onReview: (ids: string[], kind: "by_design" | "author", note: string) => void; onFixAll: (ids: string[]) => void;
}) {
  const [allRoots, setAllRoots] = useState(false);
  const [allPatterns, setAllPatterns] = useState(false);
  const roots = rootCauses ?? [];
  const pats = patterns ?? [];
  if (rootCauses && patterns && !roots.length && !pats.length) return null;
  const shownRoots = allRoots ? roots : roots.slice(0, 2);
  const shownPats = allPatterns ? pats : pats.slice(0, 4);
  return (
    <details className="insights" open>
      <summary><Sparkles size={14} aria-hidden /> Insights <span className="count">{rootCauses && patterns
        ? `${roots.length} root cause${roots.length === 1 ? "" : "s"} · ${pats.length} pattern${pats.length === 1 ? "" : "s"}`
        : "updating…"}</span></summary>

      {roots.length > 0 && <>
        <h3><Network size={14} aria-hidden /> Root causes <span className="count">one element in several clashes</span></h3>
        {shownRoots.map((r) => (
          <div key={r.hub.global_id} className="insight">
            <div className="insight-text">
              <b title={`${r.hub.ifc_class} '${r.hub.name}': ${r.partners.map((p) => p.name).join(", ")}`}>{r.hub.name}</b>
              <span className="hint">{r.partners.length} clashing · {r.hub.storey ?? r.hub.source}
                {r.cross_discipline > 0 ? " · across disciplines" : " · within one model"}
                {r.not_in_report > 0 && <> · <span className="warn">{r.not_in_report} not in the report</span></>}</span>
            </div>
            <button className="btn small" disabled={busy} onClick={() => onFixRoot(r.hub.global_id)}
              title="Find the cause and fix these clashes together"><Wand2 size={14} aria-hidden /> Fix</button>
          </div>
        ))}
        {roots.length > 2 && <button className="more" onClick={() => setAllRoots(!allRoots)}>
          {allRoots ? <><ChevronUp size={13} aria-hidden /> Fewer</> : <><ChevronDown size={13} aria-hidden /> All {roots.length} root causes</>}</button>}
      </>}

      {pats.length > 0 && <>
        <div className="row">
          <h3><Repeat2 size={14} aria-hidden /> Patterns <span className="count">the same clash many times</span></h3>
          {!verdicts && <button className="btn small" disabled={explaining || busy} onClick={onExplain}
            data-tip="Ask Sightline what each pattern is" data-tip-side="left">
            {explaining ? <><i className="spinner" aria-hidden /> Reading…</> : <><Sparkles size={13} aria-hidden /> Explain</>}</button>}
        </div>
        {shownPats.map((p) => {
          const v = verdicts?.[p.id];
          return (
            <div key={p.id} className="insight pattern">
              <div className="insight-text">
                <b>{p.clashes} × {short(p.classes[0])} × {short(p.classes[1])}</b>
                <span className="hint">{p.levels.length} level{p.levels.length === 1 ? "" : "s"} · {p.min_mm === p.max_mm ? `${p.min_mm} mm every time` : `${p.min_mm} to ${p.max_mm} mm`}
                  {p.cross_discipline ? " · across disciplines" : ""}</span>
                {v && <span className="verdict"><span className={`chip small ${VERDICT[v.verdict].cls}`}>{VERDICT[v.verdict].label}</span> {v.cause}</span>}
                {v && <span className="hint">{v.rule ? <>Rule: <i>{v.rule}</i></> : v.action}</span>}
              </div>
              <div className="insight-actions">
                <button className="ibtn" aria-label="Tick these clashes in the list" data-tip="Tick them in the list" data-tip-side="left"
                  onClick={() => onSelect(p.clash_ids)}><ListChecks size={16} aria-hidden /></button>
                {v?.verdict === "by_design" && <button className="ibtn" aria-label="Mark as by design" data-tip="Mark all as by design" data-tip-side="left"
                  onClick={() => onReview(p.clash_ids, "by_design", v.rule || v.cause)}><CircleCheck size={16} aria-hidden /></button>}
                {v?.verdict === "modelling_error" && <button className="ibtn" aria-label="Flag for the model author" data-tip="Flag all for the author" data-tip-side="left"
                  onClick={() => onReview(p.clash_ids, "author", v.action)}><Flag size={16} aria-hidden /></button>}
                {v?.verdict === "real_problem" && <button className="ibtn" disabled={busy} aria-label="Fix these together" data-tip="Fix these together (up to 8 pairs)" data-tip-side="left"
                  onClick={() => onFixAll(p.clash_ids)}><Wand2 size={16} aria-hidden /></button>}
              </div>
            </div>
          );
        })}
        {pats.length > 4 && <button className="more" onClick={() => setAllPatterns(!allPatterns)}>
          {allPatterns ? <><ChevronUp size={13} aria-hidden /> Fewer</> : <><ChevronDown size={13} aria-hidden /> All {pats.length} patterns</>}</button>}
      </>}
    </details>
  );
}
