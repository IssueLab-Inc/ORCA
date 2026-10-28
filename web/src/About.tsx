import { Box, Download, Eye, FolderOpen, ListChecks, MessageSquare, ScanSearch, ShieldCheck, Sparkles, X, Compass } from "lucide-react";
import { useEffect, type ReactNode } from "react";

/**
 * What Sightline is and does, for people who have never heard of BIM or clash detection: the start page in the
 * empty viewer (with the demo button) and the "How it works" dialog from the header.
 */
export function About({ start, onClose }: {
  start?: { label: string; details: ReactNode; disabled: boolean; onStart: () => void; onTour?: () => void };
  onClose?: () => void;
}) {
  useEffect(() => {
    if (!onClose) return;
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);

  const body = (
    <article className="about">
      {onClose && <button className="ibtn about-close" onClick={onClose} aria-label="Close"><X size={18} aria-hidden /></button>}

      <header className="about-hero">
        <div>
          <p className="eyebrow">ClashWise Sightline</p>
          <h1>An AI agent that fixes clashes in 3D building models</h1>
          <p className="lede">
            Before a building goes up, every part of it is designed in 3D. Sightline finds the places where those parts
            run into each other, works out a fix, <b>proves the fix works</b>, and edits the model for you.
          </p>
          {start && <>
            <div className="about-cta">
              <button className="btn primary big" data-tour="demo" disabled={start.disabled} onClick={start.onStart}>
                <FolderOpen size={16} aria-hidden /> {start.label}</button>
              {start.onTour && <button className="btn big" disabled={start.disabled} onClick={start.onTour}>
                <Compass size={16} aria-hidden /> Take the guided tour</button>}
            </div>
            <p className="hint about-loads">{start.details}</p>
          </>}
        </div>
        <BeforeAfter />
      </header>

      {start && (
        <section className="about-layout" aria-label="Once the demo is open">
          <h2 className="about-h">Once it's open</h2>
          <ul className="next-steps">
            <li><ListChecks size={18} aria-hidden /><span><b>On the left</b>The clash list, grouped by test, with a picture of each clash.</span></li>
            <li><Box size={18} aria-hidden /><span><b>In the middle</b>The building in 3D, with its street and riverside.</span></li>
            <li><Sparkles size={18} aria-hidden /><span><b>On the right</b>Pick a clash, press <i>Propose fixes</i>, and watch Sightline work.</span></li>
          </ul>
        </section>
      )}

      <section className="about-stats" aria-label="Sightline on the demo, measured">
        <Stat value="15–25 s" label="to a verified fix" note="From pressing Propose to an edit checked against all four models." />
        <Stat value="3 of 3" label="designer fixes matched" note="On the demo's three planted clashes, the first idea passes at the designer's own heights." />
        <Stat value="217" label="clashes sorted in 3–4 min" note="The whole demo report triaged; 99 settled by rule, the rest by an open-weights model." />
        <Stat value="Every" label="fix checked before you see it" note="Clash gone, 25 mm to spare, nothing new hit." />
      </section>

      <section>
        <h2 className="about-h">What is a clash?</h2>
        <p>
          A building is designed by several teams at once, and each one draws its own 3D model. When the models are put
          together, things overlap: an air duct running straight through a steel beam, a pipe through a wall with no
          hole in it. Each overlap is a <b>clash</b>.
        </p>
        <div className="disciplines">
          <Discipline colour="#6b7f99" name="Structure" what="The frame that holds it up: columns, beams, floors, foundations." />
          <Discipline colour="#d0342c" name="Services (MEP)" what="Mechanical, electrical and plumbing: air ducts, pipes, cable trays, lights." />
          <Discipline colour="#3f8f6b" name="Architecture" what="What people see: walls, ceilings, doors, glazing, stairs." />
        </div>
        <p>
          Clash detection software finds them by the hundred. Most are harmless (parts that only touch, or meet on
          purpose, like a bolt in a plate). A few are real, and each real one costs a meeting and a redesign. Missed, it
          costs rework on site, which is where clashes get expensive.
        </p>
      </section>

      <section>
        <h2 className="about-h">What Sightline does</h2>
        <ol className="about-steps">
          <Step n={1} icon={<ScanSearch size={18} aria-hidden />} title="Sorts the whole report">
            Every clash gets a verdict: a real problem, by design, not a physical object, or a modelling mistake. Sure
            cases are settled by rule; the rest go to <b>Muse Spark Open</b>, an open-weights model, many at a time.
          </Step>
          <Step n={2} icon={<Eye size={18} aria-hidden />} title="Understands a clash">
            <b>Muse Spark</b> looks at three pictures of the clash and reads the model's own data: what each element is,
            which way it runs, where the openings are. You can follow its reasoning as it thinks.
          </Step>
          <Step n={3} icon={<ShieldCheck size={18} aria-hidden />} title="Proposes fixes, and checks every one">
            It suggests real edits: raising a duct through an opening in a beam, or trimming a member back where it runs into another. A geometry engine then tests each
            one in the actual model: the clash is gone, there is room to spare, and nothing new is hit. Ideas that fail
            go back with the reason. <b>You only see fixes that passed.</b>
          </Step>
          <Step n={4} icon={<Download size={18} aria-hidden />} title="You review and export">
            Watch it try ideas live in the 3D view, compare before and after, accept the fix, and download the edited
            model as an IFC file that any design tool can open.
          </Step>
        </ol>
      </section>

      <section className="about-two">
        <div>
          <h2 className="about-h">Reading the 3D view</h2>
          <ul className="legend">
            <li><i style={{ background: "#d0342c" }} />Element A of the clash</li>
            <li><i style={{ background: "#1f9d3a" }} />Element B, the one it runs into</li>
            <li><i style={{ background: "#8e44ad" }} />One element on both sides (a part of itself)</li>
            <li><i style={{ background: "#f5a623" }} />An idea being tested right now</li>
            <li><i style={{ background: "#12b5cb" }} />An idea that passed the check</li>
            <li><i style={{ background: "#e040fb" }} />What a failed idea ran into</li>
            <li><i style={{ background: "#e67e22", opacity: 0.55 }} />The element as it was, before the fix</li>
          </ul>
        </div>
        <div>
          <h2 className="about-h">Words you'll see</h2>
          <dl className="glossary">
            <dt>BIM</dt><dd>Building Information Modelling: a 3D model where every object knows what it is.</dd>
            <dt>IFC</dt><dd>The open file format for those models, readable by any tool.</dd>
            <dt>Navisworks</dt><dd>Widely used software that finds clashes and exports them as a report.</dd>
            <dt>Clash test</dt><dd>One pair of things checked against each other, like ducts against beams.</dd>
            <dt>Clearance</dt><dd>Space left between two things once a clash is fixed. Sightline asks for at least 25 mm.</dd>
          </dl>
        </div>
      </section>

      <section className="about-try">
        <h2 className="about-h">Try it in a minute</h2>
        <ol>
          <li>{start ? <>Press <b>{start.label}</b> above.</> : <>Open the Northbank demo from the start page.</>}</li>
          <li>In the list on the left, open <b>IfcDuctSegment (MEP) vs IfcProject (Structure)</b> and pick <b>Clash1</b>:
            a supply air duct running through the transfer girder, the big beam on Level 02.</li>
          <li>Press <b>Propose fixes</b> and watch Sightline try its ideas in the 3D view.</li>
        </ol>
        <p className="hint"><MessageSquare size={13} aria-hidden /> Or ask it in <b>Chat</b>, typed or spoken: “Which clashes are real problems?”
          · <ScanSearch size={13} aria-hidden /> <b>Triage all</b> sorts all 217 clashes in three to four minutes.</p>
      </section>

      <section className="built-with" aria-label="Built with">
        <span className="hint">Built with</span>
        <span className="tech"><b>Muse Spark</b> understands clashes and proposes fixes</span>
        <span className="tech"><b>Muse Spark Open</b> sorts whole reports</span>
        <span className="tech"><b>Muse Voice Transcribe</b> lets you talk to it</span>
        <span className="tech"><b>IfcOpenShell</b> edits and checks the geometry</span>
        <span className="tech"><b>three.js</b> draws the 3D view</span>
        <span className="tech"><b>IFC</b> the open model format, in and out</span>
      </section>

      <p className="about-foot hint">
        Northbank is a fictional three-storey office with its street and riverside, modelled by IssueLab for demos: no
        real project data. Its models and clash report are built with three planted clashes that have a known answer.
        Fixes are limited to 20 per visitor an hour.
      </p>
    </article>
  );

  if (!onClose) return <div className="about-page" onClick={(e) => e.stopPropagation()}>{body}</div>;
  return (
    <div className="about-dialog" role="dialog" aria-modal="true" aria-label="How Sightline works" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()}>{body}</div>
    </div>
  );
}

function Stat({ value, label, note }: { value: string; label: string; note: string }) {
  return (
    <div className="stat-tile">
      <b>{value}</b>
      <span className="stat-label">{label}</span>
      <span className="stat-note">{note}</span>
    </div>
  );
}

function Discipline({ colour, name, what }: { colour: string; name: string; what: string }) {
  return (
    <div className="discipline" style={{ borderTopColor: colour }}>
      <b>{name}</b>
      <span>{what}</span>
    </div>
  );
}

function Step({ n, icon, title, children }: { n: number; icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <li className="step">
      <div className="step-icon" aria-hidden>{icon}<span>{n}</span></div>
      <div><h3>{title}</h3><p>{children}</p></div>
    </li>
  );
}

/** Side view of the demo's clash: the girder in section (an I with a gap in its web where the opening is), the duct
 * running through the solid web, then raised through the opening with square risers, as Sightline's offset does. */
function BeforeAfter() {
  const girder = (cx: number, label = false) => (
    <g fill="#1f9d3a">
      <rect x={cx - 27} y={18} width={54} height={9} rx={1.5} />
      <rect x={cx - 27} y={133} width={54} height={9} rx={1.5} />
      <rect x={cx - 4} y={27} width={8} height={15} />
      <rect x={cx - 4} y={76} width={8} height={57} />
      {label && <text x={cx + 8} y={63} className="ba-tag">← opening</text>}
    </g>
  );
  return (
    <figure className="before-after">
      <svg viewBox="0 0 400 190" role="img" aria-labelledby="ba-title">
        <title id="ba-title">Before: an air duct runs through the solid web of a steel beam. After: Sightline raises that
          part of the duct through the opening in the beam, with room to spare.</title>
        <text x={100} y={11} textAnchor="middle" className="ba-label">Before</text>
        <rect x={8} y={92} width={184} height={26} rx={2} fill="#d0342c" />
        {girder(100, true)}
        <rect x={91} y={88} width={18} height={34} fill="url(#ba-hatch)" stroke="#f5a623" strokeWidth={2} rx={2} />
        <text x={100} y={168} textAnchor="middle" className="ba-note bad-note">the duct runs into the beam</text>

        <path d="M199 105 h12" stroke="var(--muted)" strokeWidth={2} markerEnd="url(#ba-arrow)" />

        <text x={306} y={11} textAnchor="middle" className="ba-label">After</text>
        <rect x={218} y={92} width={176} height={26} rx={2} fill="#e67e22" opacity={0.28} />
        <path d="M218 105 H244 Q264 105 264 85 V79 Q264 59 284 59 H328 Q348 59 348 79 V85 Q348 105 368 105 H394"
          fill="none" stroke="#12b5cb" strokeWidth={26} />
        {girder(306)}
        <text x={306} y={168} textAnchor="middle" className="ba-note ok-note">raised through the opening</text>
        <defs>
          <pattern id="ba-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="6" height="6" fill="#f5a623" opacity={0.35} />
            <line x1="0" y1="0" x2="0" y2="6" stroke="#f5a623" strokeWidth="3" />
          </pattern>
          <marker id="ba-arrow" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="5" markerHeight="5" orient="auto">
            <path d="M0 0 L10 5 L0 10 z" fill="var(--muted)" />
          </marker>
        </defs>
      </svg>
      <figcaption className="hint">The demo's clash, seen from the side. Orange: where the duct used to run.</figcaption>
    </figure>
  );
}
