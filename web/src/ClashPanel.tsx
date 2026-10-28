import { useEffect, useRef, useState } from "react";
import { api, type Matches, type Measure, type ReportClash, type ReportElement, type TriageVerdict } from "./api";
import { mm } from "./ReportList";
import { oneElement, sameWhy } from "./noClash";
import { drawOverlay, focusSquare, readClashImage, type Box, type ClashRead } from "./clashImage";
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

const BASIS: Record<NonNullable<TriageVerdict["basis"]>, string> = {
  non_physical: "settled: not physical", touch: "settled: a touch", same_element: "settled: one element",
  no_overlap: "settled: no overlap measured", reviewed: "marked by you",
};

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
          <span className="why">{triage.basis ? BASIS[triage.basis] : triage.source === "rule" ? "by rule" : "triage model"}</span>
          {triage.understanding && <p>{triage.understanding}</p>}
          {triage.fix_hint && <p className="why">{triage.action === "exclude_with_rule" ? "Stop it coming back: " : "Fix: "}{triage.fix_hint}</p>}
          {triage.model_reading && <p className="why small">The triage model read it as {triage.model_reading}</p>}
          {triage.reasoning && <details className="triage-reasoning">
            <summary>How the triage model reasoned</summary>
            <p>{triage.reasoning}</p>
          </details>}
          {triage.error && <p className="bad small">{triage.error}</p>}
        </div>
      )}
      {clash.images.length > 0 && (
        <div className={`thumbs n${clash.images.length}`}>
          {clash.images.map((label, i) => (
            <button key={label} className="thumb" onClick={() => onImage(i)} title={`Open ${VIEW_NAMES[label] ?? label}`}>
              <ClashThumb url={api.imageUrl(reportId, clash.id, i)} alt={`${clash.name}, view ${label}`} />
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
  const url = api.imageUrl(reportId, clash.id, index);
  const [read, setRead] = useState<ClashRead | null>(null);
  const [marks, setMarks] = useState(true);
  const [zoom, setZoom] = useState(false);
  const overlay = useRef<HTMLCanvasElement | null>(null);
  useEffect(() => {
    let live = true;
    setRead(null);
    readClashImage(url).then((r) => { if (live) setRead(r); });
    return () => { live = false; };
  }, [url]);
  // Redraw the outlines at the picture's display size, and again when the window resizes.
  useEffect(() => {
    const c = overlay.current;
    if (!c || !read || !marks) return;
    const draw = () => { drawOverlay(c, read); };
    draw();
    const ro = new ResizeObserver(draw);
    ro.observe(c);
    return () => { ro.disconnect(); };
  }, [read, marks]);
  const focus = zoom && read ? focusSquare(read, 2.4, 0.3) : null;
  return (
    <div className="lightbox" role="dialog" aria-label={`${clash.name}, view ${label}`} onClick={onClose}>
      <figure onClick={(e) => e.stopPropagation()}>
        <div className="lb-frame">
          <div className="lb-zoom" style={focus ? zoomStyle(focus) : undefined}>
            <img src={url} alt={`${clash.name}, view ${label}`} />
            {marks && read && <canvas ref={overlay} className="lb-overlay" aria-hidden />}
          </div>
        </div>
        <figcaption>
          <span><b>{clash.name}</b> · {VIEW_NAMES[label] ?? label} · red {clash.a.ifc_class}, green {clash.b.ifc_class}
            {marks && read?.zone && <span className="lb-key"> · <i className="sw zone" />where they meet</span>}</span>
          <span className="lb-nav">
            <button className={`btn ${marks ? "on" : ""}`} aria-pressed={marks} onClick={() => setMarks(!marks)} disabled={!read}>Outlines</button>
            <button className={`btn ${zoom ? "on" : ""}`} aria-pressed={zoom} onClick={() => setZoom(!zoom)} disabled={!read?.pair}>Zoom to the clash</button>
            {n > 1 && clash.images.map((l, i) => <button key={l} className={`btn ${i === index ? "primary" : ""}`} onClick={() => onMove(i)}>{l}</button>)}
            <button className="btn" onClick={onClose}>Close</button>
          </span>
        </figcaption>
      </figure>
    </div>
  );
}

/** A clash picture in a small square, zoomed to where the two elements meet (read from its colours once it scrolls
 * into view). Until then, or if nothing is found, the whole picture. */
export function ClashThumb({ url, alt }: { url: string; alt: string }) {
  const el = useRef<HTMLSpanElement | null>(null);
  const [crop, setCrop] = useState<Box | null>(null);
  useEffect(() => {
    const node = el.current;
    if (!node) return;
    let live = true;
    const io = new IntersectionObserver((entries) => {
      if (!entries.some((e) => e.isIntersecting)) return;
      io.disconnect();
      readClashImage(url).then((r) => { if (live && r) setCrop(focusSquare(r)); });
    }, { rootMargin: "200px" });
    io.observe(node);
    return () => { live = false; io.disconnect(); };
  }, [url]);
  return (
    <span ref={el} className="clash-thumb" role="img" aria-label={alt}
      style={{ backgroundImage: `url("${url}")`, ...(crop ? cropStyle(crop) : { backgroundSize: "cover", backgroundPosition: "center" }) }} />
  );
}

/** CSS background placement that shows `b` (fractions of the picture) filling the box. */
function cropStyle(b: Box): React.CSSProperties {
  const side = b.x1 - b.x0;
  const pos = (start: number) => (side >= 1 ? 0 : (start / (1 - side)) * 100);
  return { backgroundSize: `${100 / side}% ${100 / (b.y1 - b.y0)}%`, backgroundPosition: `${pos(b.x0)}% ${pos(b.y0)}%` };
}

/** A transform that brings `b` (fractions of the picture) to fill the frame. */
function zoomStyle(b: Box): React.CSSProperties {
  const scale = 1 / (b.x1 - b.x0);
  return { transform: `scale(${scale}) translate(${-b.x0 * 100}%, ${-b.y0 * 100}%)`, transformOrigin: "0 0" };
}
