import { Boxes, Check, Download, FileSpreadsheet, FolderOpen, LocateFixed, MessageSquare, Move, Network, Sparkles, Upload, Wand2, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Activity, statusLine, type Progress } from "./Activity";
import { ChatPanel } from "./Chat";
import { api, type AgentEvent, type ChatEvent, type Matches, type Measure, type Option, type Pattern, type PatternVerdict, type Plan, type PlanEvent, type PlanItem, type Proposal, type Report, type ReportClash, type RootCause, type Verdict } from "./api";
import { ClashPanel, Lightbox } from "./ClashPanel";
import { PlanPanel, type PlanRun } from "./PlanPanel";
import { Insights } from "./Insights";
import { ReportList, mm, type Review } from "./ReportList";
import { Popover } from "./ui";
import { Viewer, serverPointToViewer, type Preset, type ViewMode } from "./viewer/Viewer";
import { ViewerToolbar, type ToolbarState } from "./ViewerToolbar";
import type * as THREE from "three";

type Stats = { elements: number; triangles: number; parseMs: number };
type Tab = "clash" | "plan" | "chat";

export function App() {
  const host = useRef<HTMLDivElement>(null);
  const viewer = useRef<Viewer | null>(null);
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
  const [image, setImage] = useState<number | null>(null);
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
  const [planRun, setPlanRun] = useState<PlanRun | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [planError, setPlanError] = useState<string | null>(null);

  useEffect(() => {
    if (!host.current) return;
    const v = new Viewer(host.current);
    viewer.current = v;
    api.samples().then((list) => {
      setSamples(list);
      // Default to the coordination set: the building disciplines, not site context, grids or a later revision.
      const set = list.filter((f) => /(structure|mep|architecture)\.ifc$/i.test(f));
      setPicked(set.length ? set : list.slice(0, 1));
    }).catch((e) => setError(`Can't reach the Sightline server: ${e.message}`));
    api.reportSamples().then(setReportSamples).catch(() => undefined);
    return () => v.dispose();
  }, []);

  // Pieces accepted offsets added to A or B are part of that side: coloured, and kept when isolating.
  const [standIns, setStandIns] = useState<Record<string, "a" | "b">>({});
  const group = useMemo(() => {
    const g: Record<string, "a" | "b"> = { ...standIns };
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
  const working = (!!progress && progress.phase !== "done") || (!!planRun && planRun.phase !== "done");
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
    setStandIns({ ...(shownA && shownA !== m?.a ? { [shownA]: "a" as const } : {}), ...(shownB && shownB !== m?.b ? { [shownB]: "b" as const } : {}) });
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

  // Zoom to what the chosen option changes: an offset's risers and middle piece, or the moved elements.
  useEffect(() => {
    if (!option) return;
    const changed = option.kind === "offset" && option.preview ? option.preview.slice(1, -1) : option.before;
    if (changed?.length) viewer.current?.frameMeshes(changed, 1.6);
  }, [option]);
  // A finished plan: frame everything it changes, or (nothing to change) the cluster it is about.
  useEffect(() => {
    const changed = planOptions.flatMap((o) => (o.kind === "offset" && o.preview ? o.preview.slice(1, -1) : o.before ?? []));
    if (changed.length) viewer.current?.frameMeshes(changed, 1.3);
    else if (plan?.hub) viewer.current?.frame([plan.hub.hub.global_id, ...plan.hub.partners.map((p) => p.global_id)]);
  }, [planOptions, plan]);

  function resetWork() { setProposal(null); setChosen(null); setManual(null); setProgress(null); setCompare("after"); setStandIns({}); }

  async function open() {
    if (!picked.length) return;
    setBusy(`Loading ${picked.length} model${picked.length > 1 ? "s" : ""}…`); setError(null); resetWork(); setA(null); setB(null);
    try {
      const { id, files } = await api.open(picked);
      setSceneId(id);
      const bytes = await Promise.all(files.map((_, i) => api.file(id, i)));
      setModelNames(files.map((f) => f.replace(/\.ifc$/i, "").replace(/^Northbank-/, "")));
      setTool((t) => ({ ...t, hiddenModels: [] }));
      setEdits({}); setFixes({}); setReviewed({}); setVerdicts(null); setPlan(null); setPlanRun(null); setChecked(new Set());
      setStats(await viewer.current!.load(bytes, files));
    } catch (e) { setError((e as Error).message); } finally { setBusy(null); }
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
    if (c.id !== clash?.id) { setClash(c); resetWork(); setImage(null); }
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
      else if (k === "escape") { setMeasurePts([]); setSelected(null); setImage(null); }
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
    const update = (next: Partial<Progress>) => { p = { ...p, ...next }; setProgress(p); };
    const onEvent = (e: AgentEvent) => {
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
      if (result) { setProposal(result); setChosen(result.options.length ? 0 : null); }
      update({ phase: "done", checking: null }); setNow(Date.now());
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
          <dt>After</dt><dd className="ok">clear{option.min_clearance_m != null ? `, nearest ${mm(option.min_clearance_m)}` : ""}</dd>
          <dt>Change</dt><dd>{option.kind === "offset" && option.split_m
            ? `1 segment → ${option.preview?.length ?? 5} pieces; ${(option.split_m[1] - option.split_m[0]).toFixed(2)} m of it ${option.delta_m[2] > 0 ? "raised" : "lowered"} ${Math.abs(Math.round(option.delta_m[2] * 1000))} mm`
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
    <div className="app">
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
        <span className="crumbs">
          {stats ? <span>{modelNames.join(" · ")}</span> : <span className="hint">No model open</span>}
          {report && <span>· {report.title}</span>}
          {stats && <span className="stat mono" title={`${stats.elements} elements, ${Math.round(stats.triangles / 1000)}k triangles, parsed in ${(stats.parseMs / 1000).toFixed(1)} s`}>{stats.elements} elements</span>}
        </span>
        <span className="spacer" />
        {fixedCount > 0 && <span className="chip ok">{fixedCount} fixed</span>}
        {sceneId && <a className="btn primary" href={api.exportUrl(sceneId)} data-tip="Download the changed IFC files" data-tip-side="bottom">
          <Download size={15} aria-hidden /> Export IFC</a>}
      </header>

      <aside className="pane left">
        {report
          ? <ReportList report={report} matches={matches} selected={clash?.id ?? null} onSelect={selectClash} fixes={fixes}
              reviewed={reviewed} checked={checked} busy={planning || proposing}
              onCheck={(ids, on) => setChecked((s) => { const n = new Set(s); for (const id of ids) { if (on) n.add(id); else n.delete(id); } return n; })}
              onFixChecked={() => runPlan({ clash_ids: [...checked] })}
              insights={<Insights rootCauses={rootCauses} patterns={patterns} verdicts={verdicts} explaining={explaining}
                busy={planning || proposing} onFixRoot={(hub) => runPlan({ hub })} onExplain={explainPatterns}
                onSelect={(ids) => setChecked((s) => new Set([...s, ...ids.filter((id) => !fixes[id] && !reviewed[id])]))}
                onReview={review} onFixAll={(ids) => runPlan({ clash_ids: ids })} />} />
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
          <div className="stage-empty" onClick={(e) => e.stopPropagation()}>
            <Boxes size={36} aria-hidden />
            <p>Open the models to start</p>
            <button className="btn primary" disabled={!picked.length} onClick={open}><FolderOpen size={15} aria-hidden /> Open {picked.length ? picked.map((p) => p.replace(/\.ifc$/i, "").replace(/^Northbank-/, "")).join(" + ") : "models"}</button>
          </div>
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
            ? <ClashPanel reportId={report.id} clash={clash} match={matches?.[clash.id]} measure={measure} onImage={setImage} fix={fixes[clash.id]} />
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
            <p className="understanding">{proposal?.understanding || "Muse Spark is reading the clash…"}</p>
          </>}
          {proposal && !proposing && <h2>Verified options</h2>}
          {proposal && !proposing && !proposal.options.length && <p className="bad">No fix passed the check. This clash needs a person.</p>}
          {proposal?.options.map((o, i) => (
            <div key={i} className={`card ${chosen === i ? "pick" : ""}`}>
              <button className="card-body" onClick={() => setChosen(chosen === i ? null : i)} aria-pressed={chosen === i}>
                <span className="row"><b>{i + 1} · {o.title}</b><span className="chip ok"><Check size={11} aria-hidden /> verified</span></span>
                <span className="row"><span>Edit</span><span className="mono">{o.kind === "offset" && o.split_m
                  ? `offset ${o.split_m.map((v) => v.toFixed(2)).join("–")} m, ${mm(o.delta_m[2])}`
                  : `move ${o.delta_m.map((v) => mm(v)).join(", ")}`}</span></span>
                <span className="row"><span>Clearance</span><span className="mono">{mm(o.min_clearance_m)}</span></span>
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

      <footer className="dock">
        <Activity attempts={proposal?.attempts ?? []} progress={progress} now={now} />
      </footer>

      {clash && report && image != null && clash.images[image] &&
        <Lightbox reportId={report.id} clash={clash} index={image} onClose={() => setImage(null)} onMove={setImage} />}
    </div>
  );
}
