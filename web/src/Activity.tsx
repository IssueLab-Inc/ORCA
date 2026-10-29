import type { Attempt } from "./api";
import { mm } from "./ReportList";

/** What the agent is doing now, while a proposal runs. */
export interface Progress {
  started: number;          // ms timestamp
  round: number;
  phase: "thinking" | "checking" | "done";
  thinkingSince: number;    // ms timestamp of the current model call
  modelSeconds: number[];   // per finished round
  ideas: number;            // candidates in the current round
  checking: { index: number; title: string; kind: string } | null;
}

/** The edit a fix makes, in a few words: "move 0 · 0 · +400 mm", "offset 1.10–2.30 m by +400 mm", "trim one end 60 mm". */
export const editText = (t: Pick<Attempt, "kind" | "split_m" | "delta_m" | "trim">) => t.kind === "offset" && t.split_m
  ? `offset ${t.split_m.map((v) => v.toFixed(2)).join("–")} m by ${mm(t.delta_m[2])}`
  : t.kind === "trim"
    ? t.trim ? `trim one end ${Math.round(t.trim.by_m * 1000)} mm` : "trim at the joint"
    : `move ${t.delta_m.map((v) => mm(v)).join(" · ")}`;

export const KIND_LABEL = { move: "Move", offset: "Offset", trim: "Trim" } as const;

/** "collision with IfcWall (-200 mm), collision with …" → first finding, plus how many more. */
function firstReason(reason: string): [string, number] {
  const parts = reason.split(/, (?=collision|clearance|cannot)/);
  return [parts[0], parts.length - 1];
}

export function statusLine(p: Progress | null, now: number, attempts: Attempt[]): string {
  if (!p) return "";
  const total = Math.round((now - p.started) / 1000);
  if (p.phase === "thinking") {
    return `Round ${p.round}: Muse Spark is reading the clash and the model data… ${Math.round((now - p.thinkingSince) / 1000)} s`;
  }
  if (p.phase === "checking" && p.checking) {
    return `Round ${p.round}: checking idea ${p.checking.index + 1} (${p.checking.title}) against the whole model · ${total} s`;
  }
  const ok = attempts.filter((a) => a.passed).length;
  return `Done in ${total} s: ${ok} of ${attempts.length} ideas passed the geometry check`;
}

export function Activity({ attempts, progress, now }: { attempts: Attempt[]; progress: Progress | null; now: number }) {
  if (!progress && !attempts.length) {
    return <p className="hint">ORCA's steps appear here: each idea from Muse Spark, and what the geometry check found.</p>;
  }
  const running = progress && progress.phase !== "done";
  return (
    <div className="activity">
      <div className="activity-head">
        <b>Agent activity</b>
        <span className={running ? "live" : "hint"}>{running && <i className="spinner" aria-hidden />}{statusLine(progress, now, attempts)}</span>
        {progress && progress.modelSeconds.length > 0 &&
          <span className="hint mono">model {progress.modelSeconds.map((s) => `${s.toFixed(0)} s`).join(" + ")}</span>}
      </div>
      <table className="steps">
        <thead><tr><th>#</th><th>Kind</th><th>Idea</th><th>Edit</th><th>Geometry check</th></tr></thead>
        <tbody>
          {attempts.map((t, i) => {
            const [first, more] = firstReason(t.reason);
            return (
              <tr key={i} className={t.passed ? "ok" : "fail"}>
                <td className="mono">{i + 1}</td>
                <td><span className={`badge ${t.kind}`}>{KIND_LABEL[t.kind] ?? t.kind}</span></td>
                <td>{t.title}</td>
                <td className="mono">{editText(t)}</td>
                <td>{t.passed ? <span className="ok">✓ verified</span>
                  : <span className="bad" title={t.reason}>✗ {first}{more ? ` +${more} more` : ""}</span>}</td>
              </tr>
            );
          })}
          {progress?.phase === "checking" && progress.checking && progress.checking.index >= attempts.length &&
            <tr className="pending"><td className="mono">{progress.checking.index + 1}</td><td><span className={`badge ${progress.checking.kind}`}>{KIND_LABEL[progress.checking.kind as keyof typeof KIND_LABEL] ?? progress.checking.kind}</span></td>
              <td>{progress.checking.title}</td><td /><td className="hint">checking…</td></tr>}
        </tbody>
      </table>
    </div>
  );
}
