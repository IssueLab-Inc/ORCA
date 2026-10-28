import { useState } from "react";
import { CircleCheck, Loader2, Radar, RotateCcw } from "lucide-react";
import type { DetectCoverage, DetectSetup, DetectTest, Detection } from "./api";

/** Live progress of a detection run: the current phase, and each test as it finishes. */
export interface DetectProgress { phase: string; tests: { name: string; coverage?: DetectCoverage }[]; running?: number }

const RULE: Record<string, string> = { same_element: "same element", connected: "joined by ports", assembly: "one assembly",
  host: "door or window in its wall" };
const KIND: Record<string, string> = { hard: "hard", clearance: "clearance", duplicate: "duplicates" };

function excluded(c: DetectCoverage) {
  const parts = Object.entries(c.excluded).map(([k, v]) => `${v} ${RULE[k] ?? k}`);
  return parts.length ? parts.join(", ") : "0";
}

/** Before any report is open: what Sightline will check in the open models, and the button to run it. */
export function DetectSetupCard({ setup, progress, onRun, disabled }: {
  setup: DetectSetup | null; progress: DetectProgress | null; onRun: (tests: DetectTest[]) => void; disabled: boolean;
}) {
  const [picked, setPicked] = useState<Record<string, boolean>>({});  // the user's ticks over each test's default
  const [toleranceMm, setToleranceMm] = useState(1);
  if (progress) return <section className="triage detect running"><DetectHead sub="Sightline is checking the models…" />
    <ProgressRows progress={progress} /></section>;
  if (!setup) return <section className="triage detect"><DetectHead sub="Reading the models…" /></section>;
  const enabled = (t: DetectTest) => picked[t.id] ?? t.enabled;
  const toggle = (t: DetectTest) => setPicked((p) => ({ ...p, [t.id]: !enabled(t) }));
  const chosen = setup.tests.filter(enabled).map((t) => ({ ...t, enabled: true,
    tolerance_m: t.kind === "hard" ? Math.max(0, toleranceMm) / 1000 : t.tolerance_m }));
  return (
    <section className="triage detect idle" data-tour="detect">
      <DetectHead sub="Every pair of models, and each model against itself" />
      <p className="triage-lead">Sightline checks every pair of models and each model against itself, and reports
        overlaps deeper than the tolerance. Pairs meant to meet (joined by ports, one assembly, a door in its wall) and
        touches are counted, not reported.</p>
      <ul className="detect-tests">
        {setup.tests.map((t) => (
          <li key={t.id}>
            <label><input type="checkbox" checked={enabled(t)} onChange={() => toggle(t)} /> {t.name}</label>
            <span className="chip small">{t.kind === "clearance" ? `clearance ${Math.round(t.clearance_m * 1000)} mm` : KIND[t.kind]}</span>
          </li>))}
      </ul>
      <label className="detect-tol">Hard clashes deeper than
        <input type="number" min={0} step={1} value={toleranceMm} onChange={(e) => setToleranceMm(Number(e.target.value))} /> mm</label>
      <button className="btn primary triage-go" disabled={disabled || !chosen.length} onClick={() => onRun(chosen)}>
        <Radar size={15} aria-hidden /> Check {checkedElements(setup, chosen).toLocaleString()} elements</button>
      <p className="hint">About ten seconds for a building. Then Muse names each clash, triage sorts them, and Sightline
        proposes verified fixes.</p>
    </section>
  );
}

function DetectHead({ sub, action }: { sub: string; action?: React.ReactNode }) {
  return (
    <div className="triage-head">
      <span className="triage-icon"><Radar size={15} aria-hidden /></span>
      <div><h3>Coordinate the models</h3><span className="triage-sub">{sub}</span></div>
      {action}
    </div>
  );
}

function ProgressRows({ progress }: { progress: DetectProgress }) {
  return (<>
    <p className="hint">{progress.phase}</p>
    <ul className="detect-progress">
      {progress.tests.map((t, i) => (
        <li key={t.name} className={t.coverage ? "done" : i === progress.running ? "now" : ""}>
          {t.coverage ? <CircleCheck size={13} aria-hidden /> : i === progress.running ? <Loader2 size={13} className="spin" aria-hidden /> : <i className="dot" />}
          <span>{t.name}</span>
          {t.coverage && <b>{t.coverage.clashes}</b>}
        </li>))}
    </ul>
  </>);
}

/** Over a report Sightline found: what was checked, what changed since the last run, and Detect again. */
export function DetectSummary({ detection, progress, onAgain, disabled, compact = false }: {
  detection: Detection; progress: DetectProgress | null; onAgain: () => void; disabled: boolean;
  compact?: boolean;  // the list is filtered: one line, so the list gets the room
}) {
  const clashes = detection.coverage.reduce((n, c) => n + c.clashes, 0);
  const pairs = detection.coverage.reduce((n, c) => n + c.candidate_pairs, 0);
  const meant = detection.coverage.reduce((n, c) => n + Object.values(c.excluded).reduce((x, y) => x + y, 0), 0);
  const touching = detection.coverage.reduce((n, c) => n + c.touching, 0);
  const partial = detection.coverage.filter((c) => c.partial);
  const d = detection.diff;
  return (
    <section className={`triage detect summary ${progress ? "running" : ""} ${compact && !progress ? "compact" : ""}`} data-tour="detected">
      <DetectHead sub={progress ? "Checking again…" : compact
        ? `${clashes.toLocaleString()} clashes in ${detection.elements.toLocaleString()} elements · ${detection.seconds.toFixed(1)} s`
        : `Found by Sightline · ${detection.seconds.toFixed(1)} s`}
        action={!progress && <button className="ibtn" aria-label="Detect again" data-tip="Detect again: see what your fixes resolved"
          data-tip-side="left" disabled={disabled} onClick={onAgain}><RotateCcw size={14} aria-hidden /></button>} />
      {progress ? <ProgressRows progress={progress} /> : !compact && <>
        <p className="detect-count"><b>{clashes.toLocaleString()}</b> clash{clashes === 1 ? "" : "es"} in
          {" "}{detection.elements.toLocaleString()} elements</p>
        {!d.first && (
          <div className="detect-diff">
            <span className={`chip ${d.resolved.length ? "ok" : ""}`} data-tip={d.resolved.map((r) => r.test).join(", ") || "Nothing resolved since the last run"}>
              {d.resolved.length} resolved</span>
            <span className={`chip ${d.new.length ? "warn" : ""}`}>{d.new.length} new</span>
            {d.no_longer_checked.length > 0 && <span className="chip" data-tip="Gone because an element left the test, not because it was fixed">
              {d.no_longer_checked.length} no longer checked</span>}
          </div>)}
        {partial.length > 0 && <p className="bad small">{partial.map((c) => c.name).join(", ")} reached the limit of results:
          narrow {partial.length === 1 ? "that test" : "those tests"} to see them all.</p>}
        <details className="detect-coverage">
          <summary>What was checked: {pairs.toLocaleString()} close pairs, {touching} touching, {meant} meant to meet</summary>
          <table>
            <thead><tr><th>Test</th><th>Pairs</th><th>Clashes</th><th>Touch</th><th>Meant to meet</th></tr></thead>
            <tbody>{detection.coverage.map((c) => (
              <tr key={c.test}><td>{c.name}</td><td>{c.candidate_pairs}</td><td>{c.clashes}{c.partial ? "+" : ""}</td>
                <td>{c.touching}</td><td>{excluded(c)}</td></tr>))}</tbody>
          </table>
          <p className="hint small">A pair whose boxes never come that close cannot clash, so every other pair is covered.</p>
        </details>
      </>}
    </section>
  );
}

/** How many elements the chosen tests look at: the files their selections name (an open selection is every file). */
function checkedElements(setup: DetectSetup, tests: DetectTest[]): number {
  const per = setup.file_elements;
  if (!per) return setup.elements;
  const files = new Set<string>();
  for (const t of tests) for (const sel of [t.a, t.b]) {
    if (!sel) continue;
    const pick = Object.keys(per).filter((f) => (!sel.files.length || sel.files.includes(f)) && (!sel.teams.length || sel.teams.includes(setup.teams[f])));
    pick.forEach((f) => files.add(f));
  }
  return [...files].reduce((n, f) => n + per[f], 0);
}
