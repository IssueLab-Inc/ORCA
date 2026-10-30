/** Workings (docs/workings.md): a run's events as a graph to draw. Lanes are who does the work (you, Muse, ORCA);
 * steps sit in columns in the order they happened, so nothing jumps as events land; edges join a step to the steps it
 * led to. Everything shown comes from the run's own events: times are when each arrived, numbers are the server's,
 * Muse's words are its own. Pure, so each builder is tested against the tour's recorded runs. */
import type { Run, RunEvent } from "./runlog";

export type Actor = "you" | "orca" | "spark" | "wonder" | "image";
export type Status = "run" | "ok" | "fail" | "done" | "ghost";
export type Tone = "ok" | "bad" | "muted" | "spark" | "warn" | "accent";
/** What a step says, in parts the panel knows how to draw. */
export type Part =
  | { kind: "text"; text: string; tone?: Tone; strong?: boolean; mono?: boolean; live?: boolean }
  | { kind: "fix"; fix: string; text: string }
  | { kind: "thoughts"; items: string[] }
  | { kind: "quote"; text: string }
  | { kind: "chips"; items: { text: string; tone?: Tone }[] }
  | { kind: "list"; items: { mark?: string; text: string; tone?: Tone; note?: string }[] }
  | { kind: "progress"; done: number; total: number; text: string }
  | { kind: "bars"; rows: { label: string; n: number; tone: Tone }[]; max: number }
  | { kind: "slots"; rows: { n: number; title: string; note: string }[] }
  | { kind: "image"; src: string; alt: string };

export type Side = "l" | "r" | "t" | "b" | "tr";
export interface Step {
  id: string; lane: string; col: number;
  /** Down from the lane's top, in pixels (default 14). */
  dy?: number;
  actor: Actor;
  /** The model's name, when the actor is a Muse model. */
  model?: string;
  title: string;
  /** A fix kind's badge before the title. */
  fix?: string;
  status: Status;
  /** Seconds after the run started: when the step began and, once it has, when it ended. */
  t0: number; t1?: number;
  /** The corner: a time, or the idea's number. */
  time?: string;
  body: Part[];
  /** Shown when zoomed in, or pinned. */
  detail: Part[];
  /** The stream events behind the step (Events), and what it would need from the server, if anything. */
  ev: string; newEv?: string;
  /** A check's number in the run (the pilot's step), for "in view". */
  seq?: number;
}
export interface Edge { from: string; to: string; kind?: "seq" | "ghost" | "feedback"; label?: string; fa?: Side; ta?: Side; win?: boolean }
export interface Lane { id: string; label: string; sub: string; actor: Actor; h: number }
export type BarTone = "you" | "orca" | "spark" | "wonder" | "image" | "ok" | "fail";
export interface Bar { lane: string; a: number; b: number; tone: BarTone; sub?: number }
export interface Tick { lane: string; at: number; tone: BarTone }
/** Dots carried along an edge while it is busy (triage's clashes on their way to a verdict). */
export interface Flow { from: string; to: string; a: number; b: number; n: number; tone?: "orca" | "spark" }
export interface Graph {
  lanes: Lane[];
  /** Each column's width, in pixels. */
  cols: number[];
  steps: Step[]; edges: Edge[];
  /** The timeline under the canvas: its rows (a lane, or a lane split into sub-rows), bars and ticks. */
  rows: { id: string; label: string; subs?: number }[];
  bars: Bar[]; ticks: Tick[]; flows: Flow[];
  /** Seconds the run has taken so far (or took). */
  duration: number;
  done: boolean;
}

export const sec = (s: number) => `${Math.max(0, s).toFixed(1)} s`;
const mm = (m: number) => `${Math.round(m * 1000)} mm`;
const signedMm = (m: number) => { const v = Math.round(m * 1000) || 0; return `${v > 0 ? "+" : ""}${v} mm`; };
const text = (t: string, extra: Omit<Extract<Part, { kind: "text" }>, "kind" | "text"> = {}): Part => ({ kind: "text", text: t, ...extra });
const actorOf = (model?: string): Actor => /wonder/i.test(model ?? "") ? "wonder" : /image/i.test(model ?? "") ? "image" : "spark";

/** Who started the run, as its first lane and first step name it. */
const ORIGIN: Record<Run["origin"], { label: string; sub: string; verb: string }> = {
  you: { label: "You", sub: "on this page", verb: "" },
  chat: { label: "Chat", sub: "a tool call", verb: "The chat asked: " },
  agent: { label: "Agent", sub: "linked over MCP", verb: "An agent asked: " },
  replay: { label: "Recorded", sub: "the tour replays it", verb: "Recorded run: " },
};

/** Columns handed out left to right; each step in a new column, or beside another in the same one. */
class Columns {
  widths: number[] = [];
  next(width = 236) { this.widths.push(width); return this.widths.length - 1; }
}

const upTo = (run: Run, at: number): RunEvent[] => run.events.filter((x) => x.t <= at + 1e-9);
const finished = (run: Run, at: number) => run.ended !== null && at >= run.ended - 1e-9;

/** The graph of a run as it stood `at` seconds after it started (its whole length for a finished run). */
export function graphOf(run: Run, at = run.ended ?? Infinity): Graph {
  return run.kind === "propose" ? proposal(run, at) : empty(run, at);
}

function empty(run: Run, at: number): Graph {
  const start = startStep(run, `${run.kind} run`, "", 0);
  return { lanes: [youLane(run)], cols: [236], steps: [start], edges: [], rows: [{ id: "you", label: ORIGIN[run.origin].label }],
    bars: [], ticks: [], flows: [], duration: Math.min(at, run.ended ?? at), done: finished(run, at) };
}

const youLane = (run: Run, h = 118): Lane => ({ id: "you", label: ORIGIN[run.origin].label, sub: ORIGIN[run.origin].sub, actor: "you", h });

function startStep(run: Run, title: string, ev: string, col: number): Step {
  return { id: "start", lane: "you", col, actor: "you", status: "done", t0: 0, time: "0 s", ev,
    title: `${ORIGIN[run.origin].verb}${title}`, body: run.title ? [text(run.title)] : [], detail: [] };
}

/* ---------- a proposal: rounds of ideas from Muse, each checked by ORCA ---------- */

interface Attempt { title: string; passed: boolean; reason: string; kind: string; delta_m?: number[]; split_m?: number[] | null; hit_ids?: string[]; trim?: { by_m: number } | null; edit?: { summary?: string } | null; model?: string }
interface Option { title: string; kind: string; min_clearance_m?: number | null; delta_m?: number[]; split_m?: number[] | null }
interface Round { step: Step; thoughts: string[]; notes: string[]; ideas?: { t: number; seconds: number; understanding: string; count: number } }
interface Result { options?: Option[]; escalated?: boolean; recommendation?: { title: string; rationale?: string } | null; usage?: { usd?: number } | null }
interface Check { idea: Step; check: Step; checking: number; trial?: number; attempt?: Attempt; at?: number }

/** The edit an idea makes, in a few words, as the activity table words it (fixKinds.editText). */
function editWords(a: Attempt): string {
  if (a.edit?.summary) return a.edit.summary;
  const d = a.delta_m ?? [0, 0, 0];
  if (a.kind === "offset" && a.split_m) return `offset ${a.split_m.map((v) => v.toFixed(2)).join("–")} m by ${signedMm(d[2] ?? 0)}`;
  if (a.kind === "trim") return a.trim ? `trim one end ${Math.round(a.trim.by_m * 1000)} mm` : "trim at the joint";
  const names = [["east", "west"], ["north", "south"], ["up", "down"]];
  return `move ${d.map((v, k) => Math.abs(v) >= 0.0005 ? `${names[k][v > 0 ? 0 : 1]} ${Math.abs(Math.round(v * 1000))} mm` : "").filter(Boolean).join(", ") || "0 mm"}`;
}

function proposal(run: Run, at: number): Graph {
  const events = upTo(run, at), done = finished(run, at), cols = new Columns();
  const lanes: Lane[] = [youLane(run, 104), { id: "muse", label: "Muse", sub: "proposes", actor: "spark", h: 200 },
    { id: "orca", label: "ORCA", sub: "checks the geometry", actor: "orca", h: 146 }];
  const steps: Step[] = [], edges: Edge[] = [], bars: Bar[] = [], ticks: Tick[] = [{ lane: "you", at: 0, tone: "you" }];
  const add = (s: Step) => { steps.push(s); return s; };
  add(startStep(run, "propose fixes", run.origin === "replay" ? "the tour's recording" : "POST /propose/stream", cols.next()));
  let prev = "start", tryNo = 0, model = "Muse Spark", offset = 0, seen = 0, firstIdea = true;
  let round = null as Round | null;
  const rounds: Round[] = [];
  const checks = new Map<string, Check>();
  let ofRound: string[] = [];
  let result = null as Result | null;
  let resultAt = 0, failure = null as string | null;

  for (const { t, e } of events) {
    if (e.model && typeof e.model === "string" && e.type !== "escalating") model = e.model;
    if (e.type === "escalating") {
      tryNo += 1;
      const first = e.first_try as { attempts?: Attempt[]; advice?: string; options?: Option[] } | null | undefined;
      offset = first?.attempts?.length ?? seen;
      model = String(e.model ?? "Muse Wonder");
      const passed = (first?.attempts ?? []).filter((a) => a.passed).length;
      const id = `try${tryNo}`;
      add({ id, lane: "muse", col: cols.next(), dy: 10, actor: actorOf(model), model, status: "done", t0: t, ev: "escalating",
        title: "A second, longer try",
        body: [text(first?.attempts?.length ? `Starts from the first try: ${first.attempts.length} ideas, ${passed} passed` : "Starts with nothing to read")],
        detail: first?.advice ? [{ kind: "quote", text: first.advice }] : [] });
      edges.push({ from: prev, to: id, kind: seen ? "feedback" : undefined, label: seen ? "what the first try learned" : undefined });
      prev = id; round = null;
    } else if (e.type === "thinking") {
      const r = Number(e.round ?? 1), key = `${tryNo}-${r}`;
      const brief = add({ id: `b${key}`, lane: "orca", col: cols.next(), actor: "orca", status: "done", t0: t, newEv: "new event: brief", ev: "",
        title: r === 1 ? "Brief for Muse" : `Brief for round ${r}`,
        body: [text(r === 1 ? "The pair in words and numbers: classes, levels, how far they overlap, openings it could use, and pictures A, B and C"
          : "The same brief, with every idea tried so far and why each failed")], detail: [] });
      edges.push(r > 1 ? { from: prev, to: brief.id, kind: "feedback", label: "what failed, and why" } : { from: prev, to: brief.id });
      const step = add({ id: `r${key}`, lane: "muse", col: cols.next(300), dy: 10, actor: actorOf(model), model, status: "run", t0: t,
        title: tryNo ? `${model}, round ${r}` : `Round ${r}`, body: [], detail: [], ev: "thinking · reasoning · ideas" });
      edges.push({ from: brief.id, to: step.id });
      round = { step, thoughts: [], notes: [] }; rounds.push(round);
      prev = step.id; ofRound = []; firstIdea = true;
    } else if (e.type === "reasoning" && round) {
      round.thoughts.push(String(e.text ?? ""));
    } else if (e.type === "note") {
      (round ?? rounds[rounds.length - 1])?.notes.push(String(e.text ?? ""));
    } else if (e.type === "ideas" && round) {
      round.ideas = { t, seconds: Number(e.seconds ?? t - round.step.t0), understanding: String(e.understanding ?? ""), count: Number(e.count ?? 0) };
      bars.push({ lane: "muse", a: round.step.t0, b: t, tone: actorOf(model) });
    } else if (e.type === "checking") {
      const index = Number(e.index ?? 0), key = `${tryNo}-${index}`, col = cols.next(252), n = offset + index;
      const idea = add({ id: `i${key}`, lane: "muse", col, dy: 62, actor: actorOf(model), model, status: "done", t0: t,
        title: String(e.title ?? ""), fix: String(e.kind ?? ""), time: `idea ${n + 1}`, body: [], detail: [],
        ev: "checking", newEv: firstIdea ? "titles in ideas" : undefined });
      const check = add({ id: `k${key}`, lane: "orca", col, actor: "orca", status: "run", t0: t, title: "Geometry check", seq: n,
        body: [], detail: [], ev: "checking · trial · attempt" });
      const from = round?.step.id ?? prev;
      edges.push(firstIdea ? { from, to: idea.id, win: true } : { from, to: idea.id, fa: "tr", ta: "t" });
      edges.push({ from: idea.id, to: check.id, win: true });
      if (ofRound.length) edges.push({ from: ofRound[ofRound.length - 1], to: check.id, kind: "seq" });
      checks.set(key, { idea, check, checking: t });
      ofRound.push(check.id); prev = check.id; firstIdea = false;
    } else if (e.type === "trial") {
      const c = checks.get(`${tryNo}-${Number(e.index ?? 0)}`);
      if (c) c.trial = t;
    } else if (e.type === "attempt") {
      const c = checks.get(`${tryNo}-${Number(e.index ?? 0)}`);
      if (c) { c.attempt = e as unknown as Attempt; c.at = t; bars.push({ lane: "orca", a: c.checking, b: t, tone: c.attempt.passed ? "ok" : "fail" }); }
      seen += 1;
    } else if (e.type === "result") {
      result = e as unknown as Result; resultAt = t;
    } else if (e.type === "error") {
      failure = String(e.detail ?? "The run failed");
    }
  }

  // Each round as it stands now.
  for (const r of rounds) {
    const s = r.step, thoughts = r.thoughts.length ? [{ kind: "thoughts", items: r.thoughts } as Part] : [];
    const notes: Part[] = r.notes.map((n) => text(n, { tone: "warn" }));
    if (!r.ideas) {
      const live = !done && !failure;
      Object.assign(s, { status: live ? "run" : "done", time: live ? sec(at - s.t0) : "",
        body: [text(live ? "Reading the clash and the model data" : "Stopped before it replied", { live })], detail: [...thoughts, ...notes] });
    } else {
      Object.assign(s, { status: "done", t1: r.ideas.t, time: sec(r.ideas.seconds),
        body: [text(`Replied with ${r.ideas.count} idea${r.ideas.count === 1 ? "" : "s"}`)],
        detail: [...thoughts, ...(r.ideas.understanding ? [{ kind: "quote", text: r.ideas.understanding } as Part] : []), ...notes] });
    }
  }
  // Each idea and its check.
  const options = result?.options ?? [];
  const clearance = (a: Attempt) => options.find((o) => o.title === a.title && o.kind === a.kind)?.min_clearance_m;
  for (const c of checks.values()) {
    const a = c.attempt;
    c.idea.body = a ? [text(editWords(a), { mono: true, tone: "muted" })] : [];
    if (!a) {
      const live = !done && !failure;
      Object.assign(c.check, { status: live ? "run" : "done", time: live ? sec(at - c.checking) : "",
        body: [text(!live ? "Stopped before its verdict" : c.trial != null ? "In place, checking against the model" : "Making the edit in a trial", { live })] });
      continue;
    }
    c.idea.status = a.passed ? "ok" : "fail";
    const took = `${(c.at! - c.checking).toFixed(2)} s`, clear = clearance(a);
    Object.assign(c.check, a.passed
      ? { status: "ok", t1: c.at, time: took, body: [text(`✓ Verified${clear != null ? ` · ${mm(clear)} clear` : ""}`, { tone: "ok", strong: true })],
        detail: [text(a.kind === "offset" || a.kind === "route" || a.kind === "resize" ? "Bends, risers and middle against everything; the shortened ends against the other side. Nothing new hit."
          : a.kind === "trim" ? "Only contacts new or worse than before count. Nothing new hit." : "The whole run against everything near it. Nothing new hit.", { tone: "muted" })] }
      : { status: "fail", t1: c.at, time: took, body: [text(`✗ ${a.reason || "Failed the check"}`, { tone: "bad", strong: true })],
        detail: a.hit_ids?.length ? [text(`${a.hit_ids.length} element${a.hit_ids.length === 1 ? "" : "s"} hit, lit in the viewer`, { tone: "muted" })] : [] });
  }

  // How it ended.
  if (result) {
    const tried = [...checks.values()].filter((c) => c.attempt);
    const lastRound = rounds[rounds.length - 1];
    const roundNo = lastRound ? Number(lastRound.step.id.split("-")[1]) : 1;
    if (tried.length) {
      const stop = add({ id: "stop", lane: "orca", col: cols.next(), actor: "orca", status: "done", t0: resultAt, title: "Stop or go round?",
        ev: "the attempts", body: [text(options.length ? `A fix passed by round ${roundNo}, so ORCA stops here` : `Nothing passed in ${roundNo} round${roundNo === 1 ? "" : "s"}`)],
        detail: [text("The ideas and why each failed stay on record for a second try.", { tone: "muted" })] });
      edges.push({ from: prev, to: stop.id, win: true }); prev = stop.id;
    }
    if (options.length) {
      const rank = add({ id: "rank", lane: "orca", col: cols.next(), actor: "orca", status: "done", t0: resultAt, title: "Rank", ev: "result",
        body: [{ kind: "list", items: options.map((o, i) => ({ mark: `${i + 1}`, text: `${o.kind}${o.min_clearance_m != null ? ` · ${mm(o.min_clearance_m)} clear` : ""}` })) }],
        detail: [text("Simplest kind first, then comfortable clearance, the smallest change, the most clearance.", { tone: "muted" })] });
      edges.push({ from: prev, to: rank.id, win: true }); prev = rank.id;
    }
    const col = cols.next(262);
    const usd = result.usage?.usd;
    const end = add(result.recommendation
      ? { id: "options", lane: "you", col, actor: "you", status: "done", t0: resultAt, time: sec(resultAt), title: "A recommendation", ev: "result",
        body: [text(result.recommendation.title, { strong: true })], detail: result.recommendation.rationale ? [text(result.recommendation.rationale, { tone: "muted" })] : [] }
      : { id: "options", lane: "you", col, actor: "you", status: options.length ? "ok" : "fail", t0: resultAt, time: sec(resultAt), ev: "result",
        title: options.length ? `${options.length} verified option${options.length === 1 ? "" : "s"}` : "No verified fix",
        body: options.length ? [{ kind: "list", items: options.map((o, i) => ({ mark: `${i + 1}`, text: o.title, tone: "ok" })) }]
          : [text("Every idea failed the geometry check.")],
        detail: usd ? [text(`${model}: $${usd.toFixed(2)}`, { tone: "muted", mono: true })] : [] });
    edges.push({ from: prev, to: end.id, win: true });
    ticks.push({ lane: "you", at: resultAt, tone: options.length ? "ok" : "fail" });
    if (options.length) {
      add({ id: "accept", lane: "you", col: cols.next(), actor: "you", status: "ghost", t0: resultAt, title: "Accept", ev: "POST /fix/apply",
        body: [text("Tried again on the server, then kept. It is kept only if it passes again.")], detail: [] });
      edges.push({ from: end.id, to: "accept", kind: "ghost" });
    }
    if (!result.escalated && !result.recommendation) {
      add({ id: "better", lane: "muse", col, dy: 62, actor: "wonder", model: "Muse Wonder", status: "ghost", t0: resultAt, title: "Look for a better fix",
        ev: "escalating", body: [text("A second, longer try that starts from this one: each idea, why it failed and what it hit.")], detail: [] });
      const from = steps.find((s) => s.id === "stop") ? "stop" : end.id;
      edges.push({ from, to: "better", kind: "feedback", label: "what failed, and why", fa: from === "stop" ? "t" : undefined, ta: from === "stop" ? "l" : undefined });
    }
  } else if (failure || (done && run.error)) {
    const why = failure ?? run.error ?? "Stopped";
    add({ id: "stopped", lane: "you", col: cols.next(), actor: "you", status: "fail", t0: Math.min(at, run.ended ?? at), title: "Stopped",
      ev: failure ? "error" : "", body: [text(why, { tone: "bad" })], detail: [] });
    edges.push({ from: prev, to: "stopped" });
  }
  const duration = Math.min(at, run.ended ?? at);
  return { lanes, cols: cols.widths, steps, edges, bars, ticks, flows: [], duration, done,
    rows: [{ id: "you", label: lanes[0].label }, { id: "muse", label: "Muse" }, { id: "orca", label: "ORCA" }] };
}
