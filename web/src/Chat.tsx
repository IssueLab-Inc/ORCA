import { useEffect, useRef, useState } from "react";
import { api, type ChatEvent } from "./api";

/** One step the assistant took, shown under its answer. */
export interface Step { name: string; args: Record<string, unknown>; summary?: string }
export interface Turn { role: "user" | "assistant"; text: string; steps: Step[]; pending?: boolean; error?: string }

const VERBS: Record<string, string> = {
  report_summary: "Read the report summary", list_clashes: "Listed clashes", get_clash: "Read a clash",
  look_at_clash_images: "Looked at the clash images", measure_clash: "Measured the clash",
  describe_element: "Read an element", find_elements: "Searched the model", find_openings: "Looked for openings",
  check_move: "Checked a move", check_offset: "Checked an offset", propose_fixes: "Ran the fix agent",
  show_clash: "Showed a clash", set_view: "Changed the view", find_root_causes: "Looked for root causes",
  plan_root_cause: "Planned a root-cause fix", plan_fixes_together: "Planned fixes together",
};

function stepLabel(s: Step) {
  const a = s.args;
  const detail = (a.clash_id as string) ?? (a.query as string) ?? (a.mode as string) ??
    (a.dz_m != null ? `${Number(a.dz_m) > 0 ? "+" : ""}${Math.round(Number(a.dz_m) * 1000)} mm` : "");
  return `${VERBS[s.name] ?? s.name}${detail ? ` (${detail})` : ""}`;
}

/** Just enough Markdown for chat answers: paragraphs, "- " and "1. " lists, **bold** and `code`. No HTML. */
function Rich({ text }: { text: string }) {
  const inline = (t: string, key: string) => t.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? <b key={`${key}-${i}`}>{part.slice(2, -2)}</b>
      : part.startsWith("`") && part.endsWith("`") ? <code key={`${key}-${i}`}>{part.slice(1, -1)}</code>
        : part);
  const blocks: React.ReactNode[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  const flush = () => {
    if (!list) return;
    const items = list.items.map((it, i) => <li key={i}>{inline(it, `li${blocks.length}-${i}`)}</li>);
    blocks.push(list.ordered ? <ol key={blocks.length}>{items}</ol> : <ul key={blocks.length}>{items}</ul>);
    list = null;
  };
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    const bullet = /^\s*[-*]\s+(.*)/.exec(line), numbered = /^\s*\d+[.)]\s+(.*)/.exec(line);
    if (bullet || numbered) {
      const ordered = !!numbered;
      if (list && list.ordered !== ordered) flush();
      list ??= { ordered, items: [] };
      list.items.push((bullet ?? numbered)![1]);
    } else if (!line.trim()) {
      flush();
    } else {
      flush();
      blocks.push(<p key={blocks.length}>{inline(line.replace(/^#+\s*/, ""), `p${blocks.length}`)}</p>);
    }
  }
  flush();
  return <>{blocks}</>;
}

const SUGGESTIONS = [
  "Which clashes in this report are real, and which are noise?",
  "Explain the selected clash.",
  "Fix the selected clash.",
  "Why are there so many clashes on Level 02? Fix the root cause.",
];

export function ChatPanel({ context, onEvent, ready }: {
  context: () => { scene_id: string | null; report_id: string | null; clash_id: string | null; fixed: string[] };
  onEvent: (e: ChatEvent) => void;
  ready: boolean;
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const session = useRef<string | null>(null);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [turns]);

  const patchLast = (f: (t: Turn) => Turn) => setTurns((ts) => [...ts.slice(0, -1), f(ts[ts.length - 1])]);

  async function send(text: string) {
    const message = text.trim();
    if (!message || busy) return;
    setDraft("");
    setBusy(true);
    setTurns((ts) => [...ts, { role: "user", text: message, steps: [] }, { role: "assistant", text: "", steps: [], pending: true }]);
    try {
      await api.chat({ message, session_id: session.current, ...context() }, (e) => {
        if (e.type === "session") session.current = e.id;
        if (e.type === "tool") patchLast((t) => ({ ...t, steps: [...t.steps, { name: e.name, args: e.args }] }));
        if (e.type === "tool_result") patchLast((t) => {
          const steps = [...t.steps];
          const i = steps.map((s) => s.name).lastIndexOf(e.name);
          if (i >= 0) steps[i] = { ...steps[i], summary: e.summary };
          return { ...t, steps };
        });
        if (e.type === "message") patchLast((t) => ({ ...t, text: e.text, pending: false }));
        if (e.type === "error") patchLast((t) => ({ ...t, error: e.detail, pending: false }));
        onEvent(e);
      });
    } catch (err) {
      patchLast((t) => ({ ...t, error: (err as Error).message, pending: false }));
    } finally {
      patchLast((t) => ({ ...t, pending: false }));
      setBusy(false);
    }
  }

  return (
    <div className="chat">
      <div className="chat-log" aria-live="polite">
        {!turns.length && (
          <div className="chat-empty">
            <p className="hint">Ask Sightline about the open clash report and model. It can read clashes, look at their
              images, measure, try fixes and show you what it means.</p>
            {SUGGESTIONS.map((s) => <button key={s} className="suggest" disabled={!ready} onClick={() => send(s)}>{s}</button>)}
          </div>
        )}
        {turns.map((t, i) => (
          <div key={i} className={`msg ${t.role}`}>
            {t.role === "assistant" && t.steps.length > 0 && (
              <details className="tools" open={t.pending}>
                <summary>{t.pending ? "Working" : "Steps"} · {t.steps.length} tool call{t.steps.length > 1 ? "s" : ""}</summary>
                <ul>{t.steps.map((s, j) => <li key={j}>{stepLabel(s)}{s.summary ? <span className="why"> → {s.summary}</span> : <span className="why"> …</span>}</li>)}</ul>
              </details>
            )}
            {t.pending && !t.text && <p className="hint"><i className="spinner" aria-hidden /> Thinking…</p>}
            {t.text && (t.role === "assistant" ? <Rich text={t.text} /> : <p>{t.text}</p>)}
            {t.error && <p className="bad">{t.error}</p>}
          </div>
        ))}
        <div ref={end} />
      </div>
      <form className="chat-input" onSubmit={(e) => { e.preventDefault(); send(draft); }}>
        <textarea value={draft} rows={2} placeholder={ready ? "Ask about the clashes…" : "Open a model or a clash report first"}
          disabled={!ready} onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(draft); } }} aria-label="Message" />
        <button className="btn primary" disabled={!ready || busy || !draft.trim()}>{busy ? "…" : "Send"}</button>
      </form>
    </div>
  );
}
