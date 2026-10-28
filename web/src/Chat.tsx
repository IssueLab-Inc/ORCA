import { Mic, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, type ChatEvent } from "./api";
import type { ChatRequest, ChatRequestOwner } from "./chatRequest";
import { MAX_SECONDS, VoiceRecorder } from "./voice";

/** One step the assistant took, shown under its answer. */
export interface Step { name: string; args: Record<string, unknown>; summary?: string }
export interface Turn { role: "user" | "assistant"; text: string; steps: Step[]; pending?: boolean; error?: string; voice?: boolean; request?: number }

const VERBS: Record<string, string> = {
  report_summary: "Read the report summary", list_clashes: "Listed clashes", get_clash: "Read a clash",
  look_at_clash_images: "Looked at the clash images", measure_clash: "Measured the clash",
  describe_element: "Read an element", find_elements: "Searched the model", find_openings: "Looked for openings",
  check_move: "Checked a move", check_offset: "Checked an offset", propose_fixes: "Ran the fix agent",
  show_clash: "Showed a clash", set_view: "Changed the view", find_root_causes: "Looked for root causes",
  find_patterns: "Looked for patterns",
  plan_root_cause: "Planned a root-cause fix", plan_fixes_together: "Planned fixes together",
  explore_wider_fix: "Explored a wider fix",
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

export function ChatPanel({ context, onEvent, owner, ready, ask }: {
  context: () => { scene_id: string | null; report_id: string | null; clash_id: string | null; fixed: string[] };
  onEvent: (e: ChatEvent) => void;
  owner: ChatRequestOwner;
  ready: boolean;
  ask?: { text: string; send: boolean; n: number };  // the tour: put this in the box, or send it
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const session = useRef<string | null>(null);
  const active = useRef<ChatRequest | null>(null);
  const mounted = useRef(false);
  const sequence = useRef(0);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [turns]);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; active.current?.cancel(); active.current = null; };
  }, []);
  const patchTurn = (request: number, f: (t: Turn) => Turn) => {
    if (mounted.current) setTurns((ts) => ts.map((t) => t.request === request ? f(t) : t));
  };

  // Voice: record, transcribe with Muse Voice Transcribe, then send the words like a typed message.
  const recorder = useRef<VoiceRecorder | null>(null);
  const [voice, setVoice] = useState<{ state: "idle" | "listening" | "transcribing"; since: number; level: number; note?: string }>(
    { state: "idle", since: 0, level: 0 });
  const [, setTick] = useState(0);
  useEffect(() => () => { recorder.current?.cancel(); }, []);
  useEffect(() => {
    if (voice.state !== "listening") return;
    const t = setInterval(() => {
      setTick((n) => n + 1);
      if (Date.now() - voice.since > MAX_SECONDS * 1000) void stopListening();  // a minute at most
    }, 250);
    return () => { clearInterval(t); };
  }, [voice.state, voice.since]);  // eslint-disable-line react-hooks/exhaustive-deps

  async function startListening() {
    if (busy || voice.state !== "idle") return;
    const r = new VoiceRecorder();
    const current = owner.capture();
    try {
      await r.start((level) => setVoice((v) => (v.state === "listening" ? { ...v, level } : v)));
    } catch (e) {
      if (!mounted.current || !current()) return;
      const denied = (e as Error).name === "NotAllowedError";
      setVoice({ state: "idle", since: 0, level: 0, note: denied ? "Microphone access was blocked. Allow it in the browser to talk to Sightline."
        : "No microphone found." });
      return;
    }
    if (!mounted.current || !current()) { r.cancel(); return; }
    recorder.current = r;
    setVoice({ state: "listening", since: Date.now(), level: 0 });
  }

  async function stopListening() {
    const r = recorder.current;
    if (!r) return;
    recorder.current = null;
    const current = owner.capture(), reportId = context().report_id;
    setVoice({ state: "transcribing", since: 0, level: 0 });
    try {
      const { transcript } = await api.transcribe(await r.stop(), reportId);
      if (!mounted.current) return;
      if (!current()) { setVoice({ state: "idle", since: 0, level: 0 }); return; }
      setVoice({ state: "idle", since: 0, level: 0, note: transcript ? undefined : "Didn't catch that. Try again, a little closer to the mic." });
      if (transcript) await send(transcript, true);
    } catch (e) {
      if (!mounted.current) return;
      if (!current()) { setVoice({ state: "idle", since: 0, level: 0 }); return; }
      setVoice({ state: "idle", since: 0, level: 0, note: (e as Error).message });
    }
  }

  useEffect(() => {
    if (!ask) return;
    if (ask.send) void send(ask.text); else setDraft(ask.text);
  }, [ask?.n]);  // eslint-disable-line react-hooks/exhaustive-deps

  async function send(text: string, spoken = false) {
    const message = text.trim();
    if (!message || !ready || busy || !mounted.current || active.current?.isCurrent()) return;
    const request = ++sequence.current, lease = owner.begin();
    active.current = lease;
    const current = () => mounted.current && active.current === lease && lease.isCurrent();
    const patch = (f: (t: Turn) => Turn) => patchTurn(request, f);
    const aborted = () => {
      if (!mounted.current || active.current !== lease) return;
      patch((t) => ({ ...t, pending: false, text: t.text || "Stopped when newer work took over." }));
      active.current = null; setBusy(false);
    };
    lease.signal.addEventListener("abort", aborted, { once: true });
    setDraft("");
    setBusy(true);
    setTurns((ts) => [...ts, { role: "user", text: message, steps: [], voice: spoken }, { role: "assistant", text: "", steps: [], pending: true, request }]);
    try {
      await api.chat({ message, session_id: session.current, ...context() }, (e) => {
        if (!current()) return;
        if (e.type === "session") session.current = e.id;
        if (e.type === "tool") patch((t) => ({ ...t, steps: [...t.steps, { name: e.name, args: e.args }] }));
        if (e.type === "tool_result") patch((t) => {
          const steps = [...t.steps];
          const i = steps.map((s) => s.name).lastIndexOf(e.name);
          if (i >= 0) steps[i] = { ...steps[i], summary: e.summary };
          return { ...t, steps };
        });
        if (e.type === "message") patch((t) => ({ ...t, text: e.text, pending: false }));
        if (e.type === "error") patch((t) => ({ ...t, error: e.detail, pending: false }));
        onEvent(e);
      }, lease.signal);
    } catch (err) {
      if (current()) {
        const detail = (err as Error).message;
        patch((t) => ({ ...t, error: detail, pending: false }));
        onEvent({ type: "error", detail });
      }
    } finally {
      if (current()) { patch((t) => ({ ...t, pending: false })); setBusy(false); active.current = null; }
      lease.signal.removeEventListener("abort", aborted);
      lease.finish();
    }
  }

  return (
    <div className="chat">
      <div className="chat-log" aria-live="polite">
        {!turns.length && (
          <div className="chat-empty">
            <p className="hint">Ask Sightline about the open clash report and model. It can read clashes, look at their
              images, measure, try fixes and show you what it means. Type, or press the mic and say it.</p>
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
            {t.text && (t.role === "assistant" ? <Rich text={t.text} />
              : <p>{t.voice && <Mic size={12} className="said" aria-label="Spoken" />}{t.text}</p>)}
            {t.error && <p className="bad">{t.error}</p>}
          </div>
        ))}
        <div ref={end} />
      </div>
      <form className="chat-input" onSubmit={(e) => { e.preventDefault(); send(draft); }}>
        <textarea value={draft} rows={2} placeholder={ready ? "Ask about the clashes…" : "Open a model or a clash report first"}
          disabled={!ready} onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(draft); } }} aria-label="Message" />
        <button className="btn primary" data-tour="chat-send" disabled={!ready || busy || !draft.trim()}>{busy ? "…" : "Send"}</button>
        {VoiceRecorder.supported() && (voice.state === "listening"
          ? <button type="button" className="btn mic on" onClick={() => void stopListening()} aria-label="Stop and send"
              data-tip="Stop and send" data-tip-side="top" style={{ "--level": voice.level } as React.CSSProperties}>
              <Square size={13} aria-hidden /> {Math.floor((Date.now() - voice.since) / 1000)} s</button>
          : <button type="button" className="btn mic" onClick={() => void startListening()} disabled={!ready || busy || voice.state === "transcribing"}
              aria-label="Speak to Sightline" data-tip="Speak to Sightline (Muse Voice Transcribe)" data-tip-side="top">
              {voice.state === "transcribing" ? <i className="spinner" aria-hidden /> : <Mic size={15} aria-hidden />}</button>)}
      </form>
      {voice.state === "listening" && <p className="voice-note live"><i className="rec" aria-hidden /> Listening… say what you want, then press stop.</p>}
      {voice.state === "transcribing" && <p className="voice-note">Turning your words into text…</p>}
      {voice.state === "idle" && voice.note && <p className="voice-note bad">{voice.note}</p>}
    </div>
  );
}
