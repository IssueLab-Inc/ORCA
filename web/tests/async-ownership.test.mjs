import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

// Execute production TypeScript without introducing a test runner or emitting test build files.
// `deps` maps an import ("./aiNames") to the module that stands in for it.
async function transpiled(path, deps = {}) {
  const input = await readFile(new URL(path, import.meta.url), "utf8");
  let { outputText } = ts.transpileModule(input, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } });
  for (const name of Object.keys(deps)) outputText = outputText.replaceAll(`from "${name}"`, `from ${JSON.stringify(deps[name])}`);
  return `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`;
}
async function source(path, deps = {}) {
  return import(await transpiled(path, deps));
}
const moduleUrl = (js) => `data:text/javascript;base64,${Buffer.from(js).toString("base64")}`;
const { Pilot } = await source("../src/pilot.ts", { "./aiNames": await transpiled("../src/aiNames.ts") });
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
const trial = { type: "trial", index: 0, kind: "move", moved: ["duct"], delta_m: [0, 0, .4], pieces: null };
const attempt = { ...trial, type: "attempt", title: "raise duct", passed: true, reason: "", split_m: null };
function stage() {
  const actions = [];
  const viewer = { orbit: (v) => actions.push(["orbit", v]), setHits: (v) => actions.push(["hits", v]),
    preview: () => actions.push(["clear"]), showOption: (...args) => actions.push(["show", ...args]) };
  const pilot = new Pilot(() => viewer, () => actions.push(["frame"]), (s) => actions.push(["status", s]));
  return { pilot, actions };
}

test("cancelled pilot cannot land or clear a newer context preview after its first wait", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const { pilot, actions } = stage();
  let completed = 0;
  pilot.start(); pilot.event(trial); pilot.event(attempt); pilot.finish(() => completed++);
  (pilot.cancel ?? pilot.takeOver).call(pilot);
  actions.push(["context preview"]);
  const boundary = actions.length;
  t.mock.timers.runAll(); await flush();
  assert.equal(completed, 0);
  assert.deepEqual(actions.slice(boundary), []);
});

test("cancel during the second animation wait cannot clear or mutate a replacement pilot", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const { pilot, actions } = stage();
  let oldDone = 0, newDone = 0;
  pilot.start(); pilot.event(trial); pilot.event(attempt); pilot.finish(() => oldDone++);
  t.mock.timers.tick(1100); await flush();
  assert.equal(actions.filter((a) => a[0] === "show").length, 2);
  (pilot.cancel ?? pilot.takeOver).call(pilot); pilot.start();
  pilot.event({ ...trial, index: 1 });
  const boundary = actions.length;
  t.mock.timers.tick(1400); await flush();
  assert.equal(oldDone, 0);
  assert.deepEqual(actions.slice(boundary), []);
  pilot.event({ ...attempt, index: 1 }); pilot.finish(() => newDone++);
  await flush(); t.mock.timers.runAll(); await flush();
  assert.equal(newDone, 1);
});

test("ordinary camera takeover still allows the current result to finish once", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const { pilot } = stage(); let completed = 0;
  pilot.start(); pilot.event(trial); pilot.takeOver(); pilot.finish(() => completed++);
  t.mock.timers.runAll(); await flush();
  assert.equal(completed, 1);
});

test("old-report chat events and late tool starts cannot acquire ownership after workspace replacement", async () => {
  const { ChatRequestOwner } = await source("../src/chatRequest.ts");
  const owner = new ChatRequestOwner();
  const old = owner.begin();
  const emitted = [];
  const delayed = (e) => { if (old.isCurrent()) emitted.push(e); };
  owner.invalidate(); // App invalidates before loading the replacement report.
  const current = owner.begin();
  delayed({ type: "tool", name: "explore_wider_fix" });
  delayed({ type: "ui", action: "select_clash" });
  delayed({ type: "context_event", event: { type: "context_result" } });
  assert.equal(old.signal.aborted, true);
  assert.deepEqual(emitted, []);
  assert.equal(current.isCurrent(), true);
});

test("direct work aborts old chat, while stale unmount/finally cannot cancel its successor", async () => {
  const { ChatRequestOwner } = await source("../src/chatRequest.ts");
  const owner = new ChatRequestOwner();
  const old = owner.begin(); let obsoleteToolStarts = 0;
  owner.invalidate(); // A direct wider search replaces the current chat work before tracking context.
  if (old.isCurrent()) obsoleteToolStarts++;
  assert.equal(obsoleteToolStarts, 0);
  const next = owner.begin();
  old.cancel(); old.finish();
  assert.equal(next.isCurrent(), true);
  assert.equal(next.signal.aborted, false);
  next.finish();
  assert.equal(next.isCurrent(), false);
});

// A small hook host runs the actual ChatPanel event handlers without a DOM or an added test dependency.
async function chatHost(owner, pageEvents) {
  const cells = [], effects = [];
  let cursor = 0;
  globalThis.__sightlineHooks = {
    useState(initial) {
      const index = cursor++;
      if (!(index in cells)) cells[index] = typeof initial === "function" ? initial() : initial;
      return [cells[index], (value) => { cells[index] = typeof value === "function" ? value(cells[index]) : value; }];
    },
    useRef(initial) { const index = cursor++; return cells[index] ??= { current: initial }; },
    useEffect(effect, deps) {
      const index = cursor++, previous = cells[index];
      if (!previous || deps?.some((d, i) => d !== previous.deps?.[i])) {
        effects.push(() => { previous?.cleanup?.(); cells[index] = { deps, cleanup: effect() }; });
      }
    },
  };
  const requests = [];
  globalThis.__sightlineTestApi = { chat: (body, callback, signal) => new Promise((resolve) => requests.push({ body, callback, signal, resolve })) };
  const mockReact = moduleUrl("export const useState=(...a)=>globalThis.__sightlineHooks.useState(...a), useRef=(...a)=>globalThis.__sightlineHooks.useRef(...a), useEffect=(...a)=>globalThis.__sightlineHooks.useEffect(...a);");
  const mockApi = moduleUrl("export const api={chat:(...a)=>globalThis.__sightlineTestApi.chat(...a)};");
  const mockVoice = moduleUrl("export const MAX_SECONDS=60; export class VoiceRecorder {static supported(){return false;}} export class LiveVoice {static supported(){return false;}}");
  const mockIcons = moduleUrl("export const AudioLines=()=>null, Mic=()=>null, Square=()=>null;");
  const input = await readFile(new URL("../src/Chat.tsx", import.meta.url), "utf8");
  let { outputText } = ts.transpileModule(input, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX } });
  for (const [name, url] of Object.entries({ react: mockReact, "react/jsx-runtime": import.meta.resolve("react/jsx-runtime"),
    "lucide-react": mockIcons, "./api": mockApi, "./voice": mockVoice })) outputText = outputText.replaceAll(`from "${name}"`, `from ${JSON.stringify(url)}`);
  const { ChatPanel } = await import(moduleUrl(outputText));
  let tree;
  const render = () => {
    cursor = 0;
    tree = ChatPanel({ owner, ready: true, context: () => ({ scene_id: "scene", report_id: "report", clash_id: "clash", fixed: [] }), onEvent: (e) => pageEvents.push(e) });
    while (effects.length) effects.shift()();
  };
  function find(node, predicate) {
    if (!node || typeof node !== "object") return;
    if (predicate(node)) return node;
    for (const child of [node.props?.children].flat(Infinity)) { const result = find(child, predicate); if (result) return result; }
  }
  render();
  return {
    requests,
    turns: () => cells[0],
    send(text) {
      find(tree, (n) => n.type === "textarea").props.onChange({ target: { value: text } }); render();
      find(tree, (n) => n.type === "form").props.onSubmit({ preventDefault() {} }); render();
    },
    render,
    unmount() { for (const cell of cells) cell?.cleanup?.(); },
  };
}

test("actual ChatPanel unmount aborts old-report stream and ignores delayed tool/result events", async () => {
  const { ChatRequestOwner } = await source("../src/chatRequest.ts");
  const owner = new ChatRequestOwner(), events = [];
  const host = await chatHost(owner, events);
  host.send("Read the old report");
  const old = host.requests[0];
  owner.invalidate(); host.unmount(); // App closes ownership before replacing report state/key.
  old.callback({ type: "tool", name: "explore_wider_fix", args: { clash_id: "old" } });
  old.callback({ type: "context_event", event: { type: "context_result", proposals: [] } });
  old.callback({ type: "ui", action: "select_clash", clash_id: "old" });
  old.resolve(); await flush();
  assert.equal(old.signal.aborted, true);
  assert.deepEqual(events, []);
});

test("actual ChatPanel preserves completed history and session while direct search replaces a pending turn", async () => {
  const { ChatRequestOwner } = await source("../src/chatRequest.ts");
  const owner = new ChatRequestOwner(), events = [];
  const host = await chatHost(owner, events);
  host.send("First question");
  const first = host.requests[0];
  first.callback({ type: "session", id: "kept-session" }); first.callback({ type: "message", text: "Completed answer" });
  first.resolve(); await flush(); host.render();
  host.send("Pending question");
  const old = host.requests[1];
  owner.invalidate(); // Same mounted panel: a direct wider search now owns page work.
  const boundary = events.length;
  old.callback({ type: "tool", name: "explore_wider_fix", args: {} });
  old.resolve(); await flush(); host.render();
  assert.deepEqual(events.slice(boundary), []);
  assert.equal(host.turns()[1].text, "Completed answer");
  assert.equal(host.turns()[3].pending, false);
  host.send("Resume after direct work");
  const next = host.requests[2];
  assert.equal(next.body.session_id, "kept-session");
  assert.equal(next.signal.aborted, false);
  next.callback({ type: "message", text: "New valid answer" }); next.resolve(); await flush();
  assert.equal(host.turns()[5].text, "New valid answer");
  host.unmount();
});

test("actual chat NDJSON suppresses a buffered event after abort and cancels the response reader", async (t) => {
  const { api } = await source("../src/api.ts");
  const { ChatRequestOwner } = await source("../src/chatRequest.ts");
  const owner = new ChatRequestOwner(), lease = owner.begin(), events = [];
  let stream, cancelled = false, signal;
  t.mock.method(globalThis, "fetch", async (_url, init) => {
    signal = init.signal;
    return new Response(new ReadableStream({ start(c) { stream = c; }, cancel() { cancelled = true; } }));
  });
  const task = api.chat({ message: "pending", session_id: null, scene_id: "s", report_id: "r", clash_id: null, fixed: [] }, (e) => events.push(e), lease.signal);
  await flush(); owner.invalidate();
  stream.enqueue(new TextEncoder().encode('{"type":"tool","name":"explore_wider_fix","args":{}}\n'));
  await task;
  assert.equal(signal, lease.signal);
  assert.equal(signal.aborted, true);
  assert.equal(cancelled, true);
  assert.deepEqual(events, []);
});
