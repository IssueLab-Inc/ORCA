import { ArrowDown, ArrowRight, Box, Check, RotateCcw, Cpu, Download, Eye, FolderOpen, ListChecks, MessageSquare, Play, ScanSearch, ShieldCheck, Sparkles, Upload, Compass } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";
import { useLayout } from "./layout";
import { loadClip } from "./stepClips";

/**
 * What ORCA is and does, for people who have never heard of BIM or design coordination: the start page in the
 * empty viewer (with the demo buttons). The longer story, in tabs, is About ORCA (AboutOrca.tsx).
 */
export function About({ start, onAbout, triageOpen = false }: {
  // onGolden: one click opens the demo models, checks them, picks the duct-through-girder clash and proposes a fix.
  start?: { label: string; details: ReactNode; disabled: boolean; onStart: () => void; onTour?: () => void; onGolden?: () => void;
    onCell?: () => void; onCellTour?: () => void;  // the second demo: the palletising cell from STEP
    onBlank?: () => void;  // a blank project: the visitor's own models
    resume?: Resume };  // this browser's last session, still on the server
  onAbout?: () => void;  // opens About ORCA (AboutOrca.tsx), the longer story in tabs
  triageOpen?: boolean;  // titles and triage run on the open-weights model now (server: /api/models)
}) {
  const layout = useLayout(), phone = layout === "phone";
  const body = (
    <article className="about">

      {start?.resume && <ResumeCard r={start.resume} disabled={start.disabled} />}

      <header className="about-hero">
        <div>
          <p className="eyebrow">ORCA · by IssueLab</p>
          <h1>An AI design coordinator for 3D models</h1>
          <p className="lede">
            Before anything is built, every part of it is designed in 3D, by several teams at once. ORCA checks
            their models against each other, finds where they conflict, works out a fix, <b>proves the fix works</b>,
            and edits the model for you.
          </p>
          <p className="orca-loop" aria-label="ORCA stands for Observe, Resolve, Check, Apply">
            <span><b>O</b>bserve</span><span><b>R</b>esolve</span><span><b>C</b>heck</span><span><b>A</b>pply</span>
          </p>
          {start && <>
            <div className="about-cta">
              {start.onGolden && <button className="btn primary big" data-tour="golden" disabled={start.disabled} onClick={start.onGolden}>
                <Play size={16} aria-hidden /> Watch ORCA fix a clash</button>}
              <a className="btn big" href="#demos"
                onClick={(e) => { e.preventDefault(); document.getElementById("demos")?.scrollIntoView({ behavior: "smooth", block: "start" }); }}>
                <ArrowDown size={16} aria-hidden /> Pick a demo</a>
              {start.onBlank && <button className="btn big ghost" data-tour="blank" onClick={start.onBlank}>
                <Upload size={16} aria-hidden /> Use your own models</button>}
            </div>
          </>}
        </div>
        <BeforeAfter />
      </header>

      {start && (
        <section className="about-demos-wrap" id="demos" aria-label="The demos">
          <h2 className="about-h">Pick a demo</h2>
          <div className={`about-demos${start.onCell ? "" : " one"}`}>
            <DemoCard clip="/demos/fix-northbank" eyebrow="Building · 4 IFC models" title="Northbank, a riverside office site"
              alt="ORCA fixing Northbank's clash #1, sped up: the camera flies from the whole site to the supply air duct running through the transfer girder while Muse Spark thinks. Its ideas are tried in the model, the duct raised 400 mm through the girder's web opening with square bends and with 45° ones, and the fix, clear by 50 mm, is shown before and after."
              blurb={<>Structure, building services, architecture and site, modelled by four teams. On Level 02 a transfer
                girder is hit by a duct, a cable tray and a water main.</>}
              shows={[<>Every pair of models checked: <b>464 clashes in 1,732 elements, in 4 s</b></>,
                <>Triage sorts the real problems from the noise</>,
                <>The duct raised through the girder's web opening, at the designer's own height</>,
                <>One root-cause plan for all three services</>]}
              chips={["~40 s to a verified fix", "3 of 3 designer fixes"]}
              note={start.details}>
              <button className="btn primary big" data-tour="demo" disabled={start.disabled} onClick={start.onStart}>
                <FolderOpen size={16} aria-hidden /> {start.label}</button>
              {start.onTour && <button className="btn big" disabled={start.disabled} onClick={start.onTour}>
                <Compass size={16} aria-hidden /> Take the guided tour</button>}
            </DemoCard>
            {start.onCell && (
              <DemoCard clip="/demos/fix-cell" eyebrow="Machine · 1 STEP file" title="PC-03, a robot palletising cell"
                alt="ORCA fixing the cell's clash #66, sped up: the camera flies to the compressed-air pipe running into the conveyor's side rail while Muse Spark thinks. Two of its ideas pass the check in the model, and the air line lowered 150 mm under both rails, clear by 53 mm, is shown before and after."
                blurb={<>A robot, a conveyor, safety guarding and services in a corner of the plant, from mechanical CAD.
                  Eight problems were planted in this revision.</>}
                shows={[<>The STEP converted: <b>161 parts</b> keep their names and colours, and Muse names what each is</>,
                  <>All <b>17 planted clashes</b> found, nothing unexpected</>,
                  <>The cable ladder moved, the air pipe dropped under both conveyor rails, a branch rerouted round two plant
                    columns, a rail trimmed, openings asked for in a wall and a panel's gland plate</>,
                  <>The STEP handed back with the fixes written in</>]}
                chips={["17 of 17 found", "STEP in, STEP out"]}
                note={<>Opens one STEP file and checks it, in a few seconds.</>}>
                <button className="btn primary big" data-tour="cell" disabled={start.disabled} onClick={start.onCell}>
                  <Cpu size={16} aria-hidden /> Open the machine cell</button>
                {start.onCellTour && <button className="btn big" disabled={start.disabled} onClick={start.onCellTour}>
                  <Compass size={16} aria-hidden /> Take the cell tour</button>}
              </DemoCard>
            )}
          </div>
        </section>
      )}

      {start && (
        <section className="about-layout" aria-label="Once the demo is open">
          <h2 className="about-h">Once it's open</h2>
          <ul className="next-steps">
            <li><ListChecks size={18} aria-hidden /><span><b>{phone ? "Clashes, below" : "On the left"}</b>What ORCA found: every clash numbered and named, grouped by which models it checked.</span></li>
            <li><Box size={18} aria-hidden /><span><b>{phone ? "On top" : "In the middle"}</b>The models in 3D: the building with its streets and river, or the cell.</span></li>
            <li><Sparkles size={18} aria-hidden /><span><b>{phone ? "Fix, below" : "On the right"}</b>Pick a clash, press <i>Propose fixes</i>, and watch ORCA work.</span></li>
          </ul>
        </section>
      )}

      <section aria-label="ORCA on the demo, measured">
        <h2 className="about-h">Measured on Northbank</h2>
        <div className="about-stats">
        <Stat value="~40 s" label="to a verified fix" note="From pressing Propose to an edit checked against all four models." />
        <Stat value="3 of 3" label="designer fixes matched" note="On the demo's three planted clashes, the first idea passes at the designer's own heights." />
        <Stat value="4 s" label="to check 1,732 elements" note="Every pair of the demo's three building models, and each against itself: 464 clashes." />
        <Stat value="464" label="clashes sorted in under 2 min" note={triageOpen ? "Read by an open-weights model; alike clashes once, so 39 calls."
          : "Measured on Muse Spark Open, the open-weights model; alike clashes are read once (39 calls)."} />
        </div>
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
        <h2 className="about-h">What ORCA does</h2>
        <StepsPlayer steps={[
          { icon: <ScanSearch size={18} aria-hidden />, title: "Checks the models and sorts what it finds",
            clip: { src: "/demos/check", caption: "Northbank's check, then its list: 464 clashes, numbered, being named.",
              alt: "Northbank's three building models checked: ORCA lists each pair of models and each model against itself while it checks 1,961 elements, then the list appears, 464 clashes numbered and grouped by check, the supply air main through the girder first at -300 mm, and they are being named." },
            body: <>
              ORCA checks every pair of models and each model against itself, and numbers each clash.{" "}
              {triageOpen ? <><b>Muse Spark Open</b>, an open-weights model,</> : <b>Muse Spark</b>} names every one and gives
              it a verdict: a real problem, by design, or a modelling mistake. Alike clashes (forty bolts in forty plates) are
              read once.
            </> },
          { icon: <Eye size={18} aria-hidden />, title: "Understands a clash",
            clip: { src: "/demos/understand", caption: "Muse Spark on #1, sped up: the three pictures, its reasoning as it thinks, what it understood.",
              alt: "The Clash panel for Northbank's #1 while Muse Spark works, sped up: the three pictures of the duct through the girder, then its reasoning as it thinks, then its understanding: the duct crosses the 1000 deep girder with 300 mm overlap, cannot shift as a whole without pulling apart its tees, and the girder has an opening on this line it can use." },
            body: <>
              <b>Muse Spark</b> looks at three pictures of the clash and reads the model's own data: what each element is,
              which way it runs, where the openings are. You can follow its reasoning as it thinks.
            </> },
          { icon: <ShieldCheck size={18} aria-hidden />, title: "Proposes fixes, and checks every one",
            clip: { src: "/demos/workings", caption: <><b>Workings</b>, the same run: your request, Muse Spark's ideas, ORCA's checks, the rank. Every run draws its own in <b>Activity</b>.</>,
              alt: "Workings replaying Northbank's run, sped up: one lane each for you, Muse Spark and ORCA. Your request and ORCA's brief go to Muse Spark, whose round replies with two ideas; ORCA checks the first in the model's geometry and it is verified, so ORCA stops there, ranks it and leaves one verified option, then kept." },
            body: <>
              It suggests real edits: raising a duct through an opening in a beam, or trimming a member back where it runs into another. A geometry engine then tests each
              one in the actual model: the clash is gone, there is room to spare, and nothing new is hit. Ideas that fail
              go back with the reason. <b>You only see fixes that passed.</b>
            </> },
          { icon: <Download size={18} aria-hidden />, title: "You review and export",
            clip: { src: "/demos/keep", caption: "Accept: the server tries the fix again, edits the model and checks it.",
              alt: "Northbank's #1 after the fix, Before and After: overlap -300 mm, then clear by 50 mm. Accept is pressed: Applying the fix, then Fix kept in the model, checked again, and Export IFC counts one edit to download." },
            body: <>
              Watch it try ideas live in the 3D view, compare before and after, accept the fix, and download the edited
              model as an IFC file that any design tool can open.
            </> },
        ]} />
      </section>

      {onAbout && (
        <button className="about-more" onClick={onAbout}>
          <span><b>Go deeper: About ORCA</b>How a fix is found and checked, all seven kinds of fix, the five models and what they are
            trusted with, how it is built, and what it has proven.</span>
          <ArrowRight size={20} aria-hidden />
        </button>
      )}

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
            <li><i style={{ background: "#2563eb" }} />What an element is joined to: hold Alt (Option on a Mac) and point at it, or
              turn on Connections. Shift shows its whole run.</li>
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
            <dt>Clearance</dt><dd>Space left between two things once a clash is fixed. ORCA asks for at least 25 mm.</dd>
          </dl>
        </div>
      </section>

      <section className="about-try">
        <h2 className="about-h">Try it in a minute</h2>
        <ol>
          <li>{start ? <>Press <b>{start.label}</b> above.</> : <>Open the Northbank demo from the start page.</>}</li>
          <li>ORCA checks the models. In the {layout === "desktop" ? "list on the left" : <b>Clashes</b>}{layout === "desktop" ? "" : " list"}, under <b>MEP vs Structure</b>, pick the supply air
            main running through the transfer girder, the big beam on Level 02.</li>
          <li>Press <b>Propose fixes</b> and watch ORCA try its ideas in the 3D view.</li>
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
        real project data. Its models are built with three planted clashes that have a known answer. ORCA also
        imports Navisworks clash reports.
        Fixes are limited to 20 per visitor an hour.
      </p>
    </article>
  );

  return <div className="about-page" onClick={(e) => e.stopPropagation()}>{body}</div>;
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

/** One step of "What ORCA does" and the recorded run that shows it (web/public/demos/<src>.webp and <src>-still.webp). */
interface StepItem { icon: ReactNode; title: string; body: ReactNode; clip: { src: string; alt: string; caption: ReactNode } }

/** "What ORCA does": the steps as tabs beside one frame that plays the chosen step's recorded run. It moves on when a
 * clip has played through (its length read from the file, `stepClips.ts`), until the visitor picks a step. Nothing is
 * fetched before the section scrolls into view, then only the clip on screen and the next; each plays from a fresh
 * object URL of its bytes, so it starts from its first frame every time its step comes round. Less motion: each clip's
 * last frame, and no moving on. */
function StepsPlayer({ steps }: { steps: StepItem[] }) {
  const [active, setActive] = useState(0);
  const [auto, setAuto] = useState(true);      // moving on by itself, until the visitor picks a step
  const [seen, setSeen] = useState(false);     // scrolled into view
  const [playing, setPlaying] = useState<{ src: string; url: string; ms: number | null } | null>(null);
  const [started, setStarted] = useState(false);   // the playing clip has loaded: its time runs
  const reduce = useReducedMotion();
  const box = useRef<HTMLDivElement>(null);
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);
  const step = steps[active];
  // The effects follow the clips' paths, not the list: About draws a new list on every render.
  const src = step.clip.src, next = steps[(active + 1) % steps.length].clip.src, count = steps.length;

  useEffect(() => {
    const el = box.current;
    if (!el || seen) return;
    if (typeof IntersectionObserver === "undefined") { setSeen(true); return; }
    const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) setSeen(true); }, { threshold: 0.3 });
    io.observe(el);
    return () => io.disconnect();
  }, [seen]);

  useEffect(() => {
    if (!seen || reduce) return;
    let live = true, url: string | null = null;
    setStarted(false);
    void loadClip(`${src}.webp`).then((c) => {
      if (!live) return;
      url = c ? URL.createObjectURL(c.blob) : null;
      setPlaying({ src, url: url ?? `${src}.webp`, ms: c?.ms ?? null });
      void loadClip(`${next}.webp`);
    });
    return () => {
      live = false;
      if (url) { const done = url; window.setTimeout(() => URL.revokeObjectURL(done), 1000); }   // once the next one shows
    };
  }, [seen, reduce, src, next]);

  useEffect(() => {
    if (!auto || reduce || !started || !playing?.ms || playing.src !== src) return;
    const t = window.setTimeout(() => setActive((i) => (i + 1) % count), playing.ms);
    return () => window.clearTimeout(t);
  }, [auto, reduce, started, playing, src, count]);

  const pick = (i: number, focus = false) => { setAuto(false); setActive(i); if (focus) tabs.current[i]?.focus(); };
  const onKey = (e: ReactKeyboardEvent) => {
    const d = ["ArrowDown", "ArrowRight"].includes(e.key) ? 1 : ["ArrowUp", "ArrowLeft"].includes(e.key) ? -1 : 0;
    if (!d) return;
    e.preventDefault();
    pick((active + d + count) % count, true);
  };
  const live = !reduce && playing?.src === src ? playing : null;
  return (
    <div className="steps-player" ref={box}>
      <div className="steps-tabs" role="tablist" aria-label="What ORCA does, step by step" aria-orientation="vertical" onKeyDown={onKey}>
        {steps.map((s, i) => {
          const on = i === active;
          return (
            <div key={s.title} className={`steps-item${on ? " on" : ""}`}>
              <button type="button" role="tab" id={`steps-tab-${i}`} aria-selected={on} aria-controls="steps-panel"
                tabIndex={on ? 0 : -1} ref={(el) => { tabs.current[i] = el; }} onClick={() => pick(i)}>
                <span className="step-icon" aria-hidden>{s.icon}<span>{i + 1}</span></span>
                <b>{s.title}</b>
              </button>
              {on && <p className="steps-body">{s.body}</p>}
              {on && auto && live?.ms && started &&
                <span className="steps-progress" aria-hidden><i key={live.url} style={{ animationDuration: `${live.ms}ms` }} /></span>}
            </div>
          );
        })}
      </div>
      <figure className="steps-frame" role="tabpanel" id="steps-panel" aria-labelledby={`steps-tab-${active}`}>
        <div className="steps-screen">
          {live
            ? <img key={live.url} src={live.url} alt={step.clip.alt} onLoad={() => setStarted(true)} />
            : <img key={step.clip.src} src={`${step.clip.src}-still.webp`} alt={step.clip.alt} loading="lazy" decoding="async" />}
        </div>
        <figcaption className="hint">{step.clip.caption}</figcaption>
      </figure>
    </div>
  );
}

/** The visitor asks for less motion (and changes their mind while the page is open). */
function useReducedMotion(): boolean {
  const query = "(prefers-reduced-motion: reduce)";
  const [reduce, setReduce] = useState(() => typeof window !== "undefined" && !!window.matchMedia?.(query).matches);
  useEffect(() => {
    const q = window.matchMedia?.(query);
    if (!q) return;
    const on = () => setReduce(q.matches);
    q.addEventListener("change", on);
    return () => q.removeEventListener("change", on);
  }, []);
  return reduce;
}

/** Side view of the demo's clash: the girder in section (an I with a gap in its web where the opening is), the duct
 * running through the solid web, then raised through the opening with square risers, as ORCA's offset does. */
/** A session this browser had open, which the server still holds: reopen it (models, clashes, fixes, agent link). */
export interface Resume {
  files: string[]; clashes: number | null; fixed: number; agent: boolean; agentLeft?: string | null; savedAt: number;
  onResume: () => void; onFresh: () => void;
}

/** The project a set of model files belongs to: their shared prefix ("Northbank-MEP", "Northbank-Site" → "Northbank"),
 * else the first file and how many more. */
export function projectName(files: string[]): string {
  const names = files.map((f) => f.replace(/\.(ifc|step|stp)$/i, ""));
  if (names.length <= 1) return names[0] ?? "Your models";
  let prefix = names[0];
  for (const n of names.slice(1)) while (!n.startsWith(prefix)) prefix = prefix.slice(0, -1);
  const cut = prefix.match(/^(.*[A-Za-z0-9])[\s_.-]/)?.[1] ?? (names.every((n) => n === prefix) ? prefix : "");
  return cut.length >= 3 ? cut : `${names[0]} + ${names.length - 1} more`;
}

function ResumeCard({ r, disabled }: { r: Resume; disabled: boolean }) {
  const mins = Math.max(1, Math.round((Date.now() / 1000 - r.savedAt) / 60));
  const when = mins < 60 ? `${mins} min ago` : mins < 1440 ? `${Math.round(mins / 60)} h ago` : "yesterday";
  return (
    <div className="resume-card" role="region" aria-label="Your last session">
      <span className="resume-icon" aria-hidden><RotateCcw size={18} /></span>
      <div className="resume-text">
        <p className="eyebrow">Pick up where you left off</p>
        <h2 data-tip-tap data-tip={r.files.join(", ")} data-tip-side="bottom">{projectName(r.files)}</h2>
        <div className="resume-meta">
          <span className="chip">{r.files.length} model{r.files.length === 1 ? "" : "s"}</span>
          {r.clashes != null && <span className="chip">{r.clashes} clashes</span>}
          {r.fixed > 0 && <span className="chip ok">{r.fixed} fixed</span>}
          {r.agent && <span className="chip ok">Agent connected{r.agentLeft ? ` · ${r.agentLeft} left` : ""}</span>}
          <span className="hint">{when}</span>
        </div>
      </div>
      <div className="resume-actions">
        <button className="btn primary big" disabled={disabled} onClick={r.onResume}>Resume</button>
        <button className="btn ghost big" onClick={r.onFresh}
          data-tip={r.agent ? "Forget this session here and end its agent link" : "Forget this session here"}>Start fresh</button>
      </div>
    </div>
  );
}

/** A recorded run of ORCA, as a picture that plays itself: `<src>.webp`, an animated WebP time-lapse (no controls, no
 * sound, it loops), made by web/scripts/capture-proposals.cjs --landing. People who ask for less motion get
 * `<src>-still.webp`, its last frame, instead. */
function Clip({ src, alt, width, height }: { src: string; alt: string; width: number; height: number }) {
  return (
    <picture>
      <source media="(prefers-reduced-motion: reduce)" srcSet={`${src}-still.webp`} />
      <img src={`${src}.webp`} alt={alt} width={width} height={height} loading="lazy" decoding="async" />
    </picture>
  );
}

/** One demo on the start page: a fix being found in it, what it is, what it shows, and how to start it. */
function DemoCard({ clip, alt, eyebrow, title, blurb, shows, chips, note, children }: {
  clip: string; alt: string; eyebrow: string; title: string; blurb: ReactNode; shows: ReactNode[]; chips: string[];
  note?: ReactNode; children: ReactNode;
}) {
  return (
    <article className="demo-card">
      <Clip src={clip} alt={alt} width={1000} height={625} />
      <div className="demo-body">
        <p className="eyebrow">{eyebrow}</p>
        <h3>{title}</h3>
        <p className="demo-blurb">{blurb}</p>
        <ul className="demo-shows" aria-label="What it shows">
          {shows.map((x, i) => <li key={i}><Check size={14} aria-hidden /><span>{x}</span></li>)}
        </ul>
        <div className="chips demo-chips">{chips.map((c) => <span key={c} className="chip accent">{c}</span>)}</div>
        <div className="demo-foot">
          {note && <p className="hint demo-note">{note}</p>}
          <div className="demo-actions">{children}</div>
        </div>
      </div>
    </article>
  );
}

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
        <title id="ba-title">Before: an air duct runs through the solid web of a steel beam. After: ORCA raises that
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
