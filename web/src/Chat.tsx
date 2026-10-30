import { AudioLines, Mic, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, type ChatEvent } from "./api";
import type { ChatRequest, ChatRequestOwner } from "./chatRequest";
import { LiveVoice, type LiveVoiceError, MAX_SECONDS, type VoiceMode, VoiceRecorder } from "./voice";

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
  "Which clashes share a cause? Fix the root cause.",
];

export function ChatPanel({ context, onEvent, owner, ready, ask, voiceModel = "voice transcription" }: {
  context: () => { scene_id: string | null; report_id: string | null; clash_id: string | null; fixed: string[] };
  onEvent: (e: ChatEvent) => void;
  owner: ChatRequestOwner;
  ready: boolean;
  voiceModel?: string;   // the model that hears speech (server: /api/models labels.voice)
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

  // Voice. Live (the default): the words show in the box as they are said (Muse Voice Transcribe, realtime) and go as
  // a spoken message on release. Hold the mic to talk; a quick tap keeps it open until the next tap. Hands-free keeps
  // the mic open and sends each sentence when the speaker pauses. If the live socket can't open, the mic records a
  // clip for the upload path instead (tap to stop).
  type VoiceState = "idle" | "connecting" | "listening" | "finishing" | "transcribing";
  const [voice, setVoice] = useState<{ state: VoiceState; since: number; level: number; latched?: boolean; note?: string }>(
    { state: "idle", since: 0, level: 0 });
  const [caption, setCaption] = useState("");
  const [speaking, setSpeaking] = useState(false);
  const [handsFree, setHandsFree] = useState(() => { try { return localStorage.getItem("sightline.voice.handsfree") === "1"; } catch { return false; } });
  const [queue, setQueue] = useState<string[]>([]);  // hands-free sentences said while ORCA was still answering
  const live = useRef<LiveVoice | null>(null);
  const recorder = useRef<VoiceRecorder | null>(null);
  const press = useRef<{ at: number; release: "none" | "send" | "latch" }>({ at: 0, release: "none" });
  const heard = useRef(0);  // when hands-free last heard speech
  const [, setTick] = useState(0);
  const voiceOn = voice.state !== "idle";
  const idle = (note?: string) => { setVoice({ state: "idle", since: 0, level: 0, note }); setCaption(""); setSpeaking(false); };
  useEffect(() => () => { live.current?.cancel(); recorder.current?.cancel(); }, []);
  useEffect(() => {
    if (voice.state !== "listening") return;
    const t = setInterval(() => {
      setTick((n) => n + 1);
      if (recorder.current && Date.now() - voice.since > MAX_SECONDS * 1000) void stopRecording();  // a minute at most
      if (handsFree && live.current && Date.now() - heard.current > 30_000) live.current.finish();  // 30 s of quiet
    }, 250);
    return () => { clearInterval(t); };
  }, [voice.state, voice.since, handsFree]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!handsFree || !voiceOn) return;
    // Hands-free stops when the tab is put away: the tab the chat is in, which is a window of its own when popped out.
    const doc = end.current?.ownerDocument ?? document;
    const away = () => { if (doc.hidden) live.current?.finish(); };
    doc.addEventListener("visibilitychange", away);
    return () => { doc.removeEventListener("visibilitychange", away); };
  }, [handsFree, voiceOn]);
  useEffect(() => {
    if (!queue.length || busy || !ready) return;
    const [next, ...rest] = queue;
    setQueue(rest);
    void send(next, true);
  }, [queue, busy, ready]);  // eslint-disable-line react-hooks/exhaustive-deps

  function toggleHandsFree() {
    const on = !handsFree;
    setHandsFree(on);
    try { localStorage.setItem("sightline.voice.handsfree", on ? "1" : "0"); } catch { /* private window */ }
  }

  async function startVoice(mode: VoiceMode) {
    const session = new LiveVoice(), current = owner.capture(), reportId = context().report_id;
    live.current = session;
    let said = "";
    const mine = () => mounted.current && live.current === session;
    setVoice({ state: "connecting", since: Date.now(), level: 0 });
    setCaption("");
    heard.current = Date.now();
    try {
      await session.start(mode, reportId, {
        onLevel: (level) => { if (mine()) setVoice((v) => (v.state === "listening" ? { ...v, level } : v)); },
        onPartial: (text) => { if (mine()) setCaption(text); },
        onSpeech: (on) => { if (mine()) { setSpeaking(on); heard.current = Date.now(); } },
        onFinal: (text) => {
          if (!mine()) return;
          if (mode === "hold") { said = text; return; }
          setCaption("");
          // Each sentence is its own message (send takes its own lease); a word alone is more likely a cough.
          if (text.split(/\s+/).filter(Boolean).length >= 2) setQueue((q) => [...q, text]);
        },
        onLimit: () => { if (mine()) setVoice((v) => ({ ...v, note: mode === "hold" ? "That's the longest a voice message can be." : "Hands-free stopped after its time limit. Tap the mic to go on." })); },
        onError: (detail) => { if (mine()) setVoice((v) => ({ ...v, note: detail })); },
        onEnd: () => {
          if (!mine()) return;
          live.current = null;
          setVoice((v) => ({ state: "idle", since: 0, level: 0, note: v.note }));
          setCaption("");
          setSpeaking(false);
          if (mode !== "hold" || !current()) return;
          if (said) void send(said, true);
          else setVoice((v) => ({ ...v, note: v.note ?? "Didn't catch that. Try again, a little closer to the mic." }));
        },
      }, context().scene_id);
    } catch (e) {
      if (!mine()) return;
      live.current = null;
      const err = e as LiveVoiceError;
      if (err.kind === "fallback" && mode === "hold" && VoiceRecorder.supported()) { await startRecording(); return; }
      idle(err.kind === "fallback" ? "Live voice is unavailable right now." : err.message);
      return;
    }
    if (!mine()) { session.cancel(); return; }
    setVoice({ state: "listening", since: Date.now(), level: 0, latched: press.current.release === "latch" });
    if (press.current.release === "send") finishVoice();  // let go while it was connecting
  }

  function finishVoice() {
    if (live.current) {
      live.current.finish();
      setVoice((v) => ({ ...v, state: "finishing", level: 0 }));
    } else if (recorder.current) {
      void stopRecording();
    }
  }

  // The mic button: hold to talk, a quick tap to keep it open, the next press to send. Hands-free: a press opens or
  // closes the mic.
  function micDown() {
    if (voice.state === "connecting") {  // a second press while it connects: send as soon as it is ready
      press.current = { at: 0, release: "send" };
      return;
    }
    if (voice.state === "listening") {  // latched or hands-free: this press ends it
      press.current = { at: 0, release: "none" };
      finishVoice();
      return;
    }
    if (voice.state !== "idle" || !ready || (busy && !handsFree)) return;
    press.current = { at: Date.now(), release: "none" };
    if (handsFree) { press.current.release = "latch"; void startVoice("hands_free"); return; }
    void startVoice("hold");
  }

  function micUp() {
    if (!press.current.at || handsFree) return;
    const quick = Date.now() - press.current.at < 300;
    press.current = { at: 0, release: quick ? "latch" : "send" };
    if (quick) setVoice((v) => ({ ...v, latched: true }));
    else if (voice.state === "listening") finishVoice();
  }

  // The upload path, when the live socket can't open.
  async function startRecording() {
    const r = new VoiceRecorder();
    const current = owner.capture();
    try {
      await r.start((level) => setVoice((v) => (v.state === "listening" ? { ...v, level } : v)));
    } catch (e) {
      if (!mounted.current || !current()) return;
      idle((e as LiveVoiceError).message);
      return;
    }
    if (!mounted.current || !current()) { r.cancel(); return; }
    recorder.current = r;
    setVoice({ state: "listening", since: Date.now(), level: 0, latched: true });
  }

  async function stopRecording() {
    const r = recorder.current;
    if (!r) return;
    recorder.current = null;
    const current = owner.capture(), reportId = context().report_id;
    setVoice({ state: "transcribing", since: 0, level: 0 });
    try {
      const { transcript } = await api.transcribe(await r.stop(), reportId, context().scene_id);
      if (!mounted.current) return;
      if (!current()) { idle(); return; }
      idle(transcript ? undefined : "Didn't catch that. Try again, a little closer to the mic.");
      if (transcript) await send(transcript, true);
    } catch (e) {
      if (!mounted.current) return;
      idle(current() ? (e as Error).message : undefined);
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
            <p className="hint">Ask ORCA about the models and their clashes. It can read clashes, look at their
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
      {/* The voice status sits above the input so the mic stays where the finger is. */}
      {voice.state === "connecting" && <p className="voice-note live"><i className="rec" aria-hidden /> Connecting to {voiceModel}… start talking.</p>}
      {voice.state === "listening" && <p className="voice-note live"><i className="rec" aria-hidden /> {
        recorder.current ? "Recording… press the mic again to send."
          : handsFree ? "Hands-free: talk, and each sentence goes when you pause. Press the mic to stop."
            : voice.latched ? "Listening… press the mic again to send." : "Listening… let go to send."}</p>}
      {voice.state === "finishing" && <p className="voice-note"><i className="spinner" aria-hidden /> Getting your last words…</p>}
      {voice.state === "transcribing" && <p className="voice-note">Turning your words into text…</p>}
      {queue.length > 0 && <p className="voice-note">Next: “{queue[0]}”{queue.length > 1 ? ` and ${queue.length - 1} more` : ""}</p>}
      {voice.note && <p className={`voice-note${voice.state === "idle" ? " bad" : ""}`}>{voice.note}</p>}
      <form className="chat-input" onSubmit={(e) => { e.preventDefault(); send(draft); }}>
        <textarea value={voiceOn && voice.state !== "transcribing" ? caption : draft} rows={2}
          className={voiceOn && voice.state !== "transcribing" ? "live" : undefined} readOnly={voiceOn}
          placeholder={!ready ? "Open the models first" : voice.state === "connecting" ? "Connecting… start talking"
            : voiceOn ? "Listening…" : "Ask about the clashes…"}
          disabled={!ready} onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (!voiceOn) send(draft); } }} aria-label="Message" />
        <button className="btn primary" data-tour="chat-send" disabled={!ready || busy || voiceOn || !draft.trim()}>{busy ? "…" : "Send"}</button>
        {(LiveVoice.supported() || VoiceRecorder.supported()) && <>
          <button type="button" className={`btn mic${voice.state === "listening" ? " on" : ""}${speaking ? " speaking" : ""}`}
            disabled={voice.state === "finishing" || voice.state === "transcribing" || (!voiceOn && (!ready || (busy && !handsFree)))}
            onPointerDown={(e) => { if (e.button !== 0) return; e.preventDefault(); e.currentTarget.setPointerCapture?.(e.pointerId); micDown(); }}
            onPointerUp={() => micUp()} onPointerCancel={() => micUp()} onContextMenu={(e) => e.preventDefault()}
            onKeyDown={(e) => { if ((e.key === " " || e.key === "Enter") && !e.repeat) { e.preventDefault(); micDown(); } }}
            onKeyUp={(e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); micUp(); } }}
            aria-pressed={voiceOn} data-tip-side="top" style={{ "--level": voice.level } as React.CSSProperties}
            aria-label={voiceOn ? (handsFree ? "Stop listening" : "Stop and send") : handsFree ? "Start hands-free" : "Hold to talk to ORCA"}
            data-tip={voiceOn ? (handsFree ? "Stop listening" : "Release, or press again, to send")
              : handsFree ? `Press once, then just talk: each sentence goes when you pause (${voiceModel}, live)`
                : `Hold to talk, release to send (${voiceModel}, live). A quick tap keeps the mic open.`}>
            {voice.state === "listening" ? <><Square size={13} aria-hidden /> {Math.floor((Date.now() - voice.since) / 1000)} s</>
              : voiceOn ? <i className="spinner" aria-hidden /> : <Mic size={15} aria-hidden />}</button>
          {LiveVoice.supported() && (
            <button type="button" className={`btn mic-mode${handsFree ? " on" : ""}`} aria-pressed={handsFree} disabled={voiceOn}
              onClick={toggleHandsFree} aria-label="Hands-free" data-tip-side="top"
              data-tip={handsFree ? "Hands-free is on: press the mic once, then just talk. Press here to go back to hold to talk."
                : "Hands-free: keep the mic open and send each sentence when you pause"}>
              <AudioLines size={15} aria-hidden /></button>)}
        </>}
      </form>
    </div>
  );
}
