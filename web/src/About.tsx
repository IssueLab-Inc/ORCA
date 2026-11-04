import {
  Activity, ArrowRight, Bot, Check, ClipboardCheck, Compass, Cpu, FileSpreadsheet, FileText, FolderOpen, Image, Layers,
  ListFilter, Mic, PenTool, Play, RotateCcw, ShieldCheck, Smartphone, Sparkles, Target, TriangleAlert, Upload, Users, Wand2,
} from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Wordmark } from "./Brand";
import { useLayout } from "./layout";
import { Hero } from "./landing/Hero";
import { Collide, Loop, type LoopStep } from "./landing/Story";
import { Sandbox } from "./landing/Sandbox";
import { ArtCombined, ArtMove, ArtOffset, ArtOpening, ArtResize, ArtRoute, ArtSeat, ArtTrim } from "./landing/FixArt";
import { BuiltArt, ChatArt, EditArt, FilesArt, LanesArt, McpArt, PhoneArt, ReqArt, RootArt, Tile, TriageArt, ViewsArt } from "./landing/Bento";
import { useCountUp, useReducedMotion, useReveal, useSeen, useSpy } from "./landing/motion";
import "./landing/landing.css";

/**
 * The source of the industry figure beside "rework on site" (here and in About ORCA): "the measured direct costs of
 * avoidable errors are in the order of 5% of project value", "10% and 25% of project cost" with unmeasured and
 * indirect costs. Not ORCA's own measurement: an industry number, quoted as the source states it.
 */
export const GIRI_STRATEGY = "https://getitright.uk.com/reports/strategy-for-change";

/** The repository: public, the hackathon's rule. */
const REPO = "https://github.com/IssueLab-Inc/ORCA";

/**
 * The start page in the empty viewer: what ORCA is and can do, end to end, for people who have never heard of design
 * coordination, with the ways in (the golden path, the two demos and their tours, your own models). Its sections: the
 * hero's live replay of the loop on Northbank's own geometry (landing/Hero.tsx), the problem, the loop beside the
 * real app's recordings (landing/Story.tsx), the check to try by hand (landing/Sandbox.tsx), the kinds of fix, the
 * rule the AI works under, everything around the fix, the demos, who it is for, what it has proven and what it has
 * not. Its numbers are the measured ones the README and About ORCA use (CLAUDE.md, "Numbers people see are measured").
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
  const layout = useLayout(), desktop = layout === "desktop";
  const reduce = useReducedMotion();
  const page = useRef<HTMLDivElement>(null);
  const [solid, setSolid] = useState(false);
  useReveal(page, reduce);
  const spied = useSpy(page, ["problem", "how", "try", "fixes", "ai", "platform", "demos", "who", "proof"]);
  // the header's link for the section in view (the problem counts as how it works; the AI's rule as the fixes')
  const current = spied === "problem" ? "how" : spied === "ai" ? "fixes" : spied === "who" ? "demos" : spied;

  useEffect(() => {
    const el = page.current;
    if (!el) return;
    const on = () => setSolid(el.scrollTop > 24);
    on();
    el.addEventListener("scroll", on, { passive: true });
    return () => el.removeEventListener("scroll", on);
  }, []);

  const to = (id: string) => page.current?.querySelector(`#${id}`)?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
  const link = (id: string, text: string) => (
    <a href={`#${id}`} className={current === id ? "on" : undefined} aria-current={current === id ? "true" : undefined}
      onClick={(e) => { e.preventDefault(); to(id); }}>{text}</a>
  );

  return (
    <div className={`lp-page${reduce ? " still" : ""}`} ref={page} onClick={(e) => e.stopPropagation()}>
      {desktop && (
        <header className={`lp-nav${solid ? " solid" : ""}`}>
          <a className="lp-brand" href="#top" aria-label="ORCA, back to the top"
            onClick={(e) => { e.preventDefault(); page.current?.scrollTo({ top: 0, behavior: reduce ? "auto" : "smooth" }); }}>
            <Wordmark height={20} /><span>by IssueLab</span></a>
          <nav aria-label="On this page">
            {link("how", "How it works")}{link("try", "Try the check")}{link("fixes", "Fixes")}{link("platform", "Platform")}
            {start && link("demos", "Demos")}{link("proof", "Proof")}
          </nav>
        </header>
      )}

      <Hero reduce={reduce}
        actions={{ disabled: !!start?.disabled, onGolden: start?.onGolden, onBlank: start?.onBlank, onDemos: () => to(start ? "demos" : "how") }}
        resume={start?.resume ? <ResumeCard r={start.resume} disabled={start.disabled} /> : undefined} />

      <section className="lp-sec lp-problem" id="problem" aria-labelledby="lp-problem-h">
        <div className="lp-wrap lp-split">
          <div className="lp-reveal">
            <p className="lp-kicker">The problem</p>
            <h2 id="lp-problem-h">Every team's design is right on its own. Together, they collide.</h2>
            <p className="lp-body">
              Before anything is built, it is designed in 3D by several teams at once: structure, building services and
              architecture on a building; mechanical, electrical and safety on a machine. Put their models together and
              parts land in the same space, or too close to leave room to build. The industry calls each one a <b>clash</b>.
            </p>
            <p className="lp-body">
              A check finds them by the hundred. Most are harmless, parts that meet on purpose, like a bolt in its plate.
              A few are real, and each costs a meeting and a redesign. Missed, it costs rework on site: avoidable errors
              like these cost about 5% of a project's value directly, and an estimated 10 to 25% once indirect costs are
              counted (<a className="src" href={GIRI_STRATEGY} target="_blank" rel="noopener noreferrer">Get It Right
              Initiative</a>).
            </p>
            <p className="lp-pull">Clash tools stop at the list. ORCA does the redrawing too, and proves it worked.</p>
          </div>
          <div className="lp-problem-art lp-reveal">
            <Collide reduce={reduce} />
            <ul className="lp-dis" aria-label="The teams' models">
              <li className="str"><i />Structure<span>the frame that holds it up</span></li>
              <li className="mep"><i />Services (MEP)<span>air, water, power</span></li>
              <li className="arch"><i />Architecture<span>walls, doors, ceilings</span></li>
              <li className="hit"><i />Clash<span>where they meet</span></li>
            </ul>
          </div>
        </div>
        <div className="lp-wrap lp-facts lp-reveal">
          <Fact value={464} reduce={reduce} label="clashes in about 4 s" note="One check of Northbank's three building models: every pair, and each against itself." />
          <Fact value={1732} reduce={reduce} label="elements checked" note="Structure, services and architecture, with what meets on purpose left out (a door in its wall)." />
          <Fact value={3} reduce={reduce} label="planted on one girder" note="The answer key ORCA is measured on: a duct, a cable tray and a water main through the Level 02 girder." />
        </div>
      </section>

      <section className="lp-sec lp-how" id="how" aria-labelledby="lp-how-h">
        <div className="lp-wrap">
          <Head id="lp-how-h" kicker="How it works" title={<>Observe. Resolve. Check. <span className="lp-teal">Apply.</span></>}>
            One loop, from a pile of clashes to an edited model you can hand back. Each step plays a recording of the real
            app working on Northbank, sped up.
          </Head>
          <Loop steps={LOOP_STEPS} reduce={reduce} />
        </div>
      </section>

      <section className="lp-sec lp-try" id="try" data-tone="dark" aria-labelledby="lp-try-h">
        <div className="lp-wrap">
          <Head id="lp-try-h" kicker="Try the check yourself" title="A fix isn't a fix until geometry says so.">
            This is Northbank's clash #1, seen along the duct where it meets the girder, drawn from the models. Move the
            duct and the check answers the way ORCA's does: is the clash gone, is anything new hit, is there room to spare?
          </Head>
          <div className="lp-reveal"><Sandbox reduce={reduce} /></div>
          <p className="lp-fine lp-reveal">
            A simplified, two-dimensional version of the check, exact for this straight-up move: the girder's 20 mm web and
            its openings, its flanges, the slab above, the ceiling below and the services beside it, as the models have
            them. ORCA's own check measures the whole edited model in 3D, against every open model.
          </p>
        </div>
      </section>

      <section className="lp-sec lp-fixes" id="fixes" aria-labelledby="lp-fixes-h">
        <div className="lp-wrap">
          <Head id="lp-fixes-h" kicker="Real edits, not notes" title="Seven kinds of fix, and fixes that combine them">
            Every option changes real IFC elements: new pieces, bends and fittings, ports joined back up, the original's
            id kept on its first piece. Ranked plain geometry first, then resizing, then asking for an opening.
          </Head>
          <div className="lp-fix-grid">
            {FIXES.map((f, i) => (
              <article key={f.kind} className="lp-fix lp-reveal" style={{ ["--d" as string]: `${(i % 4) * -1.4}s`, transitionDelay: `${(i % 4) * 70}ms` }}>
                <div className="lp-fix-art">{f.art}<span className="lp-fix-state" aria-hidden><b>before</b><b>after</b></span></div>
                <h3>{f.kind}</h3>
                <p>{f.what}</p>
                <p className="lp-fix-eg"><Sparkles size={13} aria-hidden /> {f.eg}</p>
                <p className="lp-fix-who"><ShieldCheck size={13} aria-hidden /> {f.who}</p>
              </article>
            ))}
          </div>
          <div className="lp-verified lp-reveal">
            <p className="lp-kicker">What “verified” means</p>
            <ul>
              <li><Target size={18} aria-hidden /><span><b>The clash is gone</b>measured again in the edited model</span></li>
              <li><ShieldCheck size={18} aria-hidden /><span><b>Clearance is kept</b>25 mm, or what your requirements ask</span></li>
              <li><Layers size={18} aria-hidden /><span><b>Nothing new is hit</b>every open model, every new piece</span></li>
              <li><Check size={18} aria-hidden /><span><b>Support is kept</b>what it stands on stays under it</span></li>
            </ul>
          </div>
        </div>
      </section>

      <section className="lp-sec lp-ai" id="ai" data-tone="dark" aria-labelledby="lp-ai-h">
        <div className="lp-wrap">
          <Head id="lp-ai-h" kicker="The rule ORCA is built on" title="The model proposes. Geometry decides." center>
            No model output is ever trusted to accept a fix or set a clearance number: only the server's geometry supplies
            those. Muse does what geometry can't: read a clash in context, think of the right edit, explain it in plain words.
          </Head>
          <div className="lp-rule lp-reveal" aria-label="Muse proposes, geometry measures, you see only what passed">
            <div className="lp-rule-node muse"><Sparkles size={22} aria-hidden /><b>Muse</b><span>ideas, words, judgement</span></div>
            <div className="lp-rule-link" aria-hidden><span>1–3 real edits</span><i /></div>
            <div className="lp-rule-node geo"><ShieldCheck size={22} aria-hidden /><b>Geometry</b><span>measures every idea in the model</span></div>
            <div className="lp-rule-link" aria-hidden><span>only what passed</span><i /></div>
            <div className="lp-rule-node you"><Check size={22} aria-hidden /><b>You</b><span>review, accept, hand back</span></div>
          </div>
          <div className="lp-models">
            <Model name="Muse Spark" role="The coordinator" icon={<Sparkles size={18} aria-hidden />} tone="spark">
              Reads each clash from three pictures and the model's own data, proposes the edits, and runs chat, root causes,
              plans and the report's words. Its reasoning streams while it thinks.
            </Model>
            <Model name="Muse Spark Open" role={triageOpen ? "Bulk reading, on now" : "Bulk reading, when switched on"} icon={<ListFilter size={18} aria-hidden />} tone="open">
              Open weights, hosted on Baseten: triage of hundreds of clashes, their titles, and names for a STEP file's parts.
            </Model>
            <Model name="Muse Wonder" role="The second opinion" icon={<Wand2 size={18} aria-hidden />} tone="wonder">
              A longer try on a larger model when nothing passed, or to beat the options, briefed with everything the first
              try learnt.
            </Model>
            <Model name="Muse Image" role="Show it built" icon={<Image size={18} aria-hidden />} tone="image">
              Paints ORCA's own view of a verified fix as a picture of what will be built, checked against the model before
              anyone sees it.
            </Model>
            <Model name="Muse Voice Transcribe" role="Talk to it" icon={<Mic size={18} aria-hidden />} tone="voice">
              Hold to talk or go hands-free: live captions, biased to the open model's own names, sent as a chat message.
            </Model>
          </div>
          <ul className="lp-guards lp-reveal">
            <li><ShieldCheck size={16} aria-hidden />Keys stay on the server: the browser never sees one.</li>
            <li><Cpu size={16} aria-hidden />Caps on every paid call, per visitor and per day.</li>
            <li><FileText size={16} aria-hidden />AI text is marked in the report, which stays DRAFT until every team has reviewed it.</li>
          </ul>
        </div>
      </section>

      <section className="lp-sec lp-platform" id="platform" aria-labelledby="lp-platform-h">
        <div className="lp-wrap">
          <Head id="lp-platform-h" kicker="Everything around the fix" title="Built for the whole coordination job">
            From the first check to the files you hand back: the work around every fix, in one place, in the browser.
          </Head>
          <div className="lp-bento">
            <Tile cls="w2" icon={<ListFilter size={16} />} title="Triage that finds the few" art={<TriageArt />}>
              Sure rules settle touches, spaces and ports without a model call; a model reads the rest and gives each clash a
              verdict. Northbank's 464 sorted in under 2 minutes{triageOpen ? " on Muse Spark Open" : ", measured on Muse Spark Open"},
              alike clashes read once: 39 calls.
            </Tile>
            <Tile cls="w2" icon={<Target size={16} />} title="Root causes, fixed together" art={<RootArt />}>
              One girder behind three clashes. Tick several, or let Insights find the element behind them: an agent per
              problem in parallel, every fix applied at once and checked against the others, kept all or nothing.
            </Tile>
            <Tile icon={<Activity size={16} />} title="Watch it think" art={<LanesArt />}>
              Workings draws every run as it happens: your request, Muse Spark's ideas, ORCA's check on each, the rank.
            </Tile>
            <Tile icon={<Mic size={16} />} title="Ask in words" art={<ChatArt />}>
              Typed or spoken. Chat uses the same tools as the buttons, and drives the 3D view.
            </Tile>
            <Tile icon={<ClipboardCheck size={16} />} title="Your standard, enforced" art={<ReqArt />}>
              Design stage L1 to L5, Lenient to Exacting: the room each kind of part needs, who moves for whom, what may
              take an opening.
            </Tile>
            <Tile icon={<Layers size={16} />} title="Plans, sections, elevations" art={<ViewsArt />}>
              Up to four drawing views beside the 3D, measuring in every view with snapping, filters by any property.
            </Tile>
            <Tile cls="w2 dark" icon={<Bot size={16} />} title="Bring your own agent" art={<McpArt />}>
              ORCA is an MCP server too. A pairing link lets Muse Code or any MCP client open models, check its own ideas,
              propose and apply fixes through the same geometry check, while your page follows along.
            </Tile>
            <Tile icon={<PenTool size={16} />} title="Edit by hand, checked" art={<EditArt />}>
              Push or pull a face, align, move, cut a void, split, clip, delete: each checked before Keep. One log for
              fixes and hand edits.
            </Tile>
            <Tile icon={<Image size={16} />} title="Show it built" art={<BuiltArt />}>
              For people who don't read drawings: a verified fix painted as a picture of what will be built.
            </Tile>
            <Tile cls="w2" icon={<FileText size={16} />} title="A hand-off any tool can open" art={<FilesArt />}>
              The edited IFC, and the STEP written back with its parts' names and colours; a PDF report with a page per real
              clash, one per team if you like; BCF 2.1 issues for the team that must act.
            </Tile>
            <Tile icon={<Smartphone size={16} />} title="In the meeting, on any screen" art={<PhoneArt />}>
              The same app on a phone or tablet: the model on top, a sheet below with the one next step.
            </Tile>
            <Tile icon={<FileSpreadsheet size={16} />} title="Already ran Navisworks?">
              Import its clash report, pictures and all, then triage and fix those clashes instead.
            </Tile>
          </div>
        </div>
      </section>

      {start && (
        <section className="lp-sec lp-demos" id="demos" aria-labelledby="lp-demos-h">
          <div className="lp-wrap">
            <Head id="lp-demos-h" kicker="Proven on buildings and machines" title="Two demos, two kinds of model">
              Both open in a few seconds, with nothing to install. Each card plays a real proposal run, sped up.
            </Head>
            <div className={`lp-demo-grid${start.onCell ? "" : " one"}`}>
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
                <button className="lp-btn primary" data-tour="demo" disabled={start.disabled} onClick={start.onStart}>
                  <FolderOpen size={16} aria-hidden /> {start.label}</button>
                {start.onTour && <button className="lp-btn line" disabled={start.disabled} onClick={start.onTour}>
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
                  <button className="lp-btn primary" data-tour="cell" disabled={start.disabled} onClick={start.onCell}>
                    <Cpu size={16} aria-hidden /> Open the machine cell</button>
                  {start.onCellTour && <button className="lp-btn line" disabled={start.disabled} onClick={start.onCellTour}>
                    <Compass size={16} aria-hidden /> Take the cell tour</button>}
                </DemoCard>
              )}
            </div>
            <ol className="lp-once lp-reveal" aria-label="Once a demo is open">
              <li><b>{desktop ? "On the left" : "Clashes"}</b>what ORCA found: every clash numbered and named, grouped by check.</li>
              <li><b>{desktop ? "In the middle" : "On top"}</b>the models in 3D: the building with its streets and river, or the cell.</li>
              <li><b>{desktop ? "On the right" : "Fix"}</b>pick a clash, press <i>Propose fixes</i>, and watch ORCA work.</li>
            </ol>
          </div>
        </section>
      )}

      <section className="lp-sec lp-who" id="who" aria-labelledby="lp-who-h">
        <div className="lp-wrap">
          <Head id="lp-who-h" kicker="Who it's for" title="Built around the design coordinator">
            One person leads, and everyone whose design meets theirs gets what they need from the same work.
          </Head>
          <div className="lp-who-grid">
            <article className="lp-who-lead lp-reveal">
              <Users size={22} aria-hidden />
              <h3>The design coordinator</h3>
              <p>Makes every team's 3D design fit together: on a building, often the BIM coordinator; on a machine, the
                engineer who owns the assembly. Runs the check, sorts what it found, asks for fixes, accepts them and hands
                back the files.</p>
            </article>
            <Who title="The design teams">A report and BCF issues each, a review of every fix to their model, and their model back with the edit in it.</Who>
            <Who title="Whoever sets the standard">Coordination requirements every fix must meet: the room each part needs, who moves for whom.</Who>
            <Who title="People who don't read drawings">Show it built paints a checked fix as a picture of what will be built.</Who>
            <Who title="Teams with their own agent">A pairing link: Muse Code or any MCP client works through the same check.</Who>
          </div>
        </div>
      </section>

      <section className="lp-sec lp-proof" id="proof" aria-labelledby="lp-proof-h">
        <div className="lp-wrap">
          <Head id="lp-proof-h" kicker="Measured, not promised" title="What it has proven on the demos">
            Every number here was measured on the two demo models, which were built with planted problems and a known answer.
          </Head>
          <div className="lp-stats">
            <Stat reduce={reduce} pre="~" value={40} unit="s" label="to a verified fix" note="Northbank #1, from pressing Propose to an edit checked against all four models." />
            <Stat reduce={reduce} value={3} suffix=" of 3" label="designer fixes matched" note="The girder's three clashes, the first idea each time, at the designer's own heights: +400, +250, +280 mm." />
            <Stat reduce={reduce} value={464} label="clashes sorted in under 2 min" note="Triage on Muse Spark Open, the open-weights model; alike clashes read once, so 39 calls." />
            <Stat reduce={reduce} value={17} suffix=" of 17" label="planted clashes found" note="PC-03, opened straight from its STEP file: 161 parts, nothing unexpected; the fixed revision checks clean." />
          </div>
          <div className="lp-proof-more lp-reveal">
            <span><b>25 of 25</b> opening hosts judged right against an answer key</span>
            <span><b>150 MB</b> model through the page, opened in about 2 minutes</span>
            <span><b>Every fix kind</b> verified on the demos' planted cases (resize on a test model)</span>
          </div>
          <div className="lp-limits lp-reveal">
            <h3><TriangleAlert size={16} aria-hidden /> Said plainly: what it doesn't do yet</h3>
            <ul>
              <li><b>It doesn't sign off engineering.</b> Whether a beam can take a hole, or a flatter duct still carries its air, needs the designer's review; options say whose.</li>
              <li><b>Edits live in memory.</b> A restart, or opening the models again, starts clean: export what you keep.</li>
              <li><b>Some shapes are out of reach.</b> Offsets and routes need straight level runs with plain rectangular or round sections.</li>
              <li><b>STEP parts mostly move.</b> Offsets and trims work on exact bars and rods; meshed parts can only be moved.</li>
              <li><b>No accounts yet.</b> A session lives in this browser and on the server until it is cleared; saved projects come later.</li>
            </ul>
          </div>
        </div>
      </section>

      <section className="lp-sec lp-words" aria-labelledby="lp-words-h">
        <div className="lp-wrap lp-words-in lp-reveal">
          <h2 id="lp-words-h">New to this? Words you'll see</h2>
          <dl>
            <div><dt>BIM</dt><dd>Building Information Modelling: a 3D model where every object knows what it is.</dd></div>
            <div><dt>IFC</dt><dd>The open file format for those models, readable by any design tool.</dd></div>
            <div><dt>STEP</dt><dd>The open format mechanical CAD uses for machines and equipment.</dd></div>
            <div><dt>Clash</dt><dd>One place where two parts of the models conflict. Each has a number, like #3.</dd></div>
            <div><dt>Check</dt><dd>One pair of things checked against each other: two models, or one model against itself.</dd></div>
            <div><dt>Triage</dt><dd>Sorting the clashes a check found: a real problem, by design, a model error, or not physical.</dd></div>
            <div><dt>Clearance</dt><dd>The room left between two things once a clash is fixed: 25 mm unless asked for more.</dd></div>
            <div><dt>BCF</dt><dd>An open format for issues on a model, which design tools read.</dd></div>
          </dl>
          <div className="lp-colours" aria-label="Colours in the 3D view">
            <span><i style={{ background: "#d0342c" }} />Element A of a clash</span>
            <span><i style={{ background: "#1f9d3a" }} />Element B, what it runs into</span>
            <span><i style={{ background: "#f5a623" }} />An idea being checked</span>
            <span><i style={{ background: "#12b5cb" }} />An idea that passed</span>
            <span><i style={{ background: "#e040fb" }} />What a failed idea hit</span>
            <span><i style={{ background: "#e67e22", opacity: 0.6 }} />The element before the fix</span>
            <span><i style={{ background: "#2563eb" }} />What an element is joined to</span>
          </div>
        </div>
      </section>

      <section className="lp-final" data-tone="dark" aria-labelledby="lp-final-h">
        <div className="lp-wrap lp-reveal">
          <h2 id="lp-final-h">See a verified fix in about 40 seconds.</h2>
          <p>One click opens Northbank, checks it, picks the duct through the girder and asks ORCA for a fix.</p>
          <div className="lp-cta center">
            {start?.onGolden && <button className="lp-btn primary" disabled={start.disabled} onClick={start.onGolden}>
              <Play size={16} aria-hidden /> Watch ORCA fix a clash</button>}
            {start?.onBlank && <button className="lp-btn glass" onClick={start.onBlank}><Upload size={16} aria-hidden /> Use your own models</button>}
            {start?.onTour && <button className="lp-btn glass" disabled={start.disabled} onClick={start.onTour}><Compass size={16} aria-hidden /> Take the guided tour</button>}
          </div>
          {onAbout && (
            <button className="lp-deeper" onClick={onAbout}>
              <span><b>Go deeper: About ORCA</b>How a fix is found and checked, every kind of fix, the five models and what
                they are trusted with, how it is built, and what it has proven.</span>
              <ArrowRight size={20} aria-hidden />
            </button>
          )}
        </div>
      </section>

      <footer className="lp-foot" data-tone="dark">
        <div className="lp-wrap">
          <div className="lp-foot-brand"><Wordmark height={22} /><span>by IssueLab · Observe. Resolve. Check. Apply.</span></div>
          <p>
            Northbank is a fictional three-storey office with its street and riverside, and PC-03 a fictional robot cell:
            demo models built by IssueLab with planted problems that have a known answer. No real project data. Fixes are
            limited to 20 per visitor an hour.
          </p>
          <p className="lp-foot-links">
            {onAbout && <button type="button" onClick={onAbout}>About ORCA</button>}
            <a href={REPO} target="_blank" rel="noopener noreferrer">Source on GitHub</a>
            <span>Built with Muse Spark, IfcOpenShell, three.js and IFC</span>
          </p>
        </div>
      </footer>
    </div>
  );
}

const LOOP_STEPS: LoopStep[] = [
  { letter: "O", word: "Observe", title: "It reads the models before it touches them.",
    points: [
      <><b>Its own clash detection:</b> every pair of models and each against itself. Or import a Navisworks report.</>,
      <><b>Every clash numbered and named,</b> then triaged: a real problem, by design, a model error, or not physical. Alike clashes are read once.</>,
      <><b>For the clash you pick,</b> Muse Spark reads three pictures and the model's own facts: what each element is, which way it runs, the openings in its way, the room around it.</>,
    ],
    clip: { src: "/demos/check", caption: "Northbank's check, then its list: 464 clashes, numbered, being named.",
      alt: "Northbank's three building models checked: ORCA lists each pair of models and each model against itself while it checks 1,961 elements, then the list appears, 464 clashes numbered and grouped by check, the supply air main through the girder first at -300 mm, and they are being named." } },
  { letter: "R", word: "Resolve", title: "It proposes real edits, not advice.",
    points: [
      <><b>One to three fixes</b> that edit the real elements: new pieces, bends and fittings, ports joined back up.</>,
      <><b>Seven kinds of fix,</b> and fixes that combine them, within your coordination requirements.</>,
      <><b>Its reasoning streams</b> as it thinks. A clash it can't fix gets a second, longer try on Muse Wonder.</>,
    ],
    clip: { src: "/demos/understand", tall: true, caption: "Muse Spark on #1, sped up: the three pictures, its reasoning as it thinks, what it understood.",
      alt: "The Clash panel for Northbank's #1 while Muse Spark works, sped up: the three pictures of the duct through the girder, then its reasoning as it thinks, then its understanding: the duct crosses the 1000 deep girder with 300 mm overlap, cannot shift as a whole without pulling apart its tees, and the girder has an opening on this line it can use." } },
  { letter: "C", word: "Check", title: "Nothing reaches you unproven.",
    points: [
      <><b>Each idea is tried on the model,</b> checked against every open model, then undone.</>,
      <><b>Four tests:</b> the clash is gone, there is clearance, nothing new is hit, and what it stands on still holds it.</>,
      <><b>A failed idea goes back</b> to Muse Spark with why and what it hit. Workings draws every round as it happens.</>,
    ],
    clip: { src: "/demos/workings", caption: "Workings of the same run: your request, Muse Spark's ideas, ORCA's checks, the rank.",
      alt: "Workings replaying Northbank's run, sped up: one lane each for you, Muse Spark and ORCA. Your request and ORCA's brief go to Muse Spark, whose round replies with two ideas; ORCA checks the first in the model's geometry and it is verified, so ORCA stops there, ranks it and leaves one verified option, then kept." } },
  { letter: "A", word: "Apply", title: "You decide. It keeps its word.",
    points: [
      <><b>Before, After or Both</b> in 3D, beside plans, sections and elevations.</>,
      <><b>Accept, and the server checks again</b> before it keeps the fix: it never trusts the page. The model is patched in place, with undo and redo.</>,
      <><b>Hand it back:</b> the edited IFC or STEP, a PDF report per team, and BCF issues.</>,
    ],
    clip: { src: "/demos/keep", caption: "Accept: the server tries the fix again, edits the model and checks it.",
      alt: "Northbank's #1 after the fix, Before and After: overlap -300 mm, then clear by 50 mm. Accept is pressed: Applying the fix, then Fix kept in the model, checked again, and Export IFC counts one edit to download." } },
];

const FIXES: { kind: string; art: ReactNode; what: string; eg: string; who: string }[] = [
  { kind: "Move", art: <ArtMove />, what: "Shifts an element, and whatever runs with it, by a vector.", eg: "The cell's cable ladder, moved 150 mm as one run.", who: "The element's own team" },
  { kind: "Offset", art: <ArtOffset />, what: "Splits a level run either side of the obstacle and takes the middle up or down, with bends.", eg: "Northbank's duct, up 400 mm through the girder's web opening.", who: "The element's own team" },
  { kind: "Reroute", art: <ArtRoute />, what: "Up to three stretches up or sideways, for what one offset can't clear.", eg: "A pipe branch rerouted round two plant columns.", who: "The element's own team" },
  { kind: "Trim", art: <ArtTrim />, what: "Cuts a slender member's end back to butt the other's face.", eg: "A curtain-wall transom running 30 mm into its mullion.", who: "Often model cleanup, not coordination" },
  { kind: "Seat", art: <ArtSeat />, what: "Cuts an element that comes down into its support, so what is left bears on it.", eg: "A lift-pit wall running 500 mm into a pad footing.", who: "The structural engineer" },
  { kind: "Resize", art: <ArtResize />, what: "A flatter, wider stretch of rectangular duct or tray that carries the same.", eg: "A duct flattened to pass under a beam.", who: "The services designer, for performance" },
  { kind: "Opening", art: <ArtOpening />, what: "Asks for a hole where a straight service crosses a wall or slab.", eg: "The cell's air line through the plant wall.", who: "The host's designer, plus fire-stopping" },
  { kind: "Combined", art: <ArtCombined />, what: "Two or three steps on different services, tried together, kept all or nothing.", eg: "A second try when no single edit clears a crowded spot.", who: "Every team whose element moves" },
];

function Head({ id, kicker, title, children, center }: { id: string; kicker: string; title: ReactNode; children?: ReactNode; center?: boolean }) {
  return (
    <div className={`lp-head lp-reveal${center ? " center" : ""}`}>
      <p className="lp-kicker">{kicker}</p>
      <h2 id={id}>{title}</h2>
      {children && <p className="lp-sub">{children}</p>}
    </div>
  );
}

function Fact({ value, label, note, reduce }: { value: number; label: string; note: string; reduce: boolean }) {
  const [ref, seen] = useSeen<HTMLDivElement>();
  const v = useCountUp(value, seen, reduce);
  return (
    <div className="lp-fact" ref={ref}>
      <b>{v.toLocaleString("en-GB")}</b>
      <span className="lp-fact-label">{label}</span>
      <span className="lp-fact-note">{note}</span>
    </div>
  );
}

function Stat({ value, pre = "", suffix = "", unit, label, note, reduce }: {
  value: number; pre?: string; suffix?: string; unit?: string; label: string; note: string; reduce: boolean;
}) {
  const [ref, seen] = useSeen<HTMLDivElement>();
  const v = useCountUp(value, seen, reduce);
  return (
    <div className="lp-stat lp-reveal" ref={ref}>
      <b>{pre}{v.toLocaleString("en-GB")}{suffix}{unit && <small>{unit}</small>}</b>
      <span className="lp-stat-label">{label}</span>
      <span className="lp-stat-note">{note}</span>
    </div>
  );
}

function Model({ name, role, icon, tone, children }: { name: string; role: string; icon: ReactNode; tone: string; children: ReactNode }) {
  return (
    <article className={`lp-model lp-reveal ${tone}`}>
      <p className="lp-model-role">{icon}{role}</p>
      <h3>{name}</h3>
      <p>{children}</p>
    </article>
  );
}

function Who({ title, children }: { title: string; children: ReactNode }) {
  return <article className="lp-who-item lp-reveal"><h3>{title}</h3><p>{children}</p></article>;
}

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
    <div className="lp-resume" role="region" aria-label="Your last session">
      <span className="lp-resume-icon" aria-hidden><RotateCcw size={16} /></span>
      <div className="lp-resume-text">
        <p>Pick up where you left off</p>
        <h2 data-tip-tap data-tip={r.files.join(", ")} data-tip-side="bottom">{projectName(r.files)}</h2>
        <div className="lp-resume-meta">
          <span>{r.files.length} model{r.files.length === 1 ? "" : "s"}</span>
          {r.clashes != null && <span>{r.clashes} clashes</span>}
          {r.fixed > 0 && <span className="ok">{r.fixed} fixed</span>}
          {r.agent && <span className="ok">Agent connected{r.agentLeft ? ` · ${r.agentLeft} left` : ""}</span>}
          <span>{when}</span>
        </div>
      </div>
      <div className="lp-resume-actions">
        <button className="lp-btn small primary" disabled={disabled} onClick={r.onResume}>Resume</button>
        <button className="lp-btn small glass" onClick={r.onFresh}
          data-tip={r.agent ? "Forget this session here and end its agent link" : "Forget this session here"}>Start fresh</button>
      </div>
    </div>
  );
}

/** A recorded run of ORCA, as a picture that plays itself: `<src>.webp`, an animated WebP time-lapse (no controls, no
 * sound, it loops), made by web/scripts/capture-proposals.cjs --landing. People who ask for less motion get
 * `<src>-still.webp`, its last frame, instead. */
function Clip({ src, alt }: { src: string; alt: string }) {
  return (
    <picture>
      <source media="(prefers-reduced-motion: reduce)" srcSet={`${src}-still.webp`} />
      <img src={`${src}.webp`} alt={alt} width={1000} height={625} loading="lazy" decoding="async" />
    </picture>
  );
}

/** One demo on the start page: a fix being found in it, what it is, what it shows, and how to start it. */
function DemoCard({ clip, alt, eyebrow, title, blurb, shows, chips, note, children }: {
  clip: string; alt: string; eyebrow: string; title: string; blurb: ReactNode; shows: ReactNode[]; chips: string[];
  note?: ReactNode; children: ReactNode;
}) {
  return (
    <article className="lp-demo lp-reveal">
      <div className="lp-demo-clip"><Clip src={clip} alt={alt} /></div>
      <div className="lp-demo-body">
        <p className="lp-kicker">{eyebrow}</p>
        <h3>{title}</h3>
        <p className="lp-demo-blurb">{blurb}</p>
        <ul className="lp-demo-shows" aria-label="What it shows">
          {shows.map((x, i) => <li key={i}><Check size={14} aria-hidden /><span>{x}</span></li>)}
        </ul>
        <div className="lp-demo-chips">{chips.map((c) => <span key={c}>{c}</span>)}</div>
        <div className="lp-demo-foot">
          {note && <p className="lp-demo-note">{note}</p>}
          <div className="lp-demo-actions">{children}</div>
        </div>
      </div>
    </article>
  );
}
