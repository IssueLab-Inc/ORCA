import { readFile } from "node:fs/promises";
import ts from "typescript";

const url = (js) => `data:text/javascript;base64,${Buffer.from(js).toString("base64")}`;
let sequence = 0;
export async function compiled(path, dependencies = {}, labels = false) {
  const input = await readFile(new URL(path, import.meta.url), "utf8");
  const labelHooks = (context) => (root) => {
    const visit = (node) => {
      if (ts.isVariableDeclaration(node) && node.initializer && ts.isCallExpression(node.initializer)
          && ["useState", "useRef"].includes(node.initializer.expression.getText())) {
        const name = ts.isArrayBindingPattern(node.name) ? node.name.elements[0].name.getText() : node.name.getText();
        const call = node.initializer;
        return context.factory.updateVariableDeclaration(node, node.name, node.exclamationToken, node.type,
          context.factory.updateCallExpression(call, call.expression, call.typeArguments, [context.factory.createStringLiteral(name), ...call.arguments]));
      }
      return ts.visitEachChild(node, visit, context);
    };
    return ts.visitNode(root, visit);
  };
  let { outputText } = ts.transpileModule(input, { compilerOptions: { target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX }, transformers: labels ? { before: [labelHooks] } : undefined });
  for (const [name, target] of Object.entries(dependencies)) outputText = outputText.replaceAll(`from "${name}"`, `from ${JSON.stringify(target)}`);
  return url(outputText + `\n// host ${sequence++}`);
}
export function find(node, predicate) {
  if (!node || typeof node !== "object") return;
  if (predicate(node)) return node;
  for (const child of [node.props?.children].flat(Infinity)) { const result = find(child, predicate); if (result) return result; }
}
export const hasText = (node, text) => typeof node === "string" ? node.includes(text)
  : !!node && [node.props?.children].flat(Infinity).some((child) => hasText(child, text));
export const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
export const option = { title: "Single fix", kind: "move", moved: ["duct"], delta_m: [0, 0, .4], preview: null,
  before: null, split_m: null, min_clearance_m: .05, rationale: "Single reason", also_needs: "" };
export const checks = { geometry: { passed: true, target_resolved: true, hits: [], existing_conflicts: [], min_clearance_m: .025 },
  integrity: { passed: true, errors: [], warnings: ["Retained frame warning"] } };
export const contextProposal = { id: "wide", title: "Coordinated fix", scene_revision: 1,
  objective: { element_a: "duct", element_b: "beam" }, passed: true, checks, review_conditions: [{ id: "review", message: "Designer review required" }],
  edits: ["duct", "blocker"].map((element, i) => ({ kind: "move", element, label: `Edit ${i + 1}`, reason: `Enabling reason ${i + 1}`,
    moved: [element], pieces: [element], before: [], preview: [], delta_m: [0, i ? .3 : 0, i ? 0 : .4] })) };
export const contextResult = { type: "context_result", proposals: [contextProposal], seconds: 1, trials: 1, model_calls: 1, message: "Complete" };

/** Runs production App render + dependency-aware passive effects, including cleanup before replacement.
 * Only external IO, the GPU viewer and leaf components are replaced. State/ref labels aid inspection;
 * the assertions always drive production event handlers and the real effect bodies. */
export async function appHost({ initial = {}, api: overrides = {}, effects = true } = {}) {
  const c = { id: "clash", name: "Clash", a: {}, b: {}, images: [] };
  const report = { id: "report", title: "Report", clashes: [c] };
  const matches = { clash: { a: "duct", b: "beam", how: [] } };
  const state = { sceneId: "scene", a: "duct", b: "beam", stats: { elements: 2, triangles: 2, parseMs: 1 }, clash: c, report, matches, ...initial };
  const cells = [], refs = {}, timers = new Map(), requests = [], contextRequests = [], planRequests = [], verifyRequests = [], actions = [];
  let cursor = 0, dirty = false, pending = [], tree;
  const viewer = new Proxy({ load: async () => ({ elements: 3, triangles: 3, parseMs: 2 }), replace: async () => {},
    capture: () => "data:image/png;base64,capture", frameFix: () => true, focusClash: () => true }, {
    get(target, key) { return key in target ? target[key] : (...args) => { actions.push([key, ...args]); }; },
  });
  const hooks = {
    useState(name, initialValue) { cursor++; if (!(name in state)) state[name] = typeof initialValue === "function" ? initialValue() : initialValue;
      return [state[name], (value) => { const next = typeof value === "function" ? value(state[name]) : value;
        if (!Object.is(next, state[name])) { state[name] = next; dirty = true; } }]; },
    useRef(name, initialValue) { cursor++; return refs[name] ??= { current: name === "host" ? {} : initialValue }; },
    useMemo(fn, deps) { const index = cursor++, old = cells[index];
      if (!old || !deps || deps.some((d, i) => !Object.is(d, old.deps?.[i]))) cells[index] = { deps, value: fn() };
      return cells[index].value; },
    useEffect(effect, deps) { const index = cursor++, old = cells[index];
      if (effects && (!old || !deps || deps.some((d, i) => !Object.is(d, old.deps?.[i])))) pending.push(() => {
        old?.cleanup?.(); cells[index] = { deps, cleanup: effect() };
      }); },
  };
  const api = { samples: async () => ["model.ifc"], reportSamples: async () => ["sample"], match: async () => matches,
    models: async () => ({ triage: { model: "m", open_weights: false } }), rootCauses: async () => [], patterns: async () => [], triage: async () => ({}), teams: async () => ({ models: [] }),
    measure: async () => ({ matched: true, physical: true, distance_m: -.3 }), element: async () => ({}), exportUrl: () => "/export",
    proposeStream: (...args) => new Promise((resolve, reject) => requests.push({ args, onEvent: args[4], resolve, reject })),
    contextStream: (_sid, objective, onEvent, signal) => new Promise((resolve, reject) => contextRequests.push({ objective, onEvent, signal, resolve, reject })),
    planStream: (_sid, body, onEvent) => new Promise((resolve, reject) => planRequests.push({ body, onEvent, resolve, reject })),
    verify: (...args) => new Promise((resolve, reject) => verifyRequests.push({ args, resolve, reject })),
    applyContext: async () => ({ files: [], edits: contextProposal.edits, pieces: [], resolved_pairs: [{ element_a: "duct", element_b: "beam" }], checks }),
    file: async () => new Uint8Array([1]), accept: async () => ({ files: [], pieces: [] }),
    titles: async () => {}, detectTests: async () => ({ tests: [], teams: {}, elements: 0, rules: {} }), ...overrides };
  const key = `__sightlineHost${sequence++}`;
  globalThis[key] = { hooks, api, viewer };
  globalThis.window = { innerWidth: 1600, addEventListener() {}, removeEventListener() {},
    setTimeout(fn) { const id = Symbol(); timers.set(id, fn); return id; }, clearTimeout(id) { timers.delete(id); } };
  globalThis.setInterval = () => Symbol(); globalThis.clearInterval = () => {};
  const react = url(`const h=globalThis.${key}.hooks; export const useState=(...a)=>h.useState(...a),useRef=(...a)=>h.useRef(...a),useMemo=(...a)=>h.useMemo(...a),useEffect=(...a)=>h.useEffect(...a);`);
  const apiModule = url(`export const api=globalThis.${key}.api; export class ApiError extends Error { constructor(message,status){super(message);this.status=status;} } export const setRequirements=()=>{};`);
  const names = ["Activity", "editText", "statusLine", "ChatPanel", "ReportDialog", "ReviewBlock", "OwnerSettingsMenu", "Tour", "About", "AgentDialog", "timeLeft", "ClashPanel", "Lightbox", "PlanPanel", "Insights", "TriageCard", "ReportList", "ViewerToolbar", "Popover", "Tooltips", "DetectSetupCard", "DetectSummary", "RequirementsDialog", "addByDesign", "hasByDesign", "load", "save", "shortLabel"];
  const mocks = url(`${names.map((name) => `export function ${name}(){return null;}`).join("\n")}
    export const TOUR={duct:[],joint:[],girder:""},TOUR_QUESTION="",CELL={ladder:[],post:[],pipe:[],rails:[]}; export const mm=(v)=>String(v); export const noClash=()=>null;
    export const clashLabel=(c)=>"#"+c.number;
    export class Viewer {constructor(){return globalThis.${key}.viewer;}} export const serverPointToViewer=(v)=>v;
    export class Pilot { start(){} event(){} cancel(){globalThis.${key}.viewer.preview([]);} finish(fn){fn();} takeOver(){} }`);
  const icons = url(["Bot", "Plug", "Boxes", "Brain", "Check", "CircleCheck", "ClipboardCheck", "Compass", "Download", "FileSpreadsheet", "FileText", "FolderOpen", "Hand", "Info", "LocateFixed", "MessageSquare", "Move", "Navigation", "Network", "Radar", "Sparkles", "Upload", "Wand2", "X", "RefreshCw", "Trash2"].map((name) => `export function ${name}(){return null;}`).join("\n"));
  const ownership = await compiled("../src/chatRequest.ts");
  const context = await compiled("../src/ContextPlan.tsx", { "react/jsx-runtime": import.meta.resolve("react/jsx-runtime"), "lucide-react": icons, "./ReportList": mocks });
  const dependencies = { "react/jsx-runtime": import.meta.resolve("react/jsx-runtime"), react, "lucide-react": icons,
    "./api": apiModule, "./chatRequest": ownership, "./ContextPlan": context };
  for (const name of ["./Activity", "./Chat", "./ReportDoc", "./Owner", "./Tour", "./About", "./Agent", "./ClashPanel", "./PlanPanel", "./Insights", "./Triage", "./Detect", "./ReportList", "./noClash", "./ui", "./pilot", "./viewer/Viewer", "./ViewerToolbar", "./Requirements", "./reqFile"]) dependencies[name] = mocks;
  const { App } = await import(await compiled("../src/App.tsx", dependencies, true));
  function render() {
    let passes = 0;
    do { dirty = false; cursor = 0; pending = []; tree = App();
      for (const effect of pending) effect();
      if (++passes > 30) throw new Error("Render/effect loop");
    } while (dirty);
  }
  render(); await flush(); render();
  return { state, refs, requests, contextRequests, planRequests, verifyRequests, actions, viewer, api, timers, render,
    async settle() { await flush(); render(); await flush(); render(); },
    button(text) { return find(tree, (n) => n.type === "button" && hasText(n, text)); },
    component(name) { return find(tree, (n) => n.type?.name === name); },
    input(id) { return find(tree, (n) => n.type === "input" && n.props.id === id); },
    reportMenu() { const p = find(tree, (n) => n.type?.name === "Popover" && n.props.label === "Coordinate"); return p.props.children(() => {}); },
    fileInput(kind) { return find(tree, (n) => n.type === "input" && n.props.type === "file"
      && (kind === "folder" ? "webkitdirectory" in n.props : String(n.props.accept ?? "").includes(".xml"))); },
    chat(event) { find(tree, (n) => n.type?.name === "ChatPanel").props.onEvent(event); render(); },
    open() { const p = find(tree, (n) => n.type?.name === "Popover" && n.props.label === "Models");
      find(p.props.children(() => {}), (n) => n.props?.id === "open").props.onClick(); render(); },
    loadReport() { const p = find(tree, (n) => n.type?.name === "Popover" && n.props.label === "Coordinate");
      find(p.props.children(() => {}), (n) => n.type === "button" && hasText(n, "sample")).props.onClick(); render(); },
    runTimers() { const entries = [...timers.values()]; timers.clear(); for (const fn of entries) fn(); render(); },
    unmount() { for (const cell of cells) cell?.cleanup?.(); delete globalThis[key]; },
  };
}
