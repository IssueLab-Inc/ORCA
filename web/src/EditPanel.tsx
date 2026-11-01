// The Edits panel (docs/manual-edits.md): the scene's edit log, newest first. Every kept edit is here, whoever made it
// (you by hand, Muse in chat or by voice, an agent, an accepted fix, a plan, a wider fix), with the clash it is for,
// the fix it amends, what its check found and any review it needs. Undo and redo walk it from the top.
import { Bot, Download, Hand, Network, Sparkles, Wand2, Wrench } from "lucide-react";
import type { EditSource, Journal, JournalEntry } from "./api";
import { RedoIcon, UndoIcon } from "./editIcons";

const SOURCE: Record<EditSource, { label: string; Icon: typeof Hand }> = {
  you: { label: "You", Icon: Hand }, muse: { label: "Muse", Icon: Sparkles }, agent: { label: "Agent", Icon: Bot },
  fix: { label: "Fix", Icon: Wand2 }, plan: { label: "Plan", Icon: Network }, wider: { label: "Wider fix", Icon: Wrench },
};

const mm = (m: number) => `${Math.round(m * 1000).toLocaleString()} mm`;

/** What the entry's check found, in one line: verified, or what a hand edit cleared and what it was kept with. */
export function checkLine(e: JournalEntry): string | null {
  const c = e.check;
  if (!c) return null;
  if (c.verified) return c.min_clearance_m != null ? `Verified · nearest ${mm(c.min_clearance_m)}` : "Verified";
  const parts: string[] = [];
  const cleared = c.cleared?.length ?? 0, made = (c.new?.length ?? 0) + (c.worse?.length ?? 0);
  if (cleared) parts.push(`cleared ${cleared}`);
  if (made) parts.push(`kept with ${made} clash${made === 1 ? "" : "es"}`);
  else parts.push(c.min_clearance_m != null ? `clear · nearest ${mm(c.min_clearance_m)}` : "clear");
  return `Checked · ${parts.join(" · ")}`;
}

/** Local time of day for an entry ("14:05"). */
export const timeOf = (e: JournalEntry) => new Date(e.when).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

export function EditPanel({ journal, busy, csvUrl, clashLabel, onUndo, onRedo, onUndoTo, onShow }: {
  journal: Journal | null; busy: boolean; csvUrl: string | null;
  /** "#042" for a clash id the list knows, else null. */ clashLabel: (id: string) => string | null;
  onUndo: () => void; onRedo: () => void; onUndoTo: (e: JournalEntry) => void; onShow: (e: JournalEntry) => void;
}) {
  const entries = [...(journal?.entries ?? [])].reverse();
  const kept = entries.filter((e) => e.state === "kept");
  return (
    <div className="edits-panel">
      <div className="edits-bar">
        <button type="button" className="ebtn btn small" disabled={busy || !journal?.can_undo} onClick={onUndo}
          data-tip={journal?.undo ? `Undo ${journal.undo}  ·  Ctrl+Z` : "Nothing to undo"}>
          <UndoIcon size={15} aria-hidden /> Undo</button>
        <button type="button" className="ebtn btn small" disabled={busy || !journal?.can_redo} onClick={onRedo}
          data-tip={journal?.redo ? `Redo ${journal.redo}  ·  Ctrl+Shift+Z` : "Nothing to redo"}>
          <RedoIcon size={15} aria-hidden /> Redo</button>
        <span className="why">{kept.length} kept</span>
        {csvUrl && entries.length > 0 && <a className="ibtn" href={csvUrl} download aria-label="Download the edit log (CSV)"
          data-tip="Download the edit log (CSV)" data-tip-side="left"><Download size={15} aria-hidden /></a>}
      </div>
      {!entries.length && <p className="hint">Every edit kept to the model shows here: fixes you accept, edits you make
        with the Edit tool (P) or ask Muse for, and what an agent keeps. Each one can be undone.</p>}
      <ol className="edits-list">
        {entries.map((e) => {
          const s = SOURCE[e.source] ?? SOURCE.you;
          const clashes = e.clashes.map((c) => (c.id ? clashLabel(c.id) : null)).filter((x): x is string => !!x);
          const line = checkLine(e);
          return (
            <li key={e.id} className={`edit-row ${e.state}`}>
              <button type="button" className="edit-main" onClick={() => onShow(e)} data-tip="Show it in the model" data-tip-side="left">
                <span className={`chip src-${e.source}`}><s.Icon size={11} aria-hidden /> {s.label}</span>
                <b className="mono">{e.id}</b><span className="why mono">{timeOf(e)}</span>
                {e.state === "undone" && <span className="chip undone-chip" data-tip="Taken back: not in the model now">Undone</span>}
                {[...new Set(clashes)].map((c) => <span key={c} className="chip">{c}</span>)}
                {e.follows.length > 0 && <span className="chip follows" data-tip="Edited by hand after this fix">after {e.follows.join(", ")}</span>}
                <span className="edit-text">{e.summary || e.title}</span>
                {line && <span className={`edit-check ${e.check?.verified ? "ok" : (e.check?.new?.length || e.check?.worse?.length) ? "warn" : ""}`}>{line}</span>}
                {e.status && e.state === "kept" && <span className={`edit-check ${e.status.resolved ? "ok" : "bad"}`}>
                  {e.status.resolved ? (e.follows.length ? "Its clash is still resolved" : "Its clash is resolved")
                    : `${e.follows.length ? "Its clash is back" : "Its clash is still open"} (${e.status.depth_m != null ? mm(e.status.depth_m) : "touching"})`}</span>}
                {e.warnings.map((w, i) => <span key={i} className="edit-warn">{w.text}{w.review ? ` · review: ${w.review}` : ""}</span>)}
              </button>
              {((e.state === "kept" && kept[0]?.id !== e.id) || (e.state === "undone" && journal?.redo === e.id)) && (
                <div className="edit-row-actions">
                  {e.state === "kept"
                    ? <button type="button" className="btn small ghost" disabled={busy} onClick={() => onUndoTo(e)}
                        data-tip={`Undo every edit back to ${e.id}, newest first`} data-tip-side="left">Undo to here</button>
                    : <button type="button" className="ebtn btn small ghost" disabled={busy} onClick={onRedo}
                        data-tip={`Redo ${e.id}  ·  Ctrl+Shift+Z`} data-tip-side="left"><RedoIcon size={13} aria-hidden /> Redo</button>}
                </div>)}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
