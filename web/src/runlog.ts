/** The runs this page watched, for Workings (docs/workings.md): each run's stream events with the moment each arrived.
 * App starts a run in the tracker that already gathers its events (a click, the chat, an agent linked over MCP and the
 * tour's replays all pass through it), and Workings draws it. Framework-free, so it is tested on its own. */

export type RunKind = "propose" | "plan" | "triage" | "built" | "detect";
/** Who started a run: the person on this page, the chat, an agent linked over MCP, or a recorded run the tour plays. */
export type Origin = "you" | "chat" | "agent" | "replay";

/** A stream event as it arrived: `t` is seconds after the run started. */
export interface RunEvent { t: number; e: { type: string; [key: string]: unknown } }

export interface Run {
  id: number;
  kind: RunKind;
  origin: Origin;
  /** What the run is about, in a few words ("#53 Supply air main × Transfer girder"). */
  title: string;
  /** When it started, on this browser's clock (ms). */
  started: number;
  events: RunEvent[];
  /** Seconds after the start when it ended; null while it runs. */
  ended: number | null;
  /** Why it stopped early, if it did. */
  error: string | null;
  /** What its builder needs to know from the start (a plan's kind). */
  meta: Record<string, unknown>;
  /** Bumped on every change, so a drawing can tell what changed. */
  version: number;
}

/** What a tracker holds: add each event as it arrives, then end the run once. Later calls do nothing. */
export interface RunHandle {
  readonly id: number;
  add(event: { type: string; [key: string]: unknown } | { type: string }): void;
  end(error?: string | null): void;
}

/** Runs kept: enough for a session's recent work, small enough that a triage's events never pile up. A run still
 * going is never let go of: the oldest finished ones go first, and the log grows past this while more are live. */
export const RUNS_KEPT = 12;

/** What Workings never reads and a run would otherwise carry: meshes (a trial's pieces, an option's preview, before
 * and placements). Dropped from every event as it is logged, at any depth. */
const HEAVY = new Set(["pieces", "preview", "before", "placements"]);
export function lean<T>(value: T, depth = 0): T {
  if (depth > 6 || value === null || typeof value !== "object") return value;
  if (Array.isArray(value)) return value.map((v) => lean(v, depth + 1)) as T;
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(value as Record<string, unknown>)) if (!HEAVY.has(k)) out[k] = lean(v, depth + 1);
  return out as T;
}

export class RunLog {
  private all: Run[] = [];
  private seq = 0;
  private listeners = new Set<() => void>();
  private snapshot: readonly Run[] = [];

  constructor(private now: () => number = () => Date.now(), private kept = RUNS_KEPT) {}

  start(kind: RunKind, { origin = "you", title = "", meta = {} }: { origin?: Origin; title?: string; meta?: Record<string, unknown> } = {}): RunHandle {
    const run: Run = { id: ++this.seq, kind, origin, title, started: this.now(), events: [], ended: null, error: null, meta, version: 0 };
    const kept = [...this.all];
    while (kept.length >= this.kept) {
      const finished = kept.findIndex((r) => r.ended !== null);
      if (finished < 0) break;
      kept.splice(finished, 1);
    }
    this.all = [...kept, run];
    this.changed();
    return {
      id: run.id,
      add: (event) => {
        if (run.ended !== null) return;
        run.events.push({ t: this.since(run), e: lean(event) as RunEvent["e"] });
        run.version++;
        this.changed();
      },
      end: (error = null) => {
        if (run.ended !== null) return;
        run.ended = this.since(run);
        run.error = error;
        run.version++;
        this.changed();
      },
    };
  }

  /** Every run still going ends now, with why (the models were closed, the page moved to other work). */
  stopAll(why: string) {
    let any = false;
    for (const run of this.all) if (run.ended === null) { run.ended = this.since(run); run.error = why; run.version++; any = true; }
    if (any) this.changed();
  }

  /** The runs kept, oldest first. The same array until something changes. */
  runs(): readonly Run[] { return this.snapshot; }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }

  private since(run: Run) { return Math.max(0, (this.now() - run.started) / 1000); }

  private changed() {
    this.snapshot = [...this.all];
    for (const listener of [...this.listeners]) listener();
  }
}

/** The page's log: App writes to it, the Activity panel reads it. */
export const runs = new RunLog();
