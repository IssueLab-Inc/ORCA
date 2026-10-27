import { Boxes, Brain, Check, Download, FileSpreadsheet, FolderOpen, Hand, Info, LocateFixed, MessageSquare, Move, Navigation, Network, Sparkles, Upload, Wand2, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Activity, editText, statusLine, type Progress } from "./Activity";
import { ChatPanel } from "./Chat";
import { api, type AgentEvent, type ChatEvent, type Matches, type Measure, type Option, type Pattern, type PatternVerdict, type Plan, type PlanEvent, type PlanItem, type Proposal, type Report, type ReportClash, type RootCause, type TriageKind, type TriageVerdict, type Verdict } from "./api";
import { About } from "./About";
import { ClashPanel, Lightbox } from "./ClashPanel";
import { PlanPanel, type PlanRun } from "./PlanPanel";
import { Insights } from "./Insights";
import { TriageCard, type TriageRun } from "./Triage";
import { ReportList, mm, type Review } from "./ReportList";
import { Popover } from "./ui";
import { Pilot, type PilotStatus } from "./pilot";
import { Viewer, serverPointToViewer, type Mesh, type Preset, type Side, type ViewMode } from "./viewer/Viewer";
import { ViewerToolbar, type ToolbarState } from "./ViewerToolbar";
import type * as THREE from "three";

type Stats = { elements: number; triangles: number; parseMs: number };
type Tab = "clash" | "plan" | "chat";

export function App() {
  const host = useRef<HTMLDivElement>(null);
  const viewer = useRef<Viewer | null>(null);
  // Side panel widths: dragged by their inner edge, remembered in this browser, double-click to reset.
  const [widths, setWidths] = useState(() => ({ left: stored("sightline.left-w", 310), right: stored("sightline.right-w", 380) }));
  const [resizing, setResizing] = useState<"left" | "right" | null>(null);
  // While the agent works it drives the viewer (pilot.ts); touching the view takes it back.
  const [pilotStatus, setPilotStatus] = useState<PilotStatus | null>(null);
  const sides = useRef<string[]>([]);
  const pilot = useRef<Pilot | null>(null);
  const folderInput = useRef<HTMLInputElement>(null);
  const filesInput = useRef<HTMLInputElement>(null);
  const [samples, setSamples] = useState<string[]>([]);
  const [picked, setPicked] = useState<string[]>([]);
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
  // Clash reports (Navisworks XML).
  const [reportSamples, setReportSamples] = useState<string[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [matches, setMatches] = useState<Matches | null>(null);
  const [clash, setClash] = useState<ReportClash | null>(null);
  const [measure, setMeasure] = useState<Measure | null | "busy">(null);
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
  // Several clashes at once.
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [rootCauses, setRootCauses] = useState<RootCause[] | null>(null);
  // Report-wide: patterns of the same clash, Muse Spark's verdict on each, and clashes reviewed without an edit.
  const [patterns, setPatterns] = useState<Pattern[] | null>(null);
  const [verdicts, setVerdicts] = useState<Record<string, PatternVerdict> | null>(null);
  const [explaining, setExplaining] = useState(false);
  const [reviewed, setReviewed] = useState<Record<string, Review>>({});
  // Bulk triage of the open report (shared on the server: a run someone else started is followed, not repeated).
  const [triage, setTriage] = useState<Record<string, TriageVerdict>>({});
  const [triageRun, setTriageRun] = useState<TriageRun | null>(null);
  const [triageFilter, setTriageFilter] = useState<TriageKind | null>(null);
  const [planRun, setPlanRun] = useState<PlanRun | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [planError, setPlanError] = useState<string | null>(null);

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
    }).catch((e) => setError(`Can't reach the Sightline server: ${e.message}`));
    api.reportSamples().then(setReportSamples).catch(() => undefined);
    return () => v.dispose();
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
    if (!plan || tab !== "plan") return null;
    const g: Record<string, "a" | "b"> = {};
    if (plan.hub) {  // the element behind the clashes in red, everything it meets in green
      g[plan.hub.hub.global_id] = "a";
      for (const p of plan.hub.partners) g[p.global_id] = "b";
    }
    for (const it of plan.items) {
      const moved = new Set(it.option?.moved ?? []);
      for (const gid of [it.element_a, it.element_b]) g[gid] = moved.has(gid) ? "b" : "a";
      for (const gid of moved) g[gid] = "b";
    }
    return g;
  }, [plan, tab]);
  useEffect(() => {
    viewer.current?.setFocus(planGroup ? { a: null, b: null, group: planGroup } : { a, b, group });
  }, [a, b, group, planGroup]);
  useEffect(() => { viewer.current?.setMode(tool.mode); }, [tool.mode]);
  useEffect(() => { viewer.current?.setEdges(tool.edges); }, [tool.edges]);
  // A section box follows the focus: re-cut it when the pair changes, drop it when there is none.
  useEffect(() => {
    if (!tool.section) { viewer.current?.setSection(false); return; }
    if (!viewer.current?.setSection(true)) setTool((t) => ({ ...t, section: false }));
  }, [tool.section, a, b]);
  useEffect(() => {
    setMeasured(viewer.current?.setMeasure(measurePts[0] ?? null, measurePts[1] ?? null) ?? null);
  }, [measurePts]);

  // A clock for the live status lines while an agent works.
  const working = (!!progress && progress.phase !== "done") || (!!planRun && planRun.phase !== "done")
    || (!!triageRun && !triageRun.done);
  useEffect(() => {
    if (!working) return;
    const t = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(t);
  }, [working]);

  // Link the report to the open model whenever either changes.
  useEffect(() => {
    setMatches(null);
    if (!report || !sceneId) return;
    api.match(report.id, sceneId).then(setMatches).catch((e) => setError((e as Error).message));
  }, [report, sceneId]);

  // Root causes and patterns, over the clashes still open (not fixed, not reviewed). Refreshed as that changes.
  const resolved = useMemo(() => [...new Set([...Object.keys(fixes), ...Object.keys(reviewed)])], [fixes, reviewed]);
  useEffect(() => {
    setRootCauses(null); setPatterns(null);
    if (!report || !sceneId || !matches) return;
    api.rootCauses(report.id, sceneId, resolved).then(setRootCauses).catch(() => setRootCauses([]));
    api.patterns(report.id, sceneId, resolved).then(setPatterns).catch(() => setPatterns([]));
  }, [report, sceneId, matches, resolved]);

  async function explainPatterns() {
    if (!report || !sceneId) return;
    setExplaining(true);
    try { setVerdicts(await api.triagePatterns(report.id, sceneId, resolved)); }
    catch (e) { setError((e as Error).message); } finally { setExplaining(false); }
  }

  /** Run the bulk triage, or follow the run already going for this report. */
  async function runTriage(rerun = false) {
    if (!report) return;
    const rid = report.id;
    if (rerun) { setTriage({}); setTriageFilter(null); }
    setTriageRun((r) => r ?? { model: "", open_weights: false, total: report.clashes.length, started: Date.now(), done: false });
    try {
      await api.triageStream(rid, (e) => {
        if (e.type === "start") setTriageRun({ model: e.model, open_weights: e.open_weights, note: e.note, images: e.images, total: e.total, started: Date.now(), done: false });
        else if (e.type === "clash") { const { type: _t, id, ...v } = e; setTriage((t) => ({ ...t, [id]: v })); }
        else if (e.type === "done") setTriageRun((r) => r && { ...r, done: true, seconds: e.seconds, error: e.error });
      }, rerun);
    } catch (e) { setError((e as Error).message); setTriageRun((r) => (r && r.model ? { ...r, done: true } : null)); }
  }

  // A newly opened report: pick up a triage that already exists for it (finished, or still running).
  useEffect(() => {
    setTriage({}); setTriageRun(null); setTriageFilter(null);
    if (!report) return;
    let live = true;
    api.triage(report.id).then((s) => {
      if (!live || !s.model) return;
      if (s.done) {
        setTriage(s.results);
        setTriageRun({ model: s.model, open_weights: !!s.open_weights, note: s.note, total: s.total ?? 0, started: Date.now(), done: true, seconds: s.seconds ?? undefined, error: s.error ?? undefined });
      } else runTriage();
    }).catch(() => {});
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [report]);

  function review(ids: string[], kind: Review["kind"], note: string) {
    setReviewed((r) => ({ ...r, ...Object.fromEntries(ids.filter((id) => !fixes[id]).map((id) => [id, { kind, note }])) }));
    setChecked((s) => { const n = new Set(s); for (const id of ids) n.delete(id); return n; });
  }

  /** Take the camera to a report clash: where its elements meet, or its reported point. */
  function goToClash(c: ReportClash, m = matches?.[c.id]) {
    const ids = [m?.show?.[0] ?? m?.a, m?.show?.[1] ?? m?.b].filter((g): g is string => !!g);
    const point = c.point && c.point.every((v) => v != null) ? serverPointToViewer(c.point as number[]) : null;
    if (!viewer.current?.focusClash(ids, point, c.name)) setError("This clash has no geometry or point to show in the open model.");
  }

  // A selected report clash: its pair in the viewer, and Sightline's own measure of it.
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
  useEffect(() => { if (clash && matches) goToClash(clash); }, [matches]);  // eslint-disable-line react-hooks/exhaustive-deps

  // What the viewer previews: the chosen option of a single proposal, else every fix of a plan.
  const option = chosen == null ? null : proposal?.options[chosen] ?? null;
  const planOptions = useMemo(() => (plan?.items.filter((i) => i.option).map((i) => i.option!) ?? []), [plan]);
  useEffect(() => {
    const v = viewer.current;
    if (!v) return;
    if (option) {
      v.showOption({ kind: option.kind, moved: option.moved, deltaM: option.delta_m, pieces: option.preview, before: option.before },
        compare, option.moved.includes(a ?? "") ? "#d0342c" : "#1f9d3a");
    } else if (plan && tab === "plan") {
      v.showOptions(planOptions.map((o) => ({ kind: o.kind, moved: o.moved, deltaM: o.delta_m, pieces: o.preview, before: o.before, color: "#1f9d3a" })), compare);
    } else v.preview([]);
  }, [option, plan, planOptions, compare, a, tab]);

  // Zoom to what the chosen option changes: an offset's risers and middle piece, or where a moved element now
  // meets the other side of the clash (not the whole moved element: a raised 16 m run would fill the screen).
  useEffect(() => {
    if (!option) return;
    const sides = [a, b, ...Object.keys(standIns)].filter((g): g is string => !!g);
    if (!frameFix(option, sides) && option.before?.length) viewer.current?.frameMeshes(option.before, 1.6);
  }, [option]);  // eslint-disable-line react-hooks/exhaustive-deps
  // A finished plan: frame everything it changes, or (nothing to change) the cluster it is about.
  useEffect(() => {
    const v = viewer.current;
    if (!v || !plan) return;
    const meshes = planOptions.flatMap((o) => (o.kind === "offset" && o.preview ? o.preview.slice(1, -1) : []));  // moves and trims: their pairs
    const pairs = plan.items.flatMap((it) => it.option && it.option.kind !== "offset"
      ? movedPairs(it.option.moved, [it.element_a, it.element_b]) : []);
    if (meshes.length || pairs.length) v.frameFix(meshes, pairs);
    else if (plan.hub) v.frame([plan.hub.hub.global_id, ...plan.hub.partners.map((p) => p.global_id)]);
  }, [planOptions, plan]);

  function frameFix(o: { kind: string; moved: string[]; preview: Mesh[] | null }, sides: string[]) {
    // An offset: its risers and middle piece. A move: where it now meets the other side. A trim: the joint it changes.
    const meshes = o.kind === "offset" && o.preview ? o.preview.slice(1, -1) : [];
    return !!viewer.current?.frameFix(meshes, o.kind === "offset" ? [] : movedPairs(o.moved, sides));
  }

  function resetWork() { setProposal(null); setChosen(null); setManual(null); setProgress(null); setCompare("after"); setStandIns({}); }

  async function open() {
    if (!picked.length) return;
    setBusy(`Loading ${picked.length} model${picked.length > 1 ? "s" : ""}…`); setError(null); resetWork(); setA(null); setB(null);
    try {
      const { id, files } = await api.open(picked);
      setSceneId(id);
      const bytes = await Promise.all(files.map((_, i) => api.file(id, i)));
      setModelNames(files.map(shortName));
      setTool((t) => ({ ...t, hiddenModels: [] }));
      setEdits({}); setFixes({}); setReviewed({}); setVerdicts(null); setPlan(null); setPlanRun(null); setChecked(new Set());
      setStats(await viewer.current!.load(bytes, files));
    } catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  }

  /** The start page's button: the sample clash report (its list shows at once), then the models. */
  async function openDemo() {
    const sample = reportSamples[0];
    if (sample && !report) await loadReport(() => api.openReport(sample), sample);
    await open();
  }

  async function loadReport(get: () => Promise<Report>, what: string) {
    setBusy(`Reading ${what}…`); setError(null);
    try { const r = await get(); setReport(r); setClash(null); resetWork(); setChecked(new Set()); setPlan(null); setFixes({}); setReviewed({}); setVerdicts(null); }
    catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  }

  function upload(list: FileList | null) {
    const files = [...(list ?? [])].filter((f) => /\.(xml|png|jpe?g)$/i.test(f.name));
    if (!files.length) return setError("Choose a Navisworks XML report, or the folder it was exported to.");
    loadReport(() => api.uploadReport(files), `${files.length} file${files.length > 1 ? "s" : ""}`);
  }

  function selectClash(c: ReportClash) {
    if (c.id !== clash?.id) { setClash(c); resetWork(); setLightbox(null); }
    if (tab === "plan" && !planRun) setTab("clash");
    if (!matches) { setA(null); setB(null); return; }
    goToClash(c);  // every click navigates, also on the clash already selected
  }

  /** Single click: measure, or show the element's properties. Double click: pick element A, then B. A drag is an
   * orbit, never a pick. */
  function onClick(ev: React.MouseEvent) {
    const d = down.current;
    if (d && Math.hypot(ev.clientX - d.x, ev.clientY - d.y) > 5) return;
    const hit = viewer.current?.pickAt(ev.nativeEvent);
    if (ev.detail === 2) {
      if (!hit || hit.globalId === a) return;
      if (!a || (a && b)) { setA(hit.globalId); setB(null); } else setB(hit.globalId);
      setClash(null); resetWork();
      return;
    }
    if (tool.measure) {
      if (hit) setMeasurePts((p) => (p.length >= 2 ? [hit.point] : [...p, hit.point]));
      return;
    }
    if (!hit) { setSelected(null); return; }
    setSelected({ globalId: hit.globalId, info: null });
    if (sceneId) api.element(sceneId, hit.globalId)
      .then((info) => setSelected((s) => (s?.globalId === hit.globalId ? { ...s, info } : s)))
      .catch(() => undefined);
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
    link.download = `sightline-${clash?.name ?? "view"}.png`;
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

  /** Start showing the agent's progress; returns the handler for its events and a function to call when done. */
  function trackAgent() {
    setError(null); setChosen(null); setManual(null);
    const t = Date.now();
    let p: Progress = { started: t, round: 1, phase: "thinking", thinkingSince: t, modelSeconds: [], ideas: 0, checking: null };
    setProgress(p); setNow(t);
    setProposal({ understanding: "", options: [], attempts: [] });
    setThoughts([]);
    pilot.current?.start();
    const update = (next: Partial<Progress>) => { p = { ...p, ...next }; setProgress(p); };
    const onEvent = (e: AgentEvent) => {
      pilot.current?.event(e);
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
      const show = () => {
        if (result) { setProposal(result); setChosen(result.options.length ? 0 : null); }
        update({ phase: "done", checking: null }); setNow(Date.now());
      };
      if (pilot.current) pilot.current.finish(show); else show();
    };
    return { onEvent, finish };
  }

  async function propose() {
    if (!sceneId || !a || !b) return;
    const { onEvent, finish } = trackAgent();
    const from = clash && report ? { report_id: report.id, clash_id: clash.id } : undefined;
    let result: Proposal | null = null;
    try { result = await api.proposeStream(sceneId, a, b, from, onEvent); }
    catch (e) { setError((e as Error).message); }
    finally { finish(result); }
  }

  /** Start showing a plan being built; returns the handler for its events and a function to call when done. */
  function trackPlan(kind: "batch" | "root_cause") {
    resetWork(); setPlan(null); setError(null); setPlanError(null);
    const t = Date.now();
    let run: PlanRun = { kind, started: t, phase: kind === "root_cause" ? "cause" : "fixing", rootCause: "", items: [], status: {} };
    setPlanRun(run); setNow(t);
    const update = (f: (r: PlanRun) => PlanRun) => { run = f(run); setPlanRun(run); };
    const onEvent = (e: PlanEvent) => {
      if (e.type === "root_cause") update((r) => ({ ...r, rootCause: e.root_cause, phase: "fixing" }));
      if (e.type === "plan_items") update((r) => ({ ...r, phase: "fixing", items: e.items,
        status: Object.fromEntries(e.items.map((i) => [i.key, { state: "waiting" as const }])) }));
      if (e.type === "item") update((r) => ({ ...r, status: { ...r.status, [e.key]: {
        state: e.status, ok: e.ok, note: e.status === "thinking" ? "Muse Spark is looking…" : e.status === "checking" ? `checked: ${e.attempt}` : e.title } } }));
      if (e.type === "checking_plan") update((r) => ({ ...r, phase: "checking" }));
    };
    const finish = (p: Plan | null) => { if (p) setPlan(p); update((r) => ({ ...r, phase: "done" })); setNow(Date.now()); };
    return { onEvent, finish };
  }

  /** Build a plan: several ticked clashes together, or the root cause around one element. */
  async function runPlan(body: { clash_ids?: string[]; hub?: string }) {
    if (!sceneId || !report) return;
    setTab("plan");
    const { onEvent, finish } = trackPlan(body.hub ? "root_cause" : "batch");
    let p: Plan | null = null;
    try { p = await api.planStream(sceneId, { report_id: report.id, fixed: resolved, ...body }, onEvent); }
    catch (e) { setPlanError((e as Error).message); }
    finally { finish(p); }
  }

  async function acceptPlan() {
    if (!sceneId || !plan) return;
    const items = plan.items.filter((i) => i.option && (plan.check.passed || plan.check.items[i.key]?.passed));
    setBusy(`Applying ${items.length} fix${items.length > 1 ? "es" : ""}…`);
    try {
      const { files, pieces } = await api.applyPlan(sceneId, items.map((i) => i.option!));
      viewer.current?.preview([]);
      for (const i of files) await viewer.current!.replace(i, await api.file(sceneId, i));
      setEdits((e) => {
        const next = { ...e };
        for (const ps of pieces) if (ps.length) { const [first, ...added] = ps; next[first] = [...(next[first] ?? []), ...added]; }
        return next;
      });
      markFixed(items.map((i) => [i.element_a, i.element_b] as const), items.map((i) => i.option!.title));
      setPlan(null); setPlanRun(null); setChecked(new Set()); setRemeasure((n) => n + 1);
    } catch (e) { setError((e as Error).message); } finally { setBusy(null); }
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
    const c = report?.clashes.find((x) => it.clash_ids.includes(x.id));
    setA(it.element_a); setB(it.element_b);
    if (c) goToClash(c, { a: it.element_a, b: it.element_b, how: [] });
    else viewer.current?.focusClash([it.element_a, it.element_b], null, it.in_report ? "" : "not in the report");
  }

  // The chat drives the page through events: select a clash, change the view, show the fix agent's work.
  const chatAgent = useRef<ReturnType<typeof trackAgent> | null>(null);
  function onChatEvent(e: ChatEvent) {
    if (e.type === "ui" && e.action === "select_clash") {
      const c = report?.clashes.find((x) => x.id === e.clash_id);
      if (c) selectClash(c);
    }
    if (e.type === "ui" && e.action === "set_view") {
      setTool((t) => ({ ...t, ...(e.mode ? { mode: e.mode as ViewMode } : {}), ...(e.section_box != null ? { section: e.section_box } : {}) }));
    }
    if (e.type === "agent") {
      if (e.event.type === "thinking" && e.event.round === 1) chatAgent.current = trackAgent();
      chatAgent.current?.onEvent(e.event);
    }
    if (e.type === "proposal") {
      setA(e.element_a); setB(e.element_b);
      (chatAgent.current ?? trackAgent()).finish(e);
      chatAgent.current = null;
    }
    if (e.type === "plan_started") chatPlan.current = trackPlan(e.kind);
    if (e.type === "plan_event") chatPlan.current?.onEvent(e.event);
    if (e.type === "plan") { (chatPlan.current ?? trackPlan(e.kind)).finish(e); chatPlan.current = null; }
  }
  const chatPlan = useRef<ReturnType<typeof trackPlan> | null>(null);

  async function accept(o: Option) {
    if (!sceneId) return;
    setBusy("Applying the fix…"); setError(null);
    try {
      const { files, pieces } = await api.accept(sceneId, o);
      viewer.current?.preview([]);
      for (const i of files) await viewer.current!.replace(i, await api.file(sceneId, i));
      if (pieces?.length) {
        const [first, ...added] = pieces;
        setEdits((e) => ({ ...e, [first]: [...(e[first] ?? []), ...added] }));
      }
      markFixed([[a, b]], [o.title]);
      resetWork(); setRemeasure((n) => n + 1);
    } catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  }

  async function checkManual() {
    if (!sceneId || !a) return;
    const v = await api.verify(sceneId, [a], [0, 0, manualDz]);
    setManual(v);
    viewer.current?.preview([{ globalIds: [a], deltaM: [0, 0, manualDz] }]);
  }

  const proposing = !!progress && progress.phase !== "done";
  // Until a report or the models are open, the page is the landing: no panels, just what Sightline is and the demo.
  const landing = !stats && !report;
  const startLabel = reportSamples.length && !report ? "Open the Northbank demo" : "Open the models";
  const planning = !!planRun && planRun.phase !== "done";
  const fixedCount = Object.keys(fixes).length;
  const compareBar = (option || (plan && tab === "plan" && planOptions.length > 0)) && (
    <div className="compare" onClick={(e) => e.stopPropagation()}>
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
          <dt>Change</dt><dd>{option.kind === "offset" && option.split_m
            ? `1 segment → ${option.preview?.length ?? 5} pieces; ${(option.split_m[1] - option.split_m[0]).toFixed(2)} m of it ${option.delta_m[2] > 0 ? "raised" : "lowered"} ${Math.abs(Math.round(option.delta_m[2] * 1000))} mm`
            : option.kind === "trim" && option.trim
              ? `one end cut back ${Math.round(option.trim.by_m * 1000)} mm; nothing moves`
              : `${option.moved.length} element${option.moved.length > 1 ? "s" : ""} moved ${option.delta_m.map((v) => mm(v)).join(" · ")}`}</dd>
        </dl>
      ) : plan && (
        <dl className="diff">
          <dt>Plan</dt><dd>{planOptions.length} fix{planOptions.length === 1 ? "" : "es"} shown together</dd>
          <dt>Check</dt><dd className={plan.check.passed ? "ok" : "bad"}>{plan.check.passed ? "all clear, checked as one" : "not all clear"}</dd>
        </dl>
      )}
      {compare === "both" && <p className="hint"><i className="sw ghost" />orange ghost: as it is now</p>}
    </div>
  );

  return (
    <div className={`app ${resizing ? "resizing" : ""} ${landing ? "landing" : ""}`}
      style={{ "--left-w": `${widths.left}px`, "--right-w": `${widths.right}px` } as React.CSSProperties}>
      <header className="bar">
        <span className="brand"><span className="logo" aria-hidden>◎</span>ClashWise <b>Sightline</b></span>
        <Popover icon={Boxes} label="Models" text="Models" tip="bottom">
          {(close) => (<>
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
          </>)}
        </Popover>
        <Popover icon={FileSpreadsheet} label="Clash report" text="Clash report" tip="bottom">
          {(close) => (<>
            <p className="pop-title">Navisworks clash report (XML)</p>
            {reportSamples.map((s) => (
              <button key={s} className="pop-item" onClick={() => { close(); loadReport(() => api.openReport(s), s); }}>
                <FileSpreadsheet size={14} aria-hidden /> {s}</button>
            ))}
            <button className="pop-item" onClick={() => { close(); folderInput.current?.click(); }}><Upload size={14} aria-hidden /> Upload an export folder…</button>
            <button className="pop-item" onClick={() => { close(); filesInput.current?.click(); }}><Upload size={14} aria-hidden /> Upload XML files…</button>
            <p className="hint">Upload the whole export folder to get each clash's images.</p>
          </>)}
        </Popover>
        <input ref={folderInput} type="file" hidden multiple {...{ webkitdirectory: "" }} onChange={(e) => { upload(e.target.files); e.target.value = ""; }} />
        <input ref={filesInput} type="file" hidden multiple accept=".xml,.png,.jpg,.jpeg" onChange={(e) => { upload(e.target.files); e.target.value = ""; }} />
        {!landing && <span className="crumbs">
          {stats ? <span>{modelNames.join(" · ")}</span> : <span className="hint">No model open</span>}
          {report && <span>· {report.title}</span>}
          {stats && <span className="stat mono" title={`${stats.elements} elements, ${Math.round(stats.triangles / 1000)}k triangles, parsed in ${(stats.parseMs / 1000).toFixed(1)} s`}>{stats.elements} elements</span>}
        </span>}
        {!landing && <button className="btn ghost" onClick={() => setAbout(true)}><Info size={15} aria-hidden /> How it works</button>}
        <span className="spacer" />
        {landing && <button className="btn primary" disabled={!picked.length || !!busy} onClick={openDemo}><FolderOpen size={15} aria-hidden /> {startLabel}</button>}
        {fixedCount > 0 && <span className="chip ok">{fixedCount} fixed</span>}
        {sceneId && <a className="btn primary" href={api.exportUrl(sceneId)} data-tip="Download the changed IFC files" data-tip-side="bottom">
          <Download size={15} aria-hidden /> Export IFC</a>}
      </header>

      <aside className="pane left">
        {report
          ? <ReportList report={report} matches={matches} selected={clash?.id ?? null} onSelect={selectClash} onImage={(c, index) => setLightbox({ clash: c, index })} fixes={fixes}
              reviewed={reviewed} checked={checked} busy={planning || proposing} triage={triage} triageFilter={triageFilter}
              onCheck={(ids, on) => setChecked((s) => { const n = new Set(s); for (const id of ids) { if (on) n.add(id); else n.delete(id); } return n; })}
              onFixChecked={() => runPlan({ clash_ids: [...checked] })}
              insights={<><TriageCard run={triageRun} results={triage} now={now} filter={triageFilter} onFilter={setTriageFilter}
                open={report.clashes.filter((c) => !fixes[c.id] && !reviewed[c.id]).length} onRun={runTriage}
                onSetAside={(ids) => review(ids, "by_design", "Triage: by design or not physical")}
                onFlag={(ids) => review(ids, "author", "Triage: modelling error")} /><Insights rootCauses={rootCauses} patterns={patterns} verdicts={verdicts} explaining={explaining}
                busy={planning || proposing} onFixRoot={(hub) => runPlan({ hub })} onExplain={explainPatterns}
                onSelect={(ids) => setChecked((s) => new Set([...s, ...ids.filter((id) => !fixes[id] && !reviewed[id])]))}
                onReview={review} onFixAll={(ids) => runPlan({ clash_ids: ids })} /></>} />
          : <div className="empty-left">
              <FileSpreadsheet size={28} aria-hidden />
              <h2>No clash report open</h2>
              <p className="hint">Open a Navisworks clash report from the header, or double-click element A, then element B, in the model.</p>
            </div>}
      </aside>

      <main className={`stage ${tool.measure ? "measuring" : ""}`} ref={host} onClick={onClick}
        onPointerDown={(e) => { down.current = { x: e.clientX, y: e.clientY }; }}>
        {stats && <ViewerToolbar state={tool} models={modelNames} hasFocus={!!(a || b)}
          onMode={(mode) => setTool((t) => ({ ...t, mode }))} onToggle={toggle} onView={(p) => viewer.current?.view(p)}
          onFit={() => viewer.current?.fitAll()} onFocus={focusNow} onModel={setModelVisible} onShot={screenshot} />}
        {!stats && !busy && (
          <About start={{
            label: startLabel,
            disabled: !picked.length,
            onStart: openDemo,
            details: <>
              {reportSamples.length > 0 && !report && <>Loads the Navisworks clash report <b>{reportSamples[0]}</b>, with a picture of every
                clash, and </>}{report ? "Loads " : ""}{picked.length} building model{picked.length === 1 ? "" : "s"}: {picked.map(shortName).join(", ")}.
              {" "}About 15 seconds. To choose other models, use <b>Models</b> in the header.
            </>,
          }} />
        )}
        {tool.measure && <div className="overlay hint-bar" onClick={(e) => e.stopPropagation()}>
          {measured != null ? `Measured ${Math.round(measured * 1000)} mm. Click again to start a new measurement.` : measurePts.length ? "Click the second point." : "Click the first point to measure from."}</div>}
        {selected && !tool.measure && (
          <div className="props" onClick={(e) => e.stopPropagation()}>
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
              <button className="btn small" onClick={() => { setA(selected.globalId); setB(null); setClash(null); resetWork(); }}><i className="sw red" />Set as A</button>
              <button className="btn small" disabled={!a || a === selected.globalId} onClick={() => { setB(selected.globalId); setClash(null); resetWork(); }}><i className="sw green" />Set as B</button>
            </div>
          </div>
        )}
        {busy && <div className="overlay live"><i className="spinner" aria-hidden />{busy}</div>}
        {proposing && <div className="overlay live"><i className="spinner" aria-hidden />{statusLine(progress, now, proposal?.attempts ?? [])}</div>}
        <div className={`pilot-glow ${pilotStatus?.driving ? "on" : ""}`} aria-hidden />
        {pilotStatus && (
          <div className={`pilot ${pilotStatus.state}`} role="status">
            {pilotStatus.driving ? <Navigation size={14} aria-hidden /> : <Hand size={14} aria-hidden />}
            <span>{pilotStatus.text}</span>
            {pilotStatus.driving
              ? <button className="btn small" onClick={() => pilot.current?.takeOver()}>Take the view</button>
              : <button className="btn small" onClick={() => pilot.current?.resume()}>Let Sightline drive</button>}
          </div>
        )}
        {compareBar}
        {error && <div className="overlay error" role="alert" onClick={() => setError(null)}>{error}<X size={14} aria-hidden /></div>}
      </main>

      <aside className={`pane right ${tab === "chat" ? "chatting" : ""}`}>
        <div className="tabs" role="tablist">
          <button role="tab" aria-selected={tab === "clash"} className={tab === "clash" ? "on" : ""} onClick={() => setTab("clash")}>
            <LocateFixed size={14} aria-hidden /> Clash{proposal?.options.length ? <span className="badge-n">{proposal.options.length}</span> : null}</button>
          <button role="tab" aria-selected={tab === "plan"} className={tab === "plan" ? "on" : ""} onClick={() => setTab("plan")}>
            <Network size={14} aria-hidden /> Plan{planning ? <i className="spinner" aria-hidden /> : planOptions.length ? <span className="badge-n">{planOptions.length}</span> : null}</button>
          <button role="tab" aria-selected={tab === "chat"} className={tab === "chat" ? "on" : ""} onClick={() => setTab("chat")}>
            <MessageSquare size={14} aria-hidden /> Chat</button>
        </div>
        {tab === "chat" && (
          <ChatPanel ready={!!(sceneId || report)} onEvent={onChatEvent}
            context={() => ({ scene_id: sceneId, report_id: report?.id ?? null, clash_id: clash?.id ?? null, fixed: resolved })} />
        )}
        {tab === "plan" && (
          <PlanPanel run={planRun} plan={plan} now={now} busy={!!busy} onAccept={acceptPlan} error={planError}
            onDiscard={() => { setPlan(null); setPlanRun(null); }} onFocus={focusItem}
            onAsDesigned={(ids, note) => { review(ids, "by_design", note); setPlan(null); setPlanRun(null); setTab("clash"); }} />
        )}
        <div className="tab-body" hidden={tab !== "clash"}>
          {clash && report
            ? <ClashPanel reportId={report.id} clash={clash} match={matches?.[clash.id]} measure={measure} onImage={(index) => setLightbox({ clash, index })} fix={fixes[clash.id]} triage={triage[clash.id]} />
            : (a || b) ? (
              <dl className="kv pair">
                <dt><i className="sw red" />A</dt><dd className="mono">{a ?? "—"}</dd>
                <dt><i className="sw green" />B</dt><dd className="mono">{b ?? "—"}</dd>
              </dl>
            ) : <p className="hint">Pick a clash from the list, or double-click two elements in the model.</p>}
          <div className="actions">
            <button className="btn primary big" disabled={!a || !b || !sceneId || !!busy || proposing} onClick={propose}>
              {proposing ? <><i className="spinner" aria-hidden /> Working…</> : <><Sparkles size={16} aria-hidden /> Propose fixes</>}</button>
            <button className="btn" disabled={!a && !b} onClick={focusNow}><LocateFixed size={15} aria-hidden /> Go to the clash</button>
          </div>

          {(proposal?.understanding || proposing) && <>
            <h2>Understanding</h2>
            {(proposal?.understanding || !thoughts.length) &&
              <p className="understanding">{proposal?.understanding || "Muse Spark is reading the clash…"}</p>}
          </>}
          <Thinking notes={thoughts} live={proposing} thinking={proposing && progress?.phase === "thinking"} />
          {proposal && !proposing && <h2>Verified options</h2>}
          {proposal && !proposing && !proposal.options.length && <NoFix proposal={proposal} />}
          {proposal?.options.map((o, i) => (
            <div key={i} className={`card ${chosen === i ? "pick" : ""}`}>
              <button className="card-body" onClick={() => setChosen(chosen === i ? null : i)} aria-pressed={chosen === i}>
                <span className="row"><b>{i + 1} · {o.title}</b><span className="chip ok"><Check size={11} aria-hidden /> verified</span></span>
                <span className="row"><span>Edit</span><span className="mono">{editText(o)}</span></span>
                <span className="row"><span>Clearance</span><span className="mono">{o.kind === "trim" ? "butt joint" : mm(o.min_clearance_m)}</span></span>
                <span className="row"><span>Also needs</span><span>{o.also_needs || "nothing"}</span></span>
                <span className="why">{o.rationale}</span>
              </button>
              {chosen === i && <button className="btn primary" disabled={!!busy} onClick={() => accept(o)}><Check size={15} aria-hidden /> Accept this fix</button>}
            </div>
          ))}

          <details className="try">
            <summary><Move size={14} aria-hidden /> Try a move yourself</summary>
            <label className="field">Move A vertically (m)
              <input id="manual-dz" type="number" step="0.05" value={manualDz} onChange={(e) => setManualDz(Number(e.target.value))} />
            </label>
            <button className="btn" disabled={!a || !sceneId} onClick={checkManual}>Check this move</button>
            {manual && <p className={manual.passed ? "ok" : "bad"}>{manual.passed ? `Clear · nearest ${mm(manual.min_clearance_m)}` : manual.hits.map((h) => `${h.kind} with ${h.other_class} ${mm(h.distance_m)}`).join("; ")}</p>}
          </details>
          {checked.size === 0 && report && matches && !proposal && (
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
      <footer className="dock">
        <Activity attempts={proposal?.attempts ?? []} progress={progress} now={now} />
      </footer>

      {about && <About onClose={() => setAbout(false)} />}
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
function shortName(file: string) { return file.replace(/\.ifc$/i, "").replace(/^Northbank-/, ""); }

/** When nothing passed: what Sightline learned, so the clash reaches a person with a head start, not a dead end. */
function NoFix({ proposal }: { proposal: Proposal }) {
  const n = proposal.attempts.length;
  const counts = new Map<string, number>();
  for (const t of proposal.attempts) {
    for (const cls of new Set([...t.reason.matchAll(/(?:collision|clearance) with (Ifc\w+)/g)].map((m) => m[1]))) {
      counts.set(cls, (counts.get(cls) ?? 0) + 1);
    }
  }
  const top = [...counts.entries()].sort((x, y) => y[1] - x[1]).slice(0, 2);
  return (
    <div className="nofix">
      <h3>No edit passed the geometry check</h3>
      <p>
        Sightline tried {n} idea{n === 1 ? "" : "s"} and left the model unchanged.
        {top.length > 0 && <> What stood in the way: {top.map(([cls, k], i) => (
          <span key={cls}>{i ? ", and " : ""}<b>{cls.replace(/^Ifc/, "")}</b> elements in {k === n ? "every attempt" : `${k} of ${n}`}</span>))}.</>}
      </p>
      {proposal.advice && <p><b>What decides it:</b> {proposal.advice}</p>}
      <p className="hint">Each idea and what it hit is in the activity table below. Propose again for fresh ideas, or flag it for the model's author.</p>
    </div>
  );
}


/** Muse Spark's reasoning, summarised by the model as it thinks: live while it works, then folded away. */
function Thinking({ notes, live, thinking }: { notes: { round: number; text: string }[]; live: boolean; thinking: boolean }) {
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
      <h3><Brain size={14} aria-hidden /> {thinking ? "Muse Spark is thinking" : "Muse Spark's thinking so far"}</h3>{list}
    </div>
  );
  return (
    <details className="thinking">
      <summary><Brain size={14} aria-hidden /> How Muse Spark reasoned <span className="hint">· {notes.length} note{notes.length === 1 ? "" : "s"}</span></summary>
      {list}
    </details>
  );
}
