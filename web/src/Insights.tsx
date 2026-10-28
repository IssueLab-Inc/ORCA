import { ChevronDown, ChevronUp, CircleCheck, Filter, Flag, ListChecks, Network, Repeat2, Sparkles, Wand2 } from "lucide-react";
import { useState } from "react";
import type { Pattern, PatternVerdict, RootCause } from "./api";

/** "IfcMechanicalFastener" → "Mechanical fastener". */
const human = (c: string) => {
  const words = c.replace(/^Ifc/, "").replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
};
const VERDICT: Record<PatternVerdict["verdict"], { label: string; cls: string }> = {
  by_design: { label: "by design", cls: "" }, modelling_error: { label: "model error", cls: "warn" }, real_problem: { label: "real problem", cls: "bad" },
};

/** What Sightline sees across the report: elements behind several clashes, and clashes that repeat the same way. */
export function Insights({ rootCauses, patterns, verdicts, explaining, busy, onFixRoot, onExplain, onSelect, onReview, onFixAll,
  resolved, focus, onFocus }: {
  rootCauses: RootCause[] | null; patterns: Pattern[] | null; verdicts: Record<string, PatternVerdict> | null;
  explaining: boolean; busy: boolean;
  resolved: Set<string>;  // fixed or reviewed: a pattern shows only its open clashes, and stays in place when none are left
  focus: string | null;   // the label the list is filtered to, if one of these
  onFocus: (f: { label: string; ids: string[] } | null) => void;
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
  const openRoots = roots.filter((r) => !r.done).length;
  const openPats = pats.filter((p) => p.clash_ids.some((id) => !resolved.has(id))).length;
  const nRoots = rootCauses ? `${openRoots} root cause${openRoots === 1 ? "" : "s"}` : "…";
  const nPats = patterns ? `${openPats} pattern${openPats === 1 ? "" : "s"}` : "…";
  // Show these clashes only, in the list; pressed again, show everything.
  const filterButton = (label: string, ids: string[]) => (
    <button className={`ibtn ${focus === label ? "on" : ""}`} aria-pressed={focus === label} aria-label="Show only these in the list"
      data-tip={focus === label ? "Show every clash again" : "Show only these in the list"} data-tip-side="left"
      onClick={() => onFocus(focus === label ? null : { label, ids })}><Filter size={15} aria-hidden /></button>
  );
  return (
    <details className="insights" open>
      <summary>
        <span className="insights-icon"><Sparkles size={14} aria-hidden /></span>
        <span className="insights-title">Insights<small>What the clashes have in common · {nRoots} · {nPats}</small></span>
        <ChevronDown size={15} className="insights-caret" aria-hidden />
      </summary>

      {roots.length > 0 && <div className="insights-part">
        <h3><Network size={14} aria-hidden /> Root causes</h3>
        <p className="hint">One element behind several clashes: fix the cause once, not each clash.</p>
        {shownRoots.map((r) => (
          <div key={r.hub.global_id} className={`insight ${r.done ? "done" : ""}`}>
            <div className="insight-text">
              <b title={`${r.hub.ifc_class} '${r.hub.name}': ${r.partners.map((p) => p.name).join(", ")}`}>{r.hub.name}</b>
              <span className="insight-meta">
                <span className="chip small count">{r.partners.length} clashing</span>
                {(r.hub.storey ?? r.hub.source) && <span className="chip small">{r.hub.storey ?? r.hub.source}</span>}
                <span className={`chip small ${r.cross_discipline > 0 ? "accent" : ""}`}>{r.cross_discipline > 0 ? "across disciplines" : "one model"}</span>
                {r.not_in_report > 0 && <span className="chip small warn">{r.not_in_report} not in the report</span>}
              </span>
            </div>
            <div className="insight-actions">
              {filterButton(`Root cause: ${r.hub.name}`, r.clash_ids)}
              {r.done
                ? <button className="btn small root-act" disabled data-tip="Its clashes are resolved" data-tip-side="left"><CircleCheck size={14} aria-hidden /> Done</button>
                : <button className="btn small root-act" disabled={busy} onClick={() => onFixRoot(r.hub.global_id)}
                    data-tip="Find the cause and fix these clashes together" data-tip-side="left"><Wand2 size={14} aria-hidden /> Fix</button>}
            </div>
          </div>
        ))}
        {roots.length > 2 && <button className="more" onClick={() => setAllRoots(!allRoots)}>
          {allRoots ? <><ChevronUp size={13} aria-hidden /> Fewer</> : <><ChevronDown size={13} aria-hidden /> All {roots.length} root causes</>}</button>}
      </div>}

      {pats.length > 0 && <div className="insights-part">
        <h3><Repeat2 size={14} aria-hidden /> Patterns</h3>
        <p className="hint">The same pair of element types clashing again and again: usually one decision, not many problems.</p>
        {!verdicts && <button className="btn small explain-all" data-tour="explain" disabled={explaining || busy} onClick={onExplain}>
          {explaining ? <><i className="spinner" aria-hidden /> Muse Spark is reading the patterns…</>
            : <><Sparkles size={13} aria-hidden /> Explain the {pats.length} patterns with Muse Spark</>}</button>}
        {shownPats.map((p) => {
          const v = verdicts?.[p.id];
          const open = p.clash_ids.filter((id) => !resolved.has(id));
          const name = `${human(p.classes[0])} with ${human(p.classes[1])}`;
          return (
            <div key={p.id} className={`insight pattern ${open.length ? "" : "done"}`} data-tour={v?.verdict === "by_design" ? "pattern-by-design" : undefined}>
              <span className="pattern-n" aria-label={`${open.length} clashes open of ${p.clashes}`}
                title={open.length < p.clashes ? `${open.length} of ${p.clashes} still open` : undefined}>{open.length ? open.length : p.clashes}×</span>
              <div className="insight-text">
                <b title={`${p.classes[0]} with ${p.classes[1]}`}>{human(p.classes[0])} <span className="with">with</span> {human(p.classes[1])}</b>
                <span className="hint">{p.levels.length} level{p.levels.length === 1 ? "" : "s"} · {p.min_mm === p.max_mm ? `${p.min_mm} mm every time` : `${p.min_mm} to ${p.max_mm} mm`}
                  {p.cross_discipline ? " · across disciplines" : ""}</span>
                {v && <span className="verdict"><span className={`chip small ${VERDICT[v.verdict].cls}`}>{VERDICT[v.verdict].label}</span> {v.cause}</span>}
                {v && <span className="hint">{v.rule ? <>Rule: <i>{v.rule}</i></> : v.action}</span>}
              </div>
              <div className="insight-actions">
                {filterButton(`Pattern: ${name}`, p.clash_ids)}
                {!open.length && <span className="ibtn done-mark" aria-label="All resolved" data-tip="All resolved" data-tip-side="left"><CircleCheck size={16} aria-hidden /></span>}
                {open.length > 0 && <>
                <button className="ibtn" aria-label="Tick these clashes in the list" data-tip="Tick them in the list" data-tip-side="left"
                  onClick={() => onSelect(open)}><ListChecks size={16} aria-hidden /></button>
                {v?.verdict === "by_design" && <button className="ibtn" data-tour="mark-by-design" aria-label="Mark as by design" data-tip="Mark all as by design" data-tip-side="left"
                  onClick={() => onReview(open, "by_design", v.rule || v.cause)}><CircleCheck size={16} aria-hidden /></button>}
                {v?.verdict === "modelling_error" && <button className="ibtn" aria-label="Flag for the model author" data-tip="Flag all for the author" data-tip-side="left"
                  onClick={() => onReview(open, "author", v.action)}><Flag size={16} aria-hidden /></button>}
                {v?.verdict === "real_problem" && <button className="ibtn" disabled={busy} aria-label="Fix these together" data-tip="Fix these together (up to 8 pairs)" data-tip-side="left"
                  onClick={() => onFixAll(open)}><Wand2 size={16} aria-hidden /></button>}
                </>}
              </div>
            </div>
          );
        })}
        {pats.length > 4 && <button className="more" onClick={() => setAllPatterns(!allPatterns)}>
          {allPatterns ? <><ChevronUp size={13} aria-hidden /> Fewer</> : <><ChevronDown size={13} aria-hidden /> All {pats.length} patterns</>}</button>}
      </div>}
    </details>
  );
}
