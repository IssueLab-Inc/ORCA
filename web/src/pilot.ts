import type { AgentEvent, Attempt, Trial } from "./api";
import type { Viewer } from "./viewer/Viewer";

/** What the pilot tells the page: is it driving, and what is on screen now. */
export interface PilotStatus {
  driving: boolean;
  state: "thinking" | "trying" | "passed" | "failed" | "idle";
  text: string;
}

type Step = { trial: Trial; title: string; attempt: Attempt | null; arrived: () => void };

const TRYING = "#f5a623";
const PASSED = "#12b5cb";  // teal: not either side's red or green

/**
 * Lets the fix agent drive the viewer while it works: each candidate appears in place as it is checked, the camera
 * flies to it, then it turns teal (clear) or lights up what it hit in magenta. Between rounds the camera turns slowly round the
 * clash. The agent runs faster than people watch, so steps play at a readable pace and catch up when they queue.
 *
 * Any camera move or click in the viewer hands the view back to the user (`takeOver`); the agent keeps working and
 * its steps still fill the activity table. `resume` gives the view back to the agent from its next step.
 */
export class Pilot {
  private driving = false;
  private active = false;
  private queue: Step[] = [];
  private steps = new Map<number, Step>();
  private titles = new Map<number, string>();
  private playing = false;
  private done: (() => void) | null = null;
  private generation = 0;
  private waits = new Set<() => void>();

  constructor(private viewer: () => Viewer | null, private frame: (t: Trial) => void,
              private onStatus: (s: PilotStatus | null) => void) {}

  /** A proposal started: take the view. */
  start() {
    this.cancel();
    this.active = this.driving = true;
    this.status("thinking", "Muse Spark is reading the clash…");
    this.viewer()?.orbit(true);
  }

  event(e: AgentEvent) {
    if (!this.active) return;
    if (e.type === "thinking" && e.round > 1 && this.driving && !this.playing) {
      this.status("thinking", `Round ${e.round}: Muse Spark is thinking again, with what failed…`);
      this.viewer()?.orbit(true);
    }
    if (e.type === "reasoning" && this.driving && !this.playing) this.status("thinking", `Thinking: ${e.text}`);
    if (e.type === "checking") this.titles.set(e.index, e.title);
    if (e.type === "trial" && this.driving) {
      const step: Step = { trial: e, title: this.titles.get(e.index) ?? "", attempt: null, arrived: () => undefined };
      this.steps.set(e.index, step);
      this.queue.push(step);
      void this.play();
    }
    if (e.type === "attempt") {
      const step = this.steps.get(e.index);
      if (step) { step.attempt = e; step.arrived(); }
    }
  }

  /** The agent finished: `then` shows its result, once the steps on screen have played out. */
  finish(then: () => void) {
    if (!this.active) { then(); return; }
    this.done = then;
    if (!this.playing || !this.driving) this.land();
  }

  /** Superseded work owns no future stage cleanup, status or completion, even after an animation wait. */
  cancel() {
    const hadWork = this.active || this.playing || !!this.done;
    ++this.generation;
    this.done = null;
    this.reset();
    this.playing = false;
    for (const end of this.waits) end();
    this.waits.clear();
    if (hadWork) { this.clear(); this.onStatus(null); }
  }

  /** The user moved the camera: stop driving, clear what the pilot drew, let the result show when it comes. */
  takeOver() {
    if (!this.active || !this.driving) return;
    this.driving = false;
    this.queue = [];
    this.clear();
    this.status("idle", "You have the view. ORCA is still working.");
  }

  /** Give the view back to the agent from its next step. */
  resume() {
    if (!this.active || this.driving) return;
    this.driving = true;
    this.status("thinking", "ORCA will show its next idea here.");
    this.viewer()?.orbit(true);
  }

  private async play() {
    if (this.playing) return;
    const generation = this.generation;
    const current = () => this.generation === generation;
    this.playing = true;
    let n = 0;
    while (this.driving && this.queue.length) {
      const step = this.queue.shift()!;
      const v = this.viewer();
      if (!v) break;
      n++;
      const busy = this.queue.length > 1;  // falling behind: shorter stops
      const t = step.trial;
      v.orbit(false);
      v.setHits([]);
      v.showOption({ kind: t.kind, moved: t.moved, deltaM: t.delta_m, pieces: t.pieces, before: null }, "after", TRYING);
      this.frame(t);
      this.status("trying", `Trying idea ${t.index + 1}: ${step.title || describe(t)}`);
      const arrived = step.attempt ? Promise.resolve() : new Promise<void>((r) => { step.arrived = r; });
      await Promise.all([arrived, this.wait(busy ? 500 : 1100)]);
      if (!current()) return;
      const a = step.attempt;
      if (!this.driving || !a) break;
      if (a.passed) {
        v.showOption({ kind: t.kind, moved: t.moved, deltaM: t.delta_m, pieces: t.pieces, before: null }, "after", PASSED);
        this.status("passed", `✓ ${step.title || describe(t)}: clear of everything`);
      } else {
        v.setHits(a.hit_ids ?? []);
        this.status("failed", `✗ ${step.title || describe(t)}: ${a.reason || "did not pass"}`);
      }
      await this.wait(busy ? 600 : 1400);
      if (!current()) return;
    }
    if (!current()) return;
    this.playing = false;
    if (n && this.driving && !this.done) {
      this.status("thinking", "Muse Spark is weighing what it found…");
      this.viewer()?.orbit(true);
    }
    if (this.done) this.land();
  }

  /** Clear the stage and show the result. */
  private land() {
    const then = this.done;
    this.cancel();
    then?.();
  }

  private wait(ms: number) {
    return new Promise<void>((resolve) => {
      const end = () => { clearTimeout(timer); this.waits.delete(end); resolve(); };
      const timer = setTimeout(end, ms);
      this.waits.add(end);
    });
  }

  private clear() {
    const v = this.viewer();
    v?.orbit(false);
    v?.setHits([]);
    v?.preview([]);
  }

  private reset() {
    this.active = this.driving = false;
    this.queue = [];
    for (const s of this.steps.values()) s.arrived();  // nothing waits on a step that will not come
    this.steps.clear();
    this.titles.clear();
  }

  private status(state: PilotStatus["state"], text: string) {
    this.onStatus({ driving: this.driving, state, text });
  }
}

function describe(t: Trial) {
  if (t.summary) return t.summary;
  const [dx, dy, dz] = t.delta_m.map((d) => Math.round(d * 1000));
  if (t.kind === "trim") return `trim one end ${Math.round(Math.hypot(dx, dy, dz))} mm`;
  return t.kind === "offset" ? `offset ${dz > 0 ? "up" : "down"} ${Math.abs(dz)} mm` : `move ${dx} · ${dy} · ${dz} mm`;
}
