import { CircleCheck, Network, Search, Sparkles, Wand2, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Matches, type Report, type ReportClash, type TriageKind, type TriageVerdict } from "./api";
import { ClashThumb } from "./ClashPanel";
import { TRIAGE } from "./Triage";
import { noClash } from "./noClash";
import { aiName } from "./aiNames";

/** A clash someone looked at and decided needs no model edit here. */
export interface Review { kind: "by_design" | "author"; note: string }

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

/** "#39 Cold-water main clips the transfer girder": its number across the report, and Muse's title or its plain name. */
export const clashLabel = (c: ReportClash) => `#${c.number} ${c.title ?? c.name}`;

function ImpactBar({ total, triage, fixes, reviewed }: { total: number; triage: Record<string, TriageVerdict>; fixes: Record<string, string>; reviewed: Record<string, Review> }) {
  const triaged = Object.keys(triage).length;
  if (!triaged) return <p className="impact-bar"><span><b>{total}</b> clashes to sort</span><span className="why">Run Triage all to separate real problems from noise.</span></p>;
  const real = Object.values(triage).filter((v) => v.verdict === "real_clash").length;
  const resolved = Object.keys(fixes).length + Object.keys(reviewed).length;
  const need = Math.max(0, real - Object.keys(fixes).length);
  const hours = (triaged * 15 / 60).toFixed(1).replace(/\.0$/, "");
  return <p className="impact-bar" role="status"><span><b>{total}</b> clashes</span><span className="bad"><b>{real}</b> real</span><span><b>{need}</b> need a fix</span><span className="ok"><b>{resolved}</b> resolved</span><span className="why">≈{hours} h of manual review sorted (est. 15 min/clash)</span></p>;
}
/** The left pane over an open report, in two tabs so the list gets the room: **Clashes** (a short head, Triage and the
 * list, which scrolls on its own) and **Insights** (the run, what the clashes add up to, root causes and patterns). */
/** Each element a clash takes, as the open model knows it (the matched element, else the report's GlobalId, else its
 * class and name): what "the same elements" are matched on. */
function elementsOf(c: ReportClash, matches: Matches | null): string[] {
  const m = matches?.[c.id];
  const key = (e: ReportClash["a"], id: string | null | undefined) => id ?? e.global_id ?? `${e.ifc_class ?? ""}:${e.name}`;
  return [...new Set([key(c.a, m?.a), key(c.b, m?.b)])];
}

/** The other clashes sharing an element (either one) with each clash in the list. */
export function sameElements(clashes: ReportClash[], matches: Matches | null): Map<string, string[]> {
  const by = new Map<string, string[]>();
  for (const c of clashes) for (const e of elementsOf(c, matches)) by.set(e, [...(by.get(e) ?? []), c.id]);
  const out = new Map<string, string[]>();
  for (const c of clashes) {
    const ids = new Set(elementsOf(c, matches).flatMap((e) => by.get(e) ?? []));
    ids.delete(c.id);
    out.set(c.id, [...ids]);
  }
  return out;
}

export function ReportList({ report, matches, selected, onSelect, onImage, fixes, reviewed, checked, onCheck, onFixChecked, triageCard, insights,
  insightsCount = null, view = "clashes", onView, status, picker, busy, triage, triageFilter, naming = 0, thumbs, onThumb, focus = null, onClearFocus,
  onPropose, onSetAside, onFocus }: {
  report: Report; matches: Matches | null; selected: string | null; onSelect: (c: ReportClash) => void;
  onImage: (c: ReportClash, index: number) => void;
  fixes: Record<string, string>; reviewed: Record<string, Review>;
  checked: Set<string>; onCheck: (ids: string[], on: boolean) => void; onFixChecked: () => void;
  triageCard?: React.ReactNode;  // Triage: the first step, and the list's verdict filter
  insights: React.ReactNode;     // the Insights tab: the run's summary, root causes, patterns
  insightsCount?: number | null; // what is still open there (root causes + patterns), for the tab
  view?: "clashes" | "insights"; onView?: (v: "clashes" | "insights") => void;
  status?: React.ReactNode;      // a check running again, shown over the list
  picker?: React.ReactNode;      // ORCA's kept checks: which one the list shows (docs/detection.md, "Kept checks")
  busy: boolean;
  triage: Record<string, TriageVerdict>; triageFilter: TriageKind | null;
  naming?: number;  // clashes Muse is still titling
  /** Thumbnails drawn in the browser for clashes with no pictures (detected ones), and a way to ask for one. */
  thumbs?: Record<string, string>; onThumb?: (c: ReportClash) => void;
  /** Only these clashes (a pattern or root cause picked in Insights), with a chip to show every clash again. */
  focus?: { label: string; ids: string[] } | null; onClearFocus?: () => void;
  /** A row's quick actions, shown on hover (and on the selected row, for touch): propose fixes for it, set it aside as
   * not a clash, and narrow the list to the clashes sharing an element with it (`onFocus`, as Insights does). */
  onPropose?: (c: ReportClash) => void; onSetAside?: (c: ReportClash, note: string) => void;
  onFocus?: (f: { label: string; ids: string[] }) => void;
}) {
  const [query, setQuery] = useState("");
  const [onlyLinked, setOnlyLinked] = useState(false);
  // Which clashes by where they stand: all, those still to fix, the fixed, the reviewed (owner request, Oct 31).
  const [show, setShow] = useState<"all" | "open" | "fixed" | "reviewed">("all");
  const fixedCount = report.clashes.filter((c) => fixes[c.id]).length;
  const reviewedCount = report.clashes.filter((c) => !fixes[c.id] && reviewed[c.id]).length;
  // Nothing fixed or reviewed (another report, a fresh check): the filter has nothing to choose from, so it is off.
  const by = fixedCount + reviewedCount > 0 ? show : "all";

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const only = focus ? new Set(focus.ids) : null;
    const out = new Map<string, ReportClash[]>();
    for (const c of report.clashes) {
      if (only && !only.has(c.id)) continue;
      if (onlyLinked && linkState(matches, c.id) !== "both") continue;
      if (by === "open" && (fixes[c.id] || reviewed[c.id])) continue;
      if (by === "fixed" && !fixes[c.id]) continue;
      if (by === "reviewed" && (fixes[c.id] || !reviewed[c.id])) continue;
      if (triageFilter && triage[c.id]?.verdict !== triageFilter) continue;
      const text = [`#${c.number}`, c.title, c.name, c.ref, c.test, c.a.name, c.b.name, c.a.ifc_class, c.b.ifc_class, c.a.level, c.b.level, c.grid].join(" ").toLowerCase();
      if (q && !q.split(/\s+/).every((w) => text.includes(w))) continue;
      out.set(c.test, [...(out.get(c.test) ?? []), c]);
    }
    return [...out.entries()];
  }, [report, matches, query, onlyLinked, by, fixes, reviewed, triage, triageFilter, focus]);

  const root = useRef<HTMLDivElement>(null);
  // Bring the selected clash into view, also when something else (the chat) selected it.
  useEffect(() => {
    if (!selected) return;
    // In the list's own document: in a pop-out window (docs/panels.md) the main document has no rows.
    const t = setTimeout(() => { root.current?.querySelector(`[data-clash="${selected}"]`)?.scrollIntoView({ block: "nearest" }); }, 50);
    return () => clearTimeout(t);
  }, [selected]);

  const related = useMemo(() => sameElements(report.clashes, matches), [report, matches]);

  const shown = groups.reduce((n, [, cs]) => n + cs.length, 0);
  const linked = matches ? report.clashes.filter((c) => linkState(matches, c.id) === "both").length : null;
  // "In the model" only when it would change the list: some clashes are not in the open models (or it is on).
  const linkFilter = linked != null && (linked < report.clashes.length || onlyLinked);
  const fixable = (c: ReportClash) => linkState(matches, c.id) === "both" && !fixes[c.id] && !reviewed[c.id]
    && !noClash(c, matches?.[c.id], null, triage[c.id]);

  const tab = (v: "clashes" | "insights", label: string, n: number | null, tour?: string) => (
    <button role="tab" aria-selected={view === v} className={view === v ? "on" : ""} data-tour={tour} onClick={() => onView?.(v)}>
      {label}{n != null && <span className={view === v ? "badge-n" : "count"}>{n}</span>}</button>
  );
  return (
    <div className="report" ref={root}>
      <div className="left-tabs" role="tablist" aria-label="The report">
        {tab("clashes", "Clashes", report.clashes.length)}
        {tab("insights", "Insights", insightsCount, "tab-insights")}
      </div>

      <div className="left-view" data-left-view="insights" hidden={view !== "insights"}>
        <div className="report-head">
          <div className="row"><h2>{report.title}</h2></div>
          <ImpactBar total={report.clashes.length} triage={triage} fixes={fixes} reviewed={reviewed} />
        </div>
        {insights}
      </div>

      <div className="left-view" data-left-view="clashes" hidden={view !== "clashes"}>
      <div className="report-head" data-tour="detected">
        <div className="row"><h2>{report.title}</h2>
          <span className="chips">{fixedCount > 0 && <button type="button" className={`chip ok as-filter ${by === "fixed" ? "on" : ""}`} aria-pressed={by === "fixed"}
              data-tip={by === "fixed" ? "Show every clash" : "Show only the fixed clashes"} data-tip-side="bottom" onClick={() => setShow(by === "fixed" ? "all" : "fixed")}>
              <CircleCheck size={12} aria-hidden /> {fixedCount} fixed</button>}
            {reviewedCount > 0 && <button type="button" className={`chip as-filter ${by === "reviewed" ? "on" : ""}`} aria-pressed={by === "reviewed"}
              data-tip={by === "reviewed" ? "Show every clash" : "Show only the reviewed clashes"} data-tip-side="bottom" onClick={() => setShow(by === "reviewed" ? "all" : "reviewed")}>
              {reviewedCount} reviewed</button>}</span></div>
        <p className="hint report-meta"><span>{new Set(report.clashes.map((c) => c.test)).size} tests
          {linked != null ? ` · ${linked} in the model` : " · open the models to link them"}</span>
          {/* A short pill, so the line never wraps while the titles land; the tip names the model */}
          {naming > 0 && <span className="naming" role="status" data-tip={`${aiName("triage")} is giving each clash a short title`} data-tip-side="bottom">
            <Sparkles size={12} aria-hidden /> Naming {naming}…</span>}</p>
        {picker}
        {status}
      </div>
      {triageCard}
      <div className="report-head list-head">
        <div className="search-box">
          <Search size={15} aria-hidden />
          <input type="search" placeholder="Filter by #, title, element, level…" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Filter clashes" />
        </div>
        {/* The search has the row to itself; the filters, when there are any, go under it */}
        {(linkFilter || fixedCount + reviewedCount > 0 || shown !== report.clashes.length) && <div className="filters">
          {linkFilter && <label className="check"><input type="checkbox" checked={onlyLinked} onChange={(e) => setOnlyLinked(e.target.checked)} /> In the model</label>}
          {fixedCount + reviewedCount > 0 && (
            <select className="status-pick" value={by} onChange={(e) => setShow(e.target.value as typeof show)} aria-label="Show clashes by status">
              <option value="all">All · {report.clashes.length}</option>
              <option value="open">To fix · {report.clashes.length - fixedCount - reviewedCount}</option>
              {fixedCount > 0 && <option value="fixed">Fixed · {fixedCount}</option>}
              {reviewedCount > 0 && <option value="reviewed">Reviewed · {reviewedCount}</option>}
            </select>)}
          {shown !== report.clashes.length && <span className="hint shown">{shown} shown</span>}
        </div>}
        {focus && <div className="list-focus" role="status">
          <span><b>{focus.label}</b> · {shown} of {focus.ids.length} shown</span>
          <button className="ibtn" onClick={onClearFocus} aria-label="Show every clash again" data-tip="Show every clash again" data-tip-side="left">
            <X size={14} aria-hidden /></button>
        </div>}
      </div>

      <div className="groups">
        {groups.map(([test, cs]) => {
          const pick = cs.filter(fixable).map((c) => c.id);
          const all = pick.length > 0 && pick.every((id) => checked.has(id));
          return (
            <details key={test} open={!!query.trim() || !!focus || by !== "all" || groups.length <= 3 || cs.some((c) => c.id === selected)}>
              <summary>
                {matches && <input type="checkbox" className="group-check" aria-label={`Select every fixable clash in ${test}`}
                  checked={all} disabled={!pick.length} onClick={(e) => e.stopPropagation()} onChange={(e) => onCheck(pick, e.target.checked)} />}
                <span className="test">{test}</span>
                {cs.some((c) => fixes[c.id] || reviewed[c.id]) && <span className="ok count">✓ {cs.filter((c) => fixes[c.id] || reviewed[c.id]).length}</span>}
                <span className="count mono">{cs.length}</span>
              </summary>
              {cs.map((c) => {
                const link = linkState(matches, c.id);
                const rv = !fixes[c.id] ? reviewed[c.id] : undefined;
                const tv = triage[c.id];
                const nc = !fixes[c.id] && !rv ? noClash(c, matches?.[c.id], null, tv) : null;
                return (
                  <div key={c.id} className={`clash-row ${selected === c.id ? "pick" : ""} ${fixes[c.id] ? "fixed" : ""} ${rv ? "reviewed" : ""} ${nc ? "noclash" : ""}`} data-clash={c.id}>
                    {matches && <input type="checkbox" aria-label={`Select ${clashLabel(c)}`} checked={checked.has(c.id)} disabled={!fixable(c)}
                      onChange={(e) => onCheck([c.id], e.target.checked)} />}
                    {c.images.length > 0
                      ? <button className="row-thumb" onClick={() => onImage(c, 0)} aria-label={`Open the images of ${clashLabel(c)}`}
                          title={`#${c.number}: open its ${c.images.length === 1 ? "image" : `${c.images.length} views`}`}>
                          <ClashThumb url={api.imageUrl(report.id, c.id, 0)} alt="" />
                        </button>
                      : thumbs && onThumb
                        ? <LazyThumb clash={c} url={thumbs[c.id]} onNeed={onThumb} onOpen={() => onSelect(c)} />
                        : report.clashes.some((x) => x.images.length) && <span className="row-thumb none" aria-hidden />}
                    <button className="clash-main" onClick={() => onSelect(c)} title={fixes[c.id] ? `Fixed: ${fixes[c.id]}` : rv ? rv.note : link ? LINK_TITLE[link] : undefined}>
                      {fixes[c.id] ? <i className="tick" aria-label="Fixed">✓</i> : rv ? <i className="tick muted" aria-label="Reviewed">✓</i> : link ? <i className={`dot ${link}`} /> : <i />}
                      <span className="clash-name">#{c.number}</span>
                      <span className={`clash-pair ${c.title ? "titled" : ""}`}>{c.title ?? c.name}</span>
                      {nc && !tv && <span className="tv muted" title={nc.why}>{nc.label}</span>}
                      {tv && !fixes[c.id] && !rv && <span className={`tv ${TRIAGE[tv.verdict].cls}`} title={tv.understanding || TRIAGE[tv.verdict].tip}
                        aria-label={`Triage: ${TRIAGE[tv.verdict].label}`}>{TRIAGE[tv.verdict].label}</span>}
                      {fixes[c.id] ? <span className="fixed-label">fixed</span>
                        : rv ? <span className={`review-label ${rv.kind}`}>{rv.kind === "by_design" ? "by design" : "for author"}</span>
                          : <span className="mono dist">{mm(c.distance_m)}</span>}
                    </button>
                    <RowActions clash={c} label={clashLabel(c)} related={related.get(c.id) ?? []}
                      canFix={fixable(c) && !nc && !busy} canSetAside={!fixes[c.id] && !rv}
                      note={nc?.why ?? (tv?.verdict === "by_design" ? tv.understanding : undefined) ?? "Set aside from the clash list"}
                      onPropose={onPropose} onSetAside={onSetAside}
                      onSame={onFocus && ((ids) => onFocus({ label: `Clashes with ${shortName(c.a)} or ${shortName(c.b)}`, ids: [c.id, ...ids] }))} />
                  </div>
                );
              })}
            </details>
          );
        })}
        {!shown && <p className="hint">No clash matches the filter.</p>}
      </div>
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

const shortName = (e: ReportClash["a"]) => (e.name || e.ifc_class || "an element").split(/\s+-\s+/)[0];

/** A row's quick actions (docs/architecture/12-web-app.md, ReportList): shown on hover, keyboard focus, and on the
 * selected row, so a touch screen has them too. Each is left out when it cannot apply. */
function RowActions({ clash, label, related, canFix, canSetAside, note, onPropose, onSetAside, onSame }: {
  clash: ReportClash; label: string; related: string[]; canFix: boolean; canSetAside: boolean; note: string;
  onPropose?: (c: ReportClash) => void; onSetAside?: (c: ReportClash, note: string) => void; onSame?: (ids: string[]) => void;
}) {
  if (!(onPropose && canFix) && !(onSetAside && canSetAside) && !(onSame && related.length)) return null;
  return (
    <span className="row-actions" role="group" aria-label={`Actions for ${label}`}>
      {onPropose && canFix && <button className="ibtn" aria-label={`Propose fixes for ${label}`} data-tip="Propose fixes"
        data-tip-side="left" onClick={() => onPropose(clash)}><Sparkles size={14} aria-hidden /></button>}
      {onSetAside && canSetAside && <button className="ibtn" aria-label={`Mark ${label} as not a clash`} data-tip="Mark as not a clash"
        data-tip-side="left" onClick={() => onSetAside(clash, note)}><CircleCheck size={14} aria-hidden /></button>}
      {onSame && related.length > 0 && <button className="ibtn same" aria-label={`${related.length} more clash${related.length === 1 ? "" : "es"} with the same elements as ${label}`}
        data-tip={`${related.length} more with the same elements`} data-tip-side="left" onClick={() => onSame(related)}>
        <Network size={14} aria-hidden /><span className="n">{related.length}</span></button>}
    </span>
  );
}

/** A row's thumbnail drawn by the viewer: asked for when the row comes into view, an empty box until it lands. */
function LazyThumb({ clash, url, onNeed, onOpen }: { clash: ReportClash; url: string | undefined; onNeed: (c: ReportClash) => void; onOpen: () => void }) {
  const el = useRef<HTMLSpanElement | null>(null);
  useEffect(() => {
    const node = el.current;
    if (url !== undefined || !node) return;
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) { io.disconnect(); onNeed(clash); }
    }, { rootMargin: "100px" });
    io.observe(node);
    return () => io.disconnect();
  }, [clash.id, url]);  // eslint-disable-line react-hooks/exhaustive-deps
  return url
    ? <button className="row-thumb" onClick={onOpen} aria-label={`Open ${clashLabel(clash)}`} title={`#${clash.number}: open it`}>
        <ClashThumb url={url} alt="" /></button>
    : <span ref={el} className="row-thumb none" aria-hidden />;
}
