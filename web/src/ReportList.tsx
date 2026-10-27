import { CircleCheck, Network, Search, Wand2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { Matches, Report, ReportClash, RootCause } from "./api";

export function mm(m: number | null | undefined) {
  if (m == null) return "—";
  const v = Math.round(m * 1000) || 0; // no "-0 mm" for touching elements
  return `${v > 0 ? "+" : ""}${v} mm`;
}

/** How much of a clash the open model can show: both elements, one, or none (null before any model is open). */
export function linkState(m: Matches | null, id: string): "both" | "one" | "none" | null {
  const x = m?.[id];
  if (!m) return null;
  if (!x) return "none";
  return x.a && x.b ? "both" : x.a || x.b ? "one" : "none";
}

const LINK_TITLE = { both: "Both elements are in the open model", one: "One element is in the open model", none: "Not in the open model" };

const short = (c: ReportClash) => `${c.a.ifc_class?.replace(/^Ifc/, "") ?? "?"} × ${c.b.ifc_class?.replace(/^Ifc/, "") ?? "?"}`;

export function ReportList({ report, matches, selected, onSelect, fixes, checked, onCheck, onFixChecked, rootCauses, onFixRoot, busy }: {
  report: Report; matches: Matches | null; selected: string | null; onSelect: (c: ReportClash) => void;
  fixes: Record<string, string>;
  checked: Set<string>; onCheck: (ids: string[], on: boolean) => void; onFixChecked: () => void;
  rootCauses: RootCause[] | null; onFixRoot: (hub: string) => void; busy: boolean;
}) {
  const [query, setQuery] = useState("");
  const [onlyLinked, setOnlyLinked] = useState(false);
  const [hideFixed, setHideFixed] = useState(false);

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const out = new Map<string, ReportClash[]>();
    for (const c of report.clashes) {
      if (onlyLinked && linkState(matches, c.id) !== "both") continue;
      if (hideFixed && fixes[c.id]) continue;
      const text = [c.name, c.test, c.a.name, c.b.name, c.a.ifc_class, c.b.ifc_class, c.a.level, c.b.level, c.grid].join(" ").toLowerCase();
      if (q && !q.split(/\s+/).every((w) => text.includes(w))) continue;
      out.set(c.test, [...(out.get(c.test) ?? []), c]);
    }
    return [...out.entries()];
  }, [report, matches, query, onlyLinked, hideFixed, fixes]);

  // Bring the selected clash into view, also when something else (the chat) selected it.
  useEffect(() => {
    if (!selected) return;
    const t = setTimeout(() => { document.querySelector(`[data-clash="${selected}"]`)?.scrollIntoView({ block: "nearest" }); }, 50);
    return () => clearTimeout(t);
  }, [selected]);

  const shown = groups.reduce((n, [, cs]) => n + cs.length, 0);
  const linked = matches ? report.clashes.filter((c) => linkState(matches, c.id) === "both").length : null;
  const fixedCount = report.clashes.filter((c) => fixes[c.id]).length;
  const fixable = (c: ReportClash) => linkState(matches, c.id) === "both" && !fixes[c.id];
  const cross = rootCauses?.filter((r) => r.cross_discipline > 0) ?? [];

  return (
    <div className="report">
      <div className="report-head">
        <div className="row"><h2>{report.title}</h2>{fixedCount > 0 && <span className="chip ok"><CircleCheck size={12} aria-hidden /> {fixedCount} fixed</span>}</div>
        <p className="hint">{report.clashes.length} clashes · {new Set(report.clashes.map((c) => c.test)).size} tests
          {linked != null ? ` · ${linked} in the model` : " · open the models to link them"}</p>
        <div className="search-box">
          <Search size={15} aria-hidden />
          <input type="search" placeholder="Filter by element, class, level…" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Filter clashes" />
        </div>
        <div className="filters">
          {matches && <label className="check"><input type="checkbox" checked={onlyLinked} onChange={(e) => setOnlyLinked(e.target.checked)} /> In the model</label>}
          {fixedCount > 0 && <label className="check"><input type="checkbox" checked={hideFixed} onChange={(e) => setHideFixed(e.target.checked)} /> Hide fixed</label>}
          {shown !== report.clashes.length && <span className="hint">{shown} shown</span>}
        </div>
      </div>

      {cross.length > 0 && (
        <section className="roots" aria-label="Root causes">
          <h3><Network size={15} aria-hidden /> Root causes</h3>
          {cross.slice(0, 3).map((r) => (
            <div key={r.hub.global_id} className="root">
              <div className="root-text">
                <b title={`${r.hub.ifc_class} '${r.hub.name}': ${r.partners.map((p) => p.name).join(", ")}`}>{r.hub.name}</b>
                <span className="hint">{r.partners.length} clashing elements · {r.hub.storey ?? r.hub.source}
                  {r.not_in_report > 0 && <> · <span className="warn">{r.not_in_report} not in the report</span></>}</span>
              </div>
              <button className="btn small" disabled={busy} onClick={() => onFixRoot(r.hub.global_id)}
                data-tip="Fix them all together" data-tip-side="left"><Wand2 size={14} aria-hidden /> Fix</button>
            </div>
          ))}
        </section>
      )}

      <div className="groups">
        {groups.map(([test, cs]) => {
          const pick = cs.filter(fixable).map((c) => c.id);
          const all = pick.length > 0 && pick.every((id) => checked.has(id));
          return (
            <details key={test} open={!!query.trim() || groups.length <= 3 || cs.some((c) => c.id === selected)}>
              <summary>
                {matches && <input type="checkbox" className="group-check" aria-label={`Select every fixable clash in ${test}`}
                  checked={all} disabled={!pick.length} onClick={(e) => e.stopPropagation()} onChange={(e) => onCheck(pick, e.target.checked)} />}
                <span className="test">{test}</span>
                {cs.some((c) => fixes[c.id]) && <span className="ok count">✓ {cs.filter((c) => fixes[c.id]).length}</span>}
                <span className="count mono">{cs.length}</span>
              </summary>
              {cs.map((c) => {
                const link = linkState(matches, c.id);
                return (
                  <div key={c.id} className={`clash-row ${selected === c.id ? "pick" : ""} ${fixes[c.id] ? "fixed" : ""}`} data-clash={c.id}>
                    {matches && <input type="checkbox" aria-label={`Select ${c.name}`} checked={checked.has(c.id)} disabled={!fixable(c)}
                      onChange={(e) => onCheck([c.id], e.target.checked)} />}
                    <button className="clash-main" onClick={() => onSelect(c)} title={fixes[c.id] ? `Fixed: ${fixes[c.id]}` : link ? LINK_TITLE[link] : undefined}>
                      {fixes[c.id] ? <i className="tick" aria-label="Fixed">✓</i> : link ? <i className={`dot ${link}`} /> : <i />}
                      <span className="clash-name">{c.name}</span>
                      <span className="clash-pair">{short(c)}</span>
                      {fixes[c.id] ? <span className="fixed-label">fixed</span> : <span className="mono dist">{mm(c.distance_m)}</span>}
                    </button>
                  </div>
                );
              })}
            </details>
          );
        })}
        {!shown && <p className="hint">No clash matches the filter.</p>}
      </div>

      {checked.size > 0 && (
        <div className="selbar">
          <span><b>{checked.size}</b> selected</span>
          <button className="ibtn" aria-label="Clear the selection" data-tip="Clear" data-tip-side="top" onClick={() => onCheck([...checked], false)}><X size={16} aria-hidden /></button>
          <button className="btn primary small" disabled={busy} onClick={onFixChecked}><Wand2 size={14} aria-hidden /> Fix {checked.size} together</button>
        </div>
      )}
    </div>
  );
}
