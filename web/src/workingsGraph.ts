/** Workings (docs/workings.md): a run's events as a graph to draw. Lanes are who does the work (you, Muse, ORCA);
 * steps sit in columns in the order they happened, so nothing jumps as events land; edges join a step to the steps it
 * led to. Everything shown comes from the run's own events: times are when each arrived, numbers are the server's,
 * Muse's words are its own. Pure, so each builder is tested against the tour's recorded runs. */
import type { Option as FixOption } from "./api";
import { clearanceText, editText, kindLabel } from "./fixKinds";
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
/** What a fix leaves between the elements, as the option cards say it (fixKinds.clearanceText). */
const clear = (kind: string, m: number) => kind === "trim" ? "butt joint"
  : `${clearanceText({ kind, min_clearance_m: m } as Pick<FixOption, "kind" | "min_clearance_m">)} clear`;
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
  switch (run.kind) {
    case "propose": return proposal(run, at);
    case "plan": return plan(run, at);
    case "triage": return triage(run, at);
    case "built": return built(run, at);
    case "detect": return detect(run, at);
    default: return empty(run, at);
  }
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

interface Attempt { title: string; passed: boolean; reason: string; kind: string; delta_m: number[]; split_m: number[] | null; hit_ids?: string[]; trim?: { by_m: number } | null; edit?: { summary?: string } | null; model?: string;
  /** The geometry check's seconds and how many elements it tested a passing fix against (server: agent.on_step). */
  seconds?: number; checked?: number }
interface Option { title: string; kind: string; min_clearance_m?: number | null; delta_m?: number[]; split_m?: number[] | null }
interface Round { step: Step; thoughts: string[]; notes: string[]; ideas?: { t: number; seconds: number; understanding: string; count: number } }
interface Result { options?: Option[]; escalated?: boolean; recommendation?: { title: string; rationale?: string } | null; usage?: { usd?: number } | null }
interface Check { idea: Step; check: Step; checking: number; trial?: number; attempt?: Attempt; at?: number }

function proposal(run: Run, at: number): Graph {
  const events = upTo(run, at), done = finished(run, at), cols = new Columns();
  const lanes: Lane[] = [youLane(run, 104), { id: "muse", label: "Muse", sub: "proposes", actor: "spark", h: 200 },
    { id: "orca", label: "ORCA", sub: "checks the geometry", actor: "orca", h: 146 }];
  const steps: Step[] = [], edges: Edge[] = [], bars: Bar[] = [], ticks: Tick[] = [{ lane: "you", at: 0, tone: "you" }];
  const add = (s: Step) => { steps.push(s); return s; };
  add(startStep(run, "propose fixes", run.origin === "replay" ? "the tour's recording" : "POST /propose/stream", cols.next()));
  let prev = "start", tryNo = 0, model = "Muse Spark", offset = 0, seen = 0, inTry = 0, firstIdea = true;
  // Ideas named before they are checked (the server sends their titles with `ideas`), by their index in the try.
  const named = new Map<string, Step>();
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
      prev = id; round = null; inTry = 0;
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
      const from = round.step.id;
      (e.candidates as { title: string; kind: string }[] | undefined)?.forEach((c, k) => {
        const index = inTry + k, key = `${tryNo}-${index}`;
        const idea = add({ id: `i${key}`, lane: "muse", col: cols.next(252), dy: 62, actor: actorOf(model), model, status: "done", t0: t,
          title: c.title, fix: c.kind, time: `idea ${offset + index + 1}`, body: [text("waiting its turn", { tone: "muted" })], detail: [], ev: "ideas" });
        edges.push(k === 0 ? { from, to: idea.id, win: true } : { from, to: idea.id, fa: "tr", ta: "t" });
        named.set(key, idea);
      });
    } else if (e.type === "checking") {
      const index = Number(e.index ?? 0), key = `${tryNo}-${index}`, n = offset + index, early = named.get(key);
      const col = early ? early.col : cols.next(252);
      const idea = early ?? add({ id: `i${key}`, lane: "muse", col, dy: 62, actor: actorOf(model), model, status: "done", t0: t,
        title: String(e.title ?? ""), fix: String(e.kind ?? ""), time: `idea ${n + 1}`, body: [], detail: [], ev: "checking" });
      inTry = Math.max(inTry, index + 1);
      const check = add({ id: `k${key}`, lane: "orca", col, actor: "orca", status: "run", t0: t, title: "Geometry check", seq: n,
        body: [], detail: [], ev: "checking · trial · attempt" });
      const from = round?.step.id ?? prev;
      if (!early) edges.push(firstIdea ? { from, to: idea.id, win: true } : { from, to: idea.id, fa: "tr", ta: "t" });
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
    c.idea.body = a ? [text(editText(a as unknown as Parameters<typeof editText>[0]), { mono: true, tone: "muted" })] : [];
    if (!a) {
      const live = !done && !failure;
      Object.assign(c.check, { status: live ? "run" : "done", time: live ? sec(at - c.checking) : "",
        body: [text(!live ? "Stopped before its verdict" : c.trial != null ? "In place, checking against the model" : "Making the edit in a trial", { live })] });
      continue;
    }
    c.idea.status = a.passed ? "ok" : "fail";
    // The server's own time for the check when it sends one, else from when the events arrived.
    const took = `${(a.seconds ?? c.at! - c.checking).toFixed(2)} s`, gap = clearance(a);
    const against = a.checked ? text(`Checked against ${a.checked} element${a.checked === 1 ? "" : "s"}${a.seconds != null ? ` in ${a.seconds.toFixed(2)} s` : ""}`, { tone: "muted" }) : null;
    Object.assign(c.check, a.passed
      ? { status: "ok", t1: c.at, time: took, body: [text(`✓ Verified${gap != null ? ` · ${clear(a.kind, gap)}` : ""}`, { tone: "ok", strong: true })],
        detail: [...(against ? [against] : []), text(a.kind === "offset" || a.kind === "route" || a.kind === "resize" ? "Bends, risers and middle against everything; the shortened ends against the other side. Nothing new hit."
          : a.kind === "trim" ? "Only contacts new or worse than before count. Nothing new hit." : "The whole run against everything near it. Nothing new hit.", { tone: "muted" })] }
      : { status: "fail", t1: c.at, time: a.seconds != null || a.hit_ids?.length ? took : "", body: [text(`✗ ${a.reason || "Failed the check"}`, { tone: "bad", strong: true })],
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
        body: [{ kind: "list", items: options.map((o, i) => ({ mark: `${i + 1}`, text: `${kindLabel(o.kind)}${o.min_clearance_m != null ? ` · ${clear(o.kind, o.min_clearance_m)}` : ""}` })) }],
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

/** How a run that ended early ends its drawing: a step in your lane saying why. */
function stoppedStep(run: Run, at: number, failure: string | null, col: number): Step | null {
  const why = failure ?? (finished(run, at) ? run.error : null);
  if (!why) return null;
  return { id: "stopped", lane: "you", col, actor: "you", status: "fail", t0: Math.min(at, run.ended ?? at), title: "Stopped",
    ev: failure ? "error" : "", body: [text(why, { tone: "bad" })], detail: [] };
}
/** An element's name out of a plan item's label ("IfcDuctSegment 'Supply air main L02' x IfcBeam '...'"). */
const firstName = (label: string) => (label.match(/'([^']+)'/)?.[1] ?? label).replace(/\s+\d+x\d+$/, "");
const STRATEGY: Record<string, string> = { fix_partners: "fix the partners", move_hub: "move the hub", as_designed: "as designed" };

/* ---------- a plan: Fix together, or the root cause around one element ---------- */

interface PlanItemLite { key: string; label: string; clash_ids?: string[]; in_report?: boolean; option?: { title: string; kind: string } | null }
interface PlanLite { title?: string; items?: PlanItemLite[]; check?: { passed: boolean; items?: Record<string, { passed: boolean; reason?: string; min_clearance_m?: number | null }>; conflicts?: unknown[] }; seconds?: number; strategy?: string }

function plan(run: Run, at: number): Graph {
  const events = upTo(run, at), done = finished(run, at), cols = new Columns();
  const rootCause = run.meta.kind === "root_cause" || events.some((x) => x.e.type === "thinking" || x.e.type === "root_cause");
  let cause: { t: number; text: string; strategy: string; reason: string } | null = null, thinkingAt: number | null = null;
  let items: PlanItemLite[] = [], skipped = 0, itemsAt = 0, checkingAt: number | null = null, retried = 0;
  let result: PlanLite | null = null, resultAt = 0, failure: string | null = null;
  const per = new Map<string, { think?: number; checks: { t: number; attempt: string; passed: boolean; seconds?: number; reason?: string }[]; done?: { t: number; ok: boolean; title: string } }>();
  for (const { t, e } of events) {
    if (e.type === "thinking") thinkingAt = t;
    else if (e.type === "root_cause") cause = { t, text: String(e.root_cause ?? ""), strategy: String(e.strategy ?? ""), reason: String(e.reason ?? "") };
    else if (e.type === "plan_items") { items = (e.items as PlanItemLite[]) ?? []; skipped = (e.skipped as unknown[] | undefined)?.length ?? 0; itemsAt = t; for (const it of items) per.set(it.key, { checks: [] }); }
    else if (e.type === "item") {
      const s = per.get(String(e.key)); if (!s) continue;
      if (e.status === "thinking") s.think ??= t;
      else if (e.status === "checking") s.checks.push({ t, attempt: String(e.attempt ?? ""), passed: !!e.passed,
        seconds: typeof e.seconds === "number" ? e.seconds : undefined, reason: e.reason ? String(e.reason) : undefined });
      else if (e.status === "done") s.done = { t, ok: !!e.ok, title: String(e.title ?? "") };
    } else if (e.type === "checking_plan") { checkingAt ??= t; if (Array.isArray(e.retry)) retried += e.retry.length; }
    else if (e.type === "plan") { result = e as unknown as PlanLite; resultAt = t; }
    else if (e.type === "error") failure = String(e.detail ?? "The plan failed");
  }
  const lanes: Lane[] = [youLane(run, 100)];
  if (rootCause) lanes.push({ id: "muse", label: "Muse", sub: "finds the cause", actor: "spark", h: 176 });
  lanes.push({ id: "orca", label: "ORCA", sub: "plans and checks", actor: "orca", h: 128 });
  items.forEach((it, k) => lanes.push({ id: `it${k}`, label: firstName(it.label).slice(0, 26), sub: "Muse + ORCA", actor: "spark", h: 108 }));
  const steps: Step[] = [], edges: Edge[] = [], bars: Bar[] = [], ticks: Tick[] = [{ lane: "you", at: 0, tone: "you" }];
  const add = (s: Step) => { steps.push(s); return s; };
  add(startStep(run, rootCause ? "find the root cause" : "fix them together", "POST /plan/stream", cols.next()));
  if (run.origin === "you") steps[0].title = rootCause ? "Find the root cause" : "Fix together";
  let prev = "start";
  if (rootCause) {
    const t0 = thinkingAt ?? 0, live = !cause && !done && !failure;
    add({ id: "cause", lane: "muse", col: cols.next(300), dy: 10, actor: "spark", model: "Muse Spark", t0, t1: cause?.t, title: "Root cause",
      status: cause ? "done" : live ? "run" : "done", time: cause ? sec(cause.t - t0) : live ? sec(at - t0) : "",
      ev: "thinking · root_cause",
      body: cause ? [{ kind: "quote", text: cause.text }] : [text(live ? "Reading the element and every clash on it" : "Stopped before it answered", { live })],
      detail: cause ? [{ kind: "chips", items: [{ text: `Strategy: ${STRATEGY[cause.strategy] ?? cause.strategy}`, tone: "accent" }] }, ...(cause.reason ? [{ kind: "quote", text: cause.reason } as Part] : [])] : [] });
    edges.push({ from: prev, to: "cause" }); prev = "cause";
    if (cause) bars.push({ lane: "muse", a: t0, b: cause.t, tone: "spark" });
  }
  if (items.length) {
    add({ id: "jobs", lane: "orca", col: cols.next(252), actor: "orca", status: "done", t0: itemsAt, ev: "plan_items",
      title: `${items.length} job${items.length === 1 ? "" : "s"}, run at once`,
      body: [{ kind: "list", items: items.map((it) => ({ text: firstName(it.label), note: it.in_report === false ? "not in the report" : it.clash_ids?.length ? `${it.clash_ids.length} in the report` : "" })) }],
      detail: [text(`Muse thinks for all of them at once; their geometry checks take turns.${skipped ? ` ${skipped} skipped.` : ""}`, { tone: "muted" })] });
    edges.push({ from: prev, to: "jobs" }); prev = "jobs";
    const most = Math.max(1, ...[...per.values()].map((s) => s.checks.length));
    const c0 = cols.next(), checkCols = Array.from({ length: most }, () => cols.next()), cDone = cols.next();
    items.forEach((it, k) => {
      const s = per.get(it.key)!, lane = `it${k}`, firstAt = s.checks[0]?.t ?? s.done?.t;
      const live = !done && !failure;
      if (s.think != null) {
        add({ id: `${lane}-t`, lane, col: c0, actor: "spark", model: "Muse Spark", t0: s.think, title: "Proposes", ev: "item: thinking",
          status: firstAt != null ? "done" : live ? "run" : "done", time: firstAt != null ? `${sec(s.think)}–${sec(firstAt)}` : live ? sec(at - s.think) : "",
          body: [text(firstAt != null ? "Ideas in, and the first verdict back" : live ? "Working on this pair" : "Stopped before its ideas", { live: firstAt == null && live })], detail: [] });
        edges.push({ from: "jobs", to: `${lane}-t` });
        if (firstAt != null) bars.push({ lane, a: s.think, b: firstAt, tone: "spark" });
      }
      let from = `${lane}-t`;
      s.checks.forEach((c, j) => {
        const id = `${lane}-c${j}`;
        add({ id, lane, col: checkCols[j], actor: "orca", t0: c.t, status: c.passed ? "ok" : "fail", title: c.attempt, ev: "item: checking",
          time: c.seconds != null ? `${c.seconds.toFixed(2)} s` : `at ${sec(c.t)}`,
          body: [text(c.passed ? "✓ Passed the check" : `✗ ${c.reason ?? "Failed the check"}`, { tone: c.passed ? "ok" : "bad", strong: true })], detail: [] });
        edges.push({ from, to: id, kind: j ? "seq" : undefined }); from = id;
        ticks.push({ lane, at: c.t, tone: c.passed ? "ok" : "fail" });
      });
      if (s.done) {
        const kept = result?.check?.items?.[it.key], kind = result?.items?.find((i) => i.key === it.key)?.option?.kind ?? "move";
        add({ id: `${lane}-d`, lane, col: cDone, actor: "orca", t0: s.done.t, status: s.done.ok ? "ok" : "fail", time: `at ${sec(s.done.t)}`,
          title: s.done.ok ? "Kept for the plan" : "No fix for this pair", ev: "item: done",
          body: s.done.title ? [text(s.done.title)] : [],
          detail: kept?.min_clearance_m != null ? [text(`${clear(kind, kept.min_clearance_m)} in the plan`, { tone: "muted" })] : [] });
        edges.push({ from, to: `${lane}-d` });
      }
    });
    if (checkingAt != null) {
      const live = !result && !done && !failure, passed = result?.check?.passed;
      add({ id: "check", lane: "orca", col: cols.next(256), actor: "orca", t0: checkingAt, t1: result ? resultAt : undefined, ev: "checking_plan · plan",
        title: "Check the plan as a whole", status: result ? (passed ? "ok" : "fail") : live ? "run" : "done",
        time: result ? sec(resultAt - checkingAt) : live ? sec(at - checkingAt) : "",
        body: [text(result ? (passed ? "✓ Passes together · no conflicts" : `✗ ${result.check?.conflicts?.length ?? 0} conflicts between the fixes`)
          : live ? "Every fix in place at once, checked against everything and each other" : "Stopped before the check", { tone: result ? (passed ? "ok" : "bad") : undefined, strong: !!result, live })],
        detail: retried ? [text(`${retried} item${retried === 1 ? "" : "s"} tried again with their next-best option`, { tone: "muted" })] : [] });
      for (let k = 0; k < items.length; k++) if (steps.some((s) => s.id === `it${k}-d`)) edges.push({ from: `it${k}-d`, to: "check", win: true });
      if (result) bars.push({ lane: "orca", a: checkingAt, b: resultAt, tone: "orca" });
      prev = "check";
    }
  }
  if (result) {
    const fixed = (result.items ?? []).filter((i) => i.option);
    add({ id: "plan", lane: "you", col: cols.next(262), actor: "you", t0: resultAt, time: sec(resultAt), ev: "plan",
      status: fixed.length && result.check?.passed ? "ok" : "fail",
      title: fixed.length ? `Plan: ${fixed.length} verified fix${fixed.length === 1 ? "" : "es"}` : "No plan",
      body: [{ kind: "list", items: fixed.map((i) => ({ mark: "✓", tone: "ok", text: i.option!.title })) }],
      detail: [text("Accepting keeps all of them or none.", { tone: "muted" })] });
    edges.push({ from: prev, to: "plan", win: true });
    ticks.push({ lane: "you", at: resultAt, tone: fixed.length ? "ok" : "fail" });
  } else {
    const s = stoppedStep(run, at, failure, cols.next());
    if (s) { add(s); edges.push({ from: prev, to: s.id }); } else cols.widths.pop();
  }
  return { lanes, cols: cols.widths, steps, edges, bars, ticks, flows: [], duration: Math.min(at, run.ended ?? at), done,
    rows: lanes.map((l) => ({ id: l.id, label: l.id.startsWith("it") ? l.label.split(" ")[0] : l.label })) };
}

/* ---------- triage: every clash in a report, settled by rule or read by the open model ---------- */

const VERDICT: Record<string, { label: string; tone: Tone }> = {
  real_clash: { label: "Real", tone: "bad" }, by_design: { label: "By design", tone: "ok" },
  non_physical: { label: "Not physical", tone: "muted" }, modelling_error: { label: "Modelling error", tone: "warn" }, unknown: { label: "Unknown", tone: "muted" },
};
const BASIS: Record<string, string> = { touch: "a touch within 1 mm", non_physical: "not physical", same_element: "one element both sides",
  requirement: "a by-design rule", no_overlap: "no overlap", reviewed: "reviewed" };

function triage(run: Run, at: number): Graph {
  const events = upTo(run, at), done = finished(run, at), cols = new Columns();
  const names = (run.meta.names ?? {}) as Record<string, string>;
  let start: { t: number; total: number; model: string; open: boolean } | null = null, end: { t: number; seconds: number; error?: string } | null = null;
  let audit: { t: number; rules: Record<string, { answer: string }> } | null = null, failure: string | null = null;
  const verdict = new Map<string, { t: number; v: Record<string, unknown> }>(), thought = new Map<string, { first: number; last: string }>();
  let ruleFirst: number | null = null, ruleLast = 0, modelFirst: number | null = null;
  for (const { t, e } of events) {
    if (e.type === "start") start = { t, total: Number(e.total ?? 0), model: String(e.model ?? "the triage model"), open: !!e.open_weights };
    else if (e.type === "clash") {
      verdict.set(String(e.id), { t, v: e });
      if (e.source === "rule") { ruleFirst ??= t; ruleLast = t; } else modelFirst ??= t;
    } else if (e.type === "reasoning") {
      const id = String(e.id), was = thought.get(id);
      thought.set(id, { first: was?.first ?? t, last: ((was?.last ?? "") + String(e.text ?? "")).slice(-160) });
    } else if (e.type === "audit") audit = { t, rules: (e.rules ?? {}) as Record<string, { answer: string }> };
    else if (e.type === "done") end = { t, seconds: Number(e.seconds ?? t), error: e.error ? String(e.error) : undefined };
    else if (e.type === "error") failure = String(e.detail ?? "Triage failed");
  }
  const muse = !start || start.open ? "Muse Spark Open" : "Muse Spark";
  const all = [...verdict.values()].map((x) => x.v);
  const byRule = all.filter((v) => v.source === "rule"), byModel = all.filter((v) => v.source !== "rule");
  // A model call is a clash read for itself (not copied from an alike one): it lands with its seconds.
  const calls = [...verdict.entries()].filter(([, x]) => x.v.source !== "rule" && !x.v.alike_of)
    .map(([id, x]) => ({ id, end: x.t, start: thought.get(id)?.first ?? Math.max(0, x.t - Number(x.v.seconds ?? 0)) }));
  const running = [...thought.entries()].filter(([id]) => !verdict.has(id));
  const groups = new Set(all.filter((v) => v.alike_of).map((v) => String(v.alike_of))).size, inGroups = all.filter((v) => v.alike_of || Number(v.alike ?? 0) > 1).length;
  const live = !end && !done && !failure;
  const lanes: Lane[] = [youLane(run, 104), { id: "orca", label: "ORCA", sub: "sorts and settles", actor: "orca", h: 186 },
    { id: "open", label: muse, sub: "reads clashes", actor: "spark", h: 262 }];
  const steps: Step[] = [], edges: Edge[] = [], flows: Flow[] = [];
  const add = (s: Step) => { steps.push(s); return s; };
  add(startStep(run, `triage ${start ? `all ${start.total}` : "the"} clashes`, "POST /triage/stream · start", cols.next()));
  if (run.origin === "you") steps[0].title = `Triage ${start ? `all ${start.total} clashes` : "the clashes"}`;
  steps[0].body = [text(start?.open ? "Muse Spark Open, the open-weights model" : start ? "Muse Spark" : "Waiting for the model")];
  const basis = Object.entries(BASIS).map(([k, label]) => [label, byRule.filter((v) => v.basis === k).length] as const).filter(([, n]) => n);
  add({ id: "rules", lane: "orca", col: cols.next(244), actor: "orca", t0: ruleFirst ?? start?.t ?? 0, title: "Settled without a model", ev: "clash (source: rule, basis)",
    status: live && modelFirst == null && !byRule.length ? "run" : "done", time: byRule.length ? sec(ruleLast) : "",
    body: [text(`${byRule.length} clash${byRule.length === 1 ? "" : "es"}`, { strong: true })],
    detail: basis.length ? [text(basis.map(([l, n]) => `${l} ${n}`).join(" · "), { tone: "muted" })] : [] });
  add({ id: "alike", lane: "orca", col: cols.next(254), actor: "orca", t0: start?.t ?? 0, title: "Alike clashes read once", ev: "clash (alike_of, alike)", newEv: "groups in start",
    status: "done", body: [text(groups ? `${inGroups} clashes in ${groups} group${groups === 1 ? "" : "s"}${live ? " so far" : ""}` : live ? "Grouped as their verdicts land" : "No alike groups")],
    detail: [text("Each group is read through its deepest member; the verdict goes to every one.", { tone: "muted" })] });
  const slots = running.slice(-8).map(([id, x], i) => ({ n: i + 1, title: names[id] ?? id, note: x.last.replace(/\s+/g, " ").trim().slice(-90) }));
  add({ id: "pool", lane: "open", col: cols.next(372), dy: 10, actor: "spark", model: muse, t0: start?.t ?? 0, t1: end?.t,
    // Calls show while running only when the model streams its reasoning (the open-weights host does).
    title: `${calls.length} call${calls.length === 1 ? "" : "s"} read${live && thought.size ? `, ${running.length} running` : ""}`, ev: "reasoning · clash (source: model)", newEv: "call start",
    status: live ? "run" : "done", time: live ? sec(at - (start?.t ?? 0)) : end ? sec(end.seconds) : "",
    body: [{ kind: "progress", done: verdict.size, total: start?.total ?? verdict.size, text: `${verdict.size} of ${start?.total ?? "?"} settled` }],
    detail: live && slots.length ? [{ kind: "slots", rows: slots }] : [] });
  const corrected = byModel.filter((v) => v.model_reading || v.basis === "strictness").length;
  add({ id: "settle", lane: "orca", col: cols.next(244), actor: "orca", t0: modelFirst ?? start?.t ?? 0, title: "Open-model facts win", ev: "clash (basis, model_reading)",
    status: "done", body: [text("A verdict the open model's facts contradict is corrected; the model's reading is kept.")],
    detail: [text(`${corrected} corrected`, { tone: "muted" })] });
  const counts = Object.keys(VERDICT).map((k) => ({ k, n: all.filter((v) => v.verdict === k).length })).filter((x) => x.n || x.k !== "unknown");
  add({ id: "verdicts", lane: "orca", col: cols.next(286), actor: "orca", t0: start?.t ?? 0, title: "Verdicts", ev: "clash",
    status: live ? "run" : end ? "ok" : "done",
    body: [{ kind: "bars", max: Math.max(1, ...counts.map((c) => c.n)), rows: counts.map((c) => ({ label: VERDICT[c.k].label, n: c.n, tone: VERDICT[c.k].tone })) }],
    detail: [text("Alike clashes take their group's verdict.", { tone: "muted" })] });
  edges.push({ from: "start", to: "rules" }, { from: "rules", to: "alike", kind: "seq" }, { from: "alike", to: "pool" }, { from: "pool", to: "settle" },
    { from: "settle", to: "verdicts" }, { from: "rules", to: "verdicts", fa: "t", ta: "t", label: "settled by rule" });
  let last = "verdicts";
  if (audit) {
    const answers = Object.values(audit.rules), disputed = answers.filter((a) => a.answer === "looks_real").length;
    add({ id: "audit", lane: "open", col: cols.next(252), dy: 10, actor: "spark", model: "Muse Spark", t0: audit.t, status: disputed ? "fail" : "done",
      title: "Audit of the by-design rules", ev: "audit", body: [text(`${answers.length} rule${answers.length === 1 ? "" : "s"} read · ${disputed} disputed`)], detail: [] });
    edges.push({ from: last, to: "audit" }); last = "audit";
  }
  if (end) {
    const real = all.filter((v) => v.verdict === "real_clash").length;
    add({ id: "done", lane: "you", col: cols.next(262), actor: "you", t0: end.t, status: end.error ? "fail" : "ok", time: sec(end.seconds), ev: "done",
      title: `Triage done · ${sec(end.seconds)}`, body: [text(`${real} real clash${real === 1 ? "" : "es"} of ${verdict.size}`, { strong: true })],
      detail: end.error ? [text(end.error, { tone: "bad" })] : [text(`${calls.length} model call${calls.length === 1 ? "" : "s"}`, { tone: "muted" })] });
    edges.push({ from: last, to: "done", win: true });
  } else {
    const s = stoppedStep(run, at, failure, cols.next());
    if (s) { add(s); edges.push({ from: last, to: s.id }); } else cols.widths.pop();
  }
  // The open model's calls, laid in rows as they overlapped (at most as many rows as ran at once).
  const rowsEnd: number[] = [], bars: Bar[] = [];
  for (const c of [...calls].sort((x, y) => x.start - y.start)) {
    let r = rowsEnd.findIndex((e) => e <= c.start + 1e-6);
    if (r < 0) { r = rowsEnd.length; rowsEnd.push(0); }
    rowsEnd[r] = c.end; if (r < 8) bars.push({ lane: "open", sub: r, a: c.start, b: c.end, tone: "spark" });
  }
  if (byRule.length && ruleFirst != null) bars.push({ lane: "orca", a: ruleFirst, b: Math.max(ruleLast, ruleFirst + 0.2), tone: "orca" });
  const stillFlowing = live ? at : -1;
  if (ruleFirst != null) flows.push({ from: "rules", to: "verdicts", a: ruleFirst, b: Math.max(ruleLast + 0.6, stillFlowing), n: 6, tone: "orca" });
  if (live && running.length) flows.push({ from: "alike", to: "pool", a: start?.t ?? 0, b: Infinity, n: 3 }, { from: "pool", to: "settle", a: modelFirst ?? at, b: Infinity, n: 3 },
    { from: "settle", to: "verdicts", a: modelFirst ?? at, b: Infinity, n: 3 });
  return { lanes, cols: cols.widths, steps, edges, bars, flows, duration: Math.min(at, run.ended ?? at), done,
    ticks: [{ lane: "you", at: 0, tone: "you" }, ...(end ? [{ lane: "you", at: end.t, tone: "ok" as BarTone }] : [])],
    rows: [{ id: "you", label: lanes[0].label }, { id: "orca", label: "ORCA" }, { id: "open", label: "Muse", subs: Math.max(1, Math.min(8, rowsEnd.length)) }] };
}

/* ---------- Show it built: Muse Image restyles ORCA's view, judged against the model ---------- */

function built(run: Run, at: number): Graph {
  const events = upTo(run, at), done = finished(run, at), cols = new Columns();
  type R = { drawing?: number; pictures: number; shared: boolean; gates: { t: number; picture: number; f?: number; tile?: number; passed: boolean; error?: string }[];
    judging: Map<number, number>; judged: Map<number, { t: number; verdicts: string[] }>; retry?: { t: number; why: string } };
  const rounds = new Map<number, R>();
  const round = (n: number) => { let r = rounds.get(n); if (!r) { r = { pictures: 0, shared: false, gates: [], judging: new Map(), judged: new Map() }; rounds.set(n, r); } return r; };
  let lastRound = 1, result: { t: number; status: string; image_url?: string; why?: string; gate?: { f: number; tile: number }; judge?: string; cached?: boolean; seconds?: number; tried?: number } | null = null;
  let failure: string | null = null;
  for (const { t, e } of events) {
    if (e.type === "drawing") { lastRound = Number(e.round ?? 1); const r = round(lastRound); r.drawing ??= t; r.pictures = Number(e.pictures ?? 2); r.shared = !!e.shared; }
    else if (e.type === "gate") round(Number(e.round ?? lastRound)).gates.push({ t, picture: Number(e.picture ?? 0), f: e.f as number | undefined, tile: e.tile as number | undefined, passed: !!e.passed, error: e.error as string | undefined });
    else if (e.type === "judging") round(Number(e.round ?? lastRound)).judging.set(Number(e.picture ?? 0), t);
    else if (e.type === "judged") round(Number(e.round ?? lastRound)).judged.set(Number(e.picture ?? 0), { t, verdicts: Array.isArray(e.verdicts) ? e.verdicts.map((v) => String(v ?? "no verdict")) : [] });
    else if (e.type === "retry") round(lastRound).retry = { t, why: String(e.why ?? "") };
    else if (e.type === "result") result = { t, ...(e as unknown as { status: string }) };
    else if (e.type === "error") failure = String(e.detail ?? "The picture failed");
  }
  const judge = result?.judge ?? "Muse Wonder", live = !result && !done && !failure;
  const lanes: Lane[] = [youLane(run, 196), { id: "orca", label: "ORCA", sub: "captures and checks", actor: "orca", h: 150 },
    { id: "image", label: "Muse Image", sub: "restyles the view", actor: "image", h: 150 }, { id: "judges", label: "Judges", sub: judge, actor: actorOf(judge), h: 150 }];
  const steps: Step[] = [], edges: Edge[] = [], bars: Bar[] = [], ticks: Tick[] = [{ lane: "you", at: 0, tone: "you" }];
  const add = (s: Step) => { steps.push(s); return s; };
  add(startStep(run, "show it built", "POST /built/stream", cols.next()));
  if (run.origin === "you") steps[0].title = "Show it built";
  add({ id: "capture", lane: "orca", col: cols.next(), actor: "orca", status: "done", t0: 0, title: "One camera, three passes", ev: "the page's own step",
    body: [text("look · ids · normals: the picture to restyle, which element is where, which way each face points", { tone: "muted" })], detail: [] });
  edges.push({ from: "start", to: "capture" });
  let prev = "capture";
  for (const [n, r] of [...rounds.entries()].sort((x, y) => x[0] - y[0])) {
    const gateAt = r.gates[0]?.t, drawId = `draw${n}`;
    if (r.drawing != null) {
      const drawing = gateAt == null && live;
      add({ id: drawId, lane: "image", col: cols.next(), actor: "image", model: "Muse Image", t0: r.drawing, t1: gateAt, ev: "drawing",
        title: `Round ${n} · ${r.pictures} restyle${r.pictures === 1 ? "" : "s"} at once`, status: drawing ? "run" : "done",
        time: gateAt != null ? sec(gateAt - r.drawing) : drawing ? sec(at - r.drawing) : "",
        body: [text(r.shared ? "Waiting for the same picture another request is making" : drawing ? "Drawing ORCA's view as a presentation render" : "Drawn", { live: drawing })], detail: [] });
      edges.push({ from: prev, to: drawId, kind: n > 1 ? "feedback" : undefined, label: n > 1 ? "what the judges found" : undefined }); prev = drawId;
      if (gateAt != null) bars.push({ lane: "image", a: r.drawing, b: gateAt, tone: "image" });
    }
    if (r.gates.length) {
      const id = `gate${n}`;
      add({ id, lane: "orca", col: cols.next(), actor: "orca", t0: gateAt!, status: r.gates.some((g) => g.passed) ? "ok" : "fail", title: "Pixel gate", ev: "gate",
        body: [{ kind: "list", items: r.gates.map((g) => ({ mark: `${g.picture + 1}`, tone: g.passed ? "ok" : "bad",
          text: g.error ? g.error : `${g.passed ? "✓" : "✗"} F ${g.f?.toFixed(2) ?? "?"} · worst tile ${g.tile?.toFixed(2) ?? "?"}` })) }],
        detail: [text("Passes with F at least 0.55 and the worst tile at most 0.45.", { tone: "muted" })] });
      edges.push({ from: prev, to: id }); prev = id;
    }
    if (r.judging.size) {
      const id = `judge${n}`, first = Math.min(...r.judging.values()), judgedAll = [...r.judging.keys()].every((p) => r.judged.has(p));
      const lastJudged = Math.max(first, ...[...r.judged.values()].map((j) => j.t));
      const anyFaithful = [...r.judged.values()].some((j) => j.verdicts.length && j.verdicts.every((v) => v === "faithful" || v === "minor_differences"));
      add({ id, lane: "judges", col: cols.next(256), actor: actorOf(judge), model: judge, t0: first, ev: "judging · judged",
        title: `Judging ${r.judging.size} picture${r.judging.size === 1 ? "" : "s"}`, status: !judgedAll && live ? "run" : anyFaithful ? "ok" : "fail",
        time: judgedAll ? sec(lastJudged - first) : live ? sec(at - first) : "",
        body: [{ kind: "list", items: [...r.judging.keys()].sort().map((p) => { const j = r.judged.get(p);
          return { mark: `${p + 1}`, tone: j ? (j.verdicts.every((v) => v === "faithful" || v === "minor_differences") ? "ok" : "bad") : undefined,
            text: j ? j.verdicts.map((v) => String(v ?? "no verdict").replace(/_/g, " ")).join(", ") || "no verdict" : "comparing with the model…" }; }) }], detail: [] });
      edges.push({ from: prev, to: id }); prev = id;
      if (judgedAll) bars.push({ lane: "judges", a: first, b: lastJudged, tone: actorOf(judge) });
    }
    if (r.retry) {
      const id = `retry${n}`;
      add({ id, lane: "orca", col: cols.next(), actor: "orca", t0: r.retry.t, status: "done", title: "Retry", ev: "retry",
        body: [text(`The next round is told: ${r.retry.why}`)], detail: [] });
      edges.push({ from: prev, to: id }); prev = id;
    }
  }
  if (result) {
    const ok = result.status === "done";
    add({ id: "kept", lane: "orca", col: cols.next(), actor: "orca", t0: result.t, status: ok ? "ok" : "fail", ev: "result",
      title: ok ? (result.cached ? "From the cache" : "Kept the picture") : "No faithful picture",
      body: [text(ok ? (result.gate ? `F ${result.gate.f.toFixed(2)} · worst tile ${result.gate.tile.toFixed(2)}` : "Every judge passed it") : result.why ?? "Muse Image couldn't keep to the model here", { tone: ok ? undefined : "bad" })],
      detail: [text(ok ? "JPEG, outline and verdicts cached for this view" : `${result.tried ?? 0} pictures tried`, { tone: "muted" })] });
    edges.push({ from: prev, to: "kept", win: true });
    add({ id: "ready", lane: "you", col: cols.next(262), actor: "you", t0: result.t, status: ok ? "ok" : "fail", time: sec(result.seconds ?? result.t), ev: "result",
      title: ok ? "Built view ready" : "No picture this time", body: ok && result.image_url ? [{ kind: "image", src: result.image_url, alt: "Muse Image's picture of the fix" }] : [],
      detail: [text(ok ? "Checked against the model before you see it" : "The option card says why", { tone: "muted" })] });
    edges.push({ from: "kept", to: "ready", win: true });
    ticks.push({ lane: "you", at: result.t, tone: ok ? "ok" : "fail" });
  } else {
    const s = stoppedStep(run, at, failure, cols.next());
    if (s) { add(s); edges.push({ from: prev, to: s.id }); } else cols.widths.pop();
  }
  return { lanes, cols: cols.widths, steps, edges, bars, ticks, flows: [], duration: Math.min(at, run.ended ?? at), done,
    rows: [{ id: "you", label: lanes[0].label }, { id: "orca", label: "ORCA" }, { id: "image", label: "Image" }, { id: "judges", label: "Judges" }] };
}

/* ---------- ORCA's own check: every test over the open models ---------- */

function detect(run: Run, at: number): Graph {
  const events = upTo(run, at), done = finished(run, at), cols = new Columns();
  const phases: { t: number; text: string }[] = [];
  let start: { t: number; elements: number; tests: { name: string; kind: string }[] } | null = null, failure: string | null = null;
  const tests = new Map<number, { t: number; name: string; candidates: number; done?: { t: number; clashes: number; seconds: number; touching: number } }>();
  type Diff = { new?: unknown[]; resolved?: unknown[]; first?: boolean };
  let end: { t: number; seconds: number; elements: number; clashes: number; diff?: Diff } | null = null;
  for (const { t, e } of events) {
    if (e.type === "phase") phases.push({ t, text: String(e.text ?? "") });
    else if (e.type === "start") start = { t, elements: Number(e.elements ?? 0), tests: (e.tests as { name: string; kind: string }[]) ?? [] };
    else if (e.type === "test") tests.set(Number(e.index ?? 0), { t, name: String(e.name ?? ""), candidates: Number(e.candidates ?? 0) });
    else if (e.type === "test_done") {
      const c = (e.coverage ?? {}) as { clashes?: number; seconds?: number; touching?: number }, s = tests.get(Number(e.index ?? 0));
      if (s) s.done = { t, clashes: Number(c.clashes ?? 0), seconds: Number(c.seconds ?? 0), touching: Number(c.touching ?? 0) };
    } else if (e.type === "done") {
      const cov = (e.coverage as { clashes?: number }[] | undefined) ?? [];
      end = { t, seconds: Number(e.seconds ?? t), elements: Number(e.elements ?? 0), clashes: cov.reduce((a, c) => a + Number(c.clashes ?? 0), 0), diff: e.diff as Diff | undefined };
    } else if (e.type === "error") failure = String(e.detail ?? "The check failed");
  }
  const live = !end && !done && !failure;
  const lanes: Lane[] = [youLane(run, 100), { id: "orca", label: "ORCA", sub: "checks every test", actor: "orca", h: 140 }];
  const steps: Step[] = [], edges: Edge[] = [], bars: Bar[] = [], ticks: Tick[] = [{ lane: "you", at: 0, tone: "you" }];
  const add = (s: Step) => { steps.push(s); return s; };
  add(startStep(run, "check the models", "POST /detect/stream", cols.next()));
  if (run.origin === "you") steps[0].title = "Check the models";
  let prev = "start";
  // A phase lasts until the first event after it (the server sends "start" between reading and building).
  const after = (t: number) => { const later = [...phases.map((p) => p.t), start?.t, ...[...tests.values()].map((s) => s.t), end?.t, failure != null ? at : undefined]
    .filter((x): x is number => x != null && x > t); return later.length ? Math.min(...later) : null; };
  phases.forEach((p, i) => {
    const next = after(p.t), id = `phase${i}`, running = next == null && live;
    add({ id, lane: "orca", col: cols.next(), actor: "orca", t0: p.t, status: running ? "run" : "done", ev: "phase", title: p.text,
      time: next != null ? sec(next - p.t) : running ? sec(at - p.t) : "", body: [], detail: [] });
    edges.push({ from: prev, to: id }); prev = id;
  });
  for (const [i, s] of [...tests.entries()].sort((x, y) => x[0] - y[0])) {
    const id = `test${i}`, running = !s.done && live;
    add({ id, lane: "orca", col: cols.next(), actor: "orca", t0: s.t, status: s.done ? (s.done.clashes ? "fail" : "ok") : running ? "run" : "done",
      ev: "test · test_done", title: s.name, time: s.done ? sec(s.done.seconds) : running ? sec(at - s.t) : "",
      body: [text(s.done ? `${s.done.clashes} clash${s.done.clashes === 1 ? "" : "es"}` : running ? "Checking" : "Stopped", { strong: !!s.done, tone: s.done?.clashes ? "bad" : s.done ? "ok" : undefined, live: running })],
      detail: [text(`${s.candidates} candidate pair${s.candidates === 1 ? "" : "s"}${s.done?.touching ? ` · ${s.done.touching} touching` : ""}`, { tone: "muted" })] });
    edges.push({ from: prev, to: id, kind: i ? "seq" : undefined }); prev = id;
    if (s.done) bars.push({ lane: "orca", a: s.t, b: s.done.t, tone: s.done.clashes ? "fail" : "ok" });
  }
  if (end) {
    const fresh = end.diff?.new?.length ?? 0, gone = end.diff?.resolved?.length ?? 0;
    add({ id: "found", lane: "you", col: cols.next(262), actor: "you", t0: end.t, status: "ok", time: sec(end.seconds), ev: "done",
      title: `${end.clashes} clash${end.clashes === 1 ? "" : "es"} in ${end.elements.toLocaleString()} elements`,
      body: [text(end.diff?.first ? "The first check of these models" : `${fresh} new · ${gone} resolved since the last check`)], detail: [] });
    edges.push({ from: prev, to: "found", win: true });
    ticks.push({ lane: "you", at: end.t, tone: "ok" });
  } else {
    const s = stoppedStep(run, at, failure, cols.next());
    if (s) { add(s); edges.push({ from: prev, to: s.id }); } else cols.widths.pop();
  }
  return { lanes, cols: cols.widths, steps, edges, bars, ticks, flows: [], duration: Math.min(at, run.ended ?? at), done,
    rows: [{ id: "you", label: lanes[0].label }, { id: "orca", label: "ORCA" }] };
}
