/**
 * The guided tour: the Sightline story told on the real app. Each step points at a real control and waits for the
 * visitor to use it (the step moves on when the app reaches the state it describes); "Show me" does the click for
 * anyone who would rather watch. Live steps that call Muse Spark offer a recorded run when the live one fails or is slow
 * (web/public/tour/*.json: real runs, replayed through the same viewer and pilot, and labelled as recorded).
 */
import { ArrowLeft, ArrowRight, Hand, PlayCircle, X } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";

// The tour's clashes, by their two elements (GlobalIds): the same whether Sightline's check found them or a report
// was imported, whatever number they get.
export const TOUR = {
  duct: ["2AbvqKF25LGeR0M34N_jld", "1eVHoPtl1IhAbbhivqVqb0"],   // supply air main through the Level 02 transfer girder (#042)
  joint: ["3FZ5_g0pXGx9qRfB9Lw5Mw", "2AgFm_5w1SU9p7tLtV6sDp"],  // curtain-wall transom 30 mm into a mullion
  girder: "1eVHoPtl1IhAbbhivqVqb0",
} as const;
export const TOUR_QUESTION = "Why are there so many clashes on Level 02? Fix the root cause.";

/** What the tour can see of the app. */
export interface TourState {
  busy: boolean; reportOpen: boolean; modelsOpen: boolean;
  triageStarted: boolean; triageDone: boolean; triageCount: number; triageTotal: number; realCount: number;
  filter: string | null; clashId: string | null; tab: string;
  fixHidden: boolean;  // the clash panel says "not a clash" and offers "Propose a fix anyway" instead
  proposing: boolean; proposingFor: number; options: number; proposalDone: boolean; error: string | null; replaying: boolean;
  compare: string; fixed: string[];
  planRunning: boolean; planFor: number; planReady: boolean; planError: string | null;
  patternsRead: boolean; reviewedCount: number; signoffs: number; docOpen: boolean; docReady: boolean;
  /** The tour's clashes in the open report: their ids and numbers (null until the check has found them). */
  duct: { id: string; number: number } | null; joint: { id: string; number: number } | null;
}

/** What "Show me" can do for the visitor beyond clicking the control the step points at. */
export interface TourActions {
  filterReal: () => void; clearFilter: () => void; selectClash: (which: "duct" | "joint") => void; compare: (m: "before" | "after" | "both") => void;
  replay: (what: "duct" | "joint" | "plan") => void; ask: (send: boolean) => void; signoff: () => void;
  overview: () => void; closeReport: () => void;
}

interface Step {
  act: string;
  title: string;
  body: (s: TourState) => React.ReactNode;
  target?: string | ((s: TourState) => string);  // CSS selector of the control to point at
  done?: (s: TourState) => boolean;    // the visitor has done what the step asks: move on
  show?: { label: string; run?: (a: TourActions, s: TourState) => void; hidden?: (s: TourState) => boolean };  // no run: click the target
  enter?: (a: TourActions, s: TourState) => void;  // set the page up for this step (a filter that would hide the target)
  reveal?: boolean;                    // open the target's group in the clash list and scroll to it
  fallback?: { what: "duct" | "joint" | "plan"; when: (s: TourState) => boolean };  // offer a recorded run
}

const row = (which: "duct" | "joint") => (s: TourState) => `[data-clash="${s[which]?.id ?? "none"}"] .clash-main`;
const no = (c: TourState["duct"]) => (c ? <b>#{c.number}</b> : null);
const ran = (s: TourState) => s.proposing || s.proposalDone;
const slowProposal = (s: TourState) => !s.proposalDone && !s.replaying && (!!s.error || s.proposingFor > 45 || !s.proposing);

export const STEPS: Step[] = [
  // 1. The problem
  {
    act: "Design coordination", title: "A building, three teams, one set of models",
    body: () => <>Structure, MEP and Architecture each model the same building. Coordination means making their models
      agree before anything is built. Open the demo: an office building called Northbank. Sightline checks every pair of
      building models, and each against itself; the site model (street, riverside, trees) is there for context.</>,
    target: "[data-tour=demo]", done: (s) => s.reportOpen && s.modelsOpen && !s.busy,
    show: { label: "Open it for me" },
  },
  {
    act: "Design coordination", title: "Hundreds of clashes. Most are detail",
    body: (s) => <>Sightline found {s.triageTotal || "hundreds of"} clashes, each with a number and a name Muse writes from
      its facts. What was checked, and what was left out on purpose (pieces joined by ports, a door in its wall), is under
      <b> What was checked</b>. A coordinator would open them one by one: bolts in their plates, beams into columns, a
      duct through a girder. Only a few need anyone to change anything.</>,
    target: "[data-tour=detected]",
  },
  // 2. Triage
  {
    act: "Triage", title: "Sort them all first",
    body: (s) => s.triageDone
      ? <>Done: {s.triageTotal} clashes sorted by <b>Muse Spark Open</b>, an open-weights model, many at a time; alike
        clashes were read once.</>
      : s.triageStarted
        ? <>Triage is running: {s.triageCount} of {s.triageTotal}. <b>Muse Spark Open</b> reads eight at a time, and
          alike clashes (forty bolts in forty plates) only once. Carry on: it keeps going.</>
        : <>Click <b>Triage all</b>. Every clash gets a verdict: a real problem, by design, not physical, or a modelling
          error for the model's author.</>,
    target: "[data-tour=triage]", done: (s) => s.triageDone,
    show: { label: "Start it for me", run: () => (document.querySelector("[data-tour=triage] .btn.primary") as HTMLElement | null)?.click(),
      hidden: (s) => s.triageStarted },
  },
  {
    act: "Triage", title: "Just the real ones",
    body: (s) => <>Click <b>Real problem</b> to keep only the clashes that need a change{s.realCount ? `: ${s.realCount} of ${s.triageTotal}` : ""}.
      The rest stay in the report, sorted, for the record.</>,
    target: "[data-tour=triage-real]", done: (s) => s.filter === "real_clash",
    show: { label: "Filter for me", run: (a) => a.filterReal() },
  },
  // 3. One fix, live
  {
    act: "One fix, live", title: "A duct through a transfer girder",
    body: (s) => <>Open {no(s.duct) ?? "the supply air main"} under <b>MEP vs Structure</b>: the Level 02 supply air main runs
      straight through a 1 m deep steel transfer girder. A classic services against structure clash.</>,
    target: row("duct"), reveal: true, done: (s) => !!s.duct && s.clashId === s.duct.id,
    show: { label: "Open it for me", run: (a) => a.selectClash("duct") },
  },
  {
    act: "One fix, live", title: "What Sightline knows",
    body: () => <>Sightline's three views of the clash (red is A, green is B), taken as you opened it, the two elements in
      the IFC models, and how far one must move to clear the other. The viewer has gone to where they meet.</>,
    target: ".clash-panel",
  },
  {
    act: "One fix, live", title: "Ask for a fix",
    body: () => <>Click <b>Propose fixes</b>. Muse Spark reads the clash and suggests edits to the real IFC elements;
      Sightline checks every one against the whole building before you see it.</>,
    target: "[data-tour=propose]", done: ran, show: { label: "Ask for me" },
  },
  {
    act: "One fix, live", title: "Sightline takes the camera",
    body: (s) => s.proposalDone
      ? <>{s.options ? <>Done: <b>{s.options} verified option{s.options > 1 ? "s" : ""}</b>.</> : "No option passed this time."}</>
      : <>The glowing border means Sightline is driving. Muse Spark's reasoning appears as it thinks, then each idea is tried
        in the model: <b className="tour-amber">amber</b> while it is checked, <b className="tour-teal">teal</b> when clear,
        <b className="tour-magenta"> magenta</b> for what it would hit. Touch the model to take over; Sightline keeps working.</>,
    target: "main.stage", done: (s) => s.proposalDone && s.options > 0,
    fallback: { what: "duct", when: slowProposal },
  },
  {
    act: "One fix, live", title: "A real edit, proved by geometry",
    body: () => <>The duct is split either side of the girder and its middle raised 400 mm through the girder's web opening,
      with bends. Switch <b>Before / After / Both</b> to compare. <i>Verified</i> means the clash is gone, it is at least
      25 mm clear, and it hits nothing else in the building.</>,
    target: ".compare", done: (s) => s.compare === "both",
    show: { label: "Show both", run: (a) => a.compare("both") },
  },
  {
    act: "One fix, live", title: "Hold on: it isn't only this duct",
    body: () => <>The same girder is also hit by a cable tray and a cold water main: the next two in the list. (Navisworks
      never reported the cold water main; Sightline's check did.) Fixed one at a time, the three fixes could run into each
      other. Leave this one for now: we'll come back to the girder and fix all three together.</>,
    target: ".pane.right",
  },
  // 4. A different kind of fix
  {
    act: "A joint, not a move", title: "A transom 30 mm into a mullion",
    body: (s) => <>Not every clash is fixed by moving something. Open this {no(s.joint) ?? "one"}: in the curtain wall, a horizontal
      transom runs 30 mm into the vertical mullion it should stop against. Triage reads joints like this as by design
      (frames are often modelled overlapping), but a model going to fabrication needs a clean joint.</>,
    target: row("joint"), reveal: true, enter: (a) => a.clearFilter(), done: (s) => !!s.joint && s.clashId === s.joint.id,
    show: { label: "Open it for me", run: (a) => a.selectClash("joint") },
  },
  {
    act: "A joint, not a move", title: "Ask again",
    body: (s) => s.proposalDone && s.options
      ? <>A <b>trim</b>: the transom's end is cut back to butt the mullion's face. Nothing moves. Sightline marks it
        <i> model cleanup</i>: both are in the Architecture model, so it tidies the joint for its author rather than
        settling something between teams.</>
      : s.fixHidden
        ? <>Sightline agrees it's by design, and offers to mark it so. You can still ask: click <b>Propose a fix anyway</b>,
          then <b>Propose fixes</b>, and watch for a different kind of edit.</>
        : <>Click <b>Propose fixes</b> and watch for a different kind of edit.</>,
    target: "[data-tour=propose], [data-tour=fix-anyway]", done: (s) => s.proposalDone && s.options > 0,
    show: { label: "Ask for me", hidden: ran, run: () => {
      (document.querySelector("[data-tour=fix-anyway]") as HTMLElement | null)?.click();
      window.setTimeout(() => (document.querySelector("[data-tour=propose]") as HTMLElement | null)?.click(), 300);
    } },
    fallback: { what: "joint", when: (s) => !s.proposalDone && !s.replaying && (!!s.error || s.proposingFor > 45) },
  },
  {
    act: "A joint, not a move", title: "Accept it",
    body: () => <>Click <b>Accept this cleanup</b>. The server edits the IFC model, the viewer reloads it, and the clash
      is marked fixed.</>,
    target: "[data-tour=accept]", reveal: true, done: (s) => !!s.joint && s.fixed.includes(s.joint.id), show: { label: "Accept for me" },
  },
  // 5. Root cause
  {
    act: "The root cause", title: "Ask Sightline, like a colleague",
    body: () => <>Open <b>Chat</b>. It can read every clash and the models, check them again, measure, propose and plan,
      and it drives the page. The mic button takes voice too.</>,
    target: "[data-tour=tab-chat]", done: (s) => s.tab === "chat", show: { label: "Open it for me" },
  },
  {
    act: "The root cause", title: "Why so many on Level 02?",
    body: () => <>Ask: <i>"{TOUR_QUESTION}"</i> Sightline finds the element at the centre of the clashes (the girder),
      works out why, and plans fixes for everything that hits it, checked together.</>,
    target: "[data-tour=chat-send]", done: (s) => s.planRunning || s.planReady,
    show: { label: "Ask for me", run: (a) => a.ask(true) }, enter: (a) => a.ask(false),
  },
  {
    act: "The root cause", title: "One plan for the girder",
    body: (s) => s.planReady
      ? <>The plan is ready: the duct, the cable tray and the cold water main each get an offset through the girder's web
        openings, and the three are checked as one. That's the fix the designers made in their next revision.</>
      : <>Sightline names the cause, then runs a fix agent for each service in parallel and checks all the fixes together,
        so one can't collide with another.</>,
    target: "main.stage", done: (s) => s.planReady,
    fallback: { what: "plan", when: (s) => !s.planReady && !s.replaying && (!!s.planError || s.planFor > 75 || !s.planRunning) },
  },
  {
    act: "The root cause", title: "Accept the plan",
    body: () => <>Open the <b>Plan</b> tab and accept it: three services rerouted, one change to the model.</>,
    target: "[data-tour=accept-plan]", enter: () => (document.querySelector("[data-tour=tab-plan]") as HTMLElement | null)?.click(),
    done: (s) => !!s.duct && s.fixed.includes(s.duct.id), show: { label: "Accept for me" },
  },
  // 6. Judgement
  {
    act: "Not everything needs a fix", title: "Patterns",
    body: () => <>The same clash, many times. Click <b>Explain</b>: Muse Spark reads each pattern and says whether it is how
      the parts are meant to go together, a modelling error, or a real problem.</>,
    target: "[data-tour=explain]", done: (s) => s.patternsRead, show: { label: "Explain for me" }, enter: (a) => a.overview(),
  },
  {
    act: "Not everything needs a fix", title: "By design",
    body: () => <>Bolts in their plates, columns through slabs: that's how they're built. Mark the pattern <b>by design</b>
      (the tick); it leaves the open list, and Sightline suggests the rule that stops it coming back.</>,
    target: "[data-tour=pattern-by-design]", done: (s) => s.reviewedCount > 0,
    show: { label: "Mark it for me", run: () => (document.querySelector("[data-tour=mark-by-design]") as HTMLElement | null)?.click() },
  },
  // 7. Sign-off
  {
    act: "People decide", title: "Each team reviews",
    body: () => <>Back to the duct. Every team with an element in a clash reviews it: here MEP and Structure. Add a review:
      your name and a decision. No sign-in yet; the name goes in the report.</>,
    target: "[data-tour=review]", enter: (a) => a.selectClash("duct"), done: (s) => s.signoffs > 0,
    show: { label: "Review for me", run: (a) => a.signoff() },
  },
  {
    act: "People decide", title: "A report for the teams",
    body: () => <>Click <b>Report</b>. One PDF, or one per team, or one per model: you choose, and you confirm which team owns
      each model.</>,
    target: "[data-tour=report]", done: (s) => s.docOpen, show: { label: "Open it for me" },
  },
  {
    act: "People decide", title: "Build it",
    body: (s) => s.docReady
      ? <>Ready. Each clash that needs action has a page: Muse Spark's explanation (marked AI-drafted), the original next to
        the fix, and a review table per team. It says DRAFT until every team has reviewed.</>
      : <>Click <b>Build the report</b>. Muse Spark writes each explanation and a summary; it takes about a minute.</>,
    target: "[data-tour=build], [data-tour=download]", done: (s) => s.docReady, show: { label: "Build it for me", hidden: (s) => s.docReady },
  },
  {
    act: "Hand-off", title: "Into the tools teams already use",
    body: () => <>Download it: the PDFs, plus BCF issues that open in Revit, Navisworks, Solibri or BIMcollab, each assigned
      to the team that acts. <b>Export IFC</b> (top right) gives the edited models.</>,
    target: "[data-tour=download]",
  },
  // 9. Close
  {
    act: "Sightline", title: "Clashes fixed, proved, signed off", enter: (a) => { a.closeReport(); a.overview(); },
    body: () => <>
      <span className="tour-stats">
        <span><b>4 s</b> to check 1,732 elements</span>
        <span><b>&lt; 2 min</b> to triage 464 clashes</span>
        <span><b>~40 s</b> to a verified fix</span>
        <span><b>3 of 3</b> designer fixes matched</span>
      </span>
      Built during the hackathon with Muse Spark (reasoning, tools, images), Muse Spark Open on Baseten (bulk triage), Muse
      Voice Transcribe and IfcOpenShell. Every fix is a real IFC edit, checked against the whole building.</>,
  },
];

const PAD = 6;
const CARD_W = 340;

export function Tour({ state, actions, onClose }: { state: TourState; actions: TourActions; onClose: () => void }) {
  const [index, setIndex] = useState(0);
  const step = STEPS[index];
  const [rect, setRect] = useState<DOMRect | null>(null);
  const card = useRef<HTMLDivElement>(null);
  const [cardH, setCardH] = useState(200);
  const done = step.done?.(state) ?? false;
  const stateRef = useRef(state);
  stateRef.current = state;

  // Set the page up, then follow the target: it can scroll, resize, or appear later.
  useEffect(() => {
    step.enter?.(actions, stateRef.current);
    // Bring each control the step points at into view once: also one that appears later (Accept, Build), but
    // without fighting a visitor who scrolls away afterwards.
    // For a moment after the step starts or a new control appears, keep it in view: the page may still be changing
    // under it (another clash selected into the same panel moves everything).
    let shown: Element | null = null;
    let settle = Date.now() + 1500;
    const find = () => {
      const sel = typeof step.target === "function" ? step.target(stateRef.current) : step.target;
      const el = sel ? document.querySelector(sel) : null;
      if (el && el !== shown) {
        const group = step.reveal ? el.closest("details") : null;
        if (group && !group.open) group.open = true;
        shown = el;
        settle = Date.now() + 1500;
      }
      if (el && Date.now() < settle && !inView(el)) el.scrollIntoView({ block: "center", behavior: reducedMotion() ? "auto" : "smooth" });
      const r = el?.getBoundingClientRect();
      setRect(r && r.width && r.height ? r : null);
    };
    find();
    const timer = window.setInterval(find, 250);
    return () => window.clearInterval(timer);
  }, [index]);  // eslint-disable-line react-hooks/exhaustive-deps

  // When the visitor has done what the step asks, move on (after a beat, so they see it land).
  useEffect(() => {
    if (!done || !step.done || index >= STEPS.length - 1) return;
    const t = window.setTimeout(() => setIndex((i) => (i === index ? i + 1 : i)), 1100);
    return () => window.clearTimeout(t);
  }, [done, index]);  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);

  useLayoutEffect(() => { if (card.current) setCardH(card.current.offsetHeight); });

  const pos = place(rect, cardH);
  const offer = step.fallback && !done && step.fallback.when(state);
  const showMe = () => {
    if (step.show?.run) step.show.run(actions, state);
    else if (step.target) (document.querySelector(typeof step.target === "function" ? step.target(state) : step.target) as HTMLElement | null)?.click();
  };

  return (
    <div className="tour" role="dialog" aria-label="Guided tour" aria-live="polite">
      {rect
        ? <div className="tour-hole" style={{ left: rect.left - PAD, top: rect.top - PAD, width: rect.width + 2 * PAD, height: rect.height + 2 * PAD }} />
        : <div className="tour-dim" />}
      <div ref={card} className="tour-card" style={{ left: pos.left, top: pos.top, width: CARD_W }}>
        <div className="row">
          <span className="tour-act">{step.act} · {index + 1} of {STEPS.length}</span>
          <button className="ibtn" aria-label="End the tour" onClick={onClose}><X size={14} aria-hidden /></button>
        </div>
        <h3>{step.title}</h3>
        <p>{step.body(state)}</p>
        {state.replaying && !done && step.fallback && <p className="hint">Playing a recorded run of this step.</p>}
        {offer && (
          <p className="tour-fallback">{state.error || state.planError
            ? `The live run failed: ${state.error || state.planError}`
            : "The live run is taking a while, or didn't start."} You can watch a recorded run of the same step instead.
            <button className="btn small" onClick={() => actions.replay(step.fallback!.what)}><PlayCircle size={13} aria-hidden /> Watch a recorded run</button></p>)}
        <div className="tour-nav">
          <button className="btn small ghost" disabled={index === 0} onClick={() => setIndex(index - 1)}><ArrowLeft size={13} aria-hidden /> Back</button>
          <span className="spacer" />
          {step.show && !done && !step.show.hidden?.(state) &&
            <button className="btn small" onClick={showMe}><Hand size={13} aria-hidden /> {step.show.label}</button>}
          {index < STEPS.length - 1
            ? <button className={`btn small ${!step.done || done ? "primary" : ""}`} onClick={() => setIndex(index + 1)}
                title={step.done && !done ? "Skip this step" : undefined}>
                {step.done && !done ? "Skip" : "Next"} <ArrowRight size={13} aria-hidden /></button>
            : <button className="btn small primary" onClick={onClose}>Finish</button>}
        </div>
      </div>
    </div>
  );
}

/** Wholly visible: inside the window and inside every scrolling panel it sits in. */
function inView(el: Element) {
  const r = el.getBoundingClientRect();
  if (!r.width || !r.height) return true;  // hidden: nothing to scroll to
  const big = r.height > window.innerHeight * 0.6;  // the viewer or a panel: its top showing is enough
  const fits = (top: number, bottom: number, left: number, right: number) =>
    r.top >= top - 1 && (big ? r.top < bottom - 40 : r.bottom <= bottom + 1) && r.left >= left - 1 && r.right <= right + 1;
  if (!fits(0, window.innerHeight, 0, window.innerWidth)) return false;
  for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
    const o = getComputedStyle(p).overflowY;
    if (o !== "auto" && o !== "scroll") continue;
    const b = p.getBoundingClientRect();
    if (!fits(b.top, b.bottom, b.left, b.right)) return false;
  }
  return true;
}

const reducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

/** Beside the target if there is room (right, then left), else below or above it, kept on screen. */
function place(r: DOMRect | null, h: number) {
  const vw = window.innerWidth, vh = window.innerHeight, gap = 14;
  if (!r) return { left: (vw - CARD_W) / 2, top: Math.max(16, (vh - h) / 2) };
  const clampTop = (t: number) => Math.min(Math.max(12, t), vh - h - 12);
  const clampLeft = (l: number) => Math.min(Math.max(12, l), vw - CARD_W - 12);
  // A large target (the viewer): sit inside its lower left corner rather than off screen.
  if (r.width * r.height > 0.3 * vw * vh) return { left: clampLeft(r.left + 16), top: clampTop(r.bottom - h - 16) };
  if (r.right + gap + CARD_W < vw - 8) return { left: r.right + gap, top: clampTop(r.top) };
  if (r.left - gap - CARD_W > 8) return { left: r.left - gap - CARD_W, top: clampTop(r.top) };
  if (r.bottom + gap + h < vh) return { left: clampLeft(r.left), top: r.bottom + gap };
  return { left: clampLeft(r.left), top: clampTop(r.top - gap - h) };
}
