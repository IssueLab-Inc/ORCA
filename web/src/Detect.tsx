import { useState } from "react";
import { CircleCheck, ClipboardCheck, Loader2, Radar, RotateCcw, X } from "lucide-react";
import type { CheckSummary, DetectCoverage, DetectSetup, DetectTest, Detection } from "./api";
import { checkLabel, checkOf } from "./checks";

/** Live progress of a detection run: the current phase, and each test as it finishes. */
export interface DetectProgress { phase: string; tests: { name: string; coverage?: DetectCoverage }[]; running?: number }

const RULE: Record<string, string> = { same_element: "same element", connected: "joined by ports", assembly: "one assembly",
  host: "door or window in its wall" };
const KIND: Record<string, string> = { hard: "hard", clearance: "clearance", duplicate: "duplicates" };

function excluded(c: DetectCoverage) {
  const parts = Object.entries(c.excluded).map(([k, v]) => `${v} ${RULE[k] ?? k}`);
  return parts.length ? parts.join(", ") : "0";
}

/** Before any report is open: what ORCA will check in the open models, and the button to run it. */
export function DetectSetupCard({ setup, progress, onRun, disabled, requirements = null, onRequirements }: {
  setup: DetectSetup | null; progress: DetectProgress | null; onRun: (tests: DetectTest[]) => void; disabled: boolean;
  requirements?: string | null; onRequirements?: () => void;  // the coordination requirements in use ("L3 · Strict")
}) {
  const [picked, setPicked] = useState<Record<string, boolean>>({});  // the user's ticks over each test's default
  const [toleranceMm, setToleranceMm] = useState(1);
  if (progress) return <section className="triage detect running"><DetectHead sub="ORCA is checking the models…" />
    <ProgressRows progress={progress} /></section>;
  if (!setup) return <section className="triage detect"><DetectHead sub="Reading the models…" /></section>;
  const enabled = (t: DetectTest) => picked[t.id] ?? t.enabled;
  const toggle = (t: DetectTest) => setPicked((p) => ({ ...p, [t.id]: !enabled(t) }));
  // Under requirements the tests are what they compile to, tolerance included: only ticks are offered here.
  const ruled = !!setup.requirements;
  const chosen = setup.tests.filter(enabled).map((t) => ({ ...t, enabled: true,
    tolerance_m: t.kind === "hard" && !ruled ? Math.max(0, toleranceMm) / 1000 : t.tolerance_m }));
  return (
    <section className="triage detect idle" data-tour="detect">
      <DetectHead sub={ruled ? `The checks your requirements ask for` : "Every pair of models, and each model against itself"} />
      {ruled ? <p className="triage-lead">ORCA runs the checks in <b>{setup.requirements!.name}</b> ({requirements ?? setup.requirements!.label}):
        each group against the others and itself, at the tolerances and clearances they set.</p>
        : <p className="triage-lead">ORCA checks every pair of models and each model against itself, and reports
        overlaps deeper than the tolerance. Pairs meant to meet (joined by ports, one assembly, a door in its wall) and
        touches are counted, not reported.</p>}
      <ReqLine requirements={ruled ? requirements ?? setup.requirements!.label : null} onRequirements={onRequirements} />
      <ul className="detect-tests">
        {setup.tests.map((t) => (
          <li key={t.id}>
            <label><input type="checkbox" checked={enabled(t)} onChange={() => toggle(t)} /> {t.name}</label>
            <span className="chip small">{t.kind === "clearance" ? `clearance ${Math.round(t.clearance_m * 1000)} mm` : KIND[t.kind]}</span>
          </li>))}
      </ul>
      {!ruled && <label className="detect-tol">Hard clashes deeper than
        <input type="number" min={0} step={1} value={toleranceMm} onChange={(e) => setToleranceMm(Number(e.target.value))} /> mm</label>}
      <button className="btn primary triage-go" disabled={disabled || !chosen.length} onClick={() => onRun(chosen)}>
        <Radar size={15} aria-hidden /> Check {checkedElements(setup, chosen).toLocaleString()} elements</button>
      <p className="hint">Seconds for a few thousand elements. Then the AI names each clash, triage sorts them, and ORCA
        proposes verified fixes.</p>
    </section>
  );
}

/** "Requirements: L3 · Strict  Edit", or the way to set some. */
function ReqLine({ requirements, name, onRequirements }: { requirements: string | null; name?: string; onRequirements?: () => void }) {
  if (!onRequirements && !requirements) return null;
  return (
    <p className="detect-req"><ClipboardCheck size={13} aria-hidden />
      {requirements ? <b data-tip-tap data-tip={name ? `Checked against "${name}"` : undefined}>{requirements}</b> : <span className="hint">ORCA's defaults · no requirements set</span>}
      {onRequirements && <button className="btn small ghost" onClick={onRequirements}>{requirements ? "Edit" : "Set requirements"}</button>}
    </p>
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

/** Over a report ORCA found: what was checked, what changed since the last run, and Detect again. */
export function DetectSummary({ detection, progress, onAgain, disabled, compact = false, requirementsId = null, onRequirements, onWhole }: {
  detection: Detection; progress: DetectProgress | null; onAgain: () => void; disabled: boolean;
  compact?: boolean;  // the list is filtered: one line, so the list gets the room
  requirementsId?: string | null; onRequirements?: () => void;  // the requirements in use now (their id)
  onWhole?: () => void;  // after a check on filters: check the open models again, every test
}) {
  const check = checkOf(detection.tests);  // a check on filters (docs/filters.md, "Checks"): its name
  const ran = detection.requirements?.label ?? null;  // what this run was checked against
  const clashes = detection.coverage.reduce((n, c) => n + c.clashes, 0);
  const pairs = detection.coverage.reduce((n, c) => n + c.candidate_pairs, 0);
  const meant = detection.coverage.reduce((n, c) => n + Object.values(c.excluded).reduce((x, y) => x + y, 0), 0);
  const touching = detection.coverage.reduce((n, c) => n + c.touching, 0);
  const partial = detection.coverage.filter((c) => c.partial);
  const d = detection.diff;
  return (
    <section className={`triage detect summary ${progress ? "running" : ""} ${compact && !progress ? "compact" : ""}`} data-tour="detected">
      <DetectHead sub={progress ? "Checking again…" : compact
        ? `${check ? `Only ${check} · ` : ""}${clashes.toLocaleString()} clashes in ${detection.elements.toLocaleString()} elements · ${detection.seconds.toFixed(1)} s`
        : `Found by ORCA · ${detection.seconds.toFixed(1)} s`}
        action={!progress && <button className="ibtn" aria-label="Detect again"
          data-tip={check ? `Detect again: ${check}, and what your fixes resolved` : "Detect again: see what your fixes resolved"}
          data-tip-side="left" disabled={disabled} onClick={onAgain}><RotateCcw size={14} aria-hidden /></button>} />
      {progress ? <ProgressRows progress={progress} /> : !compact && <>
        <p className="detect-count"><b>{clashes.toLocaleString()}</b> clash{clashes === 1 ? "" : "es"} in
          {" "}{detection.elements.toLocaleString()} elements</p>
        {check && <p className="detect-check"><span>Only <b>{check}</b></span>
          {onWhole && <button type="button" className="btn small ghost" disabled={disabled} onClick={onWhole}>
            <Radar size={14} aria-hidden /> Check the open models</button>}</p>}
        <ReqLine requirements={ran} name={detection.requirements?.name} onRequirements={onRequirements} />
        {(detection.requirements?.id ?? null) !== requirementsId &&
          <p className="hint small">The requirements changed since this run: Detect again to check under {requirementsId ? "them" : "ORCA's defaults"}.</p>}
        {!d.first && (
          <div className="detect-diff">
            <span className={`chip ${d.resolved.length ? "ok" : ""}`} data-tip-tap data-tip={d.resolved.map((r) => r.test).join(", ") || "Nothing resolved since the last run"}>
              {d.resolved.length} resolved</span>
            <span className={`chip ${d.new.length ? "warn" : ""}`}>{d.new.length} new</span>
            {d.no_longer_checked.length > 0 && <span className="chip" data-tip-tap data-tip="Gone because an element left the test, not because it was fixed">
              {d.no_longer_checked.length} no longer checked</span>}
          </div>)}
        {partial.length > 0 && <p className="bad small">{partial.map((c) => c.name).join(", ")} reached the limit of results:
          narrow {partial.length === 1 ? "that test" : "those tests"} to see them all.</p>}
        <details className="detect-coverage">
          <summary>What was checked: {pairs.toLocaleString()} close pairs, {touching} touching, {meant} meant to meet</summary>
          <table>
            <thead><tr><th>Test</th><th>Pairs</th><th>Clashes</th><th>Touch</th><th>Meant to meet</th></tr></thead>
            <tbody>{detection.coverage.map((c) => (
              <tr key={c.test}><td>{c.name}</td><td data-label="pairs">{c.candidate_pairs}</td><td data-label="clashes">{c.clashes}{c.partial ? "+" : ""}</td>
                <td data-label="touching">{c.touching}</td><td data-label="meant to meet">{excluded(c)}</td></tr>))}</tbody>
          </table>
          <p className="hint small">A pair whose boxes never come that close cannot clash, so every other pair is covered.</p>
        </details>
      </>}
    </section>
  );
}

/** Over the list: the checks ORCA keeps for the open models (docs/detection.md, "Kept checks"), which one the list
 * shows (all of them by default), and running one again, all of them again, or dropping a check on filters. */
export function CheckPicker({ checks, total, value, onPick, onAgain, onAll, onRemove, disabled }: {
  checks: CheckSummary[]; total: number; value: string | null; onPick: (key: string | null) => void;
  onAgain: (key: string) => void; onAll: () => void; onRemove: (key: string) => void; disabled: boolean;
}) {
  const cur = checks.find((c) => c.key === value) ?? null;
  const stale = checks.filter((c) => c.stale).length;
  return (<>
    <div className="check-pick" data-tour="checks">
      <select value={value ?? ""} onChange={(e) => onPick(e.target.value || null)} aria-label="Which check the list shows">
        <option value="">All {checks.length} checks · {total.toLocaleString()}</option>
        {checks.map((c) => <option key={c.key} value={c.key}>{checkLabel(c)}</option>)}
      </select>
      {cur ? <>
        <button className="ibtn" aria-label={`Run ${cur.name} again`} data-tip={`Run ${cur.name} again: see what your fixes resolved`}
          data-tip-side="bottom" disabled={disabled} onClick={() => onAgain(cur.key)}><RotateCcw size={14} aria-hidden /></button>
        {cur.key !== "models" && <button className="ibtn" aria-label={`Remove ${cur.name}`} data-tip={`Remove ${cur.name}: its clashes leave the list unless another check found them`}
          data-tip-side="bottom" disabled={disabled} onClick={() => onRemove(cur.key)}><X size={14} aria-hidden /></button>}
      </> : <button className="btn small ghost" disabled={disabled} onClick={onAll} data-tip="Run every kept check again, one after another"
        data-tip-side="bottom"><RotateCcw size={13} aria-hidden /> Run all again</button>}
    </div>
    {stale > 0 && <p className="hint small check-stale">{stale === checks.length ? (stale === 1 ? "The check" : "Every check") : `${stale} of the checks`} ran
      before a fix you kept: run {stale === 1 ? "it" : "them"} again to see what the fix resolved.</p>}
  </>);
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
