import { ArrowLeft, FileSpreadsheet, FolderOpen, Upload } from "lucide-react";
import { useState } from "react";

const MODEL = /\.(ifc|step|stp)$/i;
const REPORT = /\.(xml|png|jpe?g)$/i;

/** A blank project: the visitor's own models (IFC or STEP), dropped or chosen, then checked like the demos; or a
 *  Navisworks clash report to import. Nothing is opened until they choose. */
export function ProjectStart({ busy, onModels, onReport, onReportFolder, onBack }: {
  busy: boolean;
  onModels: (files: File[]) => void;
  onReport: (files: File[]) => void;
  onReportFolder: () => void;
  onBack: () => void;
}) {
  const [over, setOver] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [chosen, setChosen] = useState<HTMLInputElement | null>(null);

  function take(list: FileList | File[] | null) {
    const files = [...(list ?? [])];
    const models = files.filter((f) => MODEL.test(f.name));
    const report = files.filter((f) => REPORT.test(f.name));
    if (models.length) { setNote(null); onModels(models); return; }
    if (report.some((f) => /\.xml$/i.test(f.name))) { setNote(null); onReport(report); return; }
    setNote(files.length ? "Those aren't models: drop IFC (.ifc) or STEP (.step, .stp) files, or a Navisworks XML report." : null);
  }

  return (
    <div className="project-start" onClick={(e) => e.stopPropagation()}>
      <button className="btn ghost small project-back" onClick={onBack}><ArrowLeft size={14} aria-hidden /> Back to the demos</button>
      <p className="eyebrow">Your own project</p>
      <h1>Start with your models</h1>
      <p className="lede">Add the models to coordinate: buildings or plant as IFC, machines and equipment as STEP. ORCA checks
        every pair, and each model against itself, as soon as they open; then triage, fixes and the report work as in the
        demos.</p>
      <label className={`project-drop${over ? " over" : ""}${busy ? " busy" : ""}`} data-tour="project-drop"
        onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); if (!busy) take(e.dataTransfer.files); }}>
        <input ref={setChosen} type="file" multiple hidden accept=".ifc,.step,.stp" disabled={busy}
          onChange={(e) => { take(e.target.files); e.target.value = ""; }} />
        <Upload size={28} aria-hidden />
        <b>{busy ? "Opening…" : "Drop IFC or STEP files here"}</b>
        <span className="hint">Several files open together (structure, services, architecture…). Up to 150 MB in all.</span>
        <button className="btn primary" type="button" disabled={busy} onClick={() => chosen?.click()}>
          <FolderOpen size={15} aria-hidden /> Choose files</button>
      </label>
      {note && <p className="bad small">{note}</p>}
      <div className="project-alt">
        <FileSpreadsheet size={18} aria-hidden />
        <div><b>Already ran Navisworks?</b>
          <span className="hint">Import its clash report (XML, with its images) to triage and fix those results instead.</span></div>
        <button className="btn small" disabled={busy} onClick={onReportFolder}>Import a report folder</button>
      </div>
      <p className="hint small">Your files are held for your session only and are not listed for other visitors; a server
        restart clears them. Coordination requirements can be set once the models are open.</p>
    </div>
  );
}
