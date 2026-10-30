import { Bot, Boxes, Brain, Building2, Check, ChevronRight, CircleCheck, ClipboardCheck, ClipboardPlus, Compass, Download, FileSpreadsheet, FileText, FolderOpen, Hand, Info, List, LocateFixed, Menu, MessageSquare, Move, Navigation, Network, Plug, Radar, Sparkles, Upload, Wand2, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Activity, statusLine, type Progress } from "./Activity";
import { BuiltView, builtStep, cutText, type BuiltRun } from "./BuiltView";
import { changeText, clearanceText, editText, framePieces, hostRows, recEditText, reviewText } from "./fixKinds";
import { ChatPanel } from "./Chat";
import { ChatRequestOwner } from "./chatRequest";
import { ReportDialog, ReviewBlock } from "./ReportDoc";
import type { AgentLink, BuiltResult, EscalationInfo, LinkEvent, OpenedScene, OwnerSettings, Patch, SavedSession, SceneInfo, TriageModel } from "./api";
import { OwnerSettingsMenu } from "./Owner";
import { CELL, Tour, TOUR, TOUR_QUESTION, type TourActions, type TourState } from "./Tour";
import { RequirementsDialog } from "./Requirements";
import { ProjectStart } from "./ProjectStart";
import { localFile, uploadRefusal, uploadStatus } from "./uploads";
import { addByDesign, addPenetration, hasByDesign, hasPenetration, load as loadRequirements, save as saveRequirements, shortLabel, type Saved as SavedRequirements } from "./reqFile";
import { setRequirements, type Recommendation, type Requirements, type RuleAudit } from "./api";
import { api, ApiError, type DetectEvent, type DetectSetup, type DetectTest, type Detection, type ContextEvent, type ContextObjective, type ContextProposal, type Evidence, type Signoff, type Team, type AgentEvent, type ChatEvent, type Matches, type Measure, type Option, type Pattern, type PatternVerdict, type Plan, type PlanEvent, type PlanItem, type Proposal, type Report, type ReportClash, type RootCause, type TriageKind, type TriageVerdict, type Verdict } from "./api";
import { About } from "./About";
import { AgentDialog, timeLeft, type AgentLogEntry } from "./Agent";
import { ClashPanel, Lightbox } from "./ClashPanel";
import { PlanPanel, type PlanRun } from "./PlanPanel";
import { ContextPlan, contextStep, type ContextRun } from "./ContextPlan";
import { Insights } from "./Insights";
import { TriageCard, type TriageRun } from "./Triage";
import { DetectSetupCard, DetectSummary, type DetectProgress } from "./Detect";
import { ReportList, clashLabel, mm, type Review } from "./ReportList";
import { noClash } from "./noClash";
import { Popover, Tooltips } from "./ui";
import { Pilot, type PilotStatus } from "./pilot";
import { Viewer, serverPointToViewer, type BuiltPasses, type Mesh, type Preset, type Side, type ViewMode } from "./viewer/Viewer";
import { ViewerToolbar, type ToolbarState } from "./ViewerToolbar";
import { follow, useCoarse, useLayout, type Happening, type Snap } from "./layout";
import { SheetBar } from "./Sheet";
import { MenuSheet } from "./AppMenu";
import type * as THREE from "three";

type Stats = { elements: number; triangles: number; parseMs: number };
type Tab = "clash" | "plan" | "chat";
/** A fix as Show it built's capture takes it (Viewer.captureBuilt). */
type BuiltFix = Parameters<Viewer["captureBuilt"]>[0];

export function App() {
  const host = useRef<HTMLDivElement>(null);
  const viewer = useRef<Viewer | null>(null);
  // Side panel widths: dragged by their inner edge, remembered in this browser, double-click to reset.
  const [widths, setWidths] = useState(() => ({ left: stored("sightline.left-w", 310), right: stored("sightline.right-w", 380) }));
  const [resizing, setResizing] = useState<"left" | "right" | null>(null);
  // Phones and tablets (layout.ts, docs/mobile.md): the clash list in a bottom sheet's tab (phone) or a drawer (tablet),
  // how far the phone's sheet is pulled up, and the header's menu. The sheet follows what happens (see `followed`).
  const layout = useLayout();
  const compact = layout === "phone" || layout === "tablet";
  const coarse = useCoarse();
  const [listOpen, setListOpen] = useState(false);
  const [snap, setSnap] = useState<Snap>("half");
  const [menuOpen, setMenuOpen] = useState(false);
  // The left pane's tab over a report: the clash list, or Insights (the run, root causes, patterns).
  const [leftView, setLeftView] = useState<"clashes" | "insights">("clashes");
  const [toast, setToast] = useState<string | null>(null);
  const longPress = useRef<{ x: number; y: number; timer: number; fired: boolean } | null>(null);
  // While the agent works it drives the viewer (pilot.ts); touching the view takes it back.
  const [pilotStatus, setPilotStatus] = useState<PilotStatus | null>(null);
  const sides = useRef<string[]>([]);
  const pilot = useRef<Pilot | null>(null);
  const folderInput = useRef<HTMLInputElement>(null);
  const filesInput = useRef<HTMLInputElement>(null);
  const [samples, setSamples] = useState<string[]>([]);
  const [picked, setPicked] = useState<string[]>([]);
  const [stepFiles, setStepFiles] = useState<string[]>([]);  // open models that came from STEP (Export gives STEP back)
  const modelInput = useRef<HTMLInputElement>(null);
  const [sceneId, setSceneId] = useState<string | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [a, setA] = useState<string | null>(null);
  const [b, setB] = useState<string | null>(null);
  const [tool, setTool] = useState<ToolbarState>({ mode: "xray", edges: true, section: false, measure: false, hiddenModels: [] });
  const [modelNames, setModelNames] = useState<string[]>([]);
  const [selected, setSelected] = useState<{ globalId: string; info: Record<string, unknown> | null } | null>(null);
  const [measurePts, setMeasurePts] = useState<THREE.Vector3[]>([]);
  const [measured, setMeasured] = useState<number | null>(null);
  const down = useRef<{ x: number; y: number } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [chosen, setChosen] = useState<number | null>(null);
  const [manualDz, setManualDz] = useState(-0.25);
  const [manual, setManual] = useState<Verdict | null>(null);
  const [manualPreview, setManualPreview] = useState<{ element: string; delta: number[] } | null>(null);
  const previewRequest = useRef(0);
  // Clash reports (Navisworks XML).
  const [reportSamples, setReportSamples] = useState<string[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [matches, setMatches] = useState<Matches | null>(null);
  const [clash, setClash] = useState<ReportClash | null>(null);
  const [measure, setMeasure] = useState<Measure | null | "busy">(null);
  // ORCA's own detection (server: detect.py): what it would run on the open models, a run in progress, the last
  // result, and the A/B/C views taken in the browser of the clashes it found (by clash id).
  const [detectSetup, setDetectSetup] = useState<DetectSetup | null>(null);
  const [detecting, setDetecting] = useState<DetectProgress | null>(null);
  const [detection, setDetection] = useState<Detection | null>(null);
  const [views, setViews] = useState<Record<string, string[]>>({});
  const [capturing, setCapturing] = useState<string | null>(null);
  // Muse's titles for the open report's clashes (server: titles.py), as they stream in, and how many are still coming.
  const [titles, setTitles] = useState<Record<string, string>>({});
  const [naming, setNaming] = useState(0);
  const captures = useRef(new Map<string, Promise<void>>());
  // List thumbnails of detected clashes (no pictures until opened), drawn by the viewer as rows scroll into view.
  // "" marks a clash the viewer could not draw.
  const [thumbs, setThumbs] = useState<Record<string, string>>({});
  const thumbQueue = useRef<{ report: string; clash: ReportClash }[]>([]);
  const thumbPaused = useRef(false);
  const lastTests = useRef<DetectTest[] | null>(null);
  // The chat starts over when the user opens another report, not when the chat itself opened one (Detect from chat).
  const [chatReport, setChatReport] = useState<string | null>(null);
  // The image dialog: a clash's Navisworks views, opened from the clash panel or a row's thumbnail.
  const [about, setAbout] = useState(false);
  // Muse Spark's reasoning summaries for the current proposal, as they stream in.
  const [thoughts, setThoughts] = useState<{ round: number; text: string }[]>([]);
  const [lightbox, setLightbox] = useState<{ clash: ReportClash; index: number } | null>(null);
  useEffect(() => { setLightbox(null); }, [report]);
  const [remeasure, setRemeasure] = useState(0);
  // Accepted fixes. `edits`: element GlobalId → pieces an offset added to it (shown with that element from then on).
  // `fixes`: report clash id → the fix accepted for it.
  const [edits, setEdits] = useState<Record<string, string[]>>({});
  const [fixes, setFixes] = useState<Record<string, string>>({});
  const [progress, setProgress] = useState<Progress | null>(null);
  const [now, setNow] = useState(Date.now());
  const [compare, setCompare] = useState<"before" | "after" | "both">("after");
  const [tab, setTab] = useState<Tab>("clash");
  // What the viewer shows: the selected clash, or the plan. It follows the latest activity, not the open tab: a plan
  // started from Chat takes the view while the chat stays open; picking a clash or proposing gives it back.
  const [viewPlan, setViewPlan] = useState(false);
  // Several clashes at once.
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [rootCauses, setRootCauses] = useState<RootCause[] | null>(null);
  // Report-wide: patterns of the same clash, Muse Spark's verdict on each, and clashes reviewed without an edit.
  const [patterns, setPatterns] = useState<Pattern[] | null>(null);
  const [verdicts, setVerdicts] = useState<Record<string, PatternVerdict> | null>(null);
  const [explaining, setExplaining] = useState(false);
  const [reviewed, setReviewed] = useState<Record<string, Review>>({});
  // Coordination requirements (Requirements.tsx; server: requirements.py): the file kept in this browser and whether it
  // is in use, the id the server registered it under (sent with every call), and the dialog.
  const [reqSaved, setReqSaved] = useState<SavedRequirements | null>(() => loadRequirements());
  const [reqId, setReqId] = useState<string | null>(null);
  const [reqOpen, setReqOpen] = useState(false);
  // A blank project: the workspace without a demo, waiting for the visitor's own models (ProjectStart.tsx).
  const [blank, setBlank] = useState(false);
  // Muse Spark's audit of the by-design rules after a triage under requirements, and whether the triage shown was
  // read under other requirements (a level, strictness or guidance since changed).
  const [triageAudit, setTriageAudit] = useState<Record<string, RuleAudit>>({});
  const [triageStale, setTriageStale] = useState(false);
  // Bulk triage of the open report (shared on the server: a run someone else started is followed, not repeated).
  const [triage, setTriage] = useState<Record<string, TriageVerdict>>({});
  const [triageRun, setTriageRun] = useState<TriageRun | null>(null);
  // What the triage model is writing right now, per clash being read (its reasoning, newest 600 characters).
  const [triageLive, setTriageLive] = useState<Record<string, string>>({});
  // The coordination report: which team owns each model (guessed, then confirmed), the fixes to show with their
  // before/after pictures, and the teams' reviews (kept in this browser per report).
  const [modelTeams, setModelTeams] = useState<Record<string, Team>>({});
  const [evidence, setEvidence] = useState<Record<string, Evidence>>({});
  const [signoffs, setSignoffs] = useState<Record<string, Signoff[]>>({});
  const [docOpen, setDocOpen] = useState(false);
  const [touring, setTouring] = useState(false);
  const [tourWhich, setTourWhich] = useState<"northbank" | "cell">("northbank");
  const startTour = (which: "northbank" | "cell") => { setTourWhich(which); setTouring(true); };
  // An agent connected over MCP (Agent.tsx; server: agents.py, mcp_server.py). It is part of the saved session below.
  const [agentLink, setAgentLinkState] = useState<AgentLink | null>(null);
  /** Keep a link, measuring how far this browser's clock is from the server's when the server just sent its time. */
  const setAgentLink = (l: AgentLink | null) => setAgentLinkState(l && (l.server_time
    ? { ...l, clock_offset: l.server_time - Date.now() / 1000, server_time: 0 } : l));
  // This browser's last session (models, clashes, fixes, agent link), kept so a reload or a closed tab can resume it
  // while the server still holds it. One per browser: opening other models replaces it.
  const [sceneFiles, setSceneFiles] = useState<string[]>([]);
  const [resumable, setResumable] = useState<{ saved: SavedSession; info: SceneInfo; clashes: number | null } | null>(null);
  const [agentOpen, setAgentOpen] = useState(false);
  const [agentLog, setAgentLog] = useState<AgentLogEntry[]>([]);
  const [agentBusy, setAgentBusy] = useState(false);
  const [agentError, setAgentError] = useState<string | null>(null);
  const [ownerSettings, setOwnerSettingsState] = useState<OwnerSettings | null>(null);
  // Which model titles and triage use now, for the copy (asked again when the owner changes their own settings).
  const [triageModel, setTriageModel] = useState<TriageModel | null>(null);
  // Whether a clash Muse Spark could not fix may go to Muse Wonder for a second try (docs/escalation.md).
  const [escalation, setEscalation] = useState<EscalationInfo | null>(null);
  const [modelsAsked, setModelsAsked] = useState(0);   // ask again after the owner changes a setting for everyone
  useEffect(() => {
    api.models().then((m) => {
      setTriageModel(m.triage); setUploadMax(m.model_upload_max_mb ?? null); setEscalation(m.escalation ?? null);
      setBuiltOn(!!m.built_views);
    }).catch(() => undefined);
  }, [ownerSettings, modelsAsked]);
  const canEscalate = !!escalation?.available && escalation.mode !== "off";
  // Show it built (docs/show-it-built.md): pictures of fixes, only while the switch is on for this visitor.
  const [builtOn, setBuiltOn] = useState(false);
  const wonder = escalation?.label ?? "Muse Wonder";
  // How much a visitor may upload, from the server (checked here before anything is sent).
  const [uploadMax, setUploadMax] = useState<number | null>(null);
  const [replaying, setReplaying] = useState(false);
  const [docReady, setDocReady] = useState(false);
  const [chatAsk, setChatAsk] = useState<{ text: string; send: boolean; n: number } | undefined>(undefined);
  // Each agent run gets a number: a run that was replaced (by a recorded replay) can no longer change the page.
  const agentRun = useRef(0);
  const golden = useRef(false);
  const [triageFilter, setTriageFilterState] = useState<TriageKind | null>(null);
  // The list filtered to one pattern's or root cause's clashes (Insights). One filter at a time: either clears the other.
  const [listFocus, setListFocusState] = useState<{ label: string; ids: string[] } | null>(null);
  const setTriageFilter = (k: TriageKind | null) => { setTriageFilterState(k); if (k) setListFocusState(null); };
  const setListFocus = (f: { label: string; ids: string[] } | null) => { setListFocusState(f); if (f) setTriageFilterState(null); };
  useEffect(() => { setListFocusState(null); setLeftView("clashes"); }, [report?.id]);
  const [planRun, setPlanRun] = useState<PlanRun | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [planError, setPlanError] = useState<string | null>(null);
  const [context, setContext] = useState<ContextRun | null>(null);
  const [contextChosen, setContextChosen] = useState<string | null>(null);
  const [contextNames, setContextNames] = useState<Record<string, Record<string, unknown>>>({});
  const [acknowledged, setAcknowledged] = useState<string[]>([]);
  const [planKind, setPlanKind] = useState<"batch" | "context">("batch");
  const [viewContext, setViewContext] = useState(false);
  // Invalidate callbacks immediately when replacement starts, before the new scene ID arrives.
  const sceneEpoch = useRef(0);
  // The server's revision of the open scene this page's model shows: a kept fix is patched in place only from here.
  const sceneRevision = useRef<number | null>(null);
  const planRevision = useRef<number | null>(null);   // the scene's revision when the plan on screen was checked
  // A fix kept since the plan was checked (say, one item's own second try): its joint check no longer holds.
  const planStale = !!plan && planRevision.current != null && sceneRevision.current != null
    && planRevision.current !== sceneRevision.current;
  const workspaceEpoch = useRef(0);
  const chatOwner = useRef(new ChatRequestOwner());
  const contextRequest = useRef(0);
  const planRequest = useRef(0);
  const directAgent = useRef<ReturnType<typeof trackAgent> | null>(null);
  const directPlan = useRef<ReturnType<typeof trackPlan> | null>(null);
  const directContext = useRef<ReturnType<typeof trackContext> | null>(null);
  const contextProposal = context?.result?.proposals.find((p) => p.id === contextChosen) ?? null;
  const contextWorking = !!context && context.phase !== "done";
  const activeContext = viewContext && !context?.accepted;
  const renderedSceneEpoch = sceneEpoch.current;
  const renderedWorkspaceEpoch = workspaceEpoch.current;

  useEffect(() => {
    if (!sceneId || !contextProposal) return;
    const epoch = sceneEpoch.current;
    let live = true;
    const roots = [...new Set(contextProposal.edits.map((e) => e.element))].filter((gid) => !contextNames[gid]);
    void Promise.all(roots.map(async (gid) => [gid, await api.element(sceneId, gid).catch(() => ({}))] as const)).then((entries) => {
      if (live && sceneEpoch.current === epoch && entries.length) setContextNames((old) => ({ ...old, ...Object.fromEntries(entries) }));
    });
    return () => { live = false; };
    // Fetch only the chosen proposal's edit roots; long run members remain available as IDs in details.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sceneId, contextProposal]);

  useEffect(() => {
    if (!host.current) return;
    const v = new Viewer(host.current);
    viewer.current = v;
    pilot.current = new Pilot(() => viewer.current,
      (t) => frameFix({ kind: t.kind, moved: t.moved, preview: t.pieces }, sides.current), setPilotStatus);
    v.onUserCamera = () => pilot.current?.takeOver();
    api.samples().then((list) => {
      setSamples(list);
      // Default to the building disciplines and the site (the report's site clashes need it), not the grids or a later revision.
      const set = list.filter((f) => /(structure|mep|architecture|site)\.ifc$/i.test(f));
      setPicked(set.length ? set : list.slice(0, 1));
    }).catch((e) => setError(`Can't reach the ORCA server: ${e.message}`));
    api.reportSamples().then(setReportSamples).catch(() => undefined);
    return () => {
      ++sceneEpoch.current; ++workspaceEpoch.current; ++previewRequest.current;
      directContext.current?.retire(); pilot.current?.cancel(); chatOwner.current.invalidate(); v.dispose();
    };
  }, []);

  // Pieces accepted offsets added to A or B are part of that side: coloured, and kept when isolating.
  const [standIns, setStandIns] = useState<Record<string, Side>>({});
  sides.current = [a, b, ...Object.keys(standIns)].filter((g): g is string => !!g);
  const group = useMemo(() => {
    const g: Record<string, Side> = { ...standIns };
    for (const p of (b && edits[b]) || []) g[p] = "b";
    for (const p of (a && edits[a]) || []) g[p] = "a";
    return g;
  }, [a, b, edits, standIns]);
  // While a plan is on screen, its elements are the focus: what moves in green, what stays in red.
  const planGroup = useMemo(() => {
    if (!plan || !viewPlan) return null;
    const g: Record<string, "a" | "b"> = {};
    if (plan.hub) {  // the element behind the clashes in red, everything it meets in green
      g[plan.hub.hub.global_id] = "a";
      for (const p of plan.hub.partners) g[p.global_id] = "b";
    }
    for (const it of plan.items) {
      const moved = new Set(it.option?.moved ?? []);
      for (const gid of [it.element_a, it.element_b, ...(it.others ?? [])]) g[gid] = moved.has(gid) ? "b" : "a";
      for (const gid of moved) g[gid] = "b";
    }
    return g;
  }, [plan, viewPlan]);
  const contextGroup = useMemo(() => {
    if (!activeContext) return null;
    const objective = contextProposal?.objective ?? context?.objective;
    const g: Record<string, Side> = {};
    if (objective) { g[objective.element_a] = "a"; g[objective.element_b] = "a"; }
    for (const edit of contextProposal?.edits ?? []) {
      for (const gid of edit.moved) {
        g[gid] = "b";
        for (const piece of edits[gid] ?? []) g[piece] = "b";
      }
    }
    return g;
  }, [activeContext, contextProposal, context?.objective, edits]);
  useEffect(() => {
    // A plan on screen: its elements. A plan still being worked out: nothing yet (the old clash would mislead).
    viewer.current?.setFocus(contextGroup ? { a: null, b: null, group: contextGroup }
      : planGroup ? { a: null, b: null, group: planGroup } : viewPlan ? { a: null, b: null } : { a, b, group });
  }, [a, b, group, planGroup, viewPlan, contextGroup]);
  useEffect(() => { if (viewPlan || activeContext) viewer.current?.setMarker(null); }, [viewPlan, activeContext]);
  useEffect(() => { viewer.current?.setMode(tool.mode); }, [tool.mode]);
  useEffect(() => { viewer.current?.setEdges(tool.edges); }, [tool.edges]);
  // A section box follows the focus: re-cut it when the pair changes, drop it when there is none.
  useEffect(() => {
    if (!tool.section) { viewer.current?.setSection(false); return; }
    if (!viewer.current?.setSection(true)) setTool((t) => ({ ...t, section: false }));
  }, [tool.section, a, b, contextGroup, planGroup]);
  useEffect(() => {
    setMeasured(viewer.current?.setMeasure(measurePts[0] ?? null, measurePts[1] ?? null) ?? null);
  }, [measurePts]);

  // A clock for the live status lines while an agent works.
  const working = (!!progress && progress.phase !== "done") || (!!planRun && planRun.phase !== "done")
    || (!!triageRun && !triageRun.done) || contextWorking;
  useEffect(() => {
    if (!working) return;
    const t = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(t);
  }, [working]);

  // Link the report to the open model whenever either changes.
  useEffect(() => {
    setMatches(null);
    if (!report || !sceneId) return;
    let live = true;
    api.match(report.id, sceneId).then((m) => { if (live) setMatches(m); }).catch((e) => { if (live) setError((e as Error).message); });
    return () => { live = false; };
  }, [report, sceneId]);

  // Root causes and patterns, over the clashes still open (not fixed, not reviewed). Nothing jumps while the user
  // works through them: patterns are read once per report, and Insights shows each one's open clashes from `resolved`;
  // root causes are read again as clashes are resolved, but each stays in its place (a resolved hub as a done row).
  const resolved = useMemo(() => [...new Set([...Object.keys(fixes), ...Object.keys(reviewed)])], [fixes, reviewed]);
  const resolvedSet = useMemo(() => new Set(resolved), [resolved]);
  const resolvedNow = useRef(resolved);
  resolvedNow.current = resolved;
  useEffect(() => {
    setRootCauses(null); setPatterns(null);
    if (!report || !sceneId || !matches) return;
    let live = true;
    api.patterns(report.id, sceneId, resolvedNow.current).then((r) => { if (live) setPatterns(r); }).catch(() => { if (live) setPatterns([]); });
    return () => { live = false; };
  }, [report, sceneId, matches]);
  useEffect(() => {
    if (!report || !sceneId || !matches) return;
    let live = true;
    api.rootCauses(report.id, sceneId, resolved).then((r) => { if (live) setRootCauses((prev) => keepPlaces(prev, r)); })
      .catch(() => { if (live) setRootCauses((prev) => prev ?? []); });
    return () => { live = false; };
  }, [report, sceneId, matches, resolved]);

  /** Muse Spark reads every pattern (one call, cached per report on the server): its verdicts bring each pattern's
   * mark, flag and fix buttons. `quiet` (the automatic reading) leaves a failure to the Explain button, not a banner. */
  async function explainPatterns(quiet = false) {
    if (!report || !sceneId) return;
    const rid = report.id;
    setExplaining(true);
    try { const v = await api.triagePatterns(rid, sceneId, resolved); if (reportRef.current === rid) setVerdicts(v); }
    catch (e) { if (!quiet) setError((e as Error).message); } finally { setExplaining(false); }
  }
  const reportRef = useRef<string | null>(null);
  reportRef.current = report?.id ?? null;
  const explained = useRef<string | null>(null);

  /** Run the bulk triage, or follow the run already going for this report. */
  async function runTriage(rerun = false) {
    if (!report) return;
    const rid = report.id;
    if (rerun) { setTriage({}); setTriageFilter(null); setTriageAudit({}); }
    setTriageStale(false);
    setTriageLive({});
    setTriageRun((r) => r ?? { model: "", open_weights: false, total: report.clashes.length, started: Date.now(), done: false });
    try {
      await api.triageStream(rid, sceneId, (e) => {
        if (e.type === "start") setTriageRun({ model: e.model, open_weights: e.open_weights, note: e.note, images: e.images, total: e.total, started: Date.now(), done: false, requirements: e.requirements?.label ?? null });
        else if (e.type === "audit") setTriageAudit(e.rules);
        else if (e.type === "clash") {
          const { type: _t, id, ...v } = e;
          setTriage((t) => ({ ...t, [id]: v }));
          setTriageLive((l) => { if (!(id in l)) return l; const { [id]: _done, ...rest } = l; return rest; });
        }
        else if (e.type === "reasoning") setTriageLive((l) => ({ ...l, [e.id]: ((l[e.id] ?? "") + e.text).slice(-600) }));
        else if (e.type === "done") { setTriageRun((r) => r && { ...r, done: true, seconds: e.seconds, error: e.error }); setTriageLive({}); }
      }, rerun);
    } catch (e) { setError((e as Error).message); setTriageRun((r) => (r && r.model ? { ...r, done: true } : null)); }
  }

  // The requirements in use: registered with the server (content-addressed), then their id goes with every call.
  useEffect(() => {
    saveRequirements(reqSaved);
    if (!reqSaved?.enabled) { setRequirements(null, null); setReqId(null); return; }
    let live = true;
    api.registerRequirements(reqSaved.doc).then((r) => {
      if (!live) return;
      setRequirements(r.id, r.doc); setReqId(r.id);
    }).catch((e) => { if (live) setError(`Requirements not in use: ${(e as Error).message}`); });
    return () => { live = false; };
  }, [reqSaved]);
  const reqLabel = reqSaved?.enabled && reqId ? shortLabel(reqSaved.doc) : null;

  /** Keep a requirements file (null: forget it); with `again`, check the models again under it. */
  function applyRequirements(doc: Requirements | null, enabled: boolean, again: boolean) {
    setReqSaved(doc ? { doc, enabled } : null);
    setReqOpen(false);
    if (again) pendingDetect.current = true;
  }
  const pendingDetect = useRef(false);
  useEffect(() => {
    if (!pendingDetect.current || !reqId) return;
    pendingDetect.current = false;
    void runDetect(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reqId]);

  /** An opening's host reading becomes the rule for the host's group (a file is started from the models when there is
   * none: the option names the group in that file). */
  async function addPenRule(o: Option) {
    let doc = reqSaved?.doc ?? null;
    if (!doc && sceneId) doc = (await api.requirementsDefault(sceneId).catch(() => null))?.doc ?? null;
    if (!doc || !o.edit) return;
    setReqSaved({ doc: addPenetration(doc, o.edit, o.review ?? null), enabled: true });
  }

  /** A pattern Muse read as by design becomes a by-design rule (a file is started from the models when there is none):
   * its clashes are settled at once, without asking the model again. */
  async function addRule(p: Pattern, v?: PatternVerdict) {
    let doc = reqSaved?.doc ?? null;
    if (!doc && sceneId) doc = (await api.requirementsDefault(sceneId).catch(() => null))?.doc ?? null;
    if (!doc) return;
    setReqSaved({ doc: addByDesign(doc, p, v), enabled: true });
  }

  // A newly opened report, or other requirements: pick up a triage that already exists for it (finished, or still
  // running). Under requirements that only changed rules, the server carries the readings over at once; under
  // another level, strictness or guidance it returns the last run marked stale until the triage is run again.
  useEffect(() => {
    setTriage({}); setTriageRun(null); setTriageFilter(null); setTriageAudit({}); setTriageStale(false);
    if (!report) return;
    let live = true;
    api.triage(report.id, sceneId).then((s) => {
      if (!live || !s.model) return;
      setTriageAudit(s.audit ?? {}); setTriageStale(!!s.stale);
      if (s.done || s.stale) {
        setTriage(s.results);
        setTriageRun({ model: s.model, open_weights: !!s.open_weights, note: s.note, total: s.total ?? 0, started: Date.now(), done: true, seconds: s.seconds ?? undefined, error: s.error ?? undefined, requirements: s.requirements?.label ?? null });
      } else runTriage();
    }).catch(() => {});
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [report, reqId]);

  // Models opened after a triage: the server corrects what the open model settles (one element on both sides).
  const triageDone = !!triageRun?.done;
  useEffect(() => {
    if (!report || !sceneId || !matches || !triageDone) return;
    let live = true;
    api.triage(report.id, sceneId).then((s) => { if (live && s.done) setTriage(s.results); }).catch(() => {});
    return () => { live = false; };
  }, [report, sceneId, matches, triageDone]);

  useEffect(() => {
    if (!report) return;
    let live = true;
    api.teams(report.id, sceneId).then((r) => {
      // A fresh guess once the models are open (they say more than the report does); the dialog confirms it.
      if (live) setModelTeams(Object.fromEntries(r.models.map((m) => [m.file, m.guess])));
    }).catch(() => {});
    return () => { live = false; };
  }, [report, sceneId]);
  const signoffKey = report ? `sightline.signoffs.${report.title}` : null;
  useEffect(() => {
    setEvidence({});
    try { setSignoffs(signoffKey ? JSON.parse(localStorage.getItem(signoffKey) ?? "{}") : {}); } catch { setSignoffs({}); }
  }, [signoffKey]);
  function changeSignoffs(id: string, f: (s: Signoff[]) => Signoff[]) {
    setSignoffs((all) => {
      const next = { ...all, [id]: f(all[id] ?? []) };
      try { if (signoffKey) localStorage.setItem(signoffKey, JSON.stringify(next)); } catch { /* private window */ }
      return next;
    });
  }

  const addSignoff = (id: string, so: Signoff) => changeSignoffs(id, (l) => [...l, so]);
  const removeSignoff = (id: string, i: number) => changeSignoffs(id, (l) => l.filter((_, k) => k !== i));

  /** Report clash ids of these element pairs (one pair can be reported by several tests). */
  function clashIdsOf(pairs: (readonly [string | null, string | null])[]): string[][] {
    if (!report || !matches) return pairs.map(() => []);
    const key = (x: string | null | undefined, y: string | null | undefined) => [x, y].sort().join("|");
    return pairs.map((p) => report.clashes.filter((c) => key(matches[c.id]?.a, matches[c.id]?.b) === key(p[0], p[1])).map((c) => c.id));
  }

  /** The view as it is and with the fix(es), for the report. Draws both states in turn, then puts the view back. */
  function captureFix(options: Option[], color: string): { before_img?: string; after_img?: string } {
    const v = viewer.current;
    if (!v || !options.length) return {};
    const shapes = options.map((o) => ({ kind: o.kind, moved: o.moved, deltaM: o.delta_m, pieces: o.preview, before: o.before, color }));
    v.showOptions(shapes, "before");
    const before_img = v.capture();
    v.showOptions(shapes, "after");
    const after_img = v.capture();
    v.showOptions(shapes, compare);
    return { before_img, after_img };
  }

  /** Muse's recommendation where the requirements allow no edit: the report shows it on the clash's page. */
  function noteRecommendation(r: Recommendation, pair: readonly [string | null, string | null]) {
    const ids = clashIdsOf([pair])[0];
    if (!ids.length) return;
    const ev: Evidence = { status: "recommended", title: r.title, kind: r.kind, edit: recEditText(r), clearance: "", clearance_m: null,
      rationale: r.rationale, also_needs: r.also_needs, moved: [r.element], blocked_by: r.blocked_by };
    setEvidence((all) => ({ ...all, ...Object.fromEntries(ids.filter((id) => !all[id] || all[id].status === "recommended").map((id) => [id, ev])) }));
  }

  function evidenceOf(o: Option, status: Evidence["status"], pics: { before_img?: string; after_img?: string }): Evidence {
    return { status, title: o.title, kind: o.kind, edit: editText(o), moved: o.moved,
      clearance: clearanceText(o), clearance_m: o.min_clearance_m ?? null, ...(o.review ? { review: o.review } : {}),
      rationale: o.rationale, also_needs: o.also_needs, ...(o.meets?.length ? { meets: o.meets } : {}), ...pics };
  }

  // ------------------------------------------------------------------ Show it built (docs/show-it-built.md)
  // A fix's picture, drawn by Muse Image from ORCA's view and checked against the model. Runs are keyed by the pair and
  // the fix's title, so an option's picture is still there once it is accepted.
  const [builtRuns, setBuiltRuns] = useState<Record<string, BuiltRun>>({});
  // What is on screen now, for work that lands after the render it started in (chat's show_it_built).
  const latest = useRef({ proposal, chosen, a, b });
  latest.current = { proposal, chosen, a, b };
  const sceneClasses = useRef<{ scene: string; map: Record<string, [string, string]> } | null>(null);
  // Accepted fixes as the viewer can frame them again (a report's missing pictures), by clash id; finished results by
  // key; pictures still being drawn.
  const builtFixes = useRef<Record<string, { key: string; title: string; fix: BuiltFix; pair: [string, string] }>>({});
  const builtDone = useRef<Record<string, BuiltResult>>({});
  const builtPending = useRef(new Map<string, Promise<BuiltResult | null>>());
  useEffect(() => {
    if (!builtOn || !sceneId || sceneClasses.current?.scene === sceneId) return;
    api.classes(sceneId).then((map) => { sceneClasses.current = { scene: sceneId, map }; }).catch(() => undefined);
  }, [builtOn, sceneId]);
  useEffect(() => {
    builtFixes.current = {}; builtDone.current = {}; builtPending.current = new Map(); setBuiltRuns({});
  }, [sceneId]);
  /** A picture's key: the pair and the fix itself (kind, numbers, its edit), never just its title, which two
   * different fixes can share. */
  const builtKey = (pair: readonly [string | null, string | null], o: Option) => [[pair[0], pair[1]].sort().join("|"), o.kind, o.title,
    JSON.stringify([o.delta_m, o.split_m ?? null, o.trim ?? null, o.edit?.key ?? o.edit?.summary ?? null])].join("|");
  /** Show it built is for fixes big enough to see at the view's scale: not a trim or a cleanup. */
  const buildable = (o: Option) => o.kind !== "trim" && !o.cleanup;
  const canBuild = (o: Option) => builtOn && buildable(o);
  /** A fix as the viewer frames it; `ids`: an applied fix's pieces (the original first), in its preview's order. */
  const builtFix = (o: Option, applied: boolean, ids?: string[]): BuiltFix => ({ kind: o.kind, moved: o.moved, deltaM: o.delta_m,
    pieces: o.preview?.map((m, i) => (ids?.[i] ? { ...m, global_id: ids[i] } : m)) ?? null, applied });

  /** ORCA's view of a fix in the passes the picture and its check need (Viewer.captureBuilt: one task, view put back). */
  function builtPasses(fix: BuiltFix, pair: [string, string]): BuiltPasses | null {
    const known = sceneClasses.current?.scene === sceneId ? sceneClasses.current.map : null;
    const v = viewer.current;
    if (!v) return null;
    // "" for what the server lists as not physical (a space, a provision for void): not drawn in the picture.
    try { return v.captureBuilt(fix, pair, (g) => known ? (known[g]?.[0] ?? "") : undefined); } catch { return null; }
  }

  /** Draw a fix's picture from its passes; the run shows under `key`. Resolves with the result, null when the request
   * failed (switched off, capped: a report can try again). */
  function drawBuilt(key: string, passes: BuiltPasses | null, kind: string): Promise<BuiltResult | null> {
    const sid = sceneId, map = sceneClasses.current?.map ?? {}, epoch = sceneEpoch.current;
    const already = builtPending.current.get(key);
    if (already) return already;   // being drawn: one request, one charge
    if (!sid || !passes) {
      setBuiltRuns((r) => ({ ...r, [key]: { status: "failed", step: "", look: "", cut: "", error: "Nothing of the fix is in view to draw." } }));
      return Promise.resolve(null);
    }
    const cut = cutText(passes.cut, passes.sectioned, (g) => map[g]?.[0]);
    const set = (patch: Partial<BuiltRun>) => {
      if (sceneEpoch.current !== epoch) return;   // another scene now: this picture belongs to none of it
      setBuiltRuns((r) => ({ ...r, [key]: { ...(r[key] ?? { status: "working", step: "", look: passes.look, cut }), ...patch } }));
    };
    set({ status: "working", step: "Muse Image is drawing two pictures from ORCA's view…", look: passes.look, cut, result: undefined, error: undefined });
    const work = api.built(sid, { look: passes.look, ids: passes.ids, normals: passes.normals }, kind, (e) => set({ step: builtStep(e) }))
      .then((res) => {
        if (sceneEpoch.current !== epoch) return null;
        builtDone.current[key] = res; set({ status: res.status === "done" ? "done" : "failed", result: res }); return res;
      })
      .catch((e) => { set({ status: "failed", error: (e as Error).message }); return null; })
      .finally(() => { if (builtPending.current.get(key) === work) builtPending.current.delete(key); });
    builtPending.current.set(key, work);
    return work;
  }

  /** A kept fix's picture again (or for the first time), framed on the model as it now is. */
  function redrawKept(clashId: string) {
    const f = builtFixes.current[clashId];
    if (!f) return;
    const ids = Object.entries(builtFixes.current).filter(([, g]) => g.key === f.key).map(([id]) => id);
    void drawBuilt(f.key, builtPasses(f.fix, f.pair), f.fix.kind).then((res) => noteBuilt(ids, f.title, res));
  }

  /** Chat's show_it_built: the chosen option of the clash on screen, else its kept fix. */
  function builtFromChat(clashId: string) {
    const { proposal: p, chosen: k, a: x, b: y } = latest.current;
    const o = p && k != null ? p.options[k] : null;
    const m = matches?.[clashId];
    const same = !!m && !!x && !!y && [m.a, m.b].sort().join("|") === [x, y].sort().join("|");   // the option is this clash's
    if (o && same && canBuild(o)) { void drawBuilt(builtKey([x!, y!], o), builtPasses(builtFix(o, false), [x!, y!]), o.kind); return; }
    if (builtFixes.current[clashId]) { redrawKept(clashId); return; }
    setError("Nothing to draw for that clash yet: propose fixes and pick one, or accept one, then ask again.");
  }

  /** The chosen option's picture (the button on its card). */
  function showBuilt(o: Option) {
    if (!a || !b || !canBuild(o)) return;
    void drawBuilt(builtKey([a, b], o), builtPasses(builtFix(o, false), [a, b]), o.kind);
  }

  /** A kept fix's picture (or why there is none) on its clashes' evidence: the PDF's third picture. */
  function builtEvidence(ev: Evidence, res: BuiltResult | null | undefined): Evidence {
    if (!res) return ev;
    return res.status === "done" && res.image_url ? { ...ev, built_img: res.image_url, built_note: undefined }
      : { ...ev, built_note: res.why ?? "Muse Image couldn't keep to the model here." };
  }
  function noteBuilt(ids: string[], title: string, res: BuiltResult | null) {
    if (res) setEvidence((ev) => ({ ...ev, ...Object.fromEntries(ids.filter((id) => ev[id]?.title === title).map((id) => [id, builtEvidence(ev[id], res)])) }));
  }

  /** At accept: the fix's picture in the background, from the passes taken before it was applied (or the option's own
   * picture, if one was drawn), and the fix kept so a report can frame it again. */
  function buildAccepted(o: Option, pair: [string, string], ids: string[], passes: BuiltPasses | null, pieces?: string[]) {
    if (!buildable(o)) return;
    const key = builtKey(pair, o);
    const runs = o.kind === "offset" || o.kind === "route" || o.kind === "resize";
    // Kept whether or not the switch is on, so a report drawn after it goes on can frame this fix again.
    for (const id of ids) builtFixes.current[id] = { key, title: o.title, fix: builtFix(o, true, runs ? pieces : undefined), pair };
    if (!builtOn) return;
    const made = builtDone.current[key], drawing = builtPending.current.get(key);
    if (made?.status === "done") noteBuilt(ids, o.title, made);
    else if (drawing) void drawing.then((res) => noteBuilt(ids, o.title, res));
    else if (passes) void drawBuilt(key, passes, o.kind).then((res) => noteBuilt(ids, o.title, res));
  }

  /** Before a report: the pictures still drawing, and those of accepted fixes that have none (switched on later, or
   * capped then), at most 10 at once. Returns the evidence with every picture that came. */
  async function prepareReport(onStep: (done: number, total: number) => void): Promise<Record<string, Evidence>> {
    if (!builtOn) return evidence;
    const keys = new Map<string, string[]>();
    for (const id of Object.keys(evidence)) {
      const ev = evidence[id], f = builtFixes.current[id];
      if (ev.status === "accepted" && f && !ev.built_img && !ev.built_note && !builtDone.current[f.key])
        keys.set(f.key, [...(keys.get(f.key) ?? []), id]);
    }
    const waiting = [...keys].filter(([key]) => !builtPending.current.has(key));
    const todo = waiting.slice(0, 10);
    const later = waiting.slice(10).flatMap((entry) => entry[1]);   // at most 10 drawn for one report: the rest say so
    const withLater = (all: Record<string, Evidence>) => ({ ...all, ...Object.fromEntries(later.map((id) => [id,
      { ...all[id], built_note: "Not drawn for this report (at most 10 at once); building the report again draws the next ones." }])) });
    const pending = [...builtPending.current.values()];
    const total = todo.length + pending.length;
    if (!total) return withLater(withBuilt(evidence));
    let done = 0;
    onStep(0, total);
    await Promise.all([
      ...pending.map((w) => w.then(() => onStep(++done, total))),
      ...todo.map(([key, ids]) => {
        const f = builtFixes.current[ids[0]];
        return drawBuilt(key, builtPasses(f.fix, f.pair), f.fix.kind).then((res) => { noteBuilt(ids, f.title, res); onStep(++done, total); });
      }),
    ]);
    return withLater(withBuilt(evidence));
  }
  /** Evidence with every finished picture of its kept fix (state may not have caught up with the last ones yet). */
  function withBuilt(all: Record<string, Evidence>): Record<string, Evidence> {
    return Object.fromEntries(Object.entries(all).map(([id, ev]) => {
      const f = builtFixes.current[id];
      return [id, f && ev.status === "accepted" && ev.title === f.title ? builtEvidence(ev, builtDone.current[f.key]) : ev];
    }));
  }

  function captureContext(p: ContextProposal): { before_img?: string; after_img?: string } {
    const v = viewer.current;
    if (!v) return {};
    try {
      v.showOptions(contextShapes(p), "before"); const before_img = v.capture();
      v.showOptions(contextShapes(p), "after"); const after_img = v.capture();
      return { before_img, after_img };
    } catch { return {}; }
    finally { v.showOptions(contextShapes(p), compare); }
  }

  // Triage as shown: a model verdict of "real" or "model error" gives way to what is already settled in this browser
  // (marked not a clash, or ORCA's own geometry: one element, not physical, a touch, no overlap here), and the
  // model's reading is kept beside it.
  const shownTriage = useMemo(() => {
    if (!report) return triage;
    const out: Record<string, TriageVerdict> = { ...triage };
    for (const c of report.clashes) {
      const t = triage[c.id];
      if (!t || t.verdict === "by_design" || t.verdict === "non_physical") continue;
      const rv = reviewed[c.id];
      const nc = noClash(c, matches?.[c.id], c.id === clash?.id ? measure : null);
      if (rv?.kind === "by_design" || nc) {
        const basis: TriageVerdict["basis"] = rv?.kind === "by_design" ? "reviewed"
          : nc!.label === "same element" ? "same_element" : nc!.label === "not physical" ? "non_physical" : nc!.label === "touch" ? "touch" : "no_overlap";
        out[c.id] = { verdict: basis === "non_physical" ? "non_physical" : "by_design", severity: "none", responsible: "none",
          action: "exclude_with_rule", source: "rule", basis,
          understanding: rv?.kind === "by_design" ? `Marked not a clash: ${rv.note}` : `Not a clash: ${nc!.why}`,
          model_reading: t.understanding ? `${t.verdict.replace("_", " ")}: ${t.understanding}` : undefined };
      }
    }
    return out;
  }, [report, triage, reviewed, matches, clash, measure]);

  // A selected report clash that needs no fix (one element, not physical, a touch, no overlap, by design per triage):
  // the panel says why instead of offering a fix, unless someone asks for one anyway.
  const [fixAnyway, setFixAnyway] = useState(false);
  useEffect(() => { setFixAnyway(false); }, [clash]);
  const notAClash = clash && !fixes[clash.id] && !proposal && !progress ? noClash(clash, matches?.[clash.id], measure, shownTriage[clash.id]) : null;
  const hideFix = !!notAClash && !fixAnyway;

  function review(ids: string[], kind: Review["kind"], note: string) {
    setReviewed((r) => ({ ...r, ...Object.fromEntries(ids.filter((id) => !fixes[id]).map((id) => [id, { kind, note }])) }));
    setChecked((s) => { const n = new Set(s); for (const id of ids) n.delete(id); return n; });
  }

  /** Take the camera to a report clash: where its elements meet, or its reported point. */
  function goToClash(c: ReportClash, m = matches?.[c.id]) {
    const ids = [m?.show?.[0] ?? m?.a, m?.show?.[1] ?? m?.b].filter((g): g is string => !!g);
    const point = c.point && c.point.every((v) => v != null) ? serverPointToViewer(c.point as number[]) : null;
    if (!viewer.current?.focusClash(ids, point, `#${c.number}`)) setError("This clash has no geometry or point to show in the open model.");
  }

  // A selected report clash: its pair in the viewer, and ORCA's own measure of it.
  useEffect(() => {
    setMeasure(null);
    if (!clash || !report || !sceneId || !matches) return;
    const m = matches[clash.id];
    setA(m?.a ?? null); setB(m?.b ?? null);
    // Draw what can be drawn: a port's pipe or valve stands in for the port itself.
    const shownA = m?.show?.[0], shownB = m?.show?.[1];
    // Both ports of one pipe stand in for both sides: that element is A and B at once (drawn purple).
    const ins: Record<string, Side> = {};
    if (shownA && shownA !== m?.a) ins[shownA] = "a";
    if (shownB && shownB !== m?.b) ins[shownB] = ins[shownB] === "a" ? "ab" : "b";
    setStandIns(ins);
    if (!m?.a || !m?.b) return;
    let live = true;
    setMeasure("busy");
    api.measure(report.id, clash.id, sceneId).then((x) => live && setMeasure(x)).catch(() => live && setMeasure(null));
    return () => { live = false; };
  }, [clash, report, sceneId, matches, remeasure]);
  // When the model link arrives after a clash was picked, go to it then.
  useEffect(() => { if (clash && matches && !viewPlan && !activeContext) goToClash(clash); }, [matches]);  // eslint-disable-line react-hooks/exhaustive-deps

  // What the viewer previews: the chosen option of a single proposal, else every fix of a plan.
  const option = viewPlan || activeContext || chosen == null ? null : proposal?.options[chosen] ?? null;
  const planOptions = useMemo(() => (plan?.items.filter((i) => i.option).map((i) => i.option!) ?? []), [plan]);
  useEffect(() => {
    const v = viewer.current;
    if (!v) return;
    if (activeContext && contextProposal) {
      v.showOptions(contextShapes(contextProposal), compare);
    } else if (activeContext) v.preview([]);
    else if (option) {
      v.showOption({ kind: option.kind, moved: option.moved, deltaM: option.delta_m, pieces: option.preview, before: option.before },
        compare, option.moved.includes(a ?? "") ? "#d0342c" : "#1f9d3a");
    } else if (plan && viewPlan) {
      v.showOptions(planOptions.map((o) => ({ kind: o.kind, moved: o.moved, deltaM: o.delta_m, pieces: o.preview, before: o.before, color: "#1f9d3a" })), compare);
    } else if (manualPreview) {
      v.preview([{ globalIds: [manualPreview.element], deltaM: manualPreview.delta }]);
    } else v.preview([]);
  }, [option, plan, planOptions, compare, a, viewPlan, activeContext, contextProposal, manualPreview]);

  useEffect(() => {
    if (activeContext && contextProposal) viewer.current?.frameMeshes(contextProposal.edits.flatMap((e) => [...e.before, ...e.preview]), 1.4);
  }, [contextProposal, activeContext]);

  // Zoom to what the chosen option changes: an offset's risers and middle piece, or where a moved element now
  // meets the other side of the clash (not the whole moved element: a raised 16 m run would fill the screen).
  useEffect(() => {
    if (!option) return;
    const sides = [a, b, ...Object.keys(standIns)].filter((g): g is string => !!g);
    if (!frameFix(option, sides) && option.before?.length) viewer.current?.frameMeshes(option.before, 1.6);
    // Once the camera has arrived: the pictures the report shows for this proposed fix (accepting replaces them).
    const o = option, pair = [a, b] as const, request = previewRequest.current;
    const timer = window.setTimeout(() => {
      if (previewRequest.current !== request) return;
      const ids = clashIdsOf([pair])[0];
      if (!ids.length) return;
      const pics = captureFix([o], o.moved.includes(pair[0] ?? "") ? "#d0342c" : "#1f9d3a");
      setEvidence((ev) => ({ ...ev, ...Object.fromEntries(ids.filter((id) => ev[id]?.status !== "accepted").map((id) => [id, evidenceOf(o, "proposed", pics)])) }));
    }, 1400);
    return () => window.clearTimeout(timer);
  }, [option]);  // eslint-disable-line react-hooks/exhaustive-deps
  // A finished plan: frame everything it changes, or (nothing to change) the cluster it is about.
  useEffect(() => {
    const v = viewer.current;
    if (!v || !plan || !viewPlan) return;
    const meshes = planOptions.flatMap((o) => framePieces(o));  // moves and trims: their pairs
    const pairs = plan.items.flatMap((it) => it.option && !framePieces(it.option).length
      ? movedPairs(it.option.moved, [it.element_a, it.element_b, ...(it.others ?? [])]) : []);
    if (meshes.length || pairs.length) v.frameFix(meshes, pairs);
    else if (plan.hub) v.frame([plan.hub.hub.global_id, ...plan.hub.partners.map((p) => p.global_id)]);
  }, [planOptions, plan, viewPlan]);

  function frameFix(o: { kind: string; moved: string[]; preview: Mesh[] | null }, sides: string[]) {
    // A split run: its new pieces. A move: where it now meets the other side. A trim: the joint it changes.
    const meshes = framePieces(o);
    return !!viewer.current?.frameFix(meshes, meshes.length ? [] : movedPairs(o.moved, sides));
  }

  function clearManual() { ++previewRequest.current; setManual(null); setManualPreview(null); }
  function resetWork(keepContext = false, keepStandIns = false) { clearManual(); setProposal(null); setChosen(null); setProgress(null); setCompare("after"); if (!keepStandIns) setStandIns({}); if (!keepContext) setViewContext(false); }

  function retireDirectWork() {
    directAgent.current?.retire(); directPlan.current?.retire(); directContext.current?.retire();
    directAgent.current = null; directPlan.current = null; directContext.current = null;
    ++agentRun.current; ++planRequest.current; pilot.current?.cancel();
    setReplaying(false);
  }

  /** Open models: the picked samples, other sample names, or files the visitor chose (uploaded). A STEP model is
   * converted to IFC on the server; Export gives it back as STEP too. */
  /** Open models: samples, uploads, or (`existing`) a scene the server still holds, to resume a session. */
  async function open(source: string[] | File[] = picked, existing?: OpenedScene) {
    if (!source.length) return;
    const upload = source[0] instanceof File;
    const names = (source as (string | File)[]).map((x) => (typeof x === "string" ? x : x.name));
    const hasStep = names.some((n) => /\.(step|stp)$/i.test(n));
    ++workspaceEpoch.current; replaceChatWork(); retireDirectWork();
    const epoch = ++sceneEpoch.current;
    ++contextRequest.current; ++agentRun.current; ++planRequest.current;
    pilot.current?.cancel();
    setChatAsk(undefined);
    setContext(null); setContextChosen(null); setContextNames({}); setAcknowledged([]); setViewContext(false); setViewPlan(false);
    setBusy(existing ? "Reopening your session…" : upload ? `Uploading ${names.length} model${names.length > 1 ? "s" : ""}${hasStep ? " and converting the STEP" : ""}…`
      : hasStep ? "Opening the STEP model…" : `Loading ${names.length} model${names.length > 1 ? "s" : ""}…`);
    setError(null); resetWork(false, true);
    try {
      if (upload && !existing) {
        const refusal = uploadRefusal(source as File[], uploadMax);
        if (refusal) throw new Error(refusal);
      }
      const { id, files, step, revision } = existing ?? (upload
        ? await api.uploadModelsStream(source as File[], (e) => {
          const line = uploadStatus(e, hasStep);
          if (line && sceneEpoch.current === epoch) setBusy(line);
        })
        : await api.open(source as string[]));
      if (sceneEpoch.current !== epoch) return;
      if (upload) setBusy("Drawing the models…");
      // An uploaded IFC is parsed from the visitor's own file; a STEP comes back converted, samples come from the server.
      const bytes = await Promise.all(files.map(async (_, i) => {
        const local = upload ? localFile(source as File[], files, step, i) : null;
        return local ? new Uint8Array(await local.arrayBuffer()) : api.file(id, i);
      }));
      if (sceneEpoch.current !== epoch) return;
      const stats = await viewer.current!.load(bytes, files, () => sceneEpoch.current === epoch);
      if (sceneEpoch.current !== epoch || !stats) return;
      sceneRevision.current = revision ?? null;
      setModelNames(files.map(shortName));
      setTool((t) => ({ ...t, hiddenModels: [] }));
      setEdits({}); setFixes({}); setReviewed({}); setVerdicts(null); setPlan(null); setPlanRun(null); setChecked(new Set());
      setStats(stats); setSceneId(id); setA(null); setB(null); setStandIns({}); setSelected(null);
      setStepFiles(Object.values(step ?? {})); setSceneFiles(files); setResumable(null);
      return id;
    } catch (e) { if (sceneEpoch.current === epoch) setError((e as Error).message); } finally { if (sceneEpoch.current === epoch) setBusy(null); }
  }

  /** The start page's buttons: open the demo models and let ORCA check them (the golden path also picks the duct
   * through the girder and proposes a fix). A Navisworks report is optional: Coordinate › Import. */
  async function startGolden() { golden.current = true; await openDemo(); }
  async function openDemo(source?: string[] | File[]) {
    const id = await open(source);
    if (id) await runDetect(null, id);
  }
  // The second demo: the palletising cell, opened from its STEP file.
  const cellSample = samples.find((f) => /palletising-cell-reva\.(step|stp)$/i.test(f));

  /** A clash of the cell tour, by its parts' names (the STEP's own): one of `names` on each side. */
  function clashOfNames(a: readonly string[], b: readonly string[], r: Report | null = report): ReportClash[] {
    return (r?.clashes ?? []).filter((c) => (a.includes(c.a.name) && b.includes(c.b.name)) || (a.includes(c.b.name) && b.includes(c.a.name)));
  }

  /** A clash the tour or the golden path is about, by its two elements: the same in a check or an imported report. */
  function clashOfPair(pair: readonly string[], r: Report | null = report): ReportClash | undefined {
    return r?.clashes.find((c) => pair.includes(c.a.global_id ?? "") && pair.includes(c.b.global_id ?? "")
      && c.a.global_id !== c.b.global_id);
  }

  useEffect(() => {
    if (!golden.current || !report || !sceneId || !matches) return;
    const target = clashOfPair(TOUR.duct) ?? [...report.clashes].sort((x, y) => (x.distance_m ?? 0) - (y.distance_m ?? 0))[0];
    if (!target) { golden.current = false; return; }
    if (clash?.id !== target.id) { selectClash(target); return; }
    if (a && b && !proposal && !proposing) { golden.current = false; void propose(); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [report, sceneId, matches, clash, a, b]);
  async function loadReport(get: () => Promise<Report>, what: string) {
    // Report replacement changes callback ownership; defer it until committed model reloads finish.
    if (busy) return;
    const workspace = ++workspaceEpoch.current;
    replaceChatWork(); retireDirectWork(); ++agentRun.current; ++planRequest.current; ++contextRequest.current; ++sceneEpoch.current;
    pilot.current?.cancel(); resetWork(); setContext(null); setContextChosen(null); setAcknowledged([]); setPlanKind("batch"); setChatAsk(undefined);
    setBusy(`Reading ${what}…`); setError(null);
    try {
      const r = await get(); if (workspaceEpoch.current !== workspace) return;
      setReport(r); setChatReport(r.id); setClash(null); resetWork(); setChecked(new Set()); setPlan(null); setPlanRun(null); setFixes({}); setReviewed({}); setVerdicts(null);
      setDetection(null); setViews({}); captures.current.clear();
      return r;
    }
    catch (e) { if (workspaceEpoch.current === workspace) setError((e as Error).message); } finally { if (workspaceEpoch.current === workspace) setBusy(null); }
  }

  // Every report's clashes get titles: "#39 Cold-water main clips the transfer girder", not "Clash39".
  useEffect(() => {
    setTitles({}); setNaming(0);
    if (!report) return;
    const missing = report.clashes.filter((c) => !c.title).length;
    if (!missing) return;
    let live = true;
    setNaming(missing);
    api.titles(report.id, (e) => {
      if (!live) return;
      if (e.type === "titles") {
        setTitles((t) => ({ ...t, ...e.items }));
        setNaming((n) => Math.max(0, n - Object.keys(e.items).length));
      }
      if (e.type === "done") setNaming(0);
    }).catch(() => { if (live) setNaming(0); });  // no titles (no key, cap reached): the plain names stay
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [report?.id]);

  // ------------------------------------------------------------------ ORCA detection (docs/detection.md)

  useEffect(() => {
    setDetectSetup(null);
    if (!sceneId) return;
    let live = true;
    api.detectTests(sceneId).then((s) => { if (live) setDetectSetup(s); }).catch(() => undefined);
    return () => { live = false; };
  }, [sceneId, reqId]);

  function onDetectEvent(e: DetectEvent) {
    setDetecting((p) => {
      const cur = p ?? { phase: "Starting…", tests: [] };
      if (e.type === "phase") return { ...cur, phase: e.text };
      if (e.type === "start") return { ...cur, phase: `Checking ${e.elements.toLocaleString()} elements`, tests: e.tests.map((t) => ({ name: t.name })) };
      if (e.type === "test") return { ...cur, running: e.index };
      if (e.type === "test_done") return { ...cur, tests: cur.tests.map((t, i) => (i === e.index ? { ...t, coverage: e.coverage } : t)) };
      return cur;
    });
  }

  /** Find the clashes in the open models and open them as the report. `tests` null: the server's defaults. Marks on
   * clashes that are still there (by design, for the author) survive a rerun: their ids stay the same. */
  async function runDetect(tests: DetectTest[] | null, sid: string | null = sceneId) {
    if (!sid || busy || detecting) return;
    const epoch = sceneEpoch.current;
    const keep = report?.origin === "sightline" ? reviewed : {};
    const selected = report?.origin === "sightline" ? clash?.id : undefined;
    lastTests.current = tests;
    setDetecting({ phase: "Starting…", tests: [] }); setError(null);
    try {
      const done = await api.detect(sid, tests, onDetectEvent);
      if (sceneEpoch.current !== epoch) return;
      const r = await loadReport(async () => done.report, "the clashes ORCA found");
      if (!r) return;
      setDetection({ coverage: done.coverage, diff: done.diff, elements: done.elements, seconds: done.seconds, requirements: done.requirements ?? null });
      const ids = new Set(r.clashes.map((c) => c.id));
      setReviewed(Object.fromEntries(Object.entries(keep).filter(([id]) => ids.has(id))));
      const still = selected && r.clashes.find((c) => c.id === selected);
      if (still) selectClash(still);
    } catch (e) { if (sceneEpoch.current === epoch) setError((e as Error).message); }
    finally { setDetecting(null); }
  }

  /** The chat ran detection: show its report without ending the chat turn that is still answering about it. */
  async function adoptChatReport(reportId: string, found: Detection) {
    const workspace = workspaceEpoch.current;
    try {
      const r = await api.report(reportId);
      if (workspaceEpoch.current !== workspace) return;
      setReport(r); setClash(null); setChecked(new Set()); setPlan(null); setPlanRun(null); setFixes({}); setReviewed({});
      setVerdicts(null); setViews({}); captures.current.clear(); setDetection(found);
    } catch (e) { setError((e as Error).message); }
    finally { setDetecting(null); }
  }

  /** A clash ORCA found has no pictures: take its A/B/C views in the viewer and keep them on the server, where the
   * fix agent, triage and the PDF use them as they use Navisworks views. Once per clash. */
  function captureViews(reportId: string, clashId: string, ga: string, gb: string): Promise<void> {
    const pending = captures.current.get(clashId);
    if (pending) return pending;
    const shots = viewer.current?.captureClash(ga, gb);
    if (!shots) return Promise.resolve();
    setCapturing(clashId);
    const p = (async () => {
      let labels: string[] = [];
      for (const label of ["A", "B", "C"] as const) labels = await api.saveView(reportId, clashId, label, await (await fetch(shots[label])).blob());
      setViews((v) => ({ ...v, [clashId]: labels }));
    })().catch(() => undefined).finally(() => setCapturing((c) => (c === clashId ? null : c)));
    captures.current.set(clashId, p);
    return p;
  }

  function upload(list: FileList | File[] | null) {
    if (busy) return;
    const files = [...(list ?? [])].filter((f) => /\.(xml|png|jpe?g)$/i.test(f.name));
    if (!files.length) return setError("Choose a Navisworks XML report, or the folder it was exported to.");
    loadReport(() => api.uploadReport(files), `${files.length} file${files.length > 1 ? "s" : ""}`);
  }

  /** Select a report clash and take the view to it, or (`keepPlan`) only select it while a plan stays on screen. */
  function selectClash(c: ReportClash, keepPlan = false) {
    if (!keepPlan) clearManual();
    if (c.id !== clash?.id) { setClash(c); resetWork(keepPlan); setLightbox(null); }
    if (keepPlan) return;
    setViewPlan(false); setViewContext(false);
    if (tab === "plan" && !planRun) setTab("clash");
    if (!matches) { setA(null); setB(null); return; }
    goToClash(c);  // every click navigates, also on the clash already selected
  }

  /** Single click: measure, or show the element's properties. Double click: pick element A, then B. A drag is an
   * orbit, never a pick. */
  function onClick(ev: React.MouseEvent) {
    const d = down.current;
    if (d && Math.hypot(ev.clientX - d.x, ev.clientY - d.y) > (coarse ? 10 : 5)) return;
    if (longPress.current?.fired) { longPress.current = null; return; }  // the long press already picked
    const hit = viewer.current?.pickAt(ev.nativeEvent);
    if (ev.detail === 2) {
      if (!hit || hit.globalId === a) return;
      pickSide(hit.globalId);
      return;
    }
    if (tool.measure) {
      if (hit) setMeasurePts((p) => (p.length >= 2 ? [hit.point] : [...p, hit.point]));
      return;
    }
    if (!hit) { setSelected(null); return; }
    const epoch = sceneEpoch.current;
    setSelected({ globalId: hit.globalId, info: null });
    if (sceneId) api.element(sceneId, hit.globalId)
      .then((info) => { if (sceneEpoch.current === epoch) setSelected((s) => (s?.globalId === hit.globalId ? { ...s, info } : s)); })
      .catch(() => undefined);
  }

  /** Pick element A, then B (a double click, a long press, or Set as A / B on its card). */
  function pickSide(gid: string, side: "a" | "b" = !a || (a && b) ? "a" : "b") {
    if (side === "a") { setA(gid); setB(null); } else setB(gid);
    setClash(null); resetWork();
    if (compact) {  // say what comes next, and show the pair once it is whole
      setSelected(null);
      flash(side === "a" ? "A set. Now pick element B: tap it, then Set as B." : "B set. Propose fixes, below.");
      if (side === "b") { setListOpen(false); if (tab === "chat") setTab("clash"); if (snap === "peek") setSnap("half"); }
    }
  }

  function flash(text: string) {
    setToast(text);
    window.clearTimeout(flashTimer.current);
    flashTimer.current = window.setTimeout(() => setToast(null), 2800);
  }
  const flashTimer = useRef(0);

  /** A long press (half a second, finger still) on a touch screen picks A then B, as a double click does. */
  function pressStart(e: React.PointerEvent) {
    down.current = { x: e.clientX, y: e.clientY };
    if (e.pointerType !== "touch" || tool.measure) return;
    window.clearTimeout(longPress.current?.timer);
    const at = { clientX: e.clientX, clientY: e.clientY } as MouseEvent;
    const press = { x: e.clientX, y: e.clientY, fired: false, timer: 0 };
    press.timer = window.setTimeout(() => {
      const hit = viewer.current?.pickAt(at);
      if (!hit || hit.globalId === a) return;
      press.fired = true;
      navigator.vibrate?.(10);
      pickSide(hit.globalId);
    }, 500);
    longPress.current = press;
  }
  function pressMove(e: React.PointerEvent) {
    const p = longPress.current;
    if (p && !p.fired && Math.hypot(e.clientX - p.x, e.clientY - p.y) > 10) { window.clearTimeout(p.timer); longPress.current = null; }
  }
  function pressEnd() {
    const p = longPress.current;
    if (p && !p.fired) { window.clearTimeout(p.timer); longPress.current = null; }
  }

  function toggle(k: "edges" | "section" | "measure") {
    setTool((t) => ({ ...t, [k]: !t[k] }));
    if (k === "measure") setMeasurePts([]);
  }

  function setModelVisible(i: number, visible: boolean) {
    viewer.current?.setModelVisible(i, visible);
    setTool((t) => ({ ...t, hiddenModels: visible ? t.hiddenModels.filter((x) => x !== i) : [...t.hiddenModels, i] }));
  }

  function screenshot() {
    const url = viewer.current?.snapshot();
    if (!url) return;
    const link = document.createElement("a");
    link.href = url;
    link.download = `orca-${clash ? `clash-${clash.number}` : "view"}.png`;
    link.click();
  }

  function focusNow() {
    if (clash) goToClash(clash);
    else if (a || b) viewer.current?.frame([a, b].filter((g): g is string => !!g));
  }

  // Keyboard: 1-4 views, H fit, F clash, X/C/I/V modes, S section, E edges, M measure, Esc clears.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || (e.target as HTMLElement).closest("input, textarea, select")) return;
      const views: Record<string, Preset> = { "1": "top", "2": "front", "3": "right", "4": "iso" };
      const modes: Record<string, ViewMode> = { x: "xray", c: "context", i: "isolate", v: "shaded" };
      const k = e.key.toLowerCase();
      if (views[k]) viewer.current?.view(views[k]);
      else if (k === "h") viewer.current?.fitAll();
      else if (k === "f") focusNow();
      else if (modes[k]) setTool((t) => ({ ...t, mode: modes[k] }));
      else if (k === "s") toggle("section");
      else if (k === "e") toggle("edges");
      else if (k === "m") toggle("measure");
      else if (k === "escape") { setMeasurePts([]); setSelected(null); setLightbox(null); }
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  /** Start showing the agent's progress; returns the handler for its events and a function to call when done. With
   * `first` (a second try), the first try's ideas stay in the activity table and the second's are numbered after them. */
  function trackAgent(first: Proposal | null = null) {
    directContext.current?.retire();
    clearManual();
    const run = ++agentRun.current;
    const epoch = sceneEpoch.current;
    const live = () => agentRun.current === run && sceneEpoch.current === epoch;
    setError(null); setChosen(null); setViewPlan(false); setViewContext(false); setReplaying(false);
    const t = Date.now();
    let p: Progress = { started: t, round: 1, phase: "thinking", thinkingSince: t, modelSeconds: [], ideas: 0, checking: null,
      ...(first ? { model: wonder, offset: first.attempts.length } : {}) };
    setProgress(p); setNow(t);
    setProposal(first ? { understanding: first.understanding, options: [], attempts: first.attempts, advice: first.advice }
      : { understanding: "", options: [], attempts: [] });
    setThoughts([]);
    pilot.current?.start(first ? wonder : undefined);
    const update = (next: Partial<Progress>) => { p = { ...p, ...next }; setProgress(p); };
    let attempts = first?.attempts.length ?? 0;
    const onEvent = (e: AgentEvent) => {
      if (!live()) return;
      pilot.current?.event(e);
      // A second try starting in the same stream (automatic): its ideas are numbered after the first's.
      if (e.type === "escalating") {
        const seed = !first && !attempts && e.first_try?.attempts.length ? e.first_try : null;
        if (seed) {   // a try the page didn't watch (a plan's item): its ideas lead the table
          attempts = seed.attempts.length;
          setProposal((q) => q && { ...q, understanding: seed.understanding, advice: seed.advice, attempts: seed.attempts });
        }
        update({ model: e.model, offset: attempts, round: 1, modelSeconds: [] }); setThoughts([]);
        pilot.current?.model(e.model, attempts);
      }
      else if (e.model && e.model !== p.model && p.offset == null) update({ model: e.model });
      if (e.type === "attempt") attempts += 1;
      if (e.type === "note") setThoughts((t) => [...t, { round: p.round, text: e.text }]);   // e.g. why no second try
      if (e.type === "reasoning") setThoughts((t) => [...t, { round: e.round, text: e.text }]);
      if (e.type === "thinking") update({ round: e.round, phase: "thinking", thinkingSince: Date.now(), checking: null });
      if (e.type === "ideas") {
        update({ phase: "checking", modelSeconds: [...p.modelSeconds, e.seconds], ideas: e.count });
        setProposal((q) => q && { ...q, understanding: e.understanding });
      }
      if (e.type === "checking") update({ checking: { index: e.index, title: e.title, kind: e.kind } });
      if (e.type === "attempt") {
        const { type: _t, index: _i, ...attempt } = e;
        setProposal((q) => q && { ...q, attempts: [...q.attempts, attempt] });
      }
    };
    const finish = (result: Proposal | null) => {
      if (!live()) return;
      const show = () => {
        if (!live()) return;
        if (result) { setProposal(result); setChosen(result.options.length ? 0 : null); }
        // A second try that failed or was refused: the first try's fixes stand.
        else if (first) { setProposal(first); setChosen(first.options.length ? 0 : null); }
        if (result?.recommendation) noteRecommendation(result.recommendation, [a, b] as const);
        update({ phase: "done", checking: null }); setNow(Date.now());
      };
      if (pilot.current) pilot.current.finish(show); else show();
    };
    const retire = () => {
      if (!live()) return;
      ++agentRun.current; pilot.current?.cancel();
      const owned = p;
      if (owned.phase !== "done") {
        const retired: Progress = { ...owned, phase: "done", checking: null };
        setProgress((current) => current === owned ? retired : current);
      }
    };
    return { onEvent, finish, live, retire };
  }

  /** Propose fixes for the pair (Muse Spark, up to three rounds). */
  function propose() { return runProposal(false); }
  /** A second, longer try on Muse Wonder, reading this try (docs/escalation.md): after no fix, or for a better one. */
  function escalate() { return runProposal(true); }

  /** A failed Fix-together item: its clash, then a second try on it (reading the plan's try at that pair). */
  function escalateItem(it: PlanItem) {
    const c = report?.clashes.find((x) => it.clash_ids.includes(x.id)) ?? null;
    if (c) selectClash(c); else { resetWork(); setA(it.element_a); setB(it.element_b); }
    setViewPlan(false); showClashTab();
    void runProposal(true, { a: it.element_a, b: it.element_b, clash: c });
  }

  /** `pick`: a pair other than the one shown (a plan's item; the page's selection catches up as this runs). */
  async function runProposal(second: boolean, pick?: { a: string; b: string; clash: ReportClash | null }) {
    const ea = pick ? pick.a : a, eb = pick ? pick.b : b, on = pick ? pick.clash : clash;
    if (!sceneId || !ea || !eb || busy) return;
    replaceChatWork();
    const tracker = trackAgent(second && !pick ? proposal : null); directAgent.current = tracker;
    const { onEvent, finish } = tracker;
    const run = agentRun.current;
    const from = on && report ? { report_id: report.id, clash_id: on.id } : undefined;
    // A clash ORCA found: give the agent its views, as a Navisworks report would (waiting a few seconds at most).
    if (on && report?.origin === "sightline" && !on.images.length && !views[on.id])
      await Promise.race([captureViews(report.id, on.id, ea, eb), new Promise((r) => setTimeout(r, 4000))]);
    let result: Proposal | null = null;
    try { result = await api.proposeStream(sceneId, ea, eb, from, onEvent, second); }
    catch (e) { if (agentRun.current === run) setError((e as Error).message); }
    finally { finish(result); }
  }

  /** Play a recorded proposal (the tour's fallback when the live one fails or is slow) through the same viewer and
   * pilot, at the pace it was recorded. Accepting its fix edits the model for real, like a live one. */
  async function replayPropose(which: "duct" | "joint" | "ladder") {
    const c = which === "ladder" ? clashOfNames(CELL.ladder, CELL.post)[0] : clashOfPair(TOUR[which]);
    if (!c || !sceneId) return;
    replaceChatWork();
    if (clash?.id !== c.id) selectClash(c);
    const epoch = sceneEpoch.current;
    // Recorded on Oct 27 from the imported report, where these were c0053 and c0051.
    const rec: { events: { t: number; event: AgentEvent | ({ type: "result" } & Proposal) }[] } =
      await (await fetch(`/tour/${{ duct: "c0053", joint: "c0051", ladder: "cell-ladder" }[which]}.json`)).json();
    if (sceneEpoch.current !== epoch) return;
    const tracker = trackAgent(); directAgent.current = tracker;
    const { onEvent, finish } = tracker;
    const run = agentRun.current;
    setReplaying(true);
    const start = Date.now();
    for (const { t, event } of rec.events) {
      const wait = start + t * 1000 - Date.now();
      if (wait > 0) await new Promise((r) => setTimeout(r, wait));
      if (agentRun.current !== run) return;
      if (event.type === "result") { finish(event as Proposal); setReplaying(false); return; }
      onEvent(event as AgentEvent);
    }
    finish(null); setReplaying(false);
  }

  /** Play a recorded plan (the tour's fallback), at the pace it was recorded: the girder's root cause (Northbank) or
   * the air pipe through both conveyor rails, fixed together (the cell). */
  async function replayPlan(which: "girder" | "pipe" = "girder") {
    replaceChatWork();
    const epoch = sceneEpoch.current;
    const rec: { events: { t: number; event: PlanEvent }[] } =
      await (await fetch(which === "girder" ? "/tour/girder-plan.json" : "/tour/cell-pipe-plan.json")).json();
    if (sceneEpoch.current !== epoch) return;
    // It was recorded on the imported report: point its clash ids at this report's clashes of the same element pairs
    // (a fix item names its pair; a hub partner pairs with the hub).
    const pairIds = (x: string, y: string) => (report?.clashes ?? [])
      .filter((c) => [c.a.global_id, c.b.global_id].sort().join("|") === [x, y].sort().join("|")).map((c) => c.id);
    const remap = (o: unknown): unknown => {
      if (Array.isArray(o)) return o.map(remap);
      if (!o || typeof o !== "object") return o;
      const out: Record<string, unknown> = Object.fromEntries(Object.entries(o).map(([k, v]) => [k, remap(v)]));
      const pair = typeof out.element_a === "string" && typeof out.element_b === "string" ? [out.element_a, out.element_b]
        : typeof out.global_id === "string" && "in_report" in out ? [out.global_id, TOUR.girder] : null;
      if (pair && Array.isArray(out.clash_ids)) {
        // a merged item (one element, several partners) stands for the clashes with every partner
        const partners = [pair[1], ...(Array.isArray(out.others) ? out.others as string[] : [])];
        out.clash_ids = partners.flatMap((p) => pairIds(pair[0], p));
        out.in_report = (out.clash_ids as string[]).length > 0;
      }
      if (Array.isArray(out.partners)) {
        const partners = out.partners as { clash_ids: string[]; in_report?: boolean }[];
        out.clash_ids = [...new Set(partners.flatMap((x) => x.clash_ids))];
        out.not_in_report = partners.filter((x) => !x.in_report).length;
      }
      return out;
    };
    rec.events = rec.events.map((e) => ({ ...e, event: remap(e.event) as PlanEvent }));
    const tracker = trackPlan(which === "girder" ? "root_cause" : "batch"); directPlan.current = tracker;
    const { onEvent, finish, live } = tracker;
    setReplaying(true);
    const start = Date.now();
    for (const { t, event } of rec.events) {
      const wait = start + t * 1000 - Date.now();
      if (wait > 0) await new Promise((r) => setTimeout(r, wait));
      if (!live()) return;
      if (event.type === "plan") { finish(event); setReplaying(false); return; }
      if (event.type !== "error") onEvent(event);
    }
    finish(null); setReplaying(false);
  }

  /** Start showing a plan being built; returns the handler for its events and a function to call when done. */
  function trackPlan(kind: "batch" | "root_cause") {
    directContext.current?.retire();
    const epoch = sceneEpoch.current, request = ++planRequest.current;
    const live = () => sceneEpoch.current === epoch && planRequest.current === request;
    ++agentRun.current; pilot.current?.cancel();
    resetWork(); setPlan(null); setError(null); setPlanError(null);
    setViewPlan(true); setViewContext(false); setPlanKind("batch");
    const t = Date.now();
    let run: PlanRun = { kind, started: t, phase: kind === "root_cause" ? "cause" : "fixing", rootCause: "", items: [], status: {} };
    setPlanRun(run); setNow(t);
    const update = (f: (r: PlanRun) => PlanRun) => { run = f(run); setPlanRun(run); };
    const onEvent = (e: PlanEvent) => {
      if (!live()) return;
      if (e.type === "root_cause") update((r) => ({ ...r, rootCause: e.root_cause, phase: "fixing" }));
      if (e.type === "plan_items") update((r) => ({ ...r, phase: "fixing", items: e.items,
        status: Object.fromEntries(e.items.map((i) => [i.key, { state: "waiting" as const }])) }));
      if (e.type === "item") update((r) => ({ ...r, status: { ...r.status, [e.key]: {
        state: e.status, ok: e.ok, note: e.status === "thinking" ? "Muse Spark is looking…" : e.status === "checking" ? `checked: ${e.attempt}` : e.title } } }));
      if (e.type === "checking_plan") update((r) => ({ ...r, phase: "checking" }));
    };
    const finish = (p: Plan | null) => {
      if (!live()) return;
      if (p) { setPlan(p); planRevision.current = sceneRevision.current; }   // what its joint check was made on
      update((r) => ({ ...r, phase: "done" })); setNow(Date.now());
    };
    const retire = () => {
      if (!live()) return;
      const retiredRequest = ++planRequest.current, owned = run;
      if (owned.phase !== "done") {
        const note = "Stopped when newer work took over.";
        const retired: PlanRun = { ...owned, phase: "done", status: Object.fromEntries(Object.entries(owned.status).map(([key, value]) =>
          [key, value.state === "done" ? value : { ...value, state: "done", ok: false, note }])) };
        setPlanRun((current) => current === owned ? retired : current);
        setPlanError((current) => planRequest.current === retiredRequest ? note : current);
      }
    };
    return { onEvent, finish, live, retire };
  }

  /** Build a plan: several ticked clashes together, or the root cause around one element. */
  async function runPlan(body: { clash_ids?: string[]; hub?: string }) {
    if (!sceneId || !report || busy) return;
    replaceChatWork();
    setTab("plan");
    const tracker = trackPlan(body.hub ? "root_cause" : "batch"); directPlan.current = tracker;
    const { onEvent, finish, live } = tracker;
    let p: Plan | null = null;
    try { p = await api.planStream(sceneId, { report_id: report.id, fixed: resolved, ...body }, onEvent); }
    catch (e) { if (live()) setPlanError((e as Error).message); }
    finally { finish(p); }
  }

  async function acceptPlan() {
    if (!sceneId || !plan || busy || planStale) return;
    replaceChatWork(); retireDirectWork(); clearManual();
    const epoch = sceneEpoch.current;
    const live = () => sceneEpoch.current === epoch;
    const items = plan.items.filter((i) => i.option && (plan.check.passed || plan.check.items[i.key]?.passed));
    setBusy(`Applying ${items.length} fix${items.length > 1 ? "es" : ""}…`);
    const pics = captureFix(items.map((i) => i.option!), "#1f9d3a");
    const built = items.map((i) => {
      const key = builtKey([i.element_a, i.element_b], i.option!);
      return canBuild(i.option!) && builtDone.current[key]?.status !== "done" && !builtPending.current.has(key)
        ? builtPasses(builtFix(i.option!, false), [i.element_a, i.element_b]) : null;
    });
    try {
      const kept = await api.applyPlan(sceneId, items.map((i) => i.option!));
      const pieces = kept.pieces;
      if (!live()) return;
      staleContext();
      viewer.current?.preview([]);
      await applyToViewer(sceneId, kept, pieces, live);
      if (!live()) return;
      setEdits((e) => {
        const next = { ...e };
        for (const ps of pieces) if (ps.length) { const [first, ...added] = ps; next[first] = [...(next[first] ?? []), ...added]; }
        return next;
      });
      // A merged item (one pipe through two rails) fixes its clashes with every partner. A penetration its host's team
      // must cut was only asked for: its clashes stay open.
      const pairsOf = (i: PlanItem) => [i.element_b, ...(i.others ?? [])].map((o) => [i.element_a, o] as const);
      const requested = new Map((kept.not_cut ?? []).map((n) => [n.index, n.blocked_by] as const));
      const done = items.filter((_, k) => !requested.has(k));
      markFixed(done.flatMap(pairsOf), done.flatMap((i) => pairsOf(i).map(() => i.option!.title)));
      const groups = items.map((i) => clashIdsOf(pairsOf(i)).flat());
      setEvidence((ev) => {
        const next = { ...ev };
        items.forEach((it, k) => {
          const why = requested.get(k);
          for (const id of new Set([...groups[k], ...it.clash_ids])) {
            next[id] = why == null ? evidenceOf(it.option!, "accepted", pics) : { ...evidenceOf(it.option!, "recommended", pics), blocked_by: why };
          }
        });
        return next;
      });
      items.forEach((it, k) => { if (!requested.has(k)) buildAccepted(it.option!, [it.element_a, it.element_b],
        [...new Set([...groups[k], ...it.clash_ids])], built[k], kept.groups?.[k]?.[0]); });
      setPlan(null); setPlanRun(null); setChecked(new Set()); setRemeasure((n) => n + 1);
    } catch (e) { if (live()) setError((e as Error).message); } finally { if (live()) setBusy(null); }
  }

  /** Bring the viewer up to a kept fix: patch the changed elements in place when the server sent them and this page's
   * model is at the revision the fix started from (viewer/patch.ts); otherwise reload the files it changed. */
  async function applyToViewer(sid: string, kept: { files: number[] } & Patch, pieces: string[][] | undefined, live: () => boolean) {
    const origin = new Map((pieces ?? []).flatMap((ps) => ps.slice(1).map((g) => [g, ps[0]] as const)));
    if (kept.meshes && kept.scene_id === sid && kept.revision_before != null && kept.revision_before === sceneRevision.current
        && viewer.current?.patch(kept.meshes, origin)) {
      sceneRevision.current = kept.revision ?? null;
      return;
    }
    // Reload this fix's files, and any file changed by an edit this page missed (after the revision it last drew; all of
    // them when it doesn't know), so it never jumps to a revision whose edits it hasn't drawn.
    const drawn = sceneRevision.current;
    const missed = (kept.history ?? []).filter(([rev]) => drawn == null || rev > drawn).flatMap(([, files]) => files);
    for (const i of [...new Set([...kept.files, ...missed])].sort((x, y) => x - y)) {
      const bytes = await api.file(sid, i);
      if (!live()) return;
      await viewer.current!.replace(i, bytes, live);
    }
    if (live()) sceneRevision.current = kept.revision ?? null;
  }

  /** Mark every report clash of these element pairs as fixed (one pair can be reported by several tests). */
  function markFixed(pairs: (readonly [string | null, string | null])[], titles: string[]) {
    if (!report || !matches) return;
    const byPair = new Map(pairs.map((p, i) => [[p[0], p[1]].sort().join("|"), titles[i]]));
    const fixed: Record<string, string> = {};
    for (const c of report.clashes) {
      const title = byPair.get([matches[c.id]?.a, matches[c.id]?.b].sort().join("|"));
      if (title) fixed[c.id] = title;
    }
    setFixes((f) => ({ ...f, ...fixed }));
  }

  function focusItem(it: PlanItem) {
    clearManual();
    const c = report?.clashes.find((x) => it.clash_ids.includes(x.id));
    setA(it.element_a); setB(it.element_b);
    if (c) goToClash(c, { a: it.element_a, b: it.element_b, how: [] });
    else viewer.current?.focusClash([it.element_a, it.element_b], null, it.in_report ? "" : "not in the report");
  }

  /** Context events own their objective and request generation, independent of later clash selection. */
  function trackContext(objective: ContextObjective | null) {
    directContext.current?.retire();
    const controller = new AbortController();
    const epoch = sceneEpoch.current, request = ++contextRequest.current;
    const live = () => sceneEpoch.current === epoch && contextRequest.current === request;
    ++agentRun.current; pilot.current?.cancel();
    resetWork(); setViewPlan(false); setViewContext(true); setPlanKind("context"); setCompare("after");
    setContextChosen(null); setAcknowledged([]);
    const started = Date.now(); setNow(started);
    let run: ContextRun = { objective, started, phase: "inspecting", messages: [], result: null, error: null, stale: false };
    setContext(run);
    const onEvent = (event: ContextEvent) => {
      if (!live()) return;
      run = contextStep(run, event); setContext(run);
      if (event.type === "context_result") {
        setContextChosen(event.proposals[0]?.id ?? null); setAcknowledged([]);
      }
    };
    const fail = (message: string) => onEvent({ type: "error", detail: message });
    const retire = () => {
      controller.abort();
      if (!live()) return;
      ++contextRequest.current;
      const owned = run;
      if (owned.phase !== "done") {
        const retired: ContextRun = { ...owned, phase: "done", error: "Search stopped when newer work took over. Regenerate for the original objective to continue." };
        setContext((current) => current === owned ? retired : current);
      }
    };
    return { onEvent, fail, live, retire, signal: controller.signal };
  }

  async function exploreContext(objective?: ContextObjective) {
    if (!sceneId || busy) return;
    const target = objective ?? (a && b ? { element_a: a, element_b: b,
      ...(clash && report && samePair(matches?.[clash.id]?.a, matches?.[clash.id]?.b, a, b)
        ? { report_id: report.id, clash_id: clash.id } : {}) } : null);
    if (!target) return;
    replaceChatWork();
    setTab("plan");
    const tracker = trackContext(target); directContext.current = tracker;
    try { await api.contextStream(sceneId, target, tracker.onEvent, tracker.signal); }
    catch (e) { if (!tracker.signal.aborted) tracker.fail((e as Error).message); }
  }

  function staleContext() {
    // The server alone decides revisions; local mutation only disables reuse of the old proposal.
    directContext.current?.retire(); ++contextRequest.current;
    setAcknowledged([]);
    setContext((r) => r && !r.accepted ? { ...r, phase: "done", stale: true } : r);
  }

  async function acceptContext() {
    if (!sceneId || !contextProposal || context?.stale || context?.accepted || contextWorking || busy) return;
    if (!contextProposal.review_conditions.every((c) => acknowledged.includes(c.id))) return;
    replaceChatWork(); retireDirectWork(); clearManual();
    const p = contextProposal, sid = sceneId, epoch = sceneEpoch.current, request = contextRequest.current;
    const live = () => sceneEpoch.current === epoch && contextRequest.current === request;
    setBusy("Rechecking and applying the complete proposal…");
    setContext((r) => r && { ...r, error: null });
    let committed = false;
    const pics = captureContext(p);
    try {
      const applied = await api.applyContext(sid, p.id, acknowledged);
      if (!live()) return;
      committed = true;
      // Every source in a moved group maps to its actual committed pieces, never trial mesh IDs.
      setEdits((old) => {
        const next = { ...old };
        for (const edit of applied.edits) for (const source of edit.moved)
          next[source] = [...new Set([...(next[source] ?? []), ...edit.pieces.filter((g) => g !== source)])];
        return next;
      });
      markFixed(applied.resolved_pairs.map((pair) => [pair.element_a, pair.element_b] as const), applied.resolved_pairs.map(() => p.title));
      const ids = clashIdsOf(applied.resolved_pairs.map((pair) => [pair.element_a, pair.element_b] as const)).flat();
      const accepted = contextEvidence(p, applied.checks, pics);
      setEvidence((ev) => ({ ...ev, ...Object.fromEntries(ids.map((id) => [id, accepted])) }));
      // Server commit is the boundary: none of the old single/batch options can still be accepted.
      setProposal(null); setChosen(null); setPlan(null); setPlanRun(null); setChecked(new Set());
      setContext((r) => r && { ...r, accepted: true });
      viewer.current?.preview([]);
      await applyToViewer(sid, applied, applied.pieces, live);
      if (!live()) return;
      setContext((r) => r && { ...r, accepted: true });
      setViewContext(false); setChosen(null); setPlan(null); setPlanRun(null); setChecked(new Set()); setRemeasure((n) => n + 1);
    } catch (e) {
      if (!live()) return;
      const conflict = e instanceof ApiError && (e.status === 409 || e.status === 404);
      setContext((r) => r && { ...r, accepted: committed, stale: conflict,
        error: committed ? `The proposal was accepted on the server, but the viewer could not show it: ${(e as Error).message}. Export IFC includes the accepted edits.`
          : conflict ? `Revision conflict or fresh checks failed: ${(e as Error).message}` : (e as Error).message });
      if (committed) setViewContext(false);
      if (conflict) setAcknowledged([]);
    } finally { if (sceneEpoch.current === epoch) setBusy(null); }
  }

  // The chat drives the page through events: select a clash, change the view, show the fix agent's work.
  const chatAgent = useRef<ReturnType<typeof trackAgent> | null>(null);
  const chatContext = useRef<ReturnType<typeof trackContext> | null>(null);
  function replaceChatWork() {
    // Close the turn boundary before starting direct work; old tool events cannot create a fresh tracker.
    chatOwner.current.invalidate();
    chatAgent.current?.retire(); chatPlan.current?.retire(); chatContext.current?.retire();
    chatAgent.current = null; chatPlan.current = null; chatContext.current = null; planThisTurn.current = false;
    chatEscalating.current = false;
  }
  function onChatEvent(e: ChatEvent) {
    if (e.type === "thinking") directContext.current?.retire();
    if (e.type === "tool" && e.name === "explore_wider_fix") {
      const c = report?.clashes.find((x) => x.id === e.args.clash_id), pair = c && matches?.[c.id];
      chatContext.current = trackContext(c && pair?.a && pair.b ? { element_a: pair.a, element_b: pair.b, report_id: report!.id, clash_id: c.id } : null);
      planThisTurn.current = true;
    }
    if (e.type === "context_event") {
      const tracker = chatContext.current ?? trackContext(null);
      chatContext.current = tracker; tracker.onEvent(e.event); planThisTurn.current = true;
    }
    if (e.type === "ui" && e.action === "select_clash") {
      const c = report?.clashes.find((x) => x.id === e.clash_id);
      // Pointing at a clash after building a plan in the same reply: select it, but the plan keeps the view.
      if (c) selectClash(c, planThisTurn.current);
    }
    if (e.type === "tool" && e.name === "detect_clashes") setDetecting({ phase: "Starting…", tests: [] });
    if (e.type === "detect_event") onDetectEvent(e.event);
    if (e.type === "tool_result" && e.name === "detect_clashes") setDetecting(null);
    if (e.type === "ui" && e.action === "open_report") void adoptChatReport(e.report_id, e.detection);
    // After select_clash has had a render to land (the chat names a clash, then asks for its picture).
    if (e.type === "ui" && e.action === "show_it_built") { const id = e.clash_id; setTimeout(() => builtFromChat(id), 80); }
    if (e.type === "ui" && e.action === "set_view") {
      setTool((t) => ({ ...t, ...(e.mode ? { mode: e.mode as ViewMode } : {}), ...(e.section_box != null ? { section: e.section_box } : {}) }));
    }
    if (e.type === "agent") {
      // A second try from chat: the first try's ideas stay; its own round 1 is not a new proposal.
      // Seeded from the server's own first try (the page's may be another clash's, or older than this turn).
      if (e.event.type === "escalating" && !chatAgent.current) {
        const f = e.event.first_try;
        chatAgent.current = trackAgent(f ? { understanding: f.understanding, advice: f.advice, attempts: f.attempts, options: f.options ?? [] }
          : { understanding: "", attempts: [], options: [] });
        chatEscalating.current = true;
      } else if (e.event.type === "escalating") chatEscalating.current = true;
      if (e.event.type === "thinking" && e.event.round === 1 && !chatEscalating.current) chatAgent.current = trackAgent();
      chatAgent.current?.onEvent(e.event);
    }
    if (e.type === "proposal") {
      setA(e.element_a); setB(e.element_b);
      (chatAgent.current ?? trackAgent()).finish(e);
      chatAgent.current = null; chatEscalating.current = false;
    }
    if (e.type === "plan_started") { chatPlan.current = trackPlan(e.kind); planThisTurn.current = true; }
    if (e.type === "error") chatContext.current?.fail(e.detail);
    if (e.type === "tool_result" && e.name === "explore_wider_fix" && chatContext.current?.live()) {
      setContext((r) => r && r.phase !== "done" ? { ...r, phase: "done", error: e.summary } : r);
    }
    // A proposal tool that ended without its proposal (a second try that failed): put back what stood before.
    if (e.type === "tool_result" && e.name === "propose_fixes" && chatAgent.current) {
      chatAgent.current.finish(null); chatAgent.current = null;
    }
    if (e.type === "tool_result" && e.name === "propose_fixes") chatEscalating.current = false;
    if (e.type === "done" || e.type === "error") chatEscalating.current = false;
    if (e.type === "done") { planThisTurn.current = false; chatContext.current = null; }
    if (e.type === "plan_event") chatPlan.current?.onEvent(e.event);
    if (e.type === "plan") { (chatPlan.current ?? trackPlan(e.kind)).finish(e); chatPlan.current = null; }
  }
  const chatPlan = useRef<ReturnType<typeof trackPlan> | null>(null);
  const chatEscalating = useRef(false);
  const planThisTurn = useRef(false);

  // ------------------------------------------------------------------ an agent over MCP
  async function connectAgent() {
    setAgentBusy(true); setAgentError(null);
    try {
      setAgentLink(await api.createLink({ scene_id: sceneId, report_id: report?.id ?? null, clash_id: clash?.id ?? null, fixed: resolved }));
      setAgentLog([]);
    } catch (e) { setAgentError((e as Error).message); } finally { setAgentBusy(false); }
  }
  async function disconnectAgent() {
    if (agentLink) await api.revokeLink(agentLink.token).catch(() => undefined);
    setAgentLink(null); setAgentLog([]);
  }
  // The agent sees what this page has open: keep the link's context current.
  useEffect(() => {
    if (!agentLink) return;
    const t = setTimeout(() => {
      api.linkContext(agentLink.token, { scene_id: sceneId, report_id: report?.id ?? null, clash_id: clash?.id ?? null, fixed: resolved })
        .catch((e) => { if (e instanceof ApiError && e.status === 404) setAgentLink(null); });
    }, 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentLink?.token, sceneId, report?.id, clash?.id, resolved, reqId]);
  /** What the agent does, carried out here: the chat's ui events, opened models, applied fixes, pictures. */
  async function onAgentEvent(e: LinkEvent) {
    if (!agentLink) return;
    if (e.type === "hello") {
      agentStream.current = e.stream;
      setAgentLinkState((l) => l && { ...l, expires_at: e.expires_at, max_expires_at: e.max_expires_at,
        clock_offset: e.server_time - Date.now() / 1000, calls: e.calls, last_call: e.last_call ?? l.last_call });
      return;
    }
    if (e.type === "heartbeat") return;
    if (e.type === "revoked") { setAgentLink(null); return; }
    if (e.type === "agent_call") {
      setAgentLinkState((l) => l && { ...l, last_call: { tool: e.tool, at: Date.now() / 1000 }, expires_at: e.expires_at ?? l.expires_at });
      setAgentLog((log) => [...log.slice(-40), { at: Date.now() / 1000, tool: e.tool, text: "…" }]);
      return;
    }
    if (e.type === "agent_result") {
      setAgentLog((log) => {
        const i = log.map((x) => x.tool).lastIndexOf(e.tool);
        if (i < 0) return [...log, { at: Date.now() / 1000, tool: e.tool, text: e.summary }];
        const next = [...log]; next[i] = { ...next[i], text: e.summary }; return next;
      });
      return;
    }
    if (e.type === "capture_request") {
      let png: Blob | null = null;
      try {
        if (e.what === "view") {
          const url = viewer.current?.capture(1024);
          png = url ? await (await fetch(url)).blob() : null;
        } else if (e.report_id && e.clash_id && e.a && e.b) {
          await captureViews(e.report_id, e.clash_id, e.a, e.b);  // saved on the report, where the agent reads them
        }
      } finally { await api.linkCapture(agentLink.token, e.id, png).catch(() => undefined); }
      return;
    }
    if (e.type === "ui" && e.action === "open_models") { if (!busy) void openDemo(e.names); return; }
    if (e.type === "ui" && e.action === "follow_triage") { if (!triageRun || triageRun.done) void runTriage(false); return; }
    if (e.type === "ui" && e.action === "applied") {
      if (!sceneId) return;
      const epoch = sceneEpoch.current, live = () => sceneEpoch.current === epoch;
      staleContext(); viewer.current?.preview([]);
      await applyToViewer(sceneId, e, e.pieces, live);
      if (!live()) return;
      setEdits((ed) => {
        const next = { ...ed };
        for (const ps of e.pieces) if (ps.length) { const [first, ...added] = ps; next[first] = [...(next[first] ?? []), ...added]; }
        return next;
      });
      markFixed(e.pairs, e.titles);
      resetWork(); setRemeasure((n) => n + 1);  // as when the person accepts: the options are spent
      return;
    }
    onChatEvent(e as ChatEvent);
  }
  // When the tab closes, tell the server at once (a proxy may hold a dropped stream open for a while), so the agent
  // is not told a browser is following.
  const agentStream = useRef<string | null>(null);
  useEffect(() => {
    if (!agentLink) return;
    const token = agentLink.token;
    const bye = () => { if (agentStream.current) api.leaveLink(token, agentStream.current); };
    window.addEventListener("pagehide", bye);
    return () => window.removeEventListener("pagehide", bye);
  }, [agentLink?.token]);
  const agentHandler = useRef(onAgentEvent);
  agentHandler.current = onAgentEvent;
  // Follow the link while it lives: the server ends each stream after a few minutes, so reconnect.
  useEffect(() => {
    if (!agentLink) return;
    const token = agentLink.token, stop = new AbortController();
    void (async () => {
      for (let tries = 0; !stop.signal.aborted; tries++) {
        try {
          await api.linkEvents(token, (e) => { void agentHandler.current(e); }, stop.signal);
          tries = 0;
        } catch (e) {
          if (stop.signal.aborted) return;
          if (e instanceof ApiError && e.status === 404) { setAgentLink(null); return; }
        }
        await new Promise((r) => setTimeout(r, Math.min(15000, 1000 * 2 ** Math.min(tries, 4))));
      }
    })();
    return () => stop.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentLink?.token]);
  // A clock for "last call 4 s ago" and the time left, and the link's state from the server once a minute (its expiry
  // renews as it is used; a link that expired or was revoked elsewhere is dropped).
  useEffect(() => {
    if (!agentLink) return;
    const token = agentLink.token;
    const tick = setInterval(() => setNow(Date.now()), 2000);
    const poll = setInterval(() => {
      api.linkState(token).then((s) => setAgentLinkState((l) => l && l.token === token ? {
        ...l, expires_at: s.expires_at, max_expires_at: s.max_expires_at, calls: s.calls,
        clock_offset: s.server_time - Date.now() / 1000 } : l))
        .catch((e) => { if (e instanceof ApiError && e.status === 404) setAgentLink(null); });
    }, 60000);
    return () => { clearInterval(tick); clearInterval(poll); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentLink?.token]);

  // ------------------------------------------------------------------ the saved session (resume after a reload)
  const SESSION_KEY = "sightline.session";
  useEffect(() => {  // on arrival: is there a session the server still holds?
    let saved: SavedSession | null = null;
    try { saved = JSON.parse(localStorage.getItem(SESSION_KEY) ?? "null"); } catch { saved = null; }
    if (!saved?.scene_id) return;
    const s = saved;
    void (async () => {
      try {
        const info = await api.sceneInfo(s.scene_id);
        const r = s.report_id ? await api.report(s.report_id).catch(() => null) : null;
        // The link, if it still lives, and the fixes its agent applied while no page was open.
        const state = s.link ? await api.linkState(s.link.token).catch(() => null) : null;
        const link = state && s.link ? { ...s.link, expires_at: state.expires_at, max_expires_at: state.max_expires_at,
                                         clock_offset: state.server_time - Date.now() / 1000 } : null;
        setResumable({ saved: { ...s, link, fixes: { ...s.fixes, ...(state?.applied ?? {}) } },
                       info, clashes: r ? r.clashes.length : null });
      } catch { try { localStorage.removeItem(SESSION_KEY); } catch { /* private window */ } }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {  // keep it current while working
    if (!sceneId) return;
    const s: SavedSession = { scene_id: sceneId, report_id: report?.id ?? null, files: sceneFiles, fixes,
                              link: agentLink, saved_at: Date.now() / 1000 };
    try { localStorage.setItem(SESSION_KEY, JSON.stringify(s)); } catch { /* private window: no resume */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sceneId, report?.id, sceneFiles, fixes, agentLink?.token]);
  /** Reopen the saved session: the same models (with the fixes applied on the server), its clashes, its fixes, and
   * the agent link, which the page follows again. */
  async function resumeSession() {
    const r = resumable;
    if (!r || busy) return;
    const { saved, info } = r;
    const id = await open(info.files, { id: info.id, files: info.files, step: info.step, revision: info.revision });
    if (!id) return;
    if (saved.report_id) {
      const rep = await loadReport(() => api.report(saved.report_id!), "your clashes");
      if (rep) {
        setFixes(saved.fixes ?? {});
        if (info.detection && info.detection.report_id === rep.id) {
          const { report_id: _r, ...d } = info.detection;
          setDetection(d);
        }
      }
    }
    if (saved.link) setAgentLinkState(saved.link);
  }
  /** Forget the saved session here, and end its agent link: nothing would follow it any more. */
  function startFresh() {
    const link = resumable?.saved.link;
    if (link) void api.revokeLink(link.token).catch(() => undefined);
    try { localStorage.removeItem(SESSION_KEY); } catch { /* private window */ }
    setResumable(null);
  }

  async function accept(o: Option) {
    if (!sceneId || busy) return;
    replaceChatWork(); retireDirectWork(); clearManual();
    const epoch = sceneEpoch.current;
    const live = () => sceneEpoch.current === epoch;
    setBusy("Applying the fix…"); setError(null);
    const ids = clashIdsOf([[a, b]])[0];
    const pics = ids.some((id) => evidence[id]?.after_img && evidence[id]?.title === o.title)
      ? { before_img: evidence[ids[0]]?.before_img, after_img: evidence[ids[0]]?.after_img }
      : captureFix([o], o.moved.includes(a ?? "") ? "#d0342c" : "#1f9d3a");
    // Show it built: the view of the fix as proposed, taken now (once applied, the preview is gone).
    const pair: [string, string] | null = a && b ? [a, b] : null;
    const built = pair && canBuild(o) && builtDone.current[builtKey(pair, o)]?.status !== "done"
      && !builtPending.current.has(builtKey(pair, o)) ? builtPasses(builtFix(o, false), pair) : null;
    try {
      const kept = await api.accept(sceneId, o);
      // Each split run's pieces, the original first (a combined fix can split several runs).
      const groups = kept.groups ?? (kept.pieces?.length ? [kept.pieces] : []);
      if (!live()) return;
      staleContext();
      // A penetration the host's team must cut: asked for (its provision for void is in the model), not yet fixed.
      const requested = kept.cut === false;
      setEvidence((ev) => ({ ...ev, ...Object.fromEntries(ids.map((id) => [id, requested
        ? { ...evidenceOf(o, "recommended", pics), blocked_by: kept.blocked_by ?? "" } : evidenceOf(o, "accepted", pics)])) }));
      viewer.current?.preview([]);
      await applyToViewer(sceneId, kept, groups, live);
      if (!live()) return;
      setEdits((e) => {
        const next = { ...e };
        for (const ps of groups) if (ps.length) { const [first, ...added] = ps; next[first] = [...(next[first] ?? []), ...added]; }
        return next;
      });
      if (!requested) markFixed([[a, b]], [o.title]);
      if (!requested && pair) buildAccepted(o, pair, ids, built, groups[0]);
      resetWork(); setRemeasure((n) => n + 1);
    } catch (e) { if (live()) setError((e as Error).message); } finally { if (live()) setBusy(null); }
  }

  async function checkManual() {
    if (!sceneId || !a || busy) return;
    replaceChatWork(); retireDirectWork(); clearManual();
    ++agentRun.current; pilot.current?.cancel();
    const epoch = sceneEpoch.current, workspace = workspaceEpoch.current, request = previewRequest.current;
    const element = a, delta = [0, 0, manualDz];
    const live = () => sceneEpoch.current === epoch && workspaceEpoch.current === workspace && previewRequest.current === request;
    try {
      const v = await api.verify(sceneId, [element], delta, b && b !== element ? [b] : []);
      if (!live()) return;
      setViewContext(false); setViewPlan(false); setChosen(null);
      setManual(v); setManualPreview({ element, delta });
    } catch (e) { if (live()) setError((e as Error).message); }
  }

  const proposing = !!progress && progress.phase !== "done";
  // A detected clash's views, taken once the camera has reached it (selecting a clash flies there first).
  useEffect(() => {
    if (!clash || !report || report.origin !== "sightline" || clash.images.length || views[clash.id] || !a || !b) return;
    if (viewPlan || activeContext || proposing) return;
    const rid = report.id, cid = clash.id;
    const t = setTimeout(() => { void captureViews(rid, cid, a, b); }, 1500);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clash, report, a, b, views, viewPlan, activeContext, proposing]);
  // What the list and the panel show: each clash with its title and, for a detected clash, the views taken of it.
  const shown = (c: ReportClash) => (views[c.id] || (titles[c.id] && !c.title)
    ? { ...c, images: views[c.id] ?? c.images, title: c.title ?? titles[c.id] ?? null } : c);
  const shownReport = useMemo(() => (report && (Object.keys(views).length || Object.keys(titles).length)
    ? { ...report, clashes: report.clashes.map(shown) } : report),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [report, views, titles]);
  const shownClash = clash ? shown(clash) : clash;
  // Until a report or the models are open, the page is the landing: no panels, just what ORCA is and the demo.
  const landing = !stats && !report && !blank;
  // A blank project before anything opens: the drop zone has the whole stage (no sheet on a phone).
  const starting = blank && !stats && !report;
  const startLabel = picked.some((f) => /northbank/i.test(f)) ? "Open the Northbank demo" : "Open the models";
  const planning = !!planRun && planRun.phase !== "done";
  // Phones and tablets: the sheet (or drawer) follows what happens, so the panel people need is the one showing. The
  // list when a report or the models open, the clash once one is picked, out of the way while ORCA drives the model,
  // back up with the result. Moving the sheet by hand always wins until the next thing happens.
  const followed = useRef<{ report: string | null; models: boolean; clash: string | null; working: boolean }>({ report: null, models: false, clash: null, working: false });
  const fixing = proposing || planning || contextWorking;
  useEffect(() => {
    const f = followed.current, seen: Happening[] = [];
    if (report && report.id !== f.report) seen.push("report");
    else if (stats && !f.models && !report) seen.push("models");
    if (clash && clash.id !== f.clash) seen.push("select");
    if (fixing && !f.working) seen.push("work");
    if (!fixing && f.working) seen.push("result");
    followed.current = { report: report?.id ?? null, models: !!stats, clash: clash?.id ?? null, working: fixing };
    if (!compact) return;
    let list: boolean | null = null, next = snap;
    for (const what of seen) {
      const r = follow(what, next);
      if (r.list != null) list = r.list;
      if (r.snap) next = r.snap;
    }
    if (list != null) setListOpen(list);
    if (next !== snap) setSnap(next);
    // With a result, the options come into view in the pane (only the pane scrolls, never the page).
    if (seen.includes("result")) requestAnimationFrame(() => {
      const pane = document.querySelector<HTMLElement>(".pane.right"), el = pane?.querySelector<HTMLElement>(".card, .nofix, .recommended");
      if (!pane || !el) return;
      const top = el.getBoundingClientRect().top - pane.getBoundingClientRect().top;
      if (top < 0 || top > pane.clientHeight - 80) pane.scrollTo({ top: pane.scrollTop + top - 12, behavior: "smooth" });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [compact, report?.id, stats, clash?.id, fixing]);
  // Read the patterns as soon as they are found, once per report and models, unless a proposal or plan is running then
  // (it is tried again when that ends). A failure leaves the Explain button for a manual try.
  useEffect(() => {
    const key = report && sceneId ? `${report.id}:${sceneId}` : null;
    if (!key || !patterns?.length || verdicts || explaining || explained.current === key) return;
    if (proposing || planning || replaying || busy) return;
    explained.current = key;
    void explainPatterns(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [report, sceneId, patterns, verdicts, explaining, proposing, planning, replaying, busy]);
  // Thumbnails wait while the viewer is busy with something the user is watching (a proposal, a plan, a reload).
  thumbPaused.current = proposing || planning || replaying || !!busy || !!detecting;
  useEffect(() => { setThumbs({}); thumbQueue.current = []; }, [report?.id]);
  useEffect(() => { if (!thumbPaused.current && thumbQueue.current.length) pumpThumbs(); });  // eslint-disable-line react-hooks/exhaustive-deps
  const thumbSource = useRef({ report, matches });
  thumbSource.current = { report, matches };
  function needThumb(c: ReportClash) {
    if (!report || c.id in thumbs || thumbQueue.current.some((q) => q.clash.id === c.id)) return;
    thumbQueue.current.push({ report: report.id, clash: c });
    pumpThumbs();
  }
  const thumbTimer = useRef<number | null>(null);
  /** Draw one queued thumbnail every 60 ms or so, newest request first (the rows on screen now), so scrolling and the
   * viewer's own frames stay smooth. */
  function pumpThumbs() {
    if (thumbTimer.current != null) return;
    thumbTimer.current = window.setTimeout(() => {
      thumbTimer.current = null;
      if (thumbPaused.current || !viewer.current) return;
      const next = thumbQueue.current.pop();
      if (!next) return;
      const { report: r, matches: ms } = thumbSource.current;
      if (next.report === r?.id) {
        const m = ms?.[next.clash.id];
        let url = "";
        try { url = (m?.a && m.b && viewer.current.thumbClash(m.a, m.b)) || ""; } catch { /* drawn as an empty box */ }
        setThumbs((t) => ({ ...t, [next.clash.id]: url }));
      }
      if (thumbQueue.current.length) pumpThumbs();
    }, 60);
  }
  const fixedCount = Object.keys(fixes).length;
  const tourDuct = clashOfPair(TOUR.duct), tourJoint = clashOfPair(TOUR.joint);
  const cellOpen = stepFiles.some((f) => /palletising-cell/i.test(f));
  const tourLadder = cellOpen ? clashOfNames(CELL.ladder, CELL.post)[0] : undefined;
  const tourPipes = cellOpen ? clashOfNames(CELL.pipe, CELL.rails) : [];
  const tourState: TourState = {
    busy: !!busy, reportOpen: !!report, modelsOpen: !!stats,
    triageStarted: !!triageRun, triageDone: !!triageRun?.done, triageCount: Object.keys(triage).length,
    triageTotal: report?.clashes.length ?? 0, realCount: Object.values(shownTriage).filter((v) => v.verdict === "real_clash").length,
    filter: triageFilter, clashId: clash?.id ?? null, tab, fixHidden: hideFix,
    triageOpen: triageRun?.model ? !!triageRun.open_weights : !!triageModel?.open_weights,
    proposing, proposingFor: progress && proposing ? (now - progress.started) / 1000 : 0,
    options: proposal?.options.length ?? 0, proposalDone: progress?.phase === "done", error, replaying,
    compare, fixed: Object.keys(fixes),
    planRunning: planning, planFor: planRun ? (now - planRun.started) / 1000 : 0, planReady: !!plan, planError,
    patternsRead: !!verdicts, reviewedCount: Object.keys(reviewed).length, signoffs: tourDuct ? signoffs[tourDuct.id]?.length ?? 0 : 0,
    docOpen, docReady,
    reqOpen, requirements: reqLabel, reqRules: reqSaved?.enabled ? reqSaved.doc.by_design.length : 0,
    duct: tourDuct ? { id: tourDuct.id, number: tourDuct.number } : null,
    cellOpen, ladder: tourLadder ? { id: tourLadder.id, number: tourLadder.number } : null,
    pipes: tourPipes.map((c) => ({ id: c.id, number: c.number })),
    joint: tourJoint ? { id: tourJoint.id, number: tourJoint.number } : null,
  };
  const tourActions: TourActions = {
    filterReal: () => setTriageFilter("real_clash"), clearFilter: () => setTriageFilter(null),
    selectClash: (which) => { const c = { duct: tourDuct, joint: tourJoint, ladder: tourLadder }[which]; if (c) { setTab("clash"); selectClash(c); } },
    openCell: () => { if (cellSample) void openDemo([cellSample]); },
    fixPipe: () => { if (tourPipes.length) { setTab("plan"); void runPlan({ clash_ids: tourPipes.map((c) => c.id) }); } },
    compare: setCompare,
    overview: () => { setViewPlan(false); viewer.current?.preview([]); viewer.current?.fitAll(); },
    reveal: (sel, el) => {
      const view = el?.closest("[data-left-view]")?.getAttribute("data-left-view");
      if (view === "clashes" || view === "insights") setLeftView(view);
      if (!compact) return;
      if (!el) { if (/data-tour=["']?(report|export|requirements)\b/.test(sel) && layout === "phone") setMenuOpen(true); return; }
      if (el.closest(".pane.left")) { setListOpen(true); if (snap === "peek") setSnap("half"); }
      else if (el.closest(".pane.right")) {
        setListOpen(false);
        if (el.closest(".chat-slot")) setTab("chat");
        if (layout === "phone" && snap === "peek") setSnap("half");
      }
    },
    closeReport: () => setDocOpen(false),
    replay: (what) => { if (what === "plan") void replayPlan(); else if (what === "pipe") void replayPlan("pipe"); else void replayPropose(what); },
    ask: (send) => { setTab("chat"); setChatAsk((q) => ({ text: TOUR_QUESTION, send, n: (q?.n ?? 0) + 1 })); },
    signoff: () => {
      let name = "Guest reviewer";
      try { name = localStorage.getItem("sightline.reviewer") || name; } catch { /* private window */ }
      if (tourDuct) addSignoff(tourDuct.id, { team: "MEP", name, decision: "approve", note: "Reviewed in the guided tour", at: new Date().toISOString() });
    },
  };

  const compareBar = (option || (plan && viewPlan && planOptions.length > 0) || (activeContext && contextProposal)) && (
    <div className="compare" onClick={(e) => e.stopPropagation()} onPointerDown={(e) => e.stopPropagation()}>
      <div className="seg" role="group" aria-label="Compare before and after">
        {(["before", "after", "both"] as const).map((m) => (
          <button key={m} className={compare === m ? "on" : ""} onClick={() => setCompare(m)} aria-pressed={compare === m}>
            {m === "before" ? "Before" : m === "after" ? "After" : "Both"}</button>))}
      </div>
      {option ? (
        <dl className="diff">
          <dt>Before</dt><dd>{measure && measure !== "busy" && measure.distance_m != null ? `overlap ${mm(measure.distance_m)}` : "clashing"}</dd>
          <dt>After</dt><dd className="ok">{option.kind === "trim" ? "clear: the two now butt at the joint"
            : `clear${option.min_clearance_m != null ? `, nearest ${mm(option.min_clearance_m)}` : ""}`}</dd>
          <dt>Change</dt><dd>{changeText(option)}</dd>
        </dl>
      ) : activeContext && contextProposal ? (
        <dl className="diff"><dt>Wider fix</dt><dd>{contextProposal.edits.length} coordinated edits shown together</dd>
          <dt>Checks</dt><dd className="ok">Geometry and model checks passed; designer review conditions apply</dd></dl>
      ) : plan && (
        <dl className="diff">
          <dt>Plan</dt><dd>{planOptions.length} fix{planOptions.length === 1 ? "" : "es"} shown together</dd>
          <dt>Check</dt><dd className={plan.check.passed ? "ok" : "bad"}>{plan.check.passed ? "all clear, checked as one" : "not all clear"}</dd>
        </dl>
      )}
      {compare === "both" && <p className="hint"><i className="sw ghost" />orange ghost: as it is now</p>}
    </div>
  );

  // What is still open in Insights, for its tab: root causes not done, patterns with an open clash.
  const insightsOpen = rootCauses && patterns
    ? rootCauses.filter((r) => !r.done).length + patterns.filter((p) => p.clash_ids.some((id) => !resolvedSet.has(id))).length : null;
  // The right pane's tabs, also the phone sheet's Fix / Plan / Chat.
  const showClashTab = () => { setListOpen(false); setTab("clash"); setViewPlan(false); setViewContext(false); };
  const showPlanTab = () => {
    setListOpen(false); clearManual();
    setTab("plan"); setViewContext(planKind === "context" && !!context); setViewPlan(planKind === "batch" && !!(plan || planRun));
  };
  const showChatTab = () => { setListOpen(false); setTab("chat"); };
  const raise = () => { if (snap === "peek") setSnap("half"); };
  // The next clash still open after the selected one (the report's order), for "Next clash" once one is done.
  const nextClash = (() => {
    if (!report || !clash || !matches) return null;
    const list = shownReport?.clashes ?? report.clashes, at = list.findIndex((c) => c.id === clash.id);
    const open = (c: ReportClash) => c.id !== clash.id && !fixes[c.id] && !reviewed[c.id] && !!matches[c.id]?.a && !!matches[c.id]?.b;
    return list.slice(at + 1).find(open) ?? list.slice(0, Math.max(0, at)).find(open) ?? null;
  })();
  // The phone sheet's peek line: what is happening now, and the one next step, so the sheet is useful folded down.
  const peekLine: { text: React.ReactNode; live?: boolean; action?: { label: string; run: () => void; disabled?: boolean; tour?: string } } =
    busy ? { text: busy, live: true }
      : detecting ? { text: detecting.phase, live: true }
      : proposing ? { text: statusLine(progress, now, proposal?.attempts ?? []), live: true }
      : planning ? { text: "ORCA is building a plan…", live: true }
      : contextWorking ? { text: "Exploring a wider fix…", live: true }
      : viewPlan && plan ? { text: planOptions.length ? `Plan: ${planOptions.length} fix${planOptions.length === 1 ? "" : "es"} ready to review` : "Plan: nothing to accept yet",
        action: { label: "Review", run: () => { showPlanTab(); raise(); } } }
      : option && clash ? { text: <><b>{chosen! + 1}</b> · {option.title}</>,
        action: { label: option.cleanup ? "Accept cleanup" : "Accept", run: () => void accept(option), disabled: !!busy, tour: "accept" } }
      : proposal && progress?.phase === "done" && !proposal.options.length ? { text: "No verified fix: see why",
        action: canEscalate && !proposal.escalated && !proposal.recommendation
          ? { label: `Ask ${wonder.replace(/^Muse /, "")}`, run: () => { showClashTab(); void escalate(); }, disabled: !!busy }
          : { label: "See why", run: () => { showClashTab(); raise(); } } }
      : clash && shownClash && (fixes[clash.id] || reviewed[clash.id]) ? {
        text: <><CircleCheck size={15} aria-hidden className="ok" /> <b>#{shownClash.number}</b> {fixes[clash.id] ? "fixed" : "reviewed"}{nextClash ? "" : ": nothing left open"}</>,
        action: nextClash ? { label: "Next clash", run: () => { setTab("clash"); selectClash(nextClash); } } : undefined }
      : clash && shownClash ? { text: <><b>#{shownClash.number}</b> {shownClash.title ?? shownClash.name}</>,
        action: hideFix ? { label: "Not a clash", run: () => { showClashTab(); raise(); } }
          : { label: "Propose fixes", run: () => { showClashTab(); void propose(); }, disabled: !a || !b || !sceneId || !!busy, tour: "propose" } }
      : a && b ? { text: "A and B picked", action: { label: "Propose fixes", run: () => { showClashTab(); void propose(); }, disabled: !sceneId || !!busy } }
      : a ? { text: "A set: now tap element B, then Set as B" }
      : report ? { text: `${report.clashes.length} clash${report.clashes.length === 1 ? "" : "es"} · pick one to fix it`,
        action: listOpen ? undefined : { label: "Clashes", run: () => { setListOpen(true); raise(); } } }
      : sceneId ? { text: "Models open", action: { label: "Check for clashes", run: () => void runDetect(null), disabled: !!busy } }
      : { text: "Open models from the menu" };
  // iOS cannot pick a folder: the export-folder upload is left out there (XML files still upload).
  const noFolders = typeof navigator !== "undefined" && (/iPad|iPhone|iPod/.test(navigator.userAgent)
    || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1));
  // The header's two menus, as popovers on a desktop and as sections of the menu on phones and tablets.
  const modelsMenu = (close: () => void) => (<>
    <p className="pop-title">Models to open together</p>
    {samples.map((f) => (
      <label key={f} className="pop-item check">
        <input type="checkbox" value={f} checked={picked.includes(f)}
          onChange={(e) => setPicked(e.target.checked ? [...picked, f] : picked.filter((x) => x !== f))} /> {f}
      </label>
    ))}
    {!samples.length && <p className="hint">No models in samples/</p>}
    <button id="open" className="btn primary small" disabled={!picked.length || !!busy} onClick={() => { close(); open(); }}>
      <FolderOpen size={14} aria-hidden /> Open {picked.length} model{picked.length === 1 ? "" : "s"}</button>
    <p className="pop-title">Or your own</p>
    <button className="pop-item" disabled={!!busy} onClick={() => { close(); modelInput.current?.click(); }}>
      <Upload size={14} aria-hidden /> Upload models (IFC or STEP)…</button>
    <p className="hint">{uploadMax ? `Up to ${uploadMax} MB together.` : "Several files open together."} A STEP machine is converted to IFC to check; Export gives your STEP back
      with the fixes.</p>
  </>);
  const coordinateMenu = (close: () => void) => (<>
    <p className="pop-title">Coordinate the open models</p>
    <button className="pop-item" disabled={!sceneId || !!busy || !!detecting} onClick={() => { close(); void runDetect(null); }}>
      <Radar size={14} aria-hidden /> Check the open models</button>
    {!sceneId && <p className="hint">Open the models first.</p>}
    <p className="pop-title">Or import a Navisworks clash report (XML)</p>
    {reportSamples.map((s) => (
      <button key={s} className="pop-item" disabled={!!busy} onClick={() => { close(); loadReport(() => api.openReport(s), s); }}>
        <FileSpreadsheet size={14} aria-hidden /> {s}</button>
    ))}
    {!noFolders && <button className="pop-item" disabled={!!busy} onClick={() => { close(); folderInput.current?.click(); }}><Upload size={14} aria-hidden /> Upload an export folder…</button>}
    <button className="pop-item" disabled={!!busy} onClick={() => { close(); filesInput.current?.click(); }}><Upload size={14} aria-hidden /> Upload XML files…</button>
    {!noFolders && <p className="hint">Upload the whole export folder to get each clash's images.</p>}
  </>);

  return (
    <div className={`app ${resizing ? "resizing" : ""} ${landing ? "landing" : ""} ${starting ? "starting" : ""} ${compact ? `${layout} snap-${snap}` : ""} ${compact && listOpen ? "list-open" : ""}`}
      style={{ "--left-w": `${widths.left}px`, "--right-w": `${widths.right}px` } as React.CSSProperties}>
      {compact ? (
      <header className="bar">
        <span className="brand"><span className="logo" aria-hidden>◎</span><b>ORCA</b></span>
        <span className="spacer" />
        {layout === "tablet" && !landing && (report || sceneId) && <button className={`btn ghost ${listOpen ? "on" : ""}`} data-tour="drawer"
          aria-expanded={listOpen} onClick={() => setListOpen(!listOpen)}>
          <List size={16} aria-hidden /> Clashes{report ? <span className="badge-n">{report.clashes.length}</span> : null}</button>}
        {landing && layout === "tablet" && <button className="btn primary" disabled={!picked.length || !!busy} onClick={startGolden}><Sparkles size={15} aria-hidden /> Watch ORCA fix a clash</button>}
        {fixedCount > 0 && <span className="chip ok">{fixedCount} fixed</span>}
        {agentLink && <button className="btn agent-pill" onClick={() => setAgentOpen(true)} aria-label={`Agent connected · ${timeLeft(agentLink, now)} left`}><Bot size={16} aria-hidden /></button>}
        <span className="owner-pop"><OwnerSettingsMenu onChange={setOwnerSettingsState} onEveryone={() => setModelsAsked((n) => n + 1)} /></span>
        {layout === "tablet" && report && <button className="btn" data-tour="report" onClick={() => { setDocOpen(true); setDocReady(false); }}>
          <FileText size={15} aria-hidden /> Report</button>}
        {layout === "tablet" && sceneId && <a className="btn primary" data-tour="export" href={api.exportUrl(sceneId)}>
          <Download size={15} aria-hidden /> Export</a>}
        <button className="btn ghost menu-btn" data-tour="menu" aria-expanded={menuOpen} onClick={() => setMenuOpen(true)}>
          <Menu size={18} aria-hidden /><span>Menu</span></button>
      </header>
      ) : (
      <header className="bar">
        <div className="bar-side">
        <Popover icon={Boxes} label="Models" text="Models" tip="bottom">
          {modelsMenu}
        </Popover>
        {stats && <span className="stat mono" title={`${modelNames.join(", ")}: ${stats.elements} elements, ${Math.round(stats.triangles / 1000)}k triangles, parsed in ${(stats.parseMs / 1000).toFixed(1)} s`}>
          {stats.elements.toLocaleString()} elements</span>}
        <Popover icon={Radar} label="Coordinate" text="Coordinate" tip="bottom">
          {coordinateMenu}
        </Popover>
        {!landing && sceneId && <button className={`btn ${reqLabel ? "req-pill" : "ghost"}`} data-tour="requirements" onClick={() => setReqOpen(true)}
          aria-label="Coordination requirements" data-tip-side="bottom"
          data-tip={reqLabel ? `Checking, triage and fixes follow "${reqSaved!.doc.name}" (${reqLabel})` : "Optional: set the design level, how strict to be and who moves. Off: ORCA's defaults"}>
          <ClipboardCheck size={15} aria-hidden />{reqLabel ? <span className="req-pill-label"> {reqLabel}</span> : <span className="lbl"> Requirements</span>}</button>}
        {!landing && <button className="btn ghost" onClick={() => setAbout(true)} aria-label="How it works" title="How it works"><Info size={15} aria-hidden /><span className="lbl"> How it works</span></button>}
        {!landing && !touring && (stats || report) && <button className="btn ghost" onClick={() => startTour(cellOpen ? "cell" : "northbank")} aria-label="Tour" title="Take the guided tour"><Compass size={15} aria-hidden /><span className="lbl"> Tour</span></button>}
        </div>
        <span className="brand"><span className="logo" aria-hidden>◎</span><b>ORCA</b></span>
        <div className="bar-side end">
        {landing && <button className="btn primary" disabled={!picked.length || !!busy} onClick={startGolden}><Sparkles size={15} aria-hidden /> Watch ORCA fix a clash</button>}
        {fixedCount > 0 && <span className="chip ok">{fixedCount} fixed</span>}
        {!landing && <button className={`btn ${agentLink ? "agent-pill" : "ghost"}`} onClick={() => setAgentOpen(true)}
          aria-label={agentLink ? "Agent connected" : "Connect an agent"} data-tip-side="bottom"
          data-tip={agentLink ? `An agent works on this session over MCP · the link has ${timeLeft(agentLink, now)} left` : "Let an AI agent (Muse Code, Claude) work on this session over MCP"}>
          {agentLink ? <><Bot size={15} aria-hidden /><span className="lbl"> {agentLink.last_call ? `Agent · ${agentLink.last_call.tool}` : "Agent · waiting"}</span></>
            : <><Plug size={15} aria-hidden /><span className="lbl"> Connect an agent</span></>}</button>}
        {ownerSettings && <span className="chip accent" data-tip="Owner settings apply to your requests only" data-tip-side="bottom">
          owner · effort {ownerSettings.effort ?? "default"}{ownerSettings.no_caps !== false ? " · no caps" : ""}
          {ownerSettings.open_weights != null ? ` · open weights ${ownerSettings.open_weights ? "on" : "off"}` : ""}
          {ownerSettings.escalation ? ` · second try ${ownerSettings.escalation}` : ""}</span>}
        <span className="owner-pop"><OwnerSettingsMenu onChange={setOwnerSettingsState} onEveryone={() => setModelsAsked((n) => n + 1)} /></span>
        {report && <button className="btn" data-tour="report" onClick={() => { setDocOpen(true); setDocReady(false); }} data-tip="A PDF for the design teams, with BCF issues" data-tip-side="bottom">
          <FileText size={15} aria-hidden /> Report</button>}
        {sceneId && <a className="btn primary" data-tour="export" href={api.exportUrl(sceneId)} data-tip-side="bottom"
          data-tip={stepFiles.length ? "Download the changed models: the STEP with its fixes, and the IFC" : "Download the changed IFC files"}>
          <Download size={15} aria-hidden /> {stepFiles.length ? "Export STEP + IFC" : "Export IFC"}</a>}
        </div>
      </header>
      )}
      <input ref={modelInput} type="file" hidden multiple accept=".ifc,.step,.stp" disabled={!!busy}
        onChange={(e) => { const files = [...(e.target.files ?? [])]; e.target.value = ""; if (files.length) void openDemo(files); }} />
      <input ref={folderInput} type="file" hidden multiple disabled={!!busy} {...{ webkitdirectory: "" }} onChange={(e) => { upload(e.target.files); e.target.value = ""; }} />
      <input ref={filesInput} type="file" hidden multiple disabled={!!busy} accept=".xml,.png,.jpg,.jpeg" onChange={(e) => { upload(e.target.files); e.target.value = ""; }} />

      <aside className="pane left">
        {report
          ? <ReportList report={shownReport ?? report} naming={naming} matches={matches}
              thumbs={report.origin === "sightline" && matches ? thumbs : undefined} onThumb={needThumb}
              focus={listFocus} onClearFocus={() => setListFocus(null)} selected={viewPlan || activeContext ? null : clash?.id ?? null} onSelect={(c) => { if (compact && tab === "chat") setTab("clash"); selectClash(c); }} onImage={(c, index) => setLightbox({ clash: c, index })} fixes={fixes}
              reviewed={reviewed} checked={checked} busy={planning || proposing} triage={shownTriage} triageFilter={triageFilter}
              onCheck={(ids, on) => setChecked((s) => { const n = new Set(s); for (const id of ids) { if (on) n.add(id); else n.delete(id); } return n; })}
              onFixChecked={() => runPlan({ clash_ids: [...checked] })}
              view={leftView} onView={setLeftView} insightsCount={insightsOpen}
              status={detecting && <p className="live-line"><i className="spinner" aria-hidden /> {detecting.phase}</p>}
              triageCard={<TriageCard run={triageRun} active={triageModel} forceCompact={!!listFocus} results={shownTriage} now={now} filter={triageFilter} onFilter={setTriageFilter}
                live={Object.entries(triageLive).map(([id, text]) => ({ id, text, name: (() => { const c = shownReport?.clashes.find((x) => x.id === id); return c ? clashLabel(c) : id; })() }))}
                onOpen={(id) => { const c = report.clashes.find((x) => x.id === id); if (c) selectClash(c); }}
                total={report.clashes.length} resolved={(id) => !!fixes[id] || !!reviewed[id]} onRun={runTriage}
                onSetAside={(ids) => review(ids, "by_design", "Triage: by design or not physical")}
                onFlag={(ids) => review(ids, "author", "Triage: modelling error")}
                requirements={reqLabel} stale={triageStale} onRequirements={() => setReqOpen(true)} />}
              insights={<>{(detecting || (report.origin === "sightline" && detection)) && <DetectSummary
                detection={detection ?? { coverage: [], diff: { new: [], resolved: [], no_longer_checked: [], first: true }, elements: 0, seconds: 0 }}
                progress={detecting} disabled={!!busy || !sceneId} onAgain={() => void runDetect(lastTests.current)}
                requirementsId={reqSaved?.enabled ? reqId : null} onRequirements={() => setReqOpen(true)} />}
                <Insights rootCauses={rootCauses} patterns={patterns} verdicts={verdicts} explaining={explaining}
                resolved={resolvedSet} focus={listFocus?.label ?? null} onFocus={(f) => { setListFocus(f); if (f) setLeftView("clashes"); }}
                busy={planning || proposing} onFixRoot={(hub) => runPlan({ hub })} onExplain={() => void explainPatterns()}
                onSelect={(ids) => { setChecked((s) => new Set([...s, ...ids.filter((id) => !fixes[id] && !reviewed[id])])); setLeftView("clashes"); }}
                onReview={review} onFixAll={(ids) => runPlan({ clash_ids: ids })}
                onAddRule={sceneId ? (p, v) => void addRule(p, v) : undefined} hasRule={(p) => !!reqSaved?.enabled && hasByDesign(reqSaved.doc, p)} /></>} />
          : sceneId
            ? <div className="detect-slot"><DetectSetupCard setup={detectSetup} progress={detecting} disabled={!!busy}
                onRun={(tests) => void runDetect(tests)} requirements={reqLabel} onRequirements={() => setReqOpen(true)} />
                <p className="hint small">{coarse ? "Or tap element A in the model, then element B, and set each from its card."
                  : "Or double-click element A, then element B, in the model."}</p></div>
            : <div className="empty-left">
              <Radar size={28} aria-hidden />
              <h2>Nothing to coordinate yet</h2>
              <p className="hint">Open the models: ORCA checks them for clashes.</p>
            </div>}
      </aside>

      <main className={`stage ${tool.measure ? "measuring" : ""}`} ref={host} onClick={onClick}
        onPointerDown={pressStart} onPointerMove={pressMove} onPointerUp={pressEnd} onPointerCancel={pressEnd}
        onContextMenu={(e) => { if (coarse) e.preventDefault(); }}>
        {stats && <ViewerToolbar compact={layout === "phone"} state={tool} models={modelNames} hasFocus={!!(a || b)}
          onMode={(mode) => setTool((t) => ({ ...t, mode }))} onToggle={toggle} onView={(p) => viewer.current?.view(p)}
          onFit={() => viewer.current?.fitAll()} onFocus={focusNow} onModel={setModelVisible} onShot={screenshot} />}
        {!stats && !report && blank && (
          <ProjectStart busy={!!busy} maxMb={uploadMax} onModels={(files) => void openDemo(files)} onReport={(files) => upload(files)}
            onReportFolder={() => folderInput.current?.click()} onBack={() => setBlank(false)} />
        )}
        {!stats && !busy && !blank && (
          <About triageOpen={!!triageModel?.open_weights} start={{
            label: startLabel,
            disabled: !picked.length,
            onStart: () => void openDemo(),
            onCell: cellSample ? () => void openDemo([cellSample]) : undefined,
            onGolden: startGolden,
            onTour: () => startTour("northbank"),
            onBlank: () => { setBlank(true); setError(null); },
            onCellTour: cellSample ? () => startTour("cell") : undefined,
            resume: resumable ? { files: resumable.info.files, clashes: resumable.clashes, fixed: Object.keys(resumable.saved.fixes ?? {}).length,
              agent: !!resumable.saved.link, agentLeft: resumable.saved.link ? timeLeft(resumable.saved.link, now) : null, savedAt: resumable.saved.saved_at, onResume: () => void resumeSession(), onFresh: startFresh } : undefined,
            details: <>
              Loads {picked.length} building model{picked.length === 1 ? "" : "s"} ({picked.map(shortName).join(", ")}) and
              checks them, in about 25 seconds. Other models: {compact ? <><b>Menu</b>, then <b>Models</b></> : <><b>Models</b>, in the header</>}.
            </>,
          }} />
        )}
        {tool.measure && <div className="overlay hint-bar" onClick={(e) => e.stopPropagation()}>
          {measured != null ? `Measured ${Math.round(measured * 1000)} mm. ${coarse ? "Tap" : "Click"} again to start a new measurement.` : measurePts.length ? `${coarse ? "Tap" : "Click"} the second point.` : `${coarse ? "Tap" : "Click"} the first point to measure from.`}</div>}
        {selected && !tool.measure && (
          <div className="props" onClick={(e) => e.stopPropagation()} onPointerDown={(e) => e.stopPropagation()}>
            <div className="row"><b>{String(selected.info?.ifc_class ?? "Element").replace(/^Ifc/, "")}</b>
              <button className="ibtn" onClick={() => setSelected(null)} aria-label="Close" data-tip="Close" data-tip-side="left"><X size={15} aria-hidden /></button></div>
            <div>{String(selected.info?.name ?? "")}</div>
            <dl className="kv">
              <dt>GlobalId</dt><dd className="mono">{selected.globalId}</dd>
              {selected.info?.tag ? <><dt>Tag</dt><dd>{String(selected.info.tag)}</dd></> : null}
              {selected.info?.storey ? <><dt>Level</dt><dd>{String(selected.info.storey)}</dd></> : null}
              {selected.info?.source ? <><dt>File</dt><dd>{String(selected.info.source)}</dd></> : null}
              {Array.isArray(selected.info?.connected) ? <><dt>Connected</dt><dd>{(selected.info.connected as unknown[]).length} elements</dd></> : null}
            </dl>
            <div className="row">
              <button className="btn small" onClick={() => pickSide(selected.globalId, "a")}><i className="sw red" />Set as A</button>
              <button className="btn small" disabled={!a || a === selected.globalId} onClick={() => pickSide(selected.globalId, "b")}><i className="sw green" />Set as B</button>
            </div>
          </div>
        )}
        {busy && <div className="overlay live"><i className="spinner" aria-hidden />{busy}</div>}
        {proposing && <div className="overlay live"><i className="spinner" aria-hidden />{statusLine(progress, now, proposal?.attempts ?? [])}</div>}
        <div className={`pilot-glow ${pilotStatus?.driving ? "on" : ""}`} aria-hidden />
        {pilotStatus && (
          <div className={`pilot ${pilotStatus.state}`} role="status" onClick={(e) => e.stopPropagation()} onPointerDown={(e) => e.stopPropagation()}>
            {pilotStatus.driving ? <Navigation size={14} aria-hidden /> : <Hand size={14} aria-hidden />}
            <span>{pilotStatus.text}</span>
            {pilotStatus.driving
              ? <button className="btn small" onClick={() => pilot.current?.takeOver()}>Take the view</button>
              : <button className="btn small" onClick={() => pilot.current?.resume()}>Let ORCA drive</button>}
          </div>
        )}
        {compareBar}
        {error && <div className="overlay error" role="alert" onClick={() => setError(null)}>{error}<X size={14} aria-hidden /></div>}
        {toast && <div className="toast" role="status">{toast}</div>}
      </main>

      <aside className={`pane right ${tab === "chat" ? "chatting" : ""}`}>
        <div className="tabs" role="tablist">
          <button role="tab" aria-selected={tab === "clash"} className={tab === "clash" ? "on" : ""} onClick={showClashTab}>
            <LocateFixed size={14} aria-hidden /> Clash{proposal?.options.length ? <span className="badge-n">{proposal.options.length}</span> : null}</button>
          <button role="tab" data-tour="tab-plan" aria-selected={tab === "plan"} className={tab === "plan" ? "on" : ""} onClick={showPlanTab}>
            <Network size={14} aria-hidden /> Plan{planning || contextWorking ? <i className="spinner" aria-hidden />
              : planKind === "context" && context?.result?.proposals.length ? <span className="badge-n">{context.result.proposals.length}</span>
              : planOptions.length ? <span className="badge-n">{planOptions.length}</span> : null}</button>
          <button role="tab" data-tour="tab-chat" aria-selected={tab === "chat"} className={tab === "chat" ? "on" : ""} onClick={showChatTab}>
            <MessageSquare size={14} aria-hidden /> Chat</button>
        </div>
        <div className="chat-slot" hidden={tab !== "chat"}>
          {context && <button className="context-chat-link btn" onClick={() => { clearManual(); setTab("plan"); setPlanKind("context"); setViewContext(true); setViewPlan(false); }}>
            <Network size={14} aria-hidden /> {contextWorking ? "Wider fix: inspecting and checking…" : context.accepted ? "Wider fix accepted" : `Review wider fix · ${context.result?.proposals.length ?? 0} alternatives`}</button>}
          <ChatPanel key={`${sceneId}:${chatReport}`} owner={chatOwner.current} ready={!!(sceneId || report) && !busy}
            onEvent={(e) => { if (sceneEpoch.current === renderedSceneEpoch && workspaceEpoch.current === renderedWorkspaceEpoch) onChatEvent(e); }} ask={chatAsk}
            context={() => ({ scene_id: sceneId, report_id: report?.id ?? null, clash_id: clash?.id ?? null, fixed: resolved })} />
        </div>
        {tab === "plan" && <>
          {context && (plan || planRun) && <div className="seg plan-switch" role="group" aria-label="Plan type">
            <button className={planKind === "context" ? "on" : ""} onClick={() => { clearManual(); setPlanKind("context"); setViewContext(true); setViewPlan(false); }}>Wider fix</button>
            <button className={planKind === "batch" ? "on" : ""} onClick={() => { clearManual(); setPlanKind("batch"); setViewContext(false); setViewPlan(true); }}>Clash plan</button>
          </div>}
          {planKind === "context" && context ? <ContextPlan run={context} names={contextNames} chosen={contextChosen} acknowledged={acknowledged} busy={!!busy} now={now}
            onChoose={(id) => { clearManual(); setContextChosen(id); setAcknowledged([]); setViewContext(true); setViewPlan(false); }}
            onAcknowledge={(id, checked) => setAcknowledged((ids) => checked ? [...new Set([...ids, id])] : ids.filter((x) => x !== id))}
            onAccept={acceptContext} onRegenerate={() => { if (context.objective) void exploreContext(context.objective); }}
            onDiscard={() => { directContext.current?.retire(); ++contextRequest.current; clearManual(); setContext(null); setContextChosen(null); setAcknowledged([]); setViewContext(false); setPlanKind("batch"); }} /> :
          <PlanPanel run={planRun} plan={plan} now={now} busy={!!busy} onAccept={acceptPlan} error={planError}
            onEscalate={canEscalate ? escalateItem : undefined} wonder={wonder} stale={planStale}
            built={(it) => it.option ? builtRuns[builtKey([it.element_a, it.element_b], it.option)] : undefined}
            onBuild={builtOn ? (it) => { if (it.option && canBuild(it.option)) void drawBuilt(builtKey([it.element_a, it.element_b], it.option),
              builtPasses(builtFix(it.option, false), [it.element_a, it.element_b]), it.option.kind); } : undefined}
            onDiscard={() => { setPlan(null); setPlanRun(null); }} onFocus={focusItem}
            onAsDesigned={(ids, note) => { review(ids, "by_design", note); setPlan(null); setPlanRun(null); setViewPlan(false); setTab("clash"); }} />}
        </>}
        <div className="tab-body" hidden={tab !== "clash"}>
          {clash && report
            ? (<><ClashPanel reportId={report.id} clash={shownClash ?? clash} match={matches?.[clash.id]} measure={measure} onImage={(index) => setLightbox({ clash: shownClash ?? clash, index })} fix={fixes[clash.id]} triage={shownTriage[clash.id]}
              origin={report.origin} capturing={capturing === clash.id} />
              {evidence[clash.id]?.status === "recommended" && evidence[clash.id].kind === "penetration" &&
                <div className="recommended">
                  <h3>Opening requested</h3>
                  <p><b>{evidence[clash.id].title}</b> · <span className="mono">{evidence[clash.id].edit}</span></p>
                  <p className="hint">The provision for void is in the model; the opening is not cut yet: {evidence[clash.id].blocked_by}.
                    This clash stays open until it is.</p>
                </div>}
              {builtOn && evidence[clash.id]?.status === "accepted" && builtFixes.current[clash.id] && (() => {
                const f = builtFixes.current[clash.id], run = builtRuns[f.key];
                return <div className="built-kept">
                  <h3>As it could look built</h3>
                  {run ? <BuiltView run={run} onRetry={() => redrawKept(clash.id)} />
                    : <button className="btn small" disabled={!!busy} onClick={() => redrawKept(clash.id)}
                      data-tip="Muse Image draws ORCA's view of the kept fix as a presentation render, checked against the model. About a minute.">
                      <Building2 size={13} aria-hidden /> Show it built</button>}
                </div>;
              })()}
              {(evidence[clash.id] || triage[clash.id]?.verdict === "real_clash" || (signoffs[clash.id]?.length ?? 0) > 0) &&
                <ReviewBlock clash={clash} teams={modelTeams} signoffs={signoffs[clash.id] ?? []}
                  onAdd={(so) => addSignoff(clash.id, so)} onRemove={(i) => removeSignoff(clash.id, i)} />}
              </>)
            : (a || b) ? (
              <dl className="kv pair">
                <dt><i className="sw red" />A</dt><dd className="mono">{a ?? "—"}</dd>
                <dt><i className="sw green" />B</dt><dd className="mono">{b ?? "—"}</dd>
              </dl>
            ) : <p className="hint">{coarse ? "Pick a clash from the list, or tap an element in the model and set it as A, then B."
              : "Pick a clash from the list, or double-click two elements in the model."}</p>}
          {hideFix && clash && (
            <div className="noclash-card" role="status">
              <b><CircleCheck size={15} aria-hidden /> {notAClash!.title}</b>
              <p>{notAClash!.why}</p>
              {reviewed[clash.id]
                ? <p className="hint">Marked {reviewed[clash.id].kind === "by_design" ? "as by design" : "for the model's author"}.</p>
                : <button className="btn primary" onClick={() => review([clash.id], "by_design", notAClash!.why)}>
                  <CircleCheck size={15} aria-hidden /> Mark as not a clash</button>}
              <button className="link" data-tour="fix-anyway" onClick={() => setFixAnyway(true)}>Propose a fix anyway</button>
            </div>
          )}
          <div className="actions">
            {!hideFix && <button className="btn primary big" data-tour="propose" disabled={!a || !b || !sceneId || !!busy || proposing} onClick={propose}>
              {proposing ? <><i className="spinner" aria-hidden /> Working…</> : <><Sparkles size={16} aria-hidden /> Propose fixes</>}</button>}
            <button className="btn" disabled={!a || !b || a === b || !sceneId || !!busy || contextWorking || proposing || planning}
              onClick={() => void exploreContext()}><Network size={15} aria-hidden /> Explore wider fix</button>
            <button className="btn" disabled={!a && !b} onClick={focusNow}><LocateFixed size={15} aria-hidden /> Go to the clash</button>
          </div>

          {(proposal?.understanding || proposing) && <>
            <h2>Understanding</h2>
            {(proposal?.understanding || !thoughts.length) &&
              <p className="understanding">{proposal?.understanding || `${progress?.model ?? "Muse Spark"} is reading the clash…`}</p>}
          </>}
          <Thinking notes={thoughts} live={proposing} thinking={proposing && progress?.phase === "thinking"}
            model={progress?.model ?? proposal?.model ?? "Muse Spark"} />
          {proposal && !proposing && <h2>Verified options</h2>}
          {proposal && !proposing && proposal.recommendation && <Recommended rec={proposal.recommendation} advice={proposal.advice} requirements={proposal.requirements ?? null}
            onRequirements={() => setReqOpen(true)} />}
          {proposal && !proposing && !proposal.options.length && !proposal.recommendation && <NoFix proposal={proposal} onRetry={propose}
            onEscalate={canEscalate && !proposal.escalated ? () => void escalate() : undefined} wonder={wonder}
            onFlag={clash ? () => review([clash.id], "author", "No verified fix: needs the model's author") : undefined} />}
          {clash && proposal && !proposing && proposal.options.length > 0 && proposal.options.every((o) => o.cleanup) && (
            <div className="cleanup-note">
              <b>Model cleanup, not a coordination clash</b>
              <p>Both elements are in the same model, and they overlap where one frames into the other. That is often how
                they are built (a beam cast into its footing, a transom into its mullion). Tidy the joint if the model goes
                to fabrication or quantities; otherwise mark it as not a clash.</p>
              {proposal.advice && <p className="why">{proposal.model || "Muse Spark"}: {proposal.advice}</p>}
              {reviewed[clash.id]
                ? <span className="chip ok"><CircleCheck size={12} aria-hidden /> marked {reviewed[clash.id].kind === "by_design" ? "by design" : "for the author"}</span>
                : <button className="btn small" onClick={() => review([clash.id], "by_design", "A joint inside one model: built as modelled")}>
                  <CircleCheck size={13} aria-hidden /> Mark as not a clash</button>}
            </div>)}
          {proposal?.options.map((o, i) => (
            <div key={i} className={`card ${chosen === i ? "pick" : ""}`}>
              <button className="card-body" onClick={() => { clearManual(); setChosen(chosen === i ? null : i); }} aria-pressed={chosen === i}>
                <span className="row"><b>{i + 1} · {o.title}</b><span className="chips">
                  {o.cleanup && <span className="chip" title="Tidies a joint inside one model; optional">model cleanup</span>}
                  {o.review && <span className="chip warn" data-tip={reviewText(o.review)}>{o.review} review</span>}
                  {proposal!.escalated && <span className={`chip model ${o.model === wonder ? "wonder" : ""}`}
                    data-tip={o.model === wonder ? `Found on the second try, by ${wonder}` : "Found on the first try"}>{o.model || "Muse Spark"}</span>}
                  <span className="chip ok"><Check size={11} aria-hidden /> verified</span></span></span>
                <span className="row"><span>Edit</span><span className="mono">{editText(o)}</span></span>
                <span className="row"><span>Clearance</span><span className="mono">{clearanceText(o)}</span></span>
                {o.review && <span className="row"><span>Review</span><span>{reviewText(o.review)}</span></span>}
                {hostRows(o).map(([k, v]) => <span key={k} className="row"><span>{k}</span><span>{v}</span></span>)}
                <span className="row"><span>Also needs</span><span>{o.also_needs || "nothing"}</span></span>
                {o.meets?.length ? <span className="meets">{o.meets.map((m) => <span key={m}><Check size={11} aria-hidden /> {m}</span>)}</span> : null}
                <span className="why">{o.rationale}</span>
                <ProofStrip o={o} rank={i} options={proposal!.options} before={measure && measure !== "busy" ? measure.distance_m : null} need={proposal!.clearance_m} />
              </button>
              {chosen === i && <button className="btn primary" data-tour="accept" disabled={!!busy} onClick={() => accept(o)}><Check size={15} aria-hidden /> {o.cleanup ? "Accept this cleanup" : "Accept this fix"}</button>}
              {chosen === i && canBuild(o) && a && b && (() => {
                const run = builtRuns[builtKey([a, b], o)];
                return run ? <BuiltView run={run} onRetry={() => showBuilt(o)} />
                  : <button className="btn small" data-tour="show-built" disabled={!!busy} onClick={() => showBuilt(o)}
                    data-tip="Muse Image draws ORCA's view of this fix as a presentation render, checked against the model before you see it. About a minute.">
                    <Building2 size={13} aria-hidden /> Show it built</button>;
              })()}
              {chosen === i && o.kind === "penetration" && o.edit?.reading_source === "muse" && sceneId && (
                hasPenetration(reqSaved?.enabled ? reqSaved.doc : null, o.edit.host_group, o.edit.host_kind)
                  ? <span className="chip ok"><Check size={11} aria-hidden /> in the requirements</span>
                  : <button className="btn small" onClick={() => void addPenRule(o)}
                    data-tip="Make this reading a rule for the host's group in the coordination requirements"><ClipboardPlus size={13} aria-hidden /> Add to requirements</button>)}
            </div>
          ))}

          {proposal && !proposing && proposal.options.length > 0 && canEscalate && !proposal.escalated && !hideFix && (
            <button className="better-fix" data-tour="better-fix" disabled={!!busy} onClick={() => void escalate()}
              data-tip="It starts from everything this try learned: each idea, why it failed and what it hit.">
              <span className="bf-icon" aria-hidden><Sparkles size={15} /></span>
              <span className="bf-text"><b>Look for a better fix</b>
                <span>{wonder} takes a second, longer look · about a minute · these options stay</span></span>
              <ChevronRight size={16} className="bf-go" aria-hidden /></button>)}
          {proposal?.escalated && !proposing && proposal.usage && ownerSettings && (
            <p className="hint mono">{wonder}: {proposal.usage.calls} call{proposal.usage.calls === 1 ? "" : "s"},
              {" "}{Math.round(proposal.usage.input_tokens / 1000)}k in, {Math.round(proposal.usage.output_tokens / 1000)}k out
              {" "}({Math.round(proposal.usage.reasoning_tokens / 1000)}k reasoning) · ${proposal.usage.usd.toFixed(2)}</p>)}
          {compact && (proposing || (proposal?.attempts.length ?? 0) > 0) && <details className="activity-fold">
            <summary>Agent activity · {proposal?.attempts.length ?? 0} checked</summary>
            <Activity attempts={proposal?.attempts ?? []} progress={progress} now={now} />
          </details>}
          {!hideFix && <details className="try">
            <summary><Move size={14} aria-hidden /> Try a move yourself</summary>
            <label className="field">Move A vertically (m)
              <input id="manual-dz" type="number" step="0.05" value={manualDz} onChange={(e) => setManualDz(Number(e.target.value))} />
            </label>
            <button className="btn" disabled={!a || !sceneId || !!busy} onClick={checkManual}>Check this move</button>
            {manual && <p className={manual.passed ? "ok" : "bad"}>{manual.passed ? `Clear · nearest ${mm(manual.min_clearance_m)}` : manual.reason ?? manual.hits.map((h) => `${h.kind} with ${h.other_class} ${mm(h.distance_m)}`).join("; ")}</p>}
          </details>}
          {checked.size === 0 && report && matches && !proposal && !hideFix && (
            <p className="hint tipline"><Wand2 size={13} aria-hidden /> Tick several clashes in the list to fix them together.</p>
          )}
        </div>
      </aside>

      {(["left", "right"] as const).map((side) => (
        <div key={side} className={`resizer ${side} ${resizing === side ? "on" : ""}`} role="separator" aria-orientation="vertical"
          aria-label={`Resize the ${side} panel`} aria-valuenow={widths[side]} aria-valuemin={PANE[side][0]} aria-valuemax={PANE[side][1]}
          tabIndex={0} title="Drag to resize · double-click to reset"
          onPointerDown={(e) => {
            e.preventDefault();
            (e.target as HTMLElement).setPointerCapture(e.pointerId);
            setResizing(side);
          }}
          onPointerMove={(e) => {
            if (resizing !== side) return;
            const w = side === "left" ? e.clientX : window.innerWidth - e.clientX;
            setWidths((ws) => ({ ...ws, [side]: clampPane(side, w, ws[side === "left" ? "right" : "left"]) }));
          }}
          onPointerUp={() => { setResizing(null); remember(side, widths[side]); }}
          onDoubleClick={() => { setWidths((ws) => ({ ...ws, [side]: PANE[side][2] })); remember(side, PANE[side][2]); }}
          onKeyDown={(e) => {
            const step = e.key === "ArrowLeft" ? -20 : e.key === "ArrowRight" ? 20 : 0;
            if (!step) return;
            e.preventDefault();
            const w = clampPane(side, widths[side] + (side === "left" ? step : -step), widths[side === "left" ? "right" : "left"]);
            setWidths((ws) => ({ ...ws, [side]: w })); remember(side, w);
          }} />
      ))}
      {!compact && <footer className="dock">
        <Activity attempts={proposal?.attempts ?? []} progress={progress} now={now} />
      </footer>}
      {layout === "tablet" && listOpen && !landing && <div className="drawer-scrim" aria-hidden onClick={() => setListOpen(false)} />}
      {layout === "phone" && !landing && !starting && (
        <SheetBar snap={snap} onSnap={setSnap}>
          <div className={`sheet-peek ${peekLine.live ? "live" : ""} ${peekLine.action || peekLine.live ? "" : "quiet"}`} role="status">
            <button type="button" className="sheet-peek-text" onClick={raise}>
              {peekLine.live && <i className="spinner" aria-hidden />}<span>{peekLine.text}</span></button>
            {peekLine.action && <button type="button" className="btn primary" data-tour={peekLine.action.tour}
              disabled={peekLine.action.disabled} onClick={peekLine.action.run}>{peekLine.action.label}</button>}
          </div>
          <div className="sheet-tabs" role="tablist" aria-label="Panels">
            <button role="tab" aria-selected={listOpen} className={listOpen ? "on" : ""} data-tour="sheet-list"
              onClick={() => { setListOpen(true); raise(); }}>
              <List size={17} aria-hidden /><span>Clashes</span>{report ? <span className="badge-n">{report.clashes.length}</span> : null}</button>
            <button role="tab" aria-selected={!listOpen && tab === "clash"} className={!listOpen && tab === "clash" ? "on" : ""} data-tour="sheet-fix"
              onClick={() => { showClashTab(); raise(); }}>
              <LocateFixed size={17} aria-hidden /><span>Fix</span>{proposal?.options.length ? <span className="badge-n">{proposal.options.length}</span> : null}</button>
            <button role="tab" aria-selected={!listOpen && tab === "plan"} className={!listOpen && tab === "plan" ? "on" : ""} data-tour="tab-plan"
              onClick={() => { showPlanTab(); raise(); }}>
              <Network size={17} aria-hidden /><span>Plan</span>{planning || contextWorking ? <i className="spinner" aria-hidden />
                : planKind === "context" && context?.result?.proposals.length ? <span className="badge-n">{context.result.proposals.length}</span>
                : planOptions.length ? <span className="badge-n">{planOptions.length}</span> : null}</button>
            <button role="tab" aria-selected={!listOpen && tab === "chat"} className={!listOpen && tab === "chat" ? "on" : ""} data-tour="tab-chat"
              onClick={() => { showChatTab(); raise(); }}>
              <MessageSquare size={17} aria-hidden /><span>Chat</span></button>
          </div>
        </SheetBar>
      )}
      {menuOpen && compact && <MenuSheet title="ORCA" onClose={() => setMenuOpen(false)}>
        <section className="menu-section"><h3><Boxes size={15} aria-hidden /> Models</h3>{modelsMenu(() => setMenuOpen(false))}</section>
        <section className="menu-section"><h3><Radar size={15} aria-hidden /> Coordinate</h3>{coordinateMenu(() => setMenuOpen(false))}</section>
        {!landing && <section className="menu-section"><h3>This session</h3>
          {sceneId && <button className="pop-item" data-tour="requirements" onClick={() => { setMenuOpen(false); setReqOpen(true); }}>
            <ClipboardCheck size={16} aria-hidden /> Requirements{reqLabel ? <span className="chip accent">{reqLabel}</span> : <span className="why">optional</span>}</button>}
          {report && <button className="pop-item" data-tour="report" onClick={() => { setMenuOpen(false); setDocOpen(true); setDocReady(false); }}>
            <FileText size={16} aria-hidden /> Report: PDF and BCF</button>}
          {sceneId && <a className="pop-item" data-tour="export" href={api.exportUrl(sceneId)} onClick={() => setMenuOpen(false)}>
            <Download size={16} aria-hidden /> {stepFiles.length ? "Export STEP + IFC" : "Export IFC"}</a>}
          <button className="pop-item" onClick={() => { setMenuOpen(false); setAgentOpen(true); }}>
            {agentLink ? <><Bot size={16} aria-hidden /> Agent connected · {timeLeft(agentLink, now)} left</> : <><Plug size={16} aria-hidden /> Connect an agent</>}</button>
        </section>}
        <section className="menu-section"><h3>Help</h3>
          {!landing && <button className="pop-item" onClick={() => { setMenuOpen(false); setAbout(true); }}><Info size={16} aria-hidden /> How it works</button>}
          {!touring && <button className="pop-item" onClick={() => { setMenuOpen(false); startTour(cellOpen ? "cell" : "northbank"); }}>
            <Compass size={16} aria-hidden /> Take the guided tour</button>}
        </section>
      </MenuSheet>}

      <Tooltips />
      {about && <About triageOpen={!!triageModel?.open_weights} onClose={() => setAbout(false)} />}
      {agentOpen && <AgentDialog link={agentLink} log={agentLog} now={now} creating={agentBusy} error={agentError}
        canCreate={!!sceneId} onCreate={() => void connectAgent()} onRevoke={() => void disconnectAgent()} onClose={() => setAgentOpen(false)} />}
      {touring && <Tour key={tourWhich} which={tourWhich} state={tourState} actions={tourActions} onClose={() => setTouring(false)} />}
      {reqOpen && <RequirementsDialog sceneId={sceneId} initial={reqSaved?.doc ?? null} enabled={!!reqSaved?.enabled}
        audit={triageAudit} canDetectAgain={!!sceneId} onApply={applyRequirements} onClose={() => setReqOpen(false)} />}
      {docOpen && report && <ReportDialog report={report} sceneId={sceneId} triage={shownTriage} triageDone={!!triageRun?.done}
        prepare={builtOn ? prepareReport : undefined}
        teams={modelTeams} onTeams={setModelTeams} evidence={evidence} signoffs={signoffs} reviewed={reviewed}
        triageRunning={!!triageRun && !triageRun.done} onRunTriage={() => runTriage(false)} onClose={() => setDocOpen(false)} onReady={() => setDocReady(true)} />}
      {lightbox && report && lightbox.clash.images[lightbox.index] &&
        <Lightbox reportId={report.id} clash={lightbox.clash} index={lightbox.index} onClose={() => setLightbox(null)}
          onMove={(index) => setLightbox((l) => l && { ...l, index })} />}
    </div>
  );
}

/** Each moved element with every clash element that stays put: where they meet is what a move changes. */
function movedPairs(moved: string[], sides: string[]): [string, string][] {
  const still = sides.filter((g) => !moved.includes(g));
  return moved.flatMap((m) => still.map((g) => [m, g] as [string, string]));
}

/** All context previews are evaluator world meshes, including moves; originals are hidden once. */
function contextShapes(p: ContextProposal) {
  return p.edits.map((edit) => ({ kind: edit.kind, moved: edit.moved, deltaM: [0, 0, 0],
    pieces: edit.preview, before: edit.before, worldMeshes: true, color: "#1f9d3a" }));
}

function samePair(a: string | null | undefined, b: string | null | undefined, x: string, y: string) {
  return (a === x && b === y) || (a === y && b === x);
}

/** Existing report/BCF fields carry the complete coordinated change; checks come from the server commit. */
function contextEvidence(p: ContextProposal, checks: ContextProposal["checks"], pics: { before_img?: string; after_img?: string }): Evidence {
  const g = checks.geometry, integrity = checks.integrity;
  const edit = p.edits.map((e, i) => `${i + 1}. ${e.label} (${e.element}; sources ${e.moved.join(", ")}): ${e.kind} ${e.kind === "trim"
    ? `${e.end} end by ${e.by_m} m` : `delta [${e.delta_m?.join(", ")}] m${e.split_m ? `; split [${e.split_m.join(", ")}] m` : ""}`}`).join("\n");
  const rationale = [...p.edits.map((e, i) => `${i + 1}. ${e.reason}`),
    `Fresh geometry checks ${g.passed ? "passed" : "failed"}; original objective ${g.target_resolved ? "resolved" : "unresolved"}.`,
    `Fresh model integrity checks ${integrity.passed ? "passed" : "failed"}.`, ...integrity.errors, ...integrity.warnings,
    ...g.existing_conflicts.map((h) => `Unchanged baseline ${h.kind}: ${h.element} / ${h.other}, ${h.distance_m} m.`),
    ...g.hits.map((h) => `${h.kind}: ${h.element} / ${h.other}, ${h.distance_m} m.`)].join("\n");
  return { status: "accepted", title: p.title, kind: "context", edit, rationale,
    moved: [...new Set(p.edits.flatMap((e) => e.moved))],
    clearance: g.min_clearance_m == null ? "No measured nearest clearance returned" : mm(g.min_clearance_m),
    clearance_m: g.min_clearance_m, also_needs: p.review_conditions.map((c) => c.message).join("\n"), ...pics };
}

/** Side panel widths in px: [min, max, default]. */
const PANE = { left: [240, 640, 310], right: [300, 720, 380] } as const;
/** Within the side's limits, leaving the viewer at least 360 px beside the other panel (`other`). */
const clampPane = (side: "left" | "right", w: number, other = 0) =>
  Math.round(Math.max(Math.min(w, PANE[side][1], window.innerWidth - other - 360), PANE[side][0]));

function stored(key: string, fallback: number) {
  try { const v = Number(localStorage.getItem(key)); return v > 0 ? clampPane(key.includes("left") ? "left" : "right", v) : fallback; } catch { return fallback; }
}

function remember(side: "left" | "right", w: number) {
  try { localStorage.setItem(`sightline.${side}-w`, String(w)); } catch { /* private window: not remembered */ }
}

/** "Northbank-Structure.ifc" → "Structure" */
function shortName(file: string) { return file.replace(/\.(ifc|step|stp)$/i, "").replace(/^Northbank-/, ""); }

function ProofStrip({ o, rank, options, before, need = 0.025 }: { o: Option; rank: number; options: Option[]; before: number | null; need?: number }) {
  const clear = o.kind === "trim" ? "butt joint, no overlap" : o.min_clearance_m == null ? "nothing within 500 mm" : `${mm(o.min_clearance_m)} clear`;
  const margin = o.kind !== "trim" && o.min_clearance_m != null ? ` (${Math.round((o.min_clearance_m - need) * 1000)} mm over the ${Math.round(need * 1000)} mm needed)` : "";
  const change = options.map((x) => x.delta_m.reduce((s, v) => s + Math.abs(v), 0));
  const smallest = change[rank] === Math.min(...change);
  const comfy = o.min_clearance_m == null || o.min_clearance_m >= 2 * need;
  const why = rank === 0 ? (comfy && smallest ? "ranked first: comfortable clearance, smallest change" : comfy ? "ranked first: comfortable clearance" : smallest ? "ranked first: smallest change that clears" : "ranked first: best clearance of the verified fixes") : `option ${rank + 1} of ${options.length}`;
  return <span className="proof-strip"><span className="ok">✓ Clash gone</span><span>{clear}{margin}</span>{before != null && <span>was {mm(before)} overlap</span>}<span>{o.checked_against ? `checked vs ${o.checked_against} elements` : "checked vs the model"}</span><span className="why">{why}</span></span>;
}
/** The requirements allow no edit here: Muse Spark's recommendation for the designer, never tried or applied. */
function Recommended({ rec, advice, requirements, onRequirements }: { rec: Recommendation; advice?: string; requirements: string | null; onRequirements: () => void }) {
  const change = recEditText(rec);
  return (
    <div className="recommended">
      <h3>Recommended for the designer</h3>
      <p><b>{rec.title}</b>{change ? <> · <span className="mono">{change}</span></> : null}</p>
      {rec.rationale && <p>{rec.rationale}</p>}
      {rec.also_needs && <p><b>Also needs:</b> {rec.also_needs}</p>}
      {advice && <p><b>What decides it:</b> {advice}</p>}
      {rec.others.length > 0 && <p className="hint">Muse Spark also considered: {rec.others.join("; ")}</p>}
      <p className="hint">Not edited: {rec.blocked_by}{requirements ? ` (requirements ${requirements})` : ""}. Nothing was tried
        on the model. <button className="btn small ghost" onClick={onRequirements}>Requirements</button></p>
    </div>
  );
}

/** When nothing passed: what ORCA learned, so the clash reaches a person with a head start, not a dead end. */
function NoFix({ proposal, onRetry, onFlag, onEscalate, wonder }: {
  proposal: Proposal; onRetry?: () => void; onFlag?: () => void; onEscalate?: () => void; wonder: string;
}) {
  const n = proposal.attempts.length;
  const second = proposal.escalated ? proposal.attempts.filter((t) => t.model === wonder).length : 0;
  const counts = new Map<string, number>();
  for (const t of proposal.attempts) {
    for (const cls of new Set([...t.reason.matchAll(/(?:collision|clearance) with (Ifc\w+)/g)].map((m) => m[1]))) {
      counts.set(cls, (counts.get(cls) ?? 0) + 1);
    }
  }
  const top = [...counts.entries()].sort((x, y) => y[1] - x[1]).slice(0, 2);
  const blockers = proposal.attempts.filter((t) => !t.passed).slice(0, 3);
  const kinds = new Set(proposal.attempts.map((t) => t.kind));
  const lesson = kinds.has("offset") && !kinds.has("trim") ? "Whole moves and offsets are blocked along this run. A local trim, a different element, or a design change is likely needed." : kinds.has("trim") ? "Even cutting back at the joint still hits something. This needs a person to decide which element gives way." : "Every direction tried hits something else. Try the other element, or a smaller move by hand below.";
  const next = proposal.advice ? "Follow the advice below, then propose again." : lesson;
  return (
    <div className="nofix">
      <h3>No edit passed the geometry check</h3>
      <p>
        ORCA tried {n} idea{n === 1 ? "" : "s"} and left the model unchanged.
        {second > 0 && <> {wonder} took a second, longer look and tried {second} of them.</>}
        {top.length > 0 && <> What stood in the way: {top.map(([cls, k], i) => (
          <span key={cls}>{i ? ", and " : ""}<b>{cls.replace(/^Ifc/, "")}</b> elements in {k === n ? "every attempt" : `${k} of ${n}`}</span>))}.</>}
      </p>
      {proposal.advice && <p><b>What decides it:</b> {proposal.advice}</p>}
      {blockers.length > 0 && <ul className="nofix-blockers">{blockers.map((t, i) => <li key={i}><b>{t.title}</b> — {t.reason}</li>)}</ul>}
      <p><b>What this teaches:</b> {next}</p>
      {onEscalate && <div className="escalate-card">
        <button className="btn primary" data-tour="escalate" onClick={onEscalate}><Sparkles size={15} aria-hidden /> Ask {wonder}</button>
        <span className="hint">A larger model takes a second, longer look, with everything this try learned. It may move a
          neighbouring service too. About a minute.</span>
      </div>}
      <div className="row nofix-actions">{onRetry && <button className="btn small" onClick={onRetry}>Propose again</button>}{onFlag && <button className="btn small" onClick={onFlag}>Flag for the model's author</button>}<span className="hint">Full detail in the activity table below.</span></div>
    </div>
  );
}


/** The model's reasoning (Muse Spark, or Muse Wonder on a second try), summarised as it thinks: live while it works,
 * then folded away. */
function Thinking({ notes, live, thinking, model }: { notes: { round: number; text: string }[]; live: boolean; thinking: boolean; model: string }) {
  const end = useRef<HTMLLIElement | null>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "nearest" }); }, [notes.length]);
  if (!notes.length && !live) return null;
  const list = (
    <ol className="thoughts">
      {notes.map((n, i) => (
        <li key={i} ref={i === notes.length - 1 ? end : undefined}>
          {(i === 0 || notes[i - 1].round !== n.round) && n.round > 1 && <span className="round">Round {n.round}, with what failed</span>}
          {n.text}
        </li>
      ))}
      {thinking && <li className="pending"><i className="dots" aria-hidden><span /><span /><span /></i></li>}
    </ol>
  );
  if (live) return (
    <div className="thinking live" aria-live="polite">
      <h3><Brain size={14} aria-hidden /> {thinking ? `${model} is thinking` : `${model}'s thinking so far`}</h3>{list}
    </div>
  );
  return (
    <details className="thinking">
      <summary><Brain size={14} aria-hidden /> How {model} reasoned <span className="hint">· {notes.length} note{notes.length === 1 ? "" : "s"}</span></summary>
      {list}
    </details>
  );
}

/** What an offset adds, from its piece count: square corners make 5 straights; bends add four fittings (7 or 9 pieces). */
/** The new root causes in the order already on screen (new ones after), with any that dropped out kept as done rows. */
function keepPlaces(prev: RootCause[] | null, next: RootCause[]): RootCause[] {
  if (!prev) return next;
  const now = new Map(next.map((r) => [r.hub.global_id, r]));
  const out = prev.map((r) => now.get(r.hub.global_id) ?? { ...r, done: true });
  const seen = new Set(prev.map((r) => r.hub.global_id));
  return [...out, ...next.filter((r) => !seen.has(r.hub.global_id))];
}
