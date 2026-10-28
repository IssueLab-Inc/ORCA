import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

Error.prepareStackTrace = (error, frames) => `${error.name}: ${error.message}\n${frames.map((frame) =>
  `    at ${frame.getFunctionName() ?? "anonymous"} (${frame.getFileName()?.startsWith("data:") ? "transpiled production module" : frame.getFileName()}:${frame.getLineNumber()})`).join("\n")}`;

const url = (js) => `data:text/javascript;base64,${Buffer.from(js).toString("base64")}`;
const names = ["Activity", "editText", "statusLine", "ChatPanel", "ReportDialog", "ReviewBlock", "OwnerSettingsMenu", "Tour", "About", "ClashPanel", "Lightbox", "PlanPanel", "Insights", "TriageCard", "ReportList", "ViewerToolbar", "Popover", "Tooltips", "DetectSetupCard", "DetectSummary"];
const mocks = url(`${names.map((name) => `export function ${name}(){return null;}`).join("\n")}
  export const TOUR={duct:[],joint:[],girder:""},TOUR_QUESTION="",CELL={ladder:[],post:[],pipe:[],rails:[]}; export const mm=(v)=>String(v); export const noClash=()=>null;
  export const clashLabel=(c)=>"#"+c.number;
  export class Viewer{} export const serverPointToViewer=(v)=>v; export class Pilot{};`);
const icons = url(["Boxes", "Brain", "Check", "CircleCheck", "Compass", "Download", "FileSpreadsheet", "FileText", "FolderOpen", "Hand", "Info", "LocateFixed", "MessageSquare", "Move", "Navigation", "Network", "Radar", "Sparkles", "Upload", "Wand2", "X", "RefreshCw", "Trash2"].map((name) => `export function ${name}(){return null;}`).join("\n"));

async function compiled(path, dependencies, labelState = false) {
  const input = await readFile(new URL(path, import.meta.url), "utf8");
  const stateLabels = (context) => (root) => {
    const visit = (node) => {
      if (ts.isVariableDeclaration(node) && ts.isArrayBindingPattern(node.name) && ts.isCallExpression(node.initializer)
          && node.initializer.expression.getText() === "useState") {
        const call = node.initializer;
        return context.factory.updateVariableDeclaration(node, node.name, node.exclamationToken, node.type,
          context.factory.updateCallExpression(call, call.expression, call.typeArguments, [context.factory.createStringLiteral(node.name.elements[0].name.getText()), ...call.arguments]));
      }
      return ts.visitEachChild(node, visit, context);
    };
    return ts.visitNode(root, visit);
  };
  let { outputText } = ts.transpileModule(input, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX },
    transformers: labelState ? { before: [stateLabels] } : undefined });
  for (const [name, target] of Object.entries(dependencies)) outputText = outputText.replaceAll(`from "${name}"`, `from ${JSON.stringify(target)}`);
  return url(outputText);
}

function find(node, predicate) {
  if (!node || typeof node !== "object") return;
  if (predicate(node)) return node;
  for (const child of [node.props?.children].flat(Infinity)) { const result = find(child, predicate); if (result) return result; }
}
const hasText = (node, text) => typeof node === "string" ? node.includes(text)
  : !!node && [node.props?.children].flat(Infinity).some((child) => hasText(child, text));

async function appHost() {
  const c = { id: "clash", name: "Clash", a: {}, b: {}, images: [] };
  const state = { sceneId: "scene", a: "duct", b: "beam", stats: { elements: 2, triangles: 2, parseMs: 1 }, clash: c,
    report: { id: "report", title: "Report", clashes: [c] }, matches: { clash: { a: "duct", b: "beam", how: [] } } };
  const refs = []; let cursor = 0;
  globalThis.__sightlineAppHooks = {
    useState(name, initial) { if (!(name in state)) state[name] = typeof initial === "function" ? initial() : initial;
      return [state[name], (value) => { state[name] = typeof value === "function" ? value(state[name]) : value; }]; },
    useRef(initial) { const index = cursor++; return refs[index] ??= { current: initial }; },
    useMemo(fn) { return fn(); }, useEffect() {},
  };
  const requests = [];
  const contextRequests = [];
  globalThis.__sightlineAppApi = { proposeStream: () => new Promise((resolve) => requests.push(resolve)),
    contextStream: (_sid, objective, onEvent) => new Promise((resolve) => contextRequests.push({ objective, onEvent, resolve })) };
  const react = url("export const useState=(...a)=>globalThis.__sightlineAppHooks.useState(...a),useRef=(...a)=>globalThis.__sightlineAppHooks.useRef(...a),useMemo=(...a)=>globalThis.__sightlineAppHooks.useMemo(...a),useEffect=()=>{};");
  const api = url("export const api={proposeStream:(...a)=>globalThis.__sightlineAppApi.proposeStream(...a),contextStream:(...a)=>globalThis.__sightlineAppApi.contextStream(...a),exportUrl:()=>'/export',models:async()=>({triage:{model:'m',open_weights:false}})}; export class ApiError extends Error{}");
  const ownership = await compiled("../src/chatRequest.ts", {});
  const context = await compiled("../src/ContextPlan.tsx", { "react/jsx-runtime": import.meta.resolve("react/jsx-runtime"), "lucide-react": icons, "./ReportList": mocks });
  const dependencies = { "react/jsx-runtime": import.meta.resolve("react/jsx-runtime"), react, "lucide-react": icons,
    "./api": api, "./chatRequest": ownership, "./ContextPlan": context };
  for (const name of ["./Activity", "./Chat", "./ReportDoc", "./Owner", "./Tour", "./About", "./ClashPanel", "./PlanPanel", "./Insights", "./Triage", "./Detect", "./ReportList", "./noClash", "./ui", "./pilot", "./viewer/Viewer", "./ViewerToolbar"]) dependencies[name] = mocks;
  const { App } = await import(await compiled("../src/App.tsx", dependencies, true));
  let tree;
  const render = () => { cursor = 0; tree = App(); };
  render();
  return { state, requests, contextRequests, render,
    chat(event) { find(tree, (n) => n.type?.name === "ChatPanel").props.onEvent(event); render(); },
    button(text) { return find(tree, (n) => n.type === "button" && hasText(n, text)); },
    component(name) { return find(tree, (n) => n.type?.name === name); },
  };
}

test("actual App retires pending chat context before a direct single proposal and re-enables wider search", async () => {
  const host = await appHost();
  host.chat({ type: "tool", name: "explore_wider_fix", args: { clash_id: "clash" } });
  host.chat({ type: "context_event", event: { type: "context_progress", phase: "inspecting", message: "Inspecting" } });
  assert.equal(host.state.context.phase, "inspecting");
  const direct = host.button("Propose fixes").props.onClick();
  assert.equal(host.state.context.phase, "done");
  host.requests[0]({ understanding: "done", options: [], attempts: [] }); await direct; host.render();
  assert.equal(host.button("Explore wider fix").props.disabled, false);
});

test("actual App retires pending chat batch plan before direct single work", async () => {
  const host = await appHost();
  host.chat({ type: "plan_started", kind: "batch" });
  host.chat({ type: "plan_event", event: { type: "plan_items", items: [{ key: "pending", label: "Pending pair" }], skipped: [] } });
  assert.equal(host.state.planRun.phase, "fixing");
  const direct = host.button("Propose fixes").props.onClick();
  assert.equal(host.state.planRun.phase, "done");
  assert.equal(host.state.planRun.status.pending.state, "done");
  host.requests[0]({ understanding: "done", options: [], attempts: [] }); await direct; host.render();
  assert.equal(host.button("Explore wider fix").props.disabled, false);
});

test("actual App preserves a completed context proposal when direct work replaces its chat turn", async () => {
  const host = await appHost();
  host.chat({ type: "tool", name: "explore_wider_fix", args: { clash_id: "clash" } });
  const result = { type: "context_result", proposals: [{ id: "proposal", edits: [], objective: { element_a: "duct", element_b: "beam" } }],
    seconds: 1, trials: 1, model_calls: 1, message: "Complete" };
  host.chat({ type: "context_event", event: result });
  const completed = host.state.context;
  const direct = host.button("Propose fixes").props.onClick();
  assert.equal(host.state.context, completed);
  assert.equal(host.state.context.result, result);
  assert.equal(host.state.context.error, null);
  host.requests[0]({ understanding: "done", options: [], attempts: [] }); await direct;
});

test("actual App retires a pending chat plan before regenerated direct context without retiring the new search", async () => {
  const host = await appHost();
  host.chat({ type: "tool", name: "explore_wider_fix", args: { clash_id: "clash" } });
  host.chat({ type: "context_event", event: { type: "context_result", proposals: [], seconds: 1, trials: 1, model_calls: 1, message: "Complete" } });
  host.chat({ type: "plan_started", kind: "batch" });
  host.button("Plan").props.onClick(); host.render();
  host.button("Wider fix").props.onClick(); host.render();
  host.component("ContextPlan").props.onRegenerate(); host.render();
  assert.equal(host.state.planRun.phase, "done");
  assert.equal(host.state.context.phase, "inspecting");
  assert.equal(host.state.context.error, null);
  assert.equal(host.contextRequests[0].objective.element_a, "duct");
  host.contextRequests[0].onEvent({ type: "context_progress", phase: "checking", message: "Checking new arrangement" });
  assert.equal(host.state.context.phase, "checking");
  host.contextRequests[0].onEvent({ type: "context_result", proposals: [], seconds: 1, trials: 1, model_calls: 1, message: "New result" });
  host.contextRequests[0].resolve();
  assert.equal(host.state.context.phase, "done");
  assert.equal(host.state.context.result.message, "New result");
});
