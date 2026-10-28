import { Box, Cpu, Download, Eye, FolderOpen, ListChecks, MessageSquare, Play, ScanSearch, ShieldCheck, Sparkles, X, Compass } from "lucide-react";
import { useEffect, type ReactNode } from "react";

/**
 * What Sightline is and does, for people who have never heard of BIM or design coordination: the start page in the
 * empty viewer (with the demo button) and the "How it works" dialog from the header.
 */
export function About({ start, onClose, triageOpen = false }: {
  // onGolden: one click opens the demo models, checks them, picks the duct-through-girder clash and proposes a fix.
  start?: { label: string; details: ReactNode; disabled: boolean; onStart: () => void; onTour?: () => void; onGolden?: () => void;
    onCell?: () => void; onCellTour?: () => void };  // the second demo: the palletising cell from STEP
  onClose?: () => void;
  triageOpen?: boolean;  // titles and triage run on the open-weights model now (server: /api/models)
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
          <h1>An AI design coordinator for 3D models</h1>
          <p className="lede">
            Before anything is built, every part of it is designed in 3D, by several teams at once. Sightline checks
            their models against each other, finds where they conflict, works out a fix, <b>proves the fix works</b>,
            and edits the model for you.
          </p>
          {start && <>
            <div className="about-cta">
              {start.onGolden && <button className="btn primary big" data-tour="golden" disabled={start.disabled} onClick={start.onGolden}>
                <Play size={16} aria-hidden /> Watch Sightline fix a clash</button>}
              <button className="btn big" data-tour="demo" disabled={start.disabled} onClick={start.onStart}>
                <FolderOpen size={16} aria-hidden /> {start.label}</button>
              {start.onTour && <button className="btn big" disabled={start.disabled} onClick={start.onTour}>
                <Compass size={16} aria-hidden /> Take the guided tour</button>}
            </div>
            <p className="hint about-loads">{start.details}</p>
          </>}
        </div>
        <BeforeAfter />
      </header>

      {start?.onCell && (
        <section className="about-second" aria-label="Second demo">
          <div>
            <p className="eyebrow">Second demo · from STEP</p>
            <h2>A machine cell, from its STEP file</h2>
            <p>Robot palletising cell PC-03: 144 parts, five planted problems. Sightline converts the STEP, checks it,
              moves what clashes, and gives you the STEP back with the fixes.</p>
          </div>
          <div className="about-second-cta">
            <button className="btn big" data-tour="cell" disabled={start.disabled} onClick={start.onCell}>
              <Cpu size={16} aria-hidden /> Open the machine cell</button>
            {start.onCellTour && <button className="btn big" disabled={start.disabled} onClick={start.onCellTour}>
              <Compass size={16} aria-hidden /> Take the cell tour</button>}
          </div>
        </section>
      )}

      {start && (
        <section className="about-layout" aria-label="Once the demo is open">
          <h2 className="about-h">Once it's open</h2>
          <ul className="next-steps">
            <li><ListChecks size={18} aria-hidden /><span><b>On the left</b>What Sightline found: every clash numbered and named, grouped by which models it checked.</span></li>
            <li><Box size={18} aria-hidden /><span><b>In the middle</b>The building in 3D, with its street and riverside.</span></li>
            <li><Sparkles size={18} aria-hidden /><span><b>On the right</b>Pick a clash, press <i>Propose fixes</i>, and watch Sightline work.</span></li>
          </ul>
        </section>
      )}

      <section className="about-stats" aria-label="Sightline on the demo, measured">
        <Stat value="~40 s" label="to a verified fix" note="From pressing Propose to an edit checked against all four models." />
        <Stat value="3 of 3" label="designer fixes matched" note="On the demo's three planted clashes, the first idea passes at the designer's own heights." />
        <Stat value="4 s" label="to check 1,732 elements" note="Every pair of the demo's three building models, and each against itself: 464 clashes." />
        <Stat value="464" label="clashes sorted in under 2 min" note={triageOpen ? "Read by an open-weights model; alike clashes once, so 39 calls."
          : "Measured on Muse Spark Open, the open-weights model; alike clashes are read once (39 calls)."} />
      </section>

      <section>
        <h2 className="about-h">What is design coordination?</h2>
        <p>
          A building is designed by several teams at once, and each one draws its own 3D model. <b>Design
          coordination</b> is making those models agree before anything is built. Put them together and things overlap:
          an air duct running straight through a steel beam, a pipe through a wall with no hole in it. Each overlap is a
          <b> clash</b>.
        </p>
        <div className="disciplines">
          <Discipline colour="#6b7f99" name="Structure" what="The frame that holds it up: columns, beams, floors, foundations." />
          <Discipline colour="#d0342c" name="Services (MEP)" what="Mechanical, electrical and plumbing: air ducts, pipes, cable trays, lights." />
          <Discipline colour="#3f8f6b" name="Architecture" what="What people see: walls, ceilings, doors, glazing, stairs." />
        </div>
        <p>
          A check finds them by the hundred. Most are harmless: parts that meet on purpose, like a bolt in its plate.
          A few are real, and each real one costs a meeting and a redesign. Missed, it costs rework on site, which is
          where clashes get expensive. The same goes for any design made in 3D by more than one team: a machine cell, a
          plant room, a ship.
        </p>
      </section>

      <section>
        <h2 className="about-h">What Sightline does</h2>
        <ol className="about-steps">
          <Step n={1} icon={<ScanSearch size={18} aria-hidden />} title="Checks the models and sorts what it finds">
            Sightline checks every pair of models and each model against itself, and numbers each clash.{" "}
            {triageOpen ? <><b>Muse Spark Open</b>, an open-weights model,</> : <b>Muse Spark</b>} names every one and gives
            it a verdict: a real problem, by design, or a modelling mistake. Alike clashes (forty bolts in forty plates) are
            read once.
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
            <dt>Design coordination</dt><dd>Making several teams' models agree before anything is built.</dd>
            <dt>Clash</dt><dd>One place where two parts of the models conflict. Each has a number, like #3.</dd>
            <dt>Check</dt><dd>One pair of things checked against each other: two models, or one model against itself.</dd>
            <dt>Clearance</dt><dd>Space left between two things once a clash is fixed. Sightline asks for at least 25 mm.</dd>
          </dl>
        </div>
      </section>

      <section className="about-try">
        <h2 className="about-h">Try it in a minute</h2>
        <ol>
          <li>{start ? <>Press <b>{start.label}</b> above.</> : <>Open the Northbank demo from the start page.</>}</li>
          <li>Sightline checks the models. In the list on the left, under <b>MEP vs Structure</b>, pick the supply air
            main running through the transfer girder, the big beam on Level 02.</li>
          <li>Press <b>Propose fixes</b> and watch Sightline try its ideas in the 3D view.</li>
        </ol>
        <p className="hint"><MessageSquare size={13} aria-hidden /> Or ask it in <b>Chat</b>, typed or spoken: “Which clashes are real problems?”
          · <ScanSearch size={13} aria-hidden /> <b>Triage all</b> sorts every clash the check found.</p>
      </section>

      <section className="built-with" aria-label="Built with">
        <span className="hint">Built with</span>
        <span className="tech"><b>Muse Spark</b> understands clashes and proposes fixes{triageOpen ? "" : ", names and sorts them"}</span>
        {triageOpen && <span className="tech"><b>Muse Spark Open</b> names and sorts every clash</span>}
        <span className="tech"><b>Muse Voice Transcribe</b> lets you talk to it</span>
        <span className="tech"><b>IfcOpenShell</b> finds the clashes, edits and checks the geometry</span>
        <span className="tech"><b>three.js</b> draws the 3D view</span>
        <span className="tech"><b>IFC</b> the open model format, in and out</span>
      </section>

      <p className="about-foot hint">
        Northbank is a fictional three-storey office with its street and riverside, modelled by IssueLab for demos: no
        real project data. Its models are built with three planted clashes that have a known answer. Sightline also
        imports Navisworks clash reports.
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
