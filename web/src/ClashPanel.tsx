import { useEffect } from "react";
import { api, type Matches, type Measure, type ReportClash, type ReportElement, type TriageVerdict } from "./api";
import { mm } from "./ReportList";
import { TRIAGE } from "./Triage";

const VIEW_NAMES: Record<string, string> = { A: "A · pair", B: "B · context", C: "C · second angle" };

function Side({ colour, label, e, found, how }: {
  colour: "red" | "green"; label: string; e: ReportElement; found: string | null | undefined; how: string | null | undefined;
}) {
  return (
    <div className="side">
      <div className="row"><b><i className={`sw ${colour}`} />{label} · {e.ifc_class ?? "?"}</b>
        {found !== undefined && <span className={`chip ${found ? "ok" : "warn"}`}>{found ? (how === "name" ? "in model, by name" : "in model") : "not in model"}</span>}
      </div>
      <div>{e.name}{e.part_of ? <span className="why"> · part of {e.part_of}</span> : null}</div>
      <div className="why">{[e.level, e.file, e.system].filter(Boolean).join(" · ")}</div>
    </div>
  );
}

export function ClashPanel({ reportId, clash, match, measure, onImage, fix, triage }: {
  reportId: string; clash: ReportClash; match: Matches[string] | undefined; measure: Measure | null | "busy";
  onImage: (index: number) => void; fix?: string; triage?: TriageVerdict;
}) {
  return (
    <section className="clash-panel">
      <div className="row"><h2>{clash.name}</h2>{fix ? <span className="chip ok">✓ fixed</span> : clash.status && <span className="chip">{clash.status}</span>}</div>
      <p className="hint">{clash.test}</p>
      {fix && <p className="fixed-note">Fixed in this session: {fix}. The Navisworks images show the clash as reported.</p>}
      {triage && (
        <div className="triage-note">
          <span className={`chip small ${TRIAGE[triage.verdict].cls}`}>{TRIAGE[triage.verdict].label}</span>
          {triage.severity && triage.severity !== "none" && <span className="chip small">{triage.severity}</span>}
          {triage.responsible && triage.responsible !== "none" && <span className="chip small">{triage.responsible}</span>}
          <span className="why">{triage.source === "rule" ? "by rule" : "triage model"}</span>
          {triage.understanding && <p>{triage.understanding}{triage.fix_hint ? <span className="why"> {triage.fix_hint}</span> : null}</p>}
          {triage.error && <p className="bad small">{triage.error}</p>}
        </div>
      )}
      {clash.images.length > 0 && (
        <div className={`thumbs n${clash.images.length}`}>
          {clash.images.map((label, i) => (
            <button key={label} className="thumb" onClick={() => onImage(i)} title={`Open ${VIEW_NAMES[label] ?? label}`}>
              <img src={api.imageUrl(reportId, clash.id, i)} alt={`${clash.name}, view ${label}`} loading="lazy" />
              <span>{label}</span>
            </button>
          ))}
        </div>
      )}
      <dl className="kv">
        <dt>Navisworks</dt><dd className="mono">{mm(clash.distance_m)}{clash.tolerance_m ? ` (tolerance ${mm(clash.tolerance_m)})` : ""}</dd>
        <dt>Sightline</dt><dd className="mono">{
          measure === "busy" ? "measuring…"
            : !measure ? "open the models to measure"
              : !measure.matched ? "not in the open model"
                : measure.physical === false ? "not a physical element"
                  : measure.distance_m == null ? "no overlap here" : mm(measure.distance_m)}</dd>
        {clash.grid && <><dt>Grid</dt><dd>{clash.grid}</dd></>}
      </dl>
      {oneElement(match) && (
        <p className="hint"><i className="sw purple" />A and B are one element in this model, drawn purple: Navisworks
          clashed {sameWhy(clash)}.</p>
      )}
      <Side colour="red" label="A" e={clash.a} found={match ? match.a : undefined} how={match?.how[0]} />
      <Side colour="green" label="B" e={clash.b} found={match ? match.b : undefined} how={match?.how[1]} />
    </section>
  );
}

/** Both sides resolve to the same model element (a port and its own valve, or two Navisworks parts of one door). */
function oneElement(m: Matches[string] | undefined) {
  const a = m?.show?.[0] ?? m?.a, b = m?.show?.[1] ?? m?.b;
  return !!a && a === b;
}

function sameWhy(c: ReportClash) {
  const ports = [c.a, c.b].filter((e) => /Port$/.test(e.ifc_class ?? "")).length;
  return ports === 2 ? "two of its ports" : ports === 1 ? "a port with the element it belongs to" : "two parts of it";
}

export function Lightbox({ reportId, clash, index, onClose, onMove }: {
  reportId: string; clash: ReportClash; index: number; onClose: () => void; onMove: (index: number) => void;
}) {
  const n = clash.images.length;
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight") onMove((index + 1) % n);
      if (e.key === "ArrowLeft") onMove((index + n - 1) % n);
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [index, n, onClose, onMove]);
  const label = clash.images[index];
  return (
    <div className="lightbox" role="dialog" aria-label={`${clash.name}, view ${label}`} onClick={onClose}>
      <figure onClick={(e) => e.stopPropagation()}>
        <img src={api.imageUrl(reportId, clash.id, index)} alt={`${clash.name}, view ${label}`} />
        <figcaption>
          <span><b>{clash.name}</b> · {VIEW_NAMES[label] ?? label} · red {clash.a.ifc_class}, green {clash.b.ifc_class}</span>
          <span className="lb-nav">
            {n > 1 && clash.images.map((l, i) => <button key={l} className={`btn ${i === index ? "primary" : ""}`} onClick={() => onMove(i)}>{l}</button>)}
            <button className="btn" onClick={onClose}>Close</button>
          </span>
        </figcaption>
      </figure>
    </div>
  );
}
