import {
  ArrowRight, Bot, Boxes, Brain, Building2, Check, ClipboardCheck, Combine, Cpu, Download, Eye, FileText, Image, Layers,
  ListFilter, MessageSquare, Mic, MousePointerClick, Network, Radar, Ruler, ScanSearch, Server, ShieldCheck, Sparkles,
  Target, TriangleAlert, Wand2, X,
} from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";
import { ABOUT_TABS, nextTab, type AboutTab } from "./aboutRoute";

/**
 * About ORCA: a full page, in tabs, for anyone who wants more than the landing: what ORCA does, how the loop works,
 * every kind of fix, the models and what they are trusted with, how it is built, and what it has proven (and not).
 * Its numbers are the measured ones the landing and README use; keep them in step (CLAUDE.md, "Traps").
 */
export function AboutOrca({ tab, onTab, onClose, triageOpen = false }: {
  tab: AboutTab;
  onTab: (tab: AboutTab) => void;
  onClose: () => void;
  triageOpen?: boolean;  // titles and triage run on the open-weights model now (server: /api/models)
}) {
  const reduced = useReducedMotion();
  const scroll = useRef<HTMLDivElement>(null);
  const tabs = useRef<HTMLDivElement>(null);
  const hero = useRef<HTMLElement>(null);
  const panel = useRef<HTMLElement>(null);

  useEffect(() => {
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", key);
    scroll.current?.focus({ preventScroll: true });
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);

  // Keep the chosen tab in sight in a tab bar that scrolls sideways (phones).
  useEffect(() => {
    const bar = tabs.current, on = bar?.querySelector<HTMLElement>(`#oa-tab-${tab}`);
    if (bar && on && bar.scrollWidth > bar.clientWidth) bar.scrollTo({ left: on.offsetLeft - (bar.clientWidth - on.offsetWidth) / 2, behavior: "smooth" });
  }, [tab]);

  // Sections fade up as they scroll into view (each once); without IntersectionObserver they simply show.
  useEffect(() => {
    const root = scroll.current;
    if (!root) return;
    const items = Array.from(root.querySelectorAll<HTMLElement>(".oa-reveal:not([data-in])"));
    if (typeof IntersectionObserver === "undefined") { items.forEach((el) => el.setAttribute("data-in", "")); return; }
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) if (e.isIntersecting) { e.target.setAttribute("data-in", ""); io.unobserve(e.target); }
    }, { root, threshold: 0.08 });
    items.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [tab]);

  const choose = (t: AboutTab) => {
    onTab(t);
    // Past the hero, a new tab starts at its top, under the sticky tab bar (whose own offset moves while it sticks).
    const root = scroll.current, top = hero.current?.offsetHeight ?? 0;
    if (root && root.scrollTop > top) root.scrollTo({ top, behavior: reduced ? "auto" : "smooth" });
  };
  const onTabKey = (e: ReactKeyboardEvent) => {
    const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    let to: AboutTab | null = step ? nextTab(tab, step) : null;
    if (e.key === "Home") to = ABOUT_TABS[0].id;
    if (e.key === "End") to = ABOUT_TABS[ABOUT_TABS.length - 1].id;
    if (!to) return;
    e.preventDefault();
    choose(to);
    tabs.current?.querySelector<HTMLButtonElement>(`#oa-tab-${to}`)?.focus();
  };

  return (
    <div className="orca-about" role="dialog" aria-modal="true" aria-label="About ORCA">
      <div className="oa-scroll" ref={scroll} tabIndex={-1}>
        <header className="oa-hero" ref={hero}>
          <div className="oa-hero-grid" aria-hidden />
          <button className="ibtn oa-close" onClick={onClose} aria-label="Close About ORCA"><X size={20} aria-hidden /></button>
          <div className="oa-hero-inner">
            <div className="oa-hero-text">
              <p className="oa-eyebrow">About ORCA · by IssueLab</p>
              <h1>Design coordination that <em>edits the model</em>, and proves every edit.</h1>
              <p className="oa-lede">
                Buildings, plants and machines are drawn in 3D by several teams at once. Put their models together and
                things collide. ORCA finds those clashes, works out real fixes to the model, checks each one by
                geometry, and hands back the edited files.
              </p>
              <ol className="oa-acronym" aria-label="ORCA stands for Observe, Resolve, Check, Apply">
                {["Observe", "Resolve", "Check", "Apply"].map((w, i) => (
                  <li key={w} style={{ animationDelay: `${0.25 + i * 0.12}s` }}><b>{w[0]}</b>{w.slice(1)}</li>
                ))}
              </ol>
            </div>
            <OrcaLoop reduced={reduced} />
          </div>
        </header>

        <div className="oa-tabs" ref={tabs} role="tablist" aria-label="About ORCA" onKeyDown={onTabKey}>
          {ABOUT_TABS.map((t) => (
            <button key={t.id} id={`oa-tab-${t.id}`} role="tab" aria-selected={tab === t.id} aria-controls="oa-panel"
              tabIndex={tab === t.id ? 0 : -1} className={tab === t.id ? "on" : ""} onClick={() => choose(t.id)}>{t.label}</button>
          ))}
        </div>

        <main className="oa-panel" id="oa-panel" ref={panel} role="tabpanel" aria-labelledby={`oa-tab-${tab}`} key={tab}>
          {tab === "overview" && <Overview reduced={reduced} onTab={choose} />}
          {tab === "how" && <HowItWorks reduced={reduced} triageOpen={triageOpen} />}
          {tab === "fixes" && <Fixes />}
          {tab === "ai" && <TheAi triageOpen={triageOpen} />}
          {tab === "inside" && <Inside />}
          {tab === "proof" && <Proof reduced={reduced} />}
          <TabFoot tab={tab} onTab={choose} />
        </main>

        <footer className="oa-foot">
          <span><b>ORCA</b> by IssueLab. Built for the Meta Global AI Developer Hackathon, from Oct 27, 2026.</span>
          <span>Northbank and the PC-03 cell are fictional demo models with planted problems: no real project data.</span>
        </footer>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ tabs */

function Overview({ reduced, onTab }: { reduced: boolean; onTab: (t: AboutTab) => void }) {
  return <>
    <Section kicker="The problem" title="Every team's model is right on its own. Together, they collide.">
      <div className="oa-split">
        <div className="oa-prose">
          <p>
            Structure, building services and architecture each draw their own 3D model. <b>Design coordination</b> is
            making those models agree before anything is built. Put them together and an air duct runs straight through a
            steel girder, or a pipe through a wall with no hole in it. Each overlap is a <b>clash</b>.
          </p>
          <p>
            A check finds them by the hundred. Most are harmless, parts that meet on purpose. A few are real, and each
            real one costs a meeting and a redesign; missed, it costs rework on site. Today a coordinator finds them,
            explains them and waits for someone to redraw.
          </p>
          <p className="oa-pull">ORCA does the redrawing too, and proves it worked.</p>
        </div>
        <ClashScene />
      </div>
    </Section>

    <Section kicker="Measured on the demos" title="Fast enough to use in the meeting">
      <div className="oa-stats">
        <Stat value={<CountUp to={464} reduced={reduced} />} unit="clashes" label="found in about 4 s"
          note="Northbank: every pair of three building models and each against itself, 1,732 elements." />
        <Stat value={<>~<CountUp to={40} reduced={reduced} /></>} unit="s" label="to a verified fix"
          note="From pressing Propose to an edit checked against all four models." />
        <Stat value={<><CountUp to={3} reduced={reduced} /> of 3</>} label="designer fixes matched"
          note="The three planted clashes on the Level 02 girder: the first idea passes at the designer's own heights." />
        <Stat value={<><CountUp to={17} reduced={reduced} /> of 17</>} label="planted clashes found"
          note="The PC-03 machine cell, opened straight from its STEP file: 161 parts, nothing unexpected." />
      </div>
    </Section>

    <Section kicker="Observe · Resolve · Check · Apply" title="Four steps, one loop">
      <div className="oa-cards four">
        <Card icon={<ScanSearch size={20} aria-hidden />} title="Observe">
          Checks every pair of models, numbers and names every clash, sorts real problems from noise, and reads each one:
          three pictures plus the model's own facts.
        </Card>
        <Card icon={<Sparkles size={20} aria-hidden />} title="Resolve">
          Muse Spark proposes real edits to the elements: raise a duct through an opening, reroute a pipe, trim a member,
          flatten a duct, or ask for a hole.
        </Card>
        <Card icon={<ShieldCheck size={20} aria-hidden />} title="Check">
          A geometry engine tries each edit in the model: the clash is gone, there is room to spare, and nothing new is
          hit. Failures go back with the reason.
        </Card>
        <Card icon={<Download size={20} aria-hidden />} title="Apply">
          You watch it work in 3D, compare before and after, accept, and take away the edited IFC or STEP, a PDF report
          and BCF issues.
        </Card>
      </div>
    </Section>

    <Section kicker="Proven on buildings and machines" title="Two demos, two kinds of model">
      <div className="oa-demos">
        <figure className="oa-demo">
          <img src="/demos/northbank.webp" alt="The Northbank demo in ORCA's viewer: an office building among its neighbours, with streets, trees and the river." loading="lazy" />
          <figcaption>
            <span className="oa-chip">Building · 4 IFC models</span>
            <b>Northbank, a riverside office site</b>
            On Level 02 a transfer girder is hit by a duct, a cable tray and a water main. ORCA raises the duct through
            the girder's web opening, at the height the designer chose, and plans all three as one root cause.
          </figcaption>
        </figure>
        <figure className="oa-demo">
          <img src="/demos/cell.webp" alt="The PC-03 palletising cell in ORCA's viewer: a robot inside its see-through safety zone, a conveyor, fence posts and the air line." loading="lazy" />
          <figcaption>
            <span className="oa-chip">Machine · 1 STEP file</span>
            <b>PC-03, a robot palletising cell</b>
            Mechanical CAD with eight planted problems. ORCA moves a cable ladder, drops an air pipe under both conveyor
            rails, reroutes a branch round two columns, and writes the fixes back into the STEP.
          </figcaption>
        </figure>
      </div>
      <button className="oa-next" onClick={() => onTab("how")}>See how a fix is found and checked <ArrowRight size={16} aria-hidden /></button>
    </Section>
  </>;
}

const STAGES: { icon: ReactNode; title: string; short: string; body: ReactNode; facts: string[] }[] = [
  { icon: <Radar size={18} aria-hidden />, title: "Check", short: "Find every clash",
    body: <>ORCA's own clash detection checks every pair of models and each model against itself. It sweeps the element
      boxes it cached when the models opened, then tests the triangles where boxes meet, with an exact depth for
      rectangular solids. It can also import a Navisworks clash report.</>,
    facts: ["Northbank: 1,732 elements, 464 clashes, about 4 s", "Stable numbers (#1, #2…) across reruns", "Reruns mark clashes new, still there, or resolved"] },
  { icon: <ListFilter size={18} aria-hidden />, title: "Triage", short: "Sort the real from the noise",
    body: <>Sure rules settle what needs no model: touches, spaces and ports, one element on both sides. A model reads
      the rest and gives each clash a verdict: a <b>real problem</b>, <b>by design</b>, a <b>model error</b> for its
      author, or <b>not physical</b>. Alike clashes (forty bolts in forty plates) are read once.</>,
    facts: ["Northbank: 464 sorted in under 2 minutes on Muse Spark Open", "Every clash gets a plain title", "Its reasoning is kept on the verdict"] },
  { icon: <Eye size={18} aria-hidden />, title: "Understand", short: "Read one clash",
    body: <>For the clash you pick, Muse Spark gets three pictures (the pair, the pair in its surroundings, a side view)
      and the model's own facts: what each element is and which way it runs, the openings in the obstacle, the free room
      above and beside it, other clashes nearby, and your requirements. You can read its reasoning as it thinks.</>,
    facts: ["Openings found by ray casting the obstacle", "Free bands measured clear of everything along the stretch", "Severity comes from numbers, not pixels"] },
  { icon: <ShieldCheck size={18} aria-hidden />, title: "Propose and check", short: "Only verified fixes reach you",
    body: <>Muse Spark suggests edits. Each is tried on the real IFC elements inside a transaction, checked against every
      open model, then undone. An idea that fails goes back with why and what it hit, and Muse tries again. Up to three
      verified options are ranked: plain geometry first, then resizing, then asking for an opening.</>,
    facts: ["Clash gone, clearance kept, nothing new hit", "What an element stands on is kept", "If nothing passes, ORCA says what blocked each idea"] },
  { icon: <MousePointerClick size={18} aria-hidden />, title: "Review", short: "Watch it, then accept",
    body: <>The agent drives the 3D view while it works: amber while an idea is checked, teal when it is clear, magenta for
      what it hit. Compare before and after, read who must review the change, and accept. The fix is patched straight
      into the open model; nothing reloads.</>,
    facts: ["Before / After / Both views", "Take the camera any time; ORCA keeps working", "A review per team before a page leaves draft"] },
  { icon: <FileText size={18} aria-hidden />, title: "Hand off", short: "Files any tool can open",
    body: <>Download the edited IFC (and the STEP, written back with its parts' names and colours), a design coordination
      PDF with a page per real clash and its fix, and BCF 2.1 issues assigned to the team that must act.</>,
    facts: ["Only kept fixes mark a file edited", "Explanations marked as AI-drafted", "One PDF, one per team or one per model"] },
];

function HowItWorks({ reduced, triageOpen }: { reduced: boolean; triageOpen: boolean }) {
  const [auto, setAuto] = useState(true);
  const [stage, setStage] = useTicker(STAGES.length, 5200, auto && !reduced);
  const s = STAGES[stage];
  const pick = (i: number) => { setAuto(false); setStage(i); };
  return <>
    <Section kicker="From models to a kept fix" title="Six stages, all in the browser">
      <div className="oa-pipeline" style={{ ["--stages" as string]: STAGES.length }}>
        <div className="oa-pipe-line" aria-hidden><span style={{ width: `${(stage / (STAGES.length - 1)) * 100}%` }} /></div>
        {STAGES.map((x, i) => (
          <button key={x.title} className={`oa-stage${i === stage ? " on" : ""}${i < stage ? " past" : ""}`} onClick={() => pick(i)}
            aria-pressed={i === stage}>
            <span className="oa-stage-dot">{x.icon}</span>
            <b>{x.title}</b>
            <span>{x.short}</span>
            {i === stage && auto && !reduced && <i className="oa-stage-timer" aria-hidden />}
          </button>
        ))}
      </div>
      <div className="oa-stage-detail" key={stage}>
        <div>
          <p className="oa-kicker">Stage {stage + 1} of {STAGES.length}</p>
          <h3>{s.title}: {s.short.toLowerCase()}</h3>
          <p>{s.body}{stage === 1 && <> Triage runs on {triageOpen ? <b>Muse Spark Open</b> : <b>Muse Spark</b>} right now.</>}</p>
        </div>
        <ul>{s.facts.map((f) => <li key={f}><Check size={15} aria-hidden />{f}</li>)}</ul>
      </div>
    </Section>

    <Section kicker="The heart of it" title="Propose, check, retry with the reason">
      <VerifyLoop reduced={reduced} />
    </Section>

    <Section kicker="Beyond one clash" title="When the problem is bigger than a pair">
      <div className="oa-cards three">
        <Card icon={<Combine size={20} aria-hidden />} title="Fix together">
          Tick several clashes and ORCA plans them as one: an agent per problem in parallel, then every fix applied at
          once and checked against the others, kept all or nothing.
        </Card>
        <Card icon={<Target size={20} aria-hidden />} title="Root causes">
          One element behind many clashes, like Northbank's Level 02 girder. Muse Spark names the cause and the strategy:
          move it, fix what hits it, or leave it as designed.
        </Card>
        <Card icon={<Layers size={20} aria-hidden />} title="Patterns">
          The same kind of clash many times over (every column through every slab). Read once, marked by design, and
          turned into a rule so it never comes back.
        </Card>
        <Card icon={<ClipboardCheck size={20} aria-hidden />} title="Requirements">
          An optional file: design stage L1 to L5, how strict to be, who may move and how far, what may take an opening.
          It shapes the check, the triage and the fixes.
        </Card>
        <Card icon={<MessageSquare size={20} aria-hidden />} title="Chat and voice">
          Ask in words, typed or spoken: “Why are there so many clashes on Level 02? Fix the root cause.” Chat uses the
          same tools as the buttons.
        </Card>
        <Card icon={<Bot size={20} aria-hidden />} title="Your own agent">
          ORCA is an MCP server too. A pairing link lets any agent open models, propose and apply fixes, alongside the
          page you are looking at.
        </Card>
      </div>
    </Section>

    <Section kicker="Reading the 3D view" title="What the colours mean">
      <ul className="oa-legend">
        <li><i style={{ background: "#d0342c" }} />Element A of the clash</li>
        <li><i style={{ background: "#1f9d3a" }} />Element B, the one it runs into</li>
        <li><i style={{ background: "#8e44ad" }} />One element on both sides</li>
        <li><i style={{ background: "#f5a623" }} />An idea being checked right now</li>
        <li><i style={{ background: "#12b5cb" }} />An idea that passed the check</li>
        <li><i style={{ background: "#e040fb" }} />What a failed idea ran into</li>
        <li><i style={{ background: "#e67e22", opacity: 0.55 }} />The element as it was, before the fix</li>
        <li><i style={{ background: "#2563eb" }} />What an element is joined to</li>
      </ul>
    </Section>
  </>;
}

const FIXES: { kind: string; title: string; what: ReactNode; example: ReactNode; review: string; art: ReactNode }[] = [
  { kind: "move", title: "Move", what: "Shifts an element, and whatever runs with it, by a vector.",
    example: <>The cell's cable ladder, moved 150 mm as one run.</>, review: "The element's own team", art: <ArtMove /> },
  { kind: "offset", title: "Offset", what: "Splits a straight run either side of the obstacle and takes the middle up, down or sideways, with radiused bends.",
    example: <>Northbank's duct, up 400 mm through the girder's web opening: the designer's own height.</>, review: "The element's own team", art: <ArtOffset /> },
  { kind: "trim", title: "Trim", what: "Cuts a slender member's end back to butt the other's face. Refused for anything that isn't slender, like a pad footing.",
    example: <>A curtain-wall transom running 30 mm into its mullion.</>, review: "Often model cleanup, not coordination", art: <ArtTrim /> },
  { kind: "route", title: "Route", what: "Up to three steps up or sideways along the run, for what one offset can't clear.",
    example: <>A pipe branch rerouted north round two plant columns.</>, review: "The element's own team", art: <ArtRoute /> },
  { kind: "penetration", title: "Opening", what: "Asks for a hole where a straight service crosses a wall or slab: a provision for void always, the opening cut only where the host's team allows it.",
    example: <>The air line through the plant wall; a conduit through a panel's gland plate.</>, review: "Structure or architecture, plus fire-stopping", art: <ArtPenetration /> },
  { kind: "resize", title: "Resize", what: "Makes a stretch of a rectangular duct or tray flatter and wider so it carries the same, with transitions either side.",
    example: <>A duct flattened to pass under a beam, its equivalent diameter kept.</>, review: "Services, for performance", art: <ArtResize /> },
  { kind: "combined", title: "Combined", what: "Two or three steps on different services, tried in one trial, checked together and kept all or nothing.",
    example: <>Muse Wonder's second try, when no single edit can clear a crowded spot.</>, review: "Every team whose element moves", art: <ArtCombined /> },
];

function Fixes() {
  return <>
    <Section kicker="Real edits, not notes" title="Seven kinds of fix">
      <p className="oa-intro">
        Every fix ORCA offers changes real IFC elements: new pieces, bends and fittings, ports joined back up, and the
        original element's id kept on its first piece. Each is tried in the model, checked and undone before you see it.
      </p>
      <div className="oa-fixes">
        {FIXES.map((f, i) => (
          <article key={f.kind} className={`oa-fix oa-reveal${f.kind === "combined" ? " wide" : ""}`} style={{ ["--d" as string]: `${i * -0.9}s`, transitionDelay: `${(i % 3) * 60}ms` }}>
            <div className="oa-fix-art">{f.art}<span className="oa-fix-tag before">before</span><span className="oa-fix-tag after">after</span></div>
            <div className="oa-fix-body">
              <h3>{f.title} <code>{f.kind}</code></h3>
              <p>{f.what}</p>
              <p className="oa-fix-eg"><Sparkles size={13} aria-hidden /> {f.example}</p>
              <p className="oa-fix-review"><ShieldCheck size={13} aria-hidden /> Reviewed by: {f.review}</p>
            </div>
          </article>
        ))}
      </div>
    </Section>

    <Section kicker="Every option passed all four" title="What “verified” means">
      <div className="oa-checks">
        <Check4 icon={<Target size={20} aria-hidden />} title="The clash is gone">Measured again in the edited model, not assumed.</Check4>
        <Check4 icon={<Ruler size={20} aria-hidden />} title="Clearance is kept">25 mm by default, or what your requirements ask for.</Check4>
        <Check4 icon={<Boxes size={20} aria-hidden />} title="Nothing new is hit">Every open model, every piece the fix adds, bends included.</Check4>
        <Check4 icon={<Building2 size={20} aria-hidden />} title="Support is kept">What an element stands on stays under it; nothing floats.</Check4>
      </div>
      <p className="oa-note"><TriangleAlert size={15} aria-hidden /> Geometry can't judge whether a beam can take a hole or a
        flatter duct still moves enough air. Those options say who must review them before anything is built.</p>
    </Section>
  </>;
}

function TheAi({ triageOpen }: { triageOpen: boolean }) {
  return <>
    <Section kicker="The rule ORCA is built on" title="The model proposes. Geometry decides.">
      <div className="oa-principle oa-reveal">
        <div><Brain size={26} aria-hidden /><b>Muse</b><span>ideas, words, judgement</span></div>
        <ArrowRight size={22} aria-hidden className="oa-principle-arrow" />
        <div><ShieldCheck size={26} aria-hidden /><b>Geometry</b><span>measures every idea in the model</span></div>
        <ArrowRight size={22} aria-hidden className="oa-principle-arrow" />
        <div><Check size={26} aria-hidden /><b>You</b><span>see only what passed</span></div>
      </div>
      <p className="oa-intro">
        No model output is ever trusted to accept a fix or set a clearance number: only the server's geometry supplies
        those. Muse does what geometry can't: read a clash in context, think of the right edit, explain it in plain words.
      </p>
    </Section>

    <Section kicker="Five models, each with one job" title="Who does what">
      <div className="oa-models">
        <Model name="Muse Spark" role="The coordinator" icon={<Sparkles size={20} aria-hidden />} tone="spark wide">
          Reads each clash, proposes the fixes, explains them in the report, and answers in chat with ORCA's own tools.
          Its reasoning streams to the page while it thinks.
        </Model>
        <Model name="Muse Spark Open" role={triageOpen ? "Bulk reading, on now" : "Bulk reading, when switched on"} icon={<ListFilter size={20} aria-hidden />} tone="open">
          The open-weights model, hosted on Baseten. When switched on it names and triages every clash; it bills by the
          hour, so it is off unless the owner turns it on, and Muse Spark does that work instead.
        </Model>
        <Model name="Muse Wonder" role="The second opinion" icon={<Wand2 size={20} aria-hidden />} tone="wonder">
          A longer try on a larger model, for a clash Muse Spark couldn't fix or to look for a better fix, briefed with
          everything the first try learnt. Held to a daily budget.
        </Model>
        <Model name="Muse Image" role="Show it built" icon={<Image size={20} aria-hidden />} tone="image">
          Restyles ORCA's own view of a verified fix as a presentation render. Judges compare it with the model before
          anyone sees it; it is labelled an illustration, and the model stays the record.
        </Model>
        <Model name="Muse Voice Transcribe" role="Talk to ORCA" icon={<Mic size={20} aria-hidden />} tone="voice">
          Hold to talk, or go hands-free. Speech streams in real time, biased to BIM words and the open model's names,
          and becomes a chat message.
        </Model>
      </div>
    </Section>

    <Section kicker="Context, not guesswork" title="What Muse is told about a clash">
      <ul className="oa-told oa-reveal">
        <li><Eye size={16} aria-hidden /><span><b>Three pictures</b> the pair alone, the pair in its surroundings, and a side view</span></li>
        <li><Boxes size={16} aria-hidden /><span><b>What each element is</b> its class, size, profile, level, system and which way it runs</span></li>
        <li><ScanSearch size={16} aria-hidden /><span><b>Openings</b> in the obstacle, found by ray casting its real geometry</span></li>
        <li><Ruler size={16} aria-hidden /><span><b>Free room</b> above and beside, clear of everything along that stretch</span></li>
        <li><Network size={16} aria-hidden /><span><b>Nearby clashes</b> of the element that can move, so one edit can clear several</span></li>
        <li><ClipboardCheck size={16} aria-hidden /><span><b>Your requirements</b> only where they differ from the defaults</span></li>
        <li className="wide"><TriangleAlert size={16} aria-hidden /><span><b>Every failed idea</b> why it failed, and what it hit, by name</span></li>
      </ul>
    </Section>

    <Section kicker="Kept in bounds" title="Guardrails on a public demo">
      <div className="oa-cards three">
        <Card icon={<ShieldCheck size={20} aria-hidden />} title="Keys stay on the server">The browser never sees an API key; only the Python server calls the models.</Card>
        <Card icon={<Cpu size={20} aria-hidden />} title="Caps on every paid call">Proposals, second tries, chat, voice and built views are capped per visitor and per day.</Card>
        <Card icon={<FileText size={20} aria-hidden />} title="AI text is marked">Explanations in the PDF are marked AI-drafted, and a page stays DRAFT until every team has reviewed it.</Card>
      </div>
    </Section>
  </>;
}

function Inside() {
  return <>
    <Section kicker="One page, one server, the models" title="How the pieces fit">
      <div className="oa-arch oa-reveal" role="img" aria-label="The browser talks to the ORCA server over HTTP and streams; the server calls the models; agents connect over MCP.">
        <div className="oa-arch-col">
          <p className="oa-arch-h"><Eye size={15} aria-hidden /> The browser</p>
          <ArchBox title="React app">Panels, chat, tours, the report dialog</ArchBox>
          <ArchBox title="3D viewer">three.js and web-ifc; one batched mesh per model</ArchBox>
          <ArchBox title="Voice">The microphone, streamed for live captions</ArchBox>
        </div>
        <div className="oa-flow" aria-hidden><span>HTTP and live streams</span></div>
        <div className="oa-arch-col server">
          <p className="oa-arch-h"><Server size={15} aria-hidden /> The ORCA server <small>one container</small></p>
          <ArchBox title="API and MCP">Routes, streamed steps, the voice relay, the agents' door</ArchBox>
          <ArchBox title="Workspace">Open models, clash reports and jobs, held in memory</ArchBox>
          <ArchBox title="Agent workflows">Propose, plans, triage, titles, chat, second tries</ArchBox>
          <ArchBox title="Geometry">IfcOpenShell: detect, check, edit; OpenCASCADE for STEP</ArchBox>
        </div>
        <div className="oa-flow" aria-hidden><span>model calls</span></div>
        <div className="oa-arch-col">
          <p className="oa-arch-h"><Brain size={15} aria-hidden /> The models</p>
          <ArchBox title="Meta's API">Muse Spark, Muse Wonder, Muse Image, Muse Voice</ArchBox>
          <ArchBox title="Baseten">Muse Spark Open, when switched on</ArchBox>
          <ArchBox title="Your agent" dashed>Any MCP client, on a pairing link</ArchBox>
        </div>
      </div>
      <p className="oa-intro">
        Every long job (a check, a proposal, triage, a plan, the report) streams its steps as it goes, so the page can
        show the agent thinking and drive the 3D view. Geometry runs one operation at a time under one lock; model calls
        run side by side.
      </p>
    </Section>

    <Section kicker="Open formats in, open formats out" title="What goes in and what comes out">
      <div className="oa-io oa-reveal">
        <div>
          <p className="oa-arch-h">In</p>
          <IoRow title="IFC models">Several at once, in shared coordinates</IoRow>
          <IoRow title="STEP files">Mechanical CAD, converted to IFC as it opens</IoRow>
          <IoRow title="Navisworks reports">Clash XML with its pictures, matched to the model</IoRow>
          <IoRow title="Requirements">An optional JSON file of your project's rules</IoRow>
        </div>
        <div className="oa-io-core" aria-hidden><span>ORCA</span></div>
        <div>
          <p className="oa-arch-h">Out</p>
          <IoRow title="Edited IFC">Each changed model once, with all its fixes</IoRow>
          <IoRow title="Edited STEP">Written back, parts keeping names and colours</IoRow>
          <IoRow title="PDF report">A design coordination report, per team if you like</IoRow>
          <IoRow title="BCF 2.1">Issues with camera, coloured pair and reviews</IoRow>
        </div>
      </div>
    </Section>

    <Section kicker="Built with" title="The stack">
      <div className="oa-stack oa-reveal">
        {[["React 19", "the page"], ["TypeScript", "all of it"], ["Vite", "the build"], ["three.js", "the 3D view"], ["web-ifc", "IFC in the browser"],
          ["Python 3.13", "the server"], ["FastAPI", "routes and streams"], ["IfcOpenShell", "clashes, checks, edits"], ["OpenCASCADE", "STEP in and out"],
          ["WeasyPrint", "the PDF"], ["MCP", "agents"], ["Modal", "hosting"]].map(([n, w]) => <span key={n}><b>{n}</b>{w}</span>)}
      </div>
      <p className="oa-note"><Layers size={15} aria-hidden /> For developers: the repository's <code>docs/architecture/</code> maps
        every module, route, model call and diagram in depth.</p>
    </Section>
  </>;
}

function Proof({ reduced }: { reduced: boolean }) {
  return <>
    <Section kicker="Measured, not promised" title="Results on the demos">
      <div className="oa-stats">
        <Stat value={<><CountUp to={3} reduced={reduced} /> of 3</>} label="answer key, first try"
          note="Northbank's girder clashes fixed at the designer's own heights: duct +400, tray +250, water +280 mm." />
        <Stat value={<><CountUp to={161} reduced={reduced} /></>} unit="parts" label="from one STEP file"
          note="The cell's parts keep their names and colours; Muse names what each one is." />
        <Stat value={<><CountUp to={25} reduced={reduced} /> of 25</>} label="opening hosts judged right"
          note="Which kinds of element may take a hole for a service, read by Muse Spark against an answer key." />
        <Stat value={<><CountUp to={150} reduced={reduced} /></>} unit="MB" label="model through the page"
          note="Uploaded, unpacked and opened in about two minutes: the demo's upload cap." />
      </div>
      <div className="oa-results oa-reveal">
        <Result ok title="Triage">464 clashes sorted in under 2 minutes on Muse Spark Open, alike clashes read once (39 calls); the answer key read as real.</Result>
        <Result ok title="Not a clash">A pad on its ground beam, a transom at its mullion, a beam at its column: all called by design, and none of them cut.</Result>
        <Result ok title="The machine cell">All 17 planted clashes found, nothing unexpected; the fixed revision checks clean.</Result>
        <Result ok title="Every fix kind">Move, offset, trim, route and opening verified on the demos' planted cases; resize on a test model.</Result>
      </div>
    </Section>

    <Section kicker="How it is kept honest" title="Tested at every level">
      <div className="oa-cards four">
        <Card icon={<ShieldCheck size={20} aria-hidden />} title="Server tests">Geometry, detection, every fix kind, the agent loop with a scripted model, the API and MCP.</Card>
        <Card icon={<Eye size={20} aria-hidden />} title="Web tests">The app's state, layouts and breakpoints, uploads, patching fixes into the viewer.</Card>
        <Card icon={<Target size={20} aria-hidden />} title="Evals">Real model runs against answer keys, appended to a results file that is never rewritten.</Card>
        <Card icon={<MousePointerClick size={20} aria-hidden />} title="In the browser">The golden path end to end, on desktop and on phone and tablet profiles.</Card>
      </div>
    </Section>

    <Section kicker="Said plainly" title="What ORCA doesn't do (yet)">
      <ul className="oa-limits oa-reveal">
        <li><TriangleAlert size={16} aria-hidden /><span><b>It doesn't sign off engineering.</b> Whether a beam can take a hole, or a flatter duct still carries its air, needs the designer's review. Options say whose.</span></li>
        <li><TriangleAlert size={16} aria-hidden /><span><b>Edits live in memory.</b> A restart, or opening the models again, starts clean: export what you keep.</span></li>
        <li><TriangleAlert size={16} aria-hidden /><span><b>Some shapes are out of reach.</b> Offsets and routes need straight horizontal runs with plain rectangular or round sections; hollow, rounded and sloped compound routes are not edited.</span></li>
        <li><TriangleAlert size={16} aria-hidden /><span><b>STEP parts mostly move.</b> Offsets and trims work on exact bars and rods; meshed parts can only be moved.</span></li>
        <li><TriangleAlert size={16} aria-hidden /><span><b>No accounts yet.</b> A session lives in this browser and on the server until it is evicted; saved projects come later.</span></li>
      </ul>
    </Section>

    <Section kicker="Hackathon rules" title="Built during the event">
      <p className="oa-intro">
        Everything in ORCA was written from Oct 27, 2026, for the Meta Global AI Developer Hackathon, Startup track. The
        demo models were generated by IssueLab's own scripts. No customer data, ever.
      </p>
    </Section>
  </>;
}

function TabFoot({ tab, onTab }: { tab: AboutTab; onTab: (t: AboutTab) => void }) {
  const i = ABOUT_TABS.findIndex((t) => t.id === tab);
  const next = ABOUT_TABS[i + 1];
  if (!next) return null;
  return <button className="oa-next end" onClick={() => onTab(next.id)}>Next: {next.label} <ArrowRight size={16} aria-hidden /></button>;
}

/* ------------------------------------------------------------------ animated pictures */

/** The loop in the hero: a dot runs round Observe → Resolve → Check → Apply; each letter lights as it passes. */
function OrcaLoop({ reduced }: { reduced: boolean }) {
  const nodes = [{ l: "O", w: "Observe", x: 160, y: 40 }, { l: "R", w: "Resolve", x: 280, y: 160 },
    { l: "C", w: "Check", x: 160, y: 280 }, { l: "A", w: "Apply", x: 40, y: 160 }];
  return (
    <svg className="oa-loop" viewBox="-6 -6 332 332" role="img" aria-label="The ORCA loop: Observe, Resolve, Check, Apply, and round again">
      <defs>
        <linearGradient id="oa-ring" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#7fb6e8" /><stop offset="1" stopColor="#12b5cb" />
        </linearGradient>
      </defs>
      <circle cx="160" cy="160" r="120" className="oa-loop-ring" />
      <circle cx="160" cy="160" r="92" className="oa-loop-inner" />
      <path id="oa-loop-path" d="M160 40 A120 120 0 1 1 159.99 40" fill="none" />
      {!reduced && (
        <circle r="7" className="oa-loop-dot">
          <animateMotion dur="8s" repeatCount="indefinite"><mpath href="#oa-loop-path" /></animateMotion>
        </circle>
      )}
      {nodes.map((n, i) => (
        <g key={n.l} className="oa-loop-node" style={{ animationDelay: `${i * 2}s` }}>
          <circle cx={n.x} cy={n.y} r="30" />
          <text x={n.x} y={n.y + 1} className="oa-loop-letter">{n.l}</text>
          <text x={n.x} y={n.y + 17} className="oa-loop-word">{n.w}</text>
        </g>
      ))}
      <text x="160" y="152" className="oa-loop-c1">verified</text>
      <text x="160" y="176" className="oa-loop-c2">model edits</text>
    </svg>
  );
}

/** Northbank #1 end-on: the duct through the girder's web, then raised through its web opening with bends. */
function ClashScene() {
  return (
    <figure className="oa-scene oa-reveal">
      <svg viewBox="0 0 480 230" role="img" aria-label="A duct runs through a steel girder's web; ORCA raises the middle of the duct through the opening in the web, with bends either side.">
        <defs>
          <pattern id="oa-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="6" stroke="#5f7d64" strokeWidth="1.2" />
          </pattern>
        </defs>
        <line x1="10" y1="205" x2="470" y2="205" className="oa-scene-floor" />
        <g className="oa-girder">
          <rect x="196" y="22" width="88" height="14" rx="2" />
          <rect x="232" y="36" width="16" height="22" />
          <rect x="232" y="104" width="16" height="74" />
          <rect x="196" y="178" width="88" height="14" rx="2" />
          <rect x="232" y="58" width="16" height="46" className="oa-opening" />
        </g>
        <g className="oa-swap-a">
          <path d="M20 135 H460" className="oa-duct red" />
          <rect x="230" y="119" width="20" height="32" className="oa-hit" />
          <circle cx="240" cy="135" r="20" className="oa-ping" />
        </g>
        <g className="oa-swap-b">
          <path d="M20 135 H140 Q156 135 162 120 L176 96 Q182 81 198 81 H282 Q298 81 304 96 L318 120 Q324 135 340 135 H460" className="oa-duct teal" />
          <path d="M240 60 V68 M240 94 V102" className="oa-gap" />
        </g>
        <text x="20" y="215" className="oa-scene-label">Supply air duct</text>
        <text x="300" y="16" className="oa-scene-label">Transfer girder, end on</text>
      </svg>
      <figcaption>
        <span className="oa-swap-a"><b className="bad">Clash.</b> The duct runs straight through the girder's web.</span>
        <span className="oa-swap-b"><b className="ok">Verified.</b> Raised 400 mm through the web opening, 50 mm clear all round.</span>
      </figcaption>
    </figure>
  );
}

const LOOP_STEPS: { at: "propose" | "check" | "back" | "shown"; text: ReactNode; tone?: "fail" | "pass" }[] = [
  { at: "propose", text: <>Muse Spark: <i>move the whole cable tray up 250 mm</i></> },
  { at: "check", text: <>Geometry tries it in the model…</> },
  { at: "back", tone: "fail", text: <>Fails: a long run hits walls and other services along its length. That reason goes back to Muse.</> },
  { at: "propose", text: <>Muse Spark: <i>offset only the stretch at the girder, up 250 mm, with bends</i></> },
  { at: "check", text: <>Geometry tries it in the model…</> },
  { at: "shown", tone: "pass", text: <>Passes: clash gone, clearance kept, nothing new hit. You see it as a verified option.</> },
];

function VerifyLoop({ reduced }: { reduced: boolean }) {
  const [i] = useTicker(LOOP_STEPS.length, 2300, !reduced);
  const s = reduced ? LOOP_STEPS[LOOP_STEPS.length - 1] : LOOP_STEPS[i];
  const tone = s.tone ?? "";
  const node = (at: string, icon: ReactNode, title: string, sub: string) => (
    <div className={`oa-vl-node${s.at === at ? ` on ${tone}` : ""}`}>{icon}<b>{title}</b><span>{sub}</span></div>
  );
  return (
    <div className="oa-vl oa-reveal">
      <div className="oa-vl-row">
        {node("propose", <Sparkles size={22} aria-hidden />, "Propose", "Muse Spark suggests an edit")}
        <div className={`oa-vl-arrow${s.at === "check" ? " on" : ""}`} aria-hidden />
        {node("check", <ShieldCheck size={22} aria-hidden />, "Check", "tried in the real model, then undone")}
        <div className={`oa-vl-arrow${s.at === "shown" ? " on pass" : ""}`} aria-hidden />
        {node("shown", <Check size={22} aria-hidden />, "Verified option", "ranked and shown to you")}
      </div>
      <div className={`oa-vl-back${s.at === "back" ? " on" : ""}`} aria-hidden><span>back with the reason it failed, and what it hit</span></div>
      <p className={`oa-vl-status ${tone}`} key={reduced ? "still" : i}>{s.text}</p>
      <p className="oa-vl-note">Illustrated with Northbank's cable tray: whole-run moves fail there, and a local offset at the
        designer's height passes.</p>
    </div>
  );
}

/* The fix pictures: each swaps between before (red A against green B) and after (teal A), in a loop. */
function Art({ label, before, after }: { label: string; before: ReactNode; after: ReactNode }) {
  return (
    <svg viewBox="0 0 200 110" role="img" aria-label={label}>
      <g className="oa-swap-a">{before}</g>
      <g className="oa-swap-b">{after}</g>
    </svg>
  );
}
function ArtMove() {
  return <Art label="A pipe through a beam moves up, clear of it."
    before={<><rect x="82" y="40" width="36" height="50" className="b" /><rect x="30" y="58" width="140" height="14" rx="7" className="a" /><circle cx="100" cy="65" r="12" className="oa-ping" /></>}
    after={<><rect x="82" y="40" width="36" height="50" className="b" /><rect x="30" y="16" width="140" height="14" rx="7" className="ok" /><path d="M100 54 V36" className="oa-arrow" /></>} />;
}
function ArtOffset() {
  return <Art label="A duct through a beam: its middle rises over the beam with bends."
    before={<><rect x="85" y="50" width="30" height="50" className="b" /><path d="M10 72 H190" className="line a" /><circle cx="100" cy="72" r="12" className="oa-ping" /></>}
    after={<><rect x="85" y="50" width="30" height="50" className="b" /><path d="M10 72 H50 Q58 72 61 64 L68 44 Q71 36 79 36 H121 Q129 36 132 44 L139 64 Q142 72 150 72 H190" className="line ok" /></>} />;
}
function ArtTrim() {
  return <Art label="A transom running into a mullion is cut back to butt its face."
    before={<><rect x="120" y="8" width="16" height="94" className="b" /><rect x="20" y="48" width="126" height="14" className="a" /><rect x="120" y="48" width="16" height="14" className="hit" /></>}
    after={<><rect x="120" y="8" width="16" height="94" className="b" /><rect x="20" y="48" width="100" height="14" className="ok" /><path d="M146 40 L146 70" className="oa-cut" /></>} />;
}
function ArtRoute() {
  return <Art label="Plan view: a pipe through two columns steps north round both."
    before={<><rect x="58" y="45" width="24" height="24" className="b" /><rect x="118" y="45" width="24" height="24" className="b" /><path d="M10 57 H190" className="line thin a" /><circle cx="70" cy="57" r="10" className="oa-ping" /></>}
    after={<><rect x="58" y="45" width="24" height="24" className="b" /><rect x="118" y="45" width="24" height="24" className="b" /><path d="M10 57 H38 Q44 57 46 51 L50 31 Q52 25 58 25 H142 Q148 25 150 31 L154 51 Q156 57 162 57 H190" className="line thin ok" /></>} />;
}
function ArtPenetration() {
  return <Art label="A pipe through a solid wall: an opening is asked for around it."
    before={<><rect x="88" y="8" width="24" height="94" className="b" /><path d="M10 55 H190" className="line a" /><circle cx="100" cy="55" r="12" className="oa-ping" /></>}
    after={<><rect x="88" y="8" width="24" height="36" className="b" /><rect x="88" y="66" width="24" height="36" className="b" /><rect x="85" y="43" width="30" height="24" rx="3" className="void" /><path d="M10 55 H190" className="line ok" /></>} />;
}
function ArtResize() {
  return <Art label="A tall duct under a beam becomes flatter and wider where it passes."
    before={<><rect x="78" y="8" width="44" height="42" className="b" /><rect x="10" y="40" width="180" height="42" className="a" /><rect x="78" y="40" width="44" height="10" className="hit" /></>}
    after={<><rect x="78" y="8" width="44" height="42" className="b" /><path d="M10 40 H58 L70 58 H130 L142 40 H190 V82 H10 Z" className="ok" /></>} />;
}
function ArtCombined() {
  return <Art label="Two services through one beam: one rises over it, the other drops under it, checked together."
    before={<><rect x="85" y="38" width="30" height="38" className="b" /><path d="M10 50 H190" className="line thin a" /><path d="M10 66 H190" className="line thin a" /><circle cx="100" cy="58" r="14" className="oa-ping" /></>}
    after={<><rect x="85" y="38" width="30" height="38" className="b" /><path d="M10 50 H54 Q60 50 62 44 L66 32 Q68 26 74 26 H126 Q132 26 134 32 L138 44 Q140 50 146 50 H190" className="line thin ok" /><path d="M10 66 H54 Q60 66 62 72 L66 84 Q68 90 74 90 H126 Q132 90 134 84 L138 72 Q140 66 146 66 H190" className="line thin ok" /></>} />;
}

/* ------------------------------------------------------------------ small parts */

function Section({ kicker, title, children }: { kicker: string; title: string; children: ReactNode }) {
  return (
    <section className="oa-section">
      <header className="oa-reveal"><p className="oa-kicker">{kicker}</p><h2>{title}</h2></header>
      {children}
    </section>
  );
}
function Card({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return <div className="oa-card oa-reveal"><span className="oa-card-icon">{icon}</span><h3>{title}</h3><p>{children}</p></div>;
}
function Stat({ value, unit, label, note }: { value: ReactNode; unit?: string; label: string; note: string }) {
  return (
    <div className="oa-stat oa-reveal">
      <span className="oa-stat-v">{value}{unit && <small> {unit}</small>}</span>
      <b>{label}</b>
      <span>{note}</span>
    </div>
  );
}
function Check4({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return <div className="oa-check oa-reveal"><span>{icon}</span><b>{title}</b><p>{children}</p></div>;
}
function Model({ name, role, icon, tone, children }: { name: string; role: string; icon: ReactNode; tone: string; children: ReactNode }) {
  return (
    <div className={`oa-model ${tone} oa-reveal`}>
      <span className="oa-model-icon">{icon}</span>
      <div><b>{name}</b><span className="oa-model-role">{role}</span><p>{children}</p></div>
    </div>
  );
}
function ArchBox({ title, dashed, children }: { title: string; dashed?: boolean; children: ReactNode }) {
  return <div className={`oa-arch-box${dashed ? " dashed" : ""}`}><b>{title}</b><span>{children}</span></div>;
}
function IoRow({ title, children }: { title: string; children: ReactNode }) {
  return <div className="oa-io-row"><b>{title}</b><span>{children}</span></div>;
}
function Result({ ok, title, children }: { ok?: boolean; title: string; children: ReactNode }) {
  return <div className="oa-result">{ok && <Check size={16} aria-hidden />}<div><b>{title}</b><span>{children}</span></div></div>;
}

/** Counts up to `to` the first time it scrolls into view; reduced motion shows the number at once. */
function CountUp({ to, reduced }: { to: number; reduced: boolean }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [v, setV] = useState(reduced ? to : 0);
  useEffect(() => {
    if (reduced) { setV(to); return; }
    const el = ref.current;
    let raf = 0;
    const run = () => {
      const t0 = performance.now();
      const step = (t: number) => {
        const k = Math.min(1, (t - t0) / 1400);
        setV(Math.round(to * (1 - Math.pow(1 - k, 3))));
        if (k < 1) raf = requestAnimationFrame(step);
      };
      raf = requestAnimationFrame(step);
    };
    if (!el || typeof IntersectionObserver === "undefined") { run(); return () => cancelAnimationFrame(raf); }
    const io = new IntersectionObserver(([e]) => { if (e?.isIntersecting) { io.disconnect(); run(); } }, { threshold: 0.4 });
    io.observe(el);
    return () => { io.disconnect(); cancelAnimationFrame(raf); };
  }, [to, reduced]);
  return <span ref={ref} className="mono">{v.toLocaleString("en-GB")}</span>;
}

function useReducedMotion(): boolean {
  const query = "(prefers-reduced-motion: reduce)";
  const [reduced, setReduced] = useState(() => typeof matchMedia !== "undefined" && matchMedia(query).matches);
  useEffect(() => {
    if (typeof matchMedia === "undefined") return;
    const q = matchMedia(query);
    const on = () => setReduced(q.matches);
    q.addEventListener("change", on);
    return () => q.removeEventListener("change", on);
  }, []);
  return reduced;
}

/** 0 … n-1, one step every `ms` while `running`. */
function useTicker(n: number, ms: number, running: boolean): [number, (i: number) => void] {
  const [i, setI] = useState(0);
  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(() => setI((x) => (x + 1) % n), ms);
    return () => window.clearInterval(t);
  }, [n, ms, running]);
  return [i, setI];
}
