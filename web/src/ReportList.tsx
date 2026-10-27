import { useMemo, useState } from "react";
import type { Matches, Report, ReportClash } from "./api";

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

const LINK_TITLE = { both: "Both elements found in the open model", one: "One element found in the open model", none: "Not in the open model" };

const short = (c: ReportClash) => `${c.a.ifc_class ?? "?"} × ${c.b.ifc_class ?? "?"}`;

export function ReportList({ report, matches, selected, onSelect }: {
  report: Report; matches: Matches | null; selected: string | null; onSelect: (c: ReportClash) => void;
}) {
  const [query, setQuery] = useState("");
  const [onlyLinked, setOnlyLinked] = useState(false);

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const out = new Map<string, ReportClash[]>();
    for (const c of report.clashes) {
      if (onlyLinked && linkState(matches, c.id) !== "both") continue;
      const text = [c.name, c.test, c.a.name, c.b.name, c.a.ifc_class, c.b.ifc_class, c.a.level, c.b.level, c.grid].join(" ").toLowerCase();
      if (q && !text.includes(q)) continue;
      out.set(c.test, [...(out.get(c.test) ?? []), c]);
    }
    return [...out.entries()];
  }, [report, matches, query, onlyLinked]);

  const shown = groups.reduce((n, [, cs]) => n + cs.length, 0);
  const linked = matches ? report.clashes.filter((c) => linkState(matches, c.id) === "both").length : null;

  return (
    <div className="report">
      <div className="report-head">
        <h2>{report.title}</h2>
        <p className="hint">
          {report.clashes.length} clashes in {new Set(report.clashes.map((c) => c.test)).size} tests
          {linked != null ? ` · ${linked} found in the model` : " · open the models to link them"}
        </p>
        <input className="search" type="search" placeholder="Filter: element, class, level, test…" value={query}
          onChange={(e) => setQuery(e.target.value)} aria-label="Filter clashes" />
        {matches && <label className="check"><input type="checkbox" checked={onlyLinked} onChange={(e) => setOnlyLinked(e.target.checked)} /> Only clashes in the open model</label>}
        {shown !== report.clashes.length && <p className="hint">{shown} shown</p>}
      </div>
      <div className="groups">
        {groups.map(([test, cs]) => (
          <details key={test} open={!!query.trim() || groups.length <= 3 || cs.some((c) => c.id === selected)}>
            <summary><span className="test">{test}</span><span className="count mono">{cs.length}</span></summary>
            {cs.map((c) => {
              const link = linkState(matches, c.id);
              return (
                <button key={c.id} className={`clash-row ${selected === c.id ? "pick" : ""}`} onClick={() => onSelect(c)}>
                  {link && <i className={`dot ${link}`} title={LINK_TITLE[link]} />}
                  <span className="clash-name">{c.name}</span>
                  <span className="clash-pair">{short(c)}</span>
                  <span className="mono dist">{mm(c.distance_m)}</span>
                </button>
              );
            })}
          </details>
        ))}
        {!shown && <p className="hint">No clash matches the filter.</p>}
      </div>
    </div>
  );
}
