import { AlertTriangle, ArrowDown, ArrowUp, ClipboardCheck, Download, LoaderCircle, RotateCcw, Sparkles, Trash2, Upload, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, type ReqCheck, type ReqParams, type ReqPreview, type ReqScale, type Requirements, type RuleAudit, type Strictness } from "./api";
import { cellFor, download, parseUpload, removeByDesign, setCell, setMover, shiftMover, STRICTNESS, STRICTNESS_NAME } from "./reqFile";

const RULES: [string, string][] = [["same_element", "Same element"], ["connected", "Joined by ports"],
  ["assembly", "Parts of one assembly"], ["host", "A door or window in its wall"]];
const TRIMS = { yes: "trims allowed", cleanup: "trims only within one model", no: "no trims" } as const;
const LEAN = { by_design: "when unsure: by design", real_clash: "when unsure: real, for a person" } as const;

/** The pair a rule names, as the server writes it ("Wall with Beam"), so Muse's audit finds its rule. */
const pairText = (a: string[], b: string[]) =>
  `${a.map((c) => c.replace(/^Ifc/, "")).join(" / ")} with ${b.map((c) => c.replace(/^Ifc/, "")).join(" / ")}`;

/** Coordination requirements (server: requirements.py; docs/requirements.md): the level the models are at, how strict
 *  to be, what is checked against what, who moves, what is by design, and guidance for Muse Spark. Optional: off is
 *  ORCA's defaults. Muse can draft it from the open models; it downloads and uploads as a file. */
export function RequirementsDialog({ sceneId, initial, enabled: wasEnabled, audit, canDetectAgain, onApply, onClose }: {
  sceneId: string | null;
  initial: Requirements | null;
  enabled: boolean;
  audit: Record<string, RuleAudit>;
  canDetectAgain: boolean;
  onApply: (doc: Requirements | null, enabled: boolean, detectAgain: boolean) => void;
  onClose: () => void;
}) {
  const [scale, setScale] = useState<ReqScale | null>(null);
  const [draft, setDraft] = useState<Requirements | null>(initial);
  const [enabled, setEnabled] = useState(initial ? wasEnabled : true);
  const [preview, setPreview] = useState<ReqPreview | "busy" | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [suggesting, setSuggesting] = useState(false);
  const [summary, setSummary] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [kept, setKept] = useState<Set<string>>(new Set());
  const upload = useRef<HTMLInputElement>(null);
  const previewSeq = useRef(0);

  useEffect(() => { api.requirementsScale().then(setScale).catch((e) => setError((e as Error).message)); }, []);
  // A start from the open models when there is no file yet: what ORCA checks today, ready to tighten.
  useEffect(() => {
    if (draft || !sceneId) return;
    api.requirementsDefault(sceneId).then((r) => setDraft(r.doc)).catch((e) => setError((e as Error).message));
  }, [sceneId, draft]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  // Expected clashes, a moment after the last change (the server runs the check; repeated files are cached).
  useEffect(() => {
    if (!draft || !sceneId) return;
    const seq = ++previewSeq.current;
    setPreview("busy");
    setPreviewError(null);
    const t = setTimeout(() => {
      api.previewRequirements(sceneId, draft).then((p) => { if (seq === previewSeq.current) setPreview(p); })
        .catch((e) => { if (seq === previewSeq.current) { setPreview(null); setPreviewError((e as Error).message); } });
    }, 600);
    return () => clearTimeout(t);
  }, [draft, sceneId]);

  const level = scale?.levels.find((l) => l.level === draft?.level);
  const step = scale?.strictness.find((s) => s.id === draft?.strictness);
  const params: ReqParams | null = preview && preview !== "busy" ? preview.params : null;
  const groups = draft?.groups ?? [];
  const names = Object.fromEntries(groups.map((g) => [g.id, g.name]));

  async function suggest() {
    if (!sceneId || !draft) return;
    setSuggesting(true); setError(null);
    try {
      const r = await api.suggestRequirements(sceneId, draft.level, draft.strictness, draft.name);
      setDraft(r.doc); setSummary(r.summary); setEnabled(true);
    } catch (e) { setError((e as Error).message); }
    setSuggesting(false);
  }
  async function reset() {
    if (!sceneId) return;
    try { const r = await api.requirementsDefault(sceneId); setDraft({ ...r.doc, name: draft?.name || r.doc.name }); setSummary(null); }
    catch (e) { setError((e as Error).message); }
  }
  async function onFile(f: File | undefined) {
    if (!f) return;
    try { setDraft(parseUpload(await f.text())); setEnabled(true); setSummary(null); setError(null); }
    catch (e) { setError((e as Error).message); }
  }

  const update = (d: Requirements) => setDraft(d);
  const cell = (a: string, b: string | null) => draft ? cellFor(draft, a, b) : undefined;

  return (
    <div className="about-dialog" role="dialog" aria-modal="true" aria-label="Coordination requirements" onClick={onClose}>
      <div className="report-dialog req-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="row"><h2><ClipboardCheck size={18} aria-hidden /> Coordination requirements</h2>
          <button className="ibtn" aria-label="Close" onClick={onClose}><X size={16} aria-hidden /></button></div>
        <p className="hint">Optional. Set the standard ORCA checks, triages and fixes to: the design stage, how strict to be,
          what is checked against what and who moves. Muse Spark still reads every clash a rule doesn't settle and
          proposes every fix, told these requirements. Off, ORCA uses its defaults.</p>

        {!draft ? <p className="hint"><LoaderCircle size={13} className="spin" aria-hidden /> {sceneId ? "Reading the models…" : "Open models to start from them, or upload a file."}</p> : <>
          <div className="req-top">
            <input className="req-name" aria-label="Name" value={draft.name} maxLength={80}
              onChange={(e) => update({ ...draft, name: e.target.value })} />
            <label className="req-switch"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
              <span>{enabled ? "In use" : "Off: ORCA's defaults"}</span></label>
          </div>
          <div className="req-tools">
            <button className="btn small primary" disabled={!sceneId || suggesting} data-tour="req-suggest"
              data-tip="Muse Spark drafts groups, checks, who moves and by-design rules from what the open models contain, at this level and strictness. Counts as one proposal."
              onClick={suggest}>{suggesting ? <><i className="spinner" aria-hidden /> Muse Spark is drafting…</> : <><Sparkles size={14} aria-hidden /> Suggest with Muse Spark</>}</button>
            <button className="btn small" onClick={() => download(draft)} data-tip="Save the file to reuse on another project or share with the team">
              <Download size={14} aria-hidden /> Download</button>
            <button className="btn small" onClick={() => upload.current?.click()} data-tip="Open a requirements file (.json)">
              <Upload size={14} aria-hidden /> Upload</button>
            <button className="btn small ghost" disabled={!sceneId} onClick={reset} data-tip="Start again from the open models (what ORCA checks without requirements)">
              <RotateCcw size={14} aria-hidden /> Start from the models</button>
            <input ref={upload} type="file" accept=".json,application/json" hidden
              onChange={(e) => { void onFile(e.target.files?.[0]); e.target.value = ""; }} />
          </div>
          {summary && <p className="req-summary"><Sparkles size={13} aria-hidden /> <span><b>Muse Spark:</b> {summary}</span></p>}

          <fieldset className="req-body" disabled={!enabled}>
            <h3>Design level</h3>
            <p className="hint">How far the models have got. Early levels only care about gross overlaps; later ones about every
              millimetre and the space around services. The names fit any industry; the hints are rough equivalents.</p>
            <div className="req-levels" role="radiogroup" aria-label="Design level" data-tour="req-levels">
              {(scale?.levels ?? []).map((l) => (
                <button key={l.level} role="radio" aria-checked={draft.level === l.level}
                  className={`req-level${draft.level === l.level ? " on" : ""}`} onClick={() => update({ ...draft, level: l.level })}>
                  <b>L{l.level} {l.name}</b>
                  <span>{l.meaning}</span>
                  <span className="req-hints">{l.hints.map((h) => <i key={h}>{h}</i>)}</span>
                </button>))}
            </div>

            <div className="req-strict-block" data-tour="req-strict">
            <h3>Strictness</h3>
            <p className="hint">One setting for flagging and fixing. Strict flags more and fixes cautiously (more clearance, smaller
              moves, no trims); lenient flags only clear problems and allows bolder fixes.</p>
            <div className="req-strict">
              <input type="range" min={0} max={4} step={1} value={STRICTNESS.indexOf(draft.strictness)} aria-label="Strictness"
                aria-valuetext={STRICTNESS_NAME[draft.strictness]}
                onChange={(e) => update({ ...draft, strictness: STRICTNESS[Number(e.target.value)] as Strictness })} />
              <div className="req-ticks">{STRICTNESS.map((s) => (
                <button key={s} className={draft.strictness === s ? "on" : ""} onClick={() => update({ ...draft, strictness: s })}>{STRICTNESS_NAME[s]}</button>))}</div>
            </div>
            {step && <p className="hint"><b>{step.name}:</b> {step.meaning}</p>}
            <div className="req-sets" aria-live="polite">
              <span className="hint">What this sets:</span>
              {params ? <>
                <span className="chip">hard from {params.tolerance_mm} mm</span>
                {params.min_size_mm > 0 && <span className="chip">parts under {params.min_size_mm} mm skipped</span>}
                {params.service_clearance_mm > 0 && <span className="chip">services ↔ structure {params.service_clearance_mm} mm</span>}
                <span className="chip">fixes clear by {params.fix_clearance_mm} mm</span>
                <span className="chip">{params.max_move_mm ? `moves ≤ ${params.max_move_mm} mm` : "no move limit"}</span>
                <span className="chip">{TRIMS[params.trims]}</span>
                {params.edits !== "any" && <span className="chip warn">{params.edits === "none" ? "no edits: Muse recommends" : "whole moves only"}</span>}
                {params.lean && <span className="chip">{LEAN[params.lean]}</span>}
              </> : step ? <>
                <span className="chip">fixes clear by {step.fix_clearance_mm} mm</span>
                <span className="chip">{step.max_move_mm ? `moves ≤ ${step.max_move_mm} mm` : "no move limit"}</span>
                <span className="chip">{TRIMS[step.trims as keyof typeof TRIMS]}</span>
              </> : null}
            </div>
            <p className="req-expect" data-tour="req-expected">
              {preview === "busy" ? <><LoaderCircle size={13} className="spin" aria-hidden /> Counting what these would find…</>
                : preview ? <><b>Expected: {preview.clashes.toLocaleString()} clashes</b>
                  <span className="hint">ORCA's defaults find {preview.baseline.toLocaleString()} · checked in {preview.seconds} s</span></>
                : previewError ? <span className="hint">{previewError}</span> : null}
            </p>
            </div>

            <h3>Checks</h3>
            <p className="hint">What each group is checked against. Hard: any overlap past the tolerance. Clearance: a gap that must
              stay (insulation, hangers, access). Off: context only.{level && level.service_clearance_mm > 0
                ? ` At L${level.level} a hard check between services and structure keeps ${level.service_clearance_mm} mm (scaled by strictness).` : ""}</p>
            <div className="req-grid-wrap" data-tour="req-grid">
              <table className="req-grid">
                <thead><tr><th />{groups.map((g) => <th key={g.id} scope="col">{g.name}</th>)}</tr></thead>
                <tbody>{groups.map((ga, i) => (
                  <tr key={ga.id}><th scope="row">
                    <input className="req-group-name" value={ga.name} aria-label={`Name of group ${ga.name}`}
                      onChange={(e) => update({ ...draft, groups: draft.groups.map((g) => g.id === ga.id ? { ...g, name: e.target.value } : g) })} />
                    {(ga.classes.length > 0 || ga.teams.join(", ") !== ga.name) &&
                      <span className="req-selects" data-tip={[...ga.teams.map((t) => `team ${t}`), ...ga.classes.map((c) => c.replace(/^Ifc/, ""))].join(", ")}>
                        {ga.classes.length ? `${ga.classes.length} kinds of element` : `team ${ga.teams.join(", ")}`}</span>}</th>
                    {groups.map((gb, j) => j < i ? <td key={gb.id} className="req-none" /> : (
                      <td key={gb.id}><Cell value={cell(ga.id, j === i ? null : gb.id)} label={`${ga.name} vs ${j === i ? "itself" : gb.name}`}
                        levelMm={j !== i && new Set([ga.role, gb.role]).has("services") && new Set([ga.role, gb.role]).has("structure")
                          ? params?.service_clearance_mm ?? 0 : 0}
                        onChange={(patch) => update(setCell(draft, ga.id, j === i ? null : gb.id, patch))} /></td>))}
                  </tr>))}
                </tbody>
              </table>
            </div>

            <h3>Who moves</h3>
            <p className="hint">Top stays put the most; bottom moves first. ORCA refuses a fix a row forbids before trying it and
              tells Muse Spark why.</p>
            <ol className="req-movers">
              {draft.who_moves.map((m, i) => (
                <li key={m.group}>
                  <span className="req-mover-name">{names[m.group] ?? m.group}</span>
                  <span className="req-mover-ctl">
                    <button className="ibtn" aria-label="Up" disabled={i === 0} onClick={() => update(shiftMover(draft, i, -1))}><ArrowUp size={14} aria-hidden /></button>
                    <button className="ibtn" aria-label="Down" disabled={i === draft.who_moves.length - 1} onClick={() => update(shiftMover(draft, i, 1))}><ArrowDown size={14} aria-hidden /></button>
                    <select value={m.edits} aria-label={`Edits on ${names[m.group]}`} onChange={(e) => update(setMover(draft, m.group, { edits: e.target.value as typeof m.edits }))}>
                      <option value="any">Any fix</option><option value="move">Whole moves only</option><option value="none">Never edited</option></select>
                    <label className="req-mm" data-tip="The largest move or offset a fix may make to this group (empty: no limit)">≤
                      <input type="number" min={0} step={50} value={m.max_move_mm ?? ""} placeholder="any" aria-label={`Largest move for ${names[m.group]}`}
                        onChange={(e) => update(setMover(draft, m.group, { max_move_mm: e.target.value ? Number(e.target.value) : null }))} /> mm</label>
                    <label className="req-trim"><input type="checkbox" checked={m.trims} onChange={(e) => update(setMover(draft, m.group, { trims: e.target.checked }))} /> trims</label>
                  </span>
                </li>))}
            </ol>

            <h3>Never a clash</h3>
            <p className="hint">Pairs that are meant to meet. They are counted, not reported, or settled at triage without a model
              call; Muse Spark then checks each rule on the clashes it set aside.</p>
            <div className="req-rules">{RULES.map(([k, label]) => (
              <label key={k} className="check"><input type="checkbox" checked={draft.rules[k] !== false}
                onChange={(e) => update({ ...draft, rules: { ...draft.rules, [k]: e.target.checked }, version: draft.version + 1 })} /> {label}</label>))}</div>
            {draft.by_design.length ? <ul className="req-design">{draft.by_design.map((r, i) => {
              const text = pairText(r.a_classes, r.b_classes);
              const a = Object.values(audit).find((x) => x.rule === text);
              const disputed = a?.answer === "looks_real" && !kept.has(text);
              return (
                <li key={text + i} className={disputed ? "disputed" : ""}>
                  <span><b>{text}</b>{r.reason ? <> · {r.reason}</> : null} <span className="chip small">{r.source === "orca" ? "ORCA suggests" : r.source === "triage" ? "from Insights" : "yours"}</span>
                    {a && !disputed && a.answer === "consistent" && <span className="chip small ok">Muse agrees</span>}</span>
                  <button className="ibtn" aria-label={`Remove ${text}`} onClick={() => update(removeByDesign(draft, i))}><Trash2 size={14} aria-hidden /></button>
                  {disputed && <p className="req-dispute"><AlertTriangle size={13} aria-hidden /> Muse Spark thinks this rule hides real
                    clashes ({a.settled.length} set aside): {a.note}
                    <span><button className="btn small" onClick={() => setKept(new Set([...kept, text]))}>Keep rule</button>
                      <button className="btn small" onClick={() => update(removeByDesign(draft, i))}>Remove rule</button></span></p>}
                </li>);
            })}</ul> : <p className="hint">No by-design pairs yet: add them from Insights (a pattern Muse reads as by design) or ask Muse to suggest.</p>}

            <h3>Guidance for Muse Spark</h3>
            <div className="req-guidance">
              <label>For triage<textarea maxLength={1000} rows={2} value={draft.guidance.triage} placeholder="e.g. Fire dampers must keep 300 mm access."
                onChange={(e) => update({ ...draft, guidance: { ...draft.guidance, triage: e.target.value } })} /></label>
              <label>For fixes<textarea maxLength={1000} rows={2} value={draft.guidance.fixes} placeholder="e.g. Drainage keeps its fall: never raise it."
                onChange={(e) => update({ ...draft, guidance: { ...draft.guidance, fixes: e.target.value } })} /></label>
            </div>
          </fieldset>
        </>}

        {error && <p className="bad">{error}</p>}
        <div className="actions">
          <button className="btn primary big" data-tour="req-apply" disabled={!draft} onClick={() => onApply(draft, enabled, false)}>
            {enabled ? "Use these requirements" : "Keep the file, use ORCA's defaults"}</button>
          {canDetectAgain && enabled && <button className="btn big" disabled={!draft} onClick={() => onApply(draft, enabled, true)}>Use them and check again</button>}
          {initial && <button className="btn ghost" onClick={() => onApply(null, false, false)}>Forget the file</button>}
        </div>
        <p className="hint">Kept in this browser; download the file to keep it elsewhere. Reports and BCF say which requirements
          they were checked against.</p>
      </div>
    </div>
  );
}

function Cell({ value, label, levelMm, onChange }: { value: ReqCheck | undefined; label: string; levelMm: number; onChange: (p: Partial<ReqCheck>) => void }) {
  const v = value ?? { check: "hard", clearance_mm: null, reason: "", source: "level" } as Partial<ReqCheck>;
  const tip = [v.reason, v.source === "orca" ? "ORCA suggests" : v.source === "user" ? "Yours" : ""].filter(Boolean).join(" · ");
  return (
    <span className={`req-cell ${v.check}`} data-tip={tip || undefined}>
      <select value={v.check} aria-label={label} onChange={(e) => onChange({ check: e.target.value as ReqCheck["check"] })}>
        <option value="hard">Hard</option><option value="clearance">Clearance</option><option value="off">Off</option></select>
      {v.check === "clearance" && <label className="req-mm"><input type="number" min={0} max={500} step={5} value={v.clearance_mm ?? 25}
        aria-label={`${label} clearance`} onChange={(e) => onChange({ clearance_mm: Number(e.target.value) })} /> mm</label>}
      {v.check === "hard" && levelMm > 0 && <span className="req-mm" data-tip="The design level keeps this gap between services and structure">keeps {levelMm} mm</span>}
      {v.source === "orca" && <Sparkles size={11} className="req-orca" aria-label="ORCA suggests" />}
    </span>
  );
}
