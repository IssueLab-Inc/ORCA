/**
 * The hero's replay of ORCA's loop on Northbank's answer key, as a pure function of time: what is lit, lifted, kept
 * and said at second t. heroScene.ts draws a frame from it and Hero.tsx writes its log and labels, so the picture and
 * the words cannot drift apart, and a test can read any moment. It is a demonstration, sped up (CLAUDE.md: the phase
 * cycle is demonstration material, never live status), told from ORCA's own records: the fixes and numbers of the
 * recorded proposals (README, "See it work"), what Muse Spark is told about the opening (agent.py, from
 * edits.passages: +0.375 to +0.425 m clears it by 25 mm), and the tray's round as the recorded root-cause plan has it
 * (web/public/tour/girder-plan.json: "Lift full tray run 250mm" failed, "Offset tray up 250mm through web opening"
 * passed), the whole lift's hits being those ORCA's check reports (the return-air spigots, the core wall; Nov 4).
 */

export type Phase = "observe" | "resolve" | "check" | "apply";
export type RunKey = "duct" | "tray" | "cw";

export const PHASES: { id: Phase; word: string }[] = [
  { id: "observe", word: "Observe" }, { id: "resolve", word: "Resolve" }, { id: "check", word: "Check" }, { id: "apply", word: "Apply" },
];

/** One loop of the replay, in seconds. */
export const LOOP = 36;

/** When each run's story happens. The tray's round has two ideas: the whole run lifted (it fails) and the offset. */
export const T = {
  duct: { start: 4.6, read: 5.3, idea: 6.6, lift: [6.8, 8.2], check: 8.4, pass: 10.2, clear: 9.8, keep: 11.0, end: 14.4 },
  tray: { start: 14.4, wholeIdea: 15.0, wholeLift: [15.2, 16.2], wholeCheck: 16.4, fail: 17.1, back: 17.8, wholeGone: [18.6, 19.0],
    read: 18.9, idea: 18.9, lift: [19.1, 20.1], check: 20.3, pass: 21.0, clear: 21.0, keep: 21.9, end: 24.6 },
  cw: { start: 24.6, read: 25.2, idea: 25.2, lift: [25.4, 26.4], check: 26.6, pass: 27.3, clear: 27.3, keep: 28.2, end: 30.0 },
  scan: [0.2, 2.4],
  pins: { duct: 2.6, tray: 2.8, cw: 3.0 },
  finale: 30.0,
  fade: [35.2, LOOP],
} as const;

export const CHAPTERS: { at: number; label: string; key: RunKey | null }[] = [
  { at: 0, label: "Check", key: null },
  { at: T.duct.start, label: "#1", key: "duct" },
  { at: T.tray.start, label: "#2", key: "tray" },
  { at: T.cw.start, label: "#3", key: "cw" },
  { at: T.finale, label: "3 of 3", key: null },
];

export type Tone = "ai" | "ok" | "fail" | "info";
export interface LogLine { at: number; phase: Phase; text: string; tone: Tone }

/** What the replay says, and when. Every number is a recorded one. */
export const LOG: LogLine[] = [
  { at: 0.1, phase: "observe", tone: "info", text: "Checking every pair of models, and each against itself" },
  { at: 2.5, phase: "observe", tone: "info", text: "464 clashes in 1,732 elements, in about 4 s" },
  { at: 3.3, phase: "observe", tone: "info", text: "Triage: #1, #2 and #3 are real, all on one girder" },
  { at: T.duct.start, phase: "observe", tone: "info", text: "#1 Supply air main 600×300 into the girder: −300 mm" },
  { at: T.duct.read, phase: "observe", tone: "ai", text: "Muse Spark reads pictures A, B, C and the model: an opening in the web on this line, cleared by a rise of +375 to +425 mm" },
  { at: T.duct.idea, phase: "resolve", tone: "ai", text: "Idea: offset 1.40 m of the duct up 400 mm, with bends" },
  { at: T.duct.check, phase: "check", tone: "info", text: "Trying it in the model, checking every open model" },
  { at: 9.4, phase: "check", tone: "ok", text: "✓ Clash gone" },
  { at: T.duct.clear, phase: "check", tone: "ok", text: "✓ 50 mm clear all round (25 mm needed)" },
  { at: T.duct.pass, phase: "check", tone: "ok", text: "✓ Nothing new hit, checked against 21 elements" },
  { at: T.duct.keep, phase: "apply", tone: "ok", text: "Accepted: checked again on the server, kept in the model" },
  { at: T.tray.start, phase: "observe", tone: "info", text: "#2 Cable tray 300×100 into the girder: −100 mm" },
  { at: T.tray.wholeIdea, phase: "resolve", tone: "ai", text: "Muse Spark's round: lift the whole tray 250 mm, or offset only the stretch at the girder" },
  { at: T.tray.wholeCheck, phase: "check", tone: "info", text: "Trying the whole lift in the model" },
  { at: T.tray.fail, phase: "check", tone: "fail", text: "✗ It hits the return-air spigots, and a core wall further along" },
  { at: T.tray.back, phase: "check", tone: "info", text: "The failed idea stays on record, with what it hit" },
  { at: T.tray.idea, phase: "resolve", tone: "ai", text: "The round's other idea: offset only the stretch at the girder, up 250 mm" },
  { at: T.tray.check, phase: "check", tone: "info", text: "Trying it in the model" },
  { at: T.tray.pass, phase: "check", tone: "ok", text: "✓ Clash gone · 50 mm clear · nothing new hit (5 elements)" },
  { at: T.tray.keep, phase: "apply", tone: "ok", text: "Accepted and kept" },
  { at: T.cw.start, phase: "observe", tone: "info", text: "#3 Cold water main DN54 into the girder: −77 mm" },
  { at: T.cw.idea, phase: "resolve", tone: "ai", text: "Idea: offset the stretch at the girder up 280 mm" },
  { at: T.cw.check, phase: "check", tone: "info", text: "Trying it in the model" },
  { at: T.cw.pass, phase: "check", tone: "ok", text: "✓ Clash gone · 53 mm clear · nothing new hit (15 elements)" },
  { at: T.cw.keep, phase: "apply", tone: "ok", text: "Accepted and kept" },
  { at: T.finale, phase: "apply", tone: "ok", text: "3 of 3 at the designer's own heights: +400, +250, +280 mm" },
];

/** One run's state at a moment. */
export interface RunFrame {
  pin: "hidden" | "clash" | "fixed";
  flag: number;          // red, as the clash's element A (0..1)
  ghost: number;         // the idea being tried, drawn over the run (opacity 0..1)
  lift: number;          // how far up the idea has risen (0..1 of the fix's rise)
  tone: "try" | "pass";  // amber while checked, teal once it passed
  checking: number;      // the check sweeping along the edited run (0..1), or -1
  fixed: number;         // the kept geometry taking over (0..1)
  before: number;        // the run as it was, in orange, once kept (opacity 0..1)
  opening: number;       // the web opening it reads, outlined (0..1)
  clearance: number;     // the clearance callout (0..1)
}

export interface HeroFrame {
  t: number;
  phase: Phase;
  chapter: number;
  focus: RunKey | "all";
  scan: number;          // the check's sweep across the scene (0..1), or -1
  girder: number;        // green, as the clash's element B (0..1)
  runs: Record<RunKey, RunFrame>;
  whole: { lift: number; opacity: number; fail: number };  // the tray moved whole, and failing
  hits: number;          // what the failed idea hit, in magenta (0..1, pulsing)
  exports: number;       // fixes kept so far
  finale: number;        // the closing line (0..1)
  fade: number;          // the picture dimmed at the loop's turn: out at its end, back in at its start (0..1)
}

/** 0 before a, 1 after b, smooth between. */
export function ramp(t: number, a: number, b: number): number {
  if (t <= a) return 0;
  if (t >= b) return 1;
  const x = (t - a) / (b - a);
  return x * x * (3 - 2 * x);
}

const between = (t: number, a: number, b: number) => (t >= a && t < b ? (t - a) / (b - a) : -1);

function run(t: number, key: RunKey): RunFrame {
  const s = T[key], pinAt = T.pins[key];
  const kept = t >= s.keep;
  return {
    pin: t < pinAt ? "hidden" : kept ? "fixed" : "clash",
    flag: ramp(t, pinAt, pinAt + 0.4) * (1 - ramp(t, s.keep, s.keep + 0.6)),
    ghost: ramp(t, s.idea, s.idea + 0.35) * (1 - ramp(t, s.keep, s.keep + 0.7)),
    lift: ramp(t, s.lift[0], s.lift[1]),
    tone: t >= s.pass ? "pass" : "try",
    checking: between(t, s.check, s.pass),
    fixed: ramp(t, s.keep, s.keep + 0.8),
    before: ramp(t, s.keep, s.keep + 0.25) * (1 - ramp(t, s.keep + 1.2, s.keep + 2.4)) * 0.85,
    opening: ramp(t, s.read, s.read + 0.4) * (1 - ramp(t, s.pass, s.pass + 0.8)),
    clearance: ramp(t, s.clear, s.clear + 0.35) * (1 - ramp(t, s.end - 1.0, s.end - 0.2)),
  };
}

/** Everything the hero shows at second t of the loop (t wraps). */
export function heroAt(time: number): HeroFrame {
  const t = ((time % LOOP) + LOOP) % LOOP;
  const chapter = CHAPTERS.reduce((c, ch, i) => (t >= ch.at ? i : c), 0);
  const phase = LOG.reduce<Phase>((p, l) => (t >= l.at ? l.phase : p), "observe");
  const w = T.tray;
  return {
    t, phase, chapter,
    focus: CHAPTERS[chapter].key ?? "all",
    scan: between(t, T.scan[0], T.scan[1]),
    girder: ramp(t, T.pins.duct, T.pins.duct + 0.4) * (1 - ramp(t, T.cw.keep, T.cw.keep + 0.8)),
    runs: { duct: run(t, "duct"), tray: run(t, "tray"), cw: run(t, "cw") },
    whole: {
      lift: ramp(t, w.wholeLift[0], w.wholeLift[1]),
      opacity: ramp(t, w.wholeIdea, w.wholeIdea + 0.35) * (1 - ramp(t, w.wholeGone[0], w.wholeGone[1])),
      fail: ramp(t, w.fail, w.fail + 0.25),
    },
    hits: t >= w.fail && t < w.wholeGone[1] ? (0.65 + 0.35 * Math.cos((t - w.fail) * Math.PI * 2.4)) * (1 - ramp(t, w.wholeGone[0], w.wholeGone[1])) : 0,
    exports: (["duct", "tray", "cw"] as const).filter((k) => t >= T[k].keep).length,
    finale: ramp(t, T.finale, T.finale + 0.6),
    fade: Math.max(ramp(t, T.fade[0], T.fade[1]), 1 - ramp(t, 0, 0.7)),
  };
}

/** The log as it stands at second t: the lines said so far, newest last. */
export function logAt(time: number, keep = 5): LogLine[] {
  const t = ((time % LOOP) + LOOP) % LOOP;
  return LOG.filter((l) => l.at <= t).slice(-keep);
}

/** The still frame for people who ask for less motion, and the moment each chapter button shows them. */
export const STILL = T.finale + 1;
export const chapterStill = (i: number) => [T.scan[1] + 1.2, T.duct.keep + 1.4, T.tray.keep + 1.4, T.cw.keep + 1.2, STILL][i] ?? STILL;
