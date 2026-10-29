import { CircleCheck, CircleX, Download, FileText, LoaderCircle, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api, type DocEvent, type Evidence, type ModelTeam, type Report, type ReportClash, type Signoff, type Team, type TriageVerdict } from "./api";
import type { Review } from "./ReportList";

export const TEAMS: Team[] = ["Structure", "MEP", "Architecture", "Site"];
type Scope = "combined" | "team" | "model";

/** The teams with an element in this clash: they review it (the server applies the same rule). */
export function reviewersOf(c: ReportClash, teams: Record<string, Team>): Team[] {
  const out = [c.a.file, c.b.file].map((f) => (f && teams[f]) || null).filter((t): t is Team => !!t);
  return out.length ? [...new Set(out)] : TEAMS;
}

/** Reviews recorded per team for one clash, and a form to add one. Feeds the report's review blocks. */
export function ReviewBlock({ clash, teams, signoffs, onAdd, onRemove }: {
  clash: ReportClash; teams: Record<string, Team>; signoffs: Signoff[];
  onAdd: (s: Signoff) => void; onRemove: (index: number) => void;
}) {
  const reviewers = reviewersOf(clash, teams);
  const [team, setTeam] = useState<Team>(reviewers[0]);
  const [name, setName] = useState(() => { try { return localStorage.getItem("sightline.reviewer") ?? ""; } catch { return ""; } });
  const [note, setNote] = useState("");
  useEffect(() => { setTeam(reviewers.find((t) => !signoffs.some((s) => s.team === t)) ?? reviewers[0]); setNote(""); },
    [clash.id]);  // eslint-disable-line react-hooks/exhaustive-deps
  const add = (decision: Signoff["decision"]) => {
    if (!name.trim()) return;
    try { localStorage.setItem("sightline.reviewer", name.trim()); } catch { /* private window */ }
    onAdd({ team, name: name.trim(), decision, note: note.trim(), at: new Date().toISOString() });
    setNote("");
  };
  const waiting = reviewers.filter((t) => !signoffs.some((s) => s.team === t));
  return (
    <details className="review-block" data-tour="review" open={signoffs.length > 0}>
      <summary>
        <b>Team review</b>
        <span className={`chip small ${waiting.length ? "warn" : "ok"}`}>
          {waiting.length ? `waiting on ${waiting.join(", ")}` : "reviewed by every team"}</span>
      </summary>
      {signoffs.length > 0 && (
        <ul className="signoffs">
          {signoffs.map((s, i) => (
            <li key={i}>
              {s.decision === "approve" ? <CircleCheck size={14} className="ok" aria-label="approved" /> : <CircleX size={14} className="bad" aria-label="rejected" />}
              <span><b>{s.team}</b> · {s.name}{s.note ? <span className="why"> · {s.note}</span> : null}</span>
              <button className="ibtn" aria-label="Remove this review" onClick={() => onRemove(i)}><X size={12} aria-hidden /></button>
            </li>))}
        </ul>)}
      <div className="review-form">
        <select value={team} onChange={(e) => setTeam(e.target.value as Team)} aria-label="Team">
          {reviewers.map((t) => <option key={t}>{t}</option>)}
        </select>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Your name" aria-label="Your name" />
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Comment (optional)" aria-label="Comment" className="wide" />
        <button className="btn small" disabled={!name.trim()} onClick={() => add("approve")}><CircleCheck size={13} aria-hidden /> Approve</button>
        <button className="btn small" disabled={!name.trim()} onClick={() => add("reject")}><CircleX size={13} aria-hidden /> Reject</button>
      </div>
      <p className="hint">No sign-in yet: a review is a name and a decision, printed in the report. The report stays DRAFT until every
        team involved has reviewed each clash that needs action.</p>
    </details>
  );
}

const STEP: Record<string, string> = {
  explaining: "Muse Spark is writing each clash's explanation", summarising: "Writing the summary",
  rendering: "Laying out the PDF", bcf: "Writing the BCF issues",
};

/** Build a coordination report: scope, which team owns each model, BCF, then progress and the download. */
export function ReportDialog({ report, sceneId, triage, triageDone, triageRunning, teams, onTeams, evidence, signoffs, reviewed, onRunTriage, onClose, onReady }: {
  report: Report; sceneId: string | null; triage: Record<string, TriageVerdict>; triageDone: boolean; triageRunning: boolean;
  teams: Record<string, Team>; onTeams: (t: Record<string, Team>) => void;
  evidence: Record<string, Evidence>; signoffs: Record<string, Signoff[]>; reviewed: Record<string, Review>;
  onRunTriage: () => void; onClose: () => void; onReady?: () => void;
}) {
  const [models, setModels] = useState<ModelTeam[] | null>(null);
  const [scope, setScope] = useState<Scope>("combined");
  const [bcf, setBcf] = useState(true);
  const [step, setStep] = useState<DocEvent | null>(null);
  const [ready, setReady] = useState<{ url: string; name: string; bytes: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const busy = !!step && !ready && !error;

  useEffect(() => {
    api.teams(report.id, sceneId).then((r) => {
      setModels(r.models);
      onTeams({ ...Object.fromEntries(r.models.map((m) => [m.file, m.guess])), ...teams });  // keep what was confirmed
    }).catch((e) => setError((e as Error).message));
  }, [report.id, sceneId]);  // eslint-disable-line react-hooks/exhaustive-deps

  const pages = report.clashes.filter((c) => evidence[c.id] || (triage[c.id]?.verdict === "real_clash" && !reviewed[c.id])).length;
  const reviewedPages = report.clashes.filter((c) => (evidence[c.id] || (triage[c.id]?.verdict === "real_clash" && !reviewed[c.id]))
    && reviewersOf(c, teams).every((t) => signoffs[c.id]?.some((s) => s.team === t))).length;

  async function build() {
    setError(null); setReady(null); setStep({ type: "progress", step: "explaining", done: 0, total: pages });
    try {
      await api.document(report.id, {
        scene_id: sceneId, scope, teams, bcf, evidence, reviews: signoffs,
        marks: Object.fromEntries(Object.entries(reviewed).map(([id, r]) => [id, r.kind])),
        // The verdicts on screen, without the model's reasoning (kept in the browser; not needed for the report).
        triage: Object.fromEntries(Object.entries(triage).map(([id, { reasoning: _r, ...v }]) => [id, v])),
      }, (e) => {
        if (e.type === "ready") { setReady(e); onReady?.(); }
        else if (e.type === "error") setError(e.message);
        else setStep(e);
      });
    } catch (e) { setError((e as Error).message); }
  }

  return (
    <div className="about-dialog" role="dialog" aria-modal="true" aria-label="Coordination report" onClick={busy ? undefined : onClose}>
      <div className="report-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="row"><h2><FileText size={18} aria-hidden /> Coordination report</h2>
          <button className="ibtn" aria-label="Close" onClick={onClose}><X size={16} aria-hidden /></button></div>
        <p className="hint">A PDF for the design teams: every real clash and every fix on its own page, with Muse Spark's explanation,
          the original and the fix side by side, and a review block for each team involved. Model errors go in a table for the
          models' authors; noise in a summary by clash test. BCF issues open in Revit, Navisworks, Solibri or BIMcollab.</p>

        <h3>What to produce</h3>
        <div className="seg" role="group" aria-label="Scope">
          {([["combined", "One report"], ["team", "One per team"], ["model", "One per model"]] as const).map(([k, label]) => (
            <button key={k} className={scope === k ? "on" : ""} aria-pressed={scope === k} onClick={() => setScope(k)}>{label}</button>))}
        </div>
        <p className="hint">{scope === "combined" ? "Everything in one PDF." : scope === "team"
          ? "Each team gets the clashes it acts on or reviews." : "Each model's file gets the clashes it is part of."}</p>

        <h3>Which team owns each model</h3>
        <p className="hint">Guessed from what each model contains (ducts and pipes, beams and columns, walls and doors), not
          its name. Check it: it decides who acts and who reviews.</p>
        {!models ? <p className="hint"><LoaderCircle size={13} className="spin" aria-hidden /> Reading the models…</p> : (
          <table className="team-table"><tbody>
            {models.map((m) => (
              <tr key={m.file}><td className="mono">{m.file}</td>
                <td><select value={teams[m.file] ?? m.guess} aria-label={`Team for ${m.file}`}
                  onChange={(e) => onTeams({ ...teams, [m.file]: e.target.value as Team })}>
                  {TEAMS.map((t) => <option key={t}>{t}</option>)}</select></td>
                <td className="why">{m.elements ? `${m.elements} elements` : ""}</td></tr>))}
          </tbody></table>)}

        <label className="check"><input type="checkbox" checked={bcf} onChange={(e) => setBcf(e.target.checked)} /> Include BCF issues
          (one per clash that needs action, assigned to the team that acts)</label>

        <dl className="kv">
          <dt>Pages</dt><dd>{triageDone ? `${pages} clashes need action` : "after triage"}</dd>
          <dt>Fixes</dt><dd>{Object.values(evidence).filter((e) => e.status === "accepted").length} applied, {Object.values(evidence).filter((e) => e.status === "proposed").length} proposed</dd>
          <dt>Reviews</dt><dd>{reviewedPages} of {pages} reviewed by every team: {reviewedPages >= pages && pages ? "final" : "the report will say DRAFT"}</dd>
        </dl>

        {!triageDone && <p className="nofix">{triageRunning
          ? <><LoaderCircle size={13} className="spin" aria-hidden /> Triage is running ({Object.keys(triage).length} of {report.clashes.length}). The report can be built when it ends.</>
          : <>The report sorts clashes by triage. Run it first (about 3 minutes for Northbank).
            <button className="btn small" onClick={onRunTriage}>Triage all</button></>}</p>}
        {busy && step?.type === "progress" && (
          <p className="hint"><LoaderCircle size={13} className="spin" aria-hidden /> {STEP[step.step]}
            {step.total ? ` · ${step.done ?? 0} of ${step.total}` : ""}…</p>)}
        {error && <p className="bad">{error}</p>}
        {error?.startsWith("Triage the report first") && !triageRunning &&
          <button className="btn small" onClick={() => { setError(null); onRunTriage(); }}>Triage all</button>}
        <div className="actions">
          {ready
            ? <a className="btn primary big" data-tour="download" href={ready.url} download={ready.name}><Download size={16} aria-hidden /> Download {ready.name} ({Math.max(1, Math.round(ready.bytes / 1024))} KB)</a>
            : <button className="btn primary big" data-tour="build" disabled={!triageDone || busy || !models} onClick={build}>
              {busy ? <><i className="spinner" aria-hidden /> Building…</> : <><FileText size={16} aria-hidden /> Build the report</>}</button>}
          {ready && <button className="btn" onClick={() => setReady(null)}>Change and build again</button>}
        </div>
        <p className="hint">Explanations are drafted by Muse Spark and marked as such; a fix marked verified passed ORCA's
          geometry check against the whole model. Building costs one proposal from the demo allowance.</p>
      </div>
    </div>
  );
}
