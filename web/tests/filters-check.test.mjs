import assert from "node:assert/strict";
import test from "node:test";
import { appHost, compiled, find, hasText } from "./app-host.mjs";

/** Checks on filters (docs/filters.md, "Checks"): a filter as side A of a clash test, against everything, itself or
 * another filter; the page builds the test (checks.ts, FiltersPanel), App runs it and Detect again repeats it. */

const filters = await compiled("../src/filters.ts", {});
const f = await import(filters);
const checks = await import(await compiled("../src/checks.ts", { "./filters": filters }));

const index = {
  revision: 0, files: ["S.ifc", "M.ifc"], elements: ["beam", "duct1", "duct2", "room", "wall"], file: [0, 1, 1, 0, 0],
  facets: [
    { key: "class", kind: "text", values: ["IfcBeam", "IfcDuctSegment", "IfcSpace", "IfcWall"], items: [[0], [1, 2], [3], [4]] },
    { key: "storey", kind: "text", values: ["Level 01", "Level 02"], items: [[0, 3, 4], [1, 2]] },
    { key: "pset:Model data/Width", kind: "number", unit: "m", values: [0.4, 1.2], items: [[0], [1, 2]] },
  ],
};
const p = f.prepare(index);
const ducts = { id: "d", name: "Ducts", on: true, when: [{ facet: "class", op: "is", values: ["IfcDuctSegment"] },
  { facet: "pset:Model data/Width", op: "gt" }], action: "colour" };   // the second condition is not complete yet
const beams = { id: "b", name: "", on: false, when: [{ facet: "class", op: "is", values: ["IfcBeam"] }], action: "hide" };
const everything = { id: "e", name: "By width", on: true, when: [], action: "byValue", by: { facet: "pset:Model data/Width" } };
const defaults = { tolerance_m: 0.01, clearance_m: 0.025, rules: { same_element: true, connected: true }, min_size_m: 0.005 };

test("a check's sides are a filter's complete conditions; its name says what it compares", () => {
  assert.deepEqual(checks.sideOf(ducts).filter, { when: [ducts.when[0]], invert: false }, "an unfinished condition is left out, as the filter does");
  assert.equal(checks.checkName(ducts, "everything"), "Ducts vs Everything");
  assert.equal(checks.checkName(ducts, "itself"), "Ducts (within)");
  assert.equal(checks.checkName(ducts, beams), "Ducts vs Beam", "an unnamed filter goes by what it finds");
  assert.equal(checks.checkName(ducts, beams, "clearance", 0.05), "Ducts vs Beam, 50 mm clearance");
});

test("a check's test has no id (the server's), the defaults for what is not given, and Everything or Itself as side B", () => {
  const hard = checks.checkTest(ducts, "everything", "hard", null, defaults);
  assert.equal(hard.id, "");
  assert.equal(hard.kind, "hard"); assert.equal(hard.tolerance_m, 0.01); assert.equal(hard.min_size_m, 0.005);
  assert.deepEqual(hard.b, { files: [], teams: [], classes: [], exclude_classes: [], systems: [], ids: [] }, "everything: an open selection");
  assert.equal(checks.checkTest(ducts, "itself", "hard", 0, defaults).b, null, "itself: no side B");
  assert.equal(checks.checkTest(ducts, "itself", "hard", 0, defaults).tolerance_m, 0, "0 mm deep is a tolerance");
  const near = checks.checkTest(ducts, beams, "clearance", 100, defaults);
  assert.equal(near.clearance_m, 0.1); assert.equal(near.tolerance_m, 0.01);
  assert.deepEqual(near.b.filter, { when: beams.when, invert: false });
  assert.equal(near.name, "Ducts vs Beam, 100 mm clearance");
  assert.equal(checks.checkTest(ducts, beams, "clearance", 0, defaults).clearance_m, 0.025, "no clearance: the default");
});

test("a side counts what a check can test (spaces have no body), and a run says it was a check", () => {
  assert.equal(checks.sideCount(p, ducts), 2);
  assert.equal(checks.sideCount(p, { ...beams, when: [{ facet: "storey", op: "is", values: ["Level 01"] }] }), 2, "the room is left out");
  const t = checks.checkTest(ducts, "everything", "hard", null, defaults);
  assert.equal(checks.checkOf([t]), "Ducts vs Everything");
  assert.equal(checks.checkOf([{ ...t, a: { ...t.a, filter: null } }]), null, "a test of whole models is no check on filters");
  assert.equal(checks.checkOf([t, t]), null); assert.equal(checks.checkOf(null), null);
});

test("the page shares its filters by name, with only their complete conditions, within what the server takes", () => {
  const shared = f.shareable([ducts, beams, { ...beams, id: "long", name: "x".repeat(300) }]);
  assert.deepEqual(shared[0], { id: "d", name: "Ducts", when: [ducts.when[0]], invert: false, on: true, origin: null });
  assert.equal(shared[1].name, "Beam"); assert.equal(shared[1].on, false);
  assert.equal(shared[2].name.length, 200, "a long name never refuses the chat turn");
});

// ---------------------------------------------------------------- the panel

const stub = (names) => `data:text/javascript;base64,${Buffer.from(names.map((n) => `export function ${n}(){return null;}`).join("\n")).toString("base64")}`;
const react = `data:text/javascript;base64,${Buffer.from("export const useState=(v)=>[typeof v==='function'?v():v,()=>{}];export const useMemo=(fn)=>fn();").toString("base64")}`;
const { FiltersPanel } = await import(await compiled("../src/FiltersPanel.tsx", { react, "react/jsx-runtime": import.meta.resolve("react/jsx-runtime"),
  "lucide-react": stub(["ArrowDown", "ArrowUp", "Check", "EyeOff", "Focus", "LocateFixed", "Palette", "Plus", "Radar", "Rows3", "Trash2", "X"]),
  "./filters": filters, "./checks": await compiled("../src/checks.ts", { "./filters": filters }) }));
/** The panel with its own components drawn (not the icons), so its buttons can be found and pressed. */
function draw(node) {
  if (Array.isArray(node)) return node.map(draw);
  if (!node || typeof node !== "object") return node;
  if (typeof node.type === "function" && /^[A-Z]/.test(node.type.name) && node.type.name !== "FiltersPanel") {
    const out = node.type(node.props);
    return out === null ? null : draw(out);
  }
  return node.props?.children === undefined ? node : { ...node, props: { ...node.props, children: draw(node.props.children) } };
}
function panel(rules, check, more = {}, onState = () => {}) {
  const state = { v: 1, rules, colours: true, greyRest: false, ...more };
  return draw(FiltersPanel({ index: p, loading: false, state, onState, draft: null, onDraft() {}, check }));
}
const all = (tree, predicate, out = []) => {
  if (!tree || typeof tree !== "object") return out;
  if (Array.isArray(tree)) { tree.forEach((t) => all(t, predicate, out)); return out; }
  if (predicate(tree)) out.push(tree);
  for (const c of [tree.props?.children].flat(Infinity)) all(c, predicate, out);
  return out;
};

test("The rest: show, grey or hide, one at a time", () => {
  const saved = [];
  const rest = (more) => find(panel([ducts], undefined, more, (st) => saved.push(st)), (n) => n.props?.role === "radiogroup" && n.props["aria-label"] === "The rest");
  const buttons = (g) => all(g, (n) => n.type === "button");
  assert.deepEqual(buttons(rest({})).map((b) => [b.props.children, b.props["aria-checked"]]), [["Show", true], ["Grey", false], ["Hide", false]]);
  assert.deepEqual(buttons(rest({ hideRest: true })).map((b) => b.props["aria-checked"]), [false, false, true]);
  buttons(rest({ greyRest: true }))[2].props.onClick();
  assert.deepEqual([saved[0].greyRest, saved[0].hideRest], [false, true], "hiding the rest stops greying it");
  buttons(rest({ hideRest: true }))[1].props.onClick();
  assert.deepEqual([saved[1].greyRest, saved[1].hideRest], [true, false]);
  buttons(rest({ hideRest: true }))[0].props.onClick();
  assert.deepEqual([saved[2].greyRest, saved[2].hideRest], [false, false]);
});

test("What do these hit? checks a filter against everything; off while a check runs, or for nothing or everything", () => {
  const ran = [];
  const check = { defaults, busy: false, onCheck: (t) => ran.push(t) };
  const tree = panel([ducts, everything, { ...beams, id: "none", when: [{ facet: "class", op: "is", values: ["IfcPipeSegment"] }] }], check);
  const buttons = all(tree, (n) => n.type === "button" && n.props["aria-label"] === "What do these hit?");
  assert.equal(buttons.length, 3);
  assert.deepEqual(buttons.map((b) => !!b.props.disabled), [false, true, true]);
  assert.match(buttons[1].props["data-tip"], /finds everything/);
  assert.match(buttons[2].props["data-tip"], /finds nothing/);
  buttons[0].props.onClick();
  assert.equal(ran.length, 1);
  assert.equal(ran[0].name, "Ducts vs Everything"); assert.equal(ran[0].id, "");
  const busy = all(panel([ducts], { ...check, busy: true }), (n) => n.type === "button" && n.props["aria-label"] === "What do these hit?");
  assert.equal(busy[0].props.disabled, true, "one check at a time");
  const early = all(panel([ducts], { ...check, defaults: null }), (n) => n.type === "button" && n.props["aria-label"] === "What do these hit?");
  assert.equal(early[0].props.disabled, true, "not before the models are read");
});

test("Check clashes: the first filter against everything until another side is chosen, and what the clashes do", () => {
  const ran = [];
  const tree = panel([ducts, beams], { defaults, busy: false, onCheck: (t) => ran.push(t) });
  const block = find(tree, (n) => n.type === "details" && n.props.className === "fcheck");
  assert.ok(block && hasText(block, "Check clashes"));
  const sideB = find(block, (n) => n.type === "select" && n.props["aria-label"] === "Side B");
  const options = all(sideB, (n) => n.type === "option").map((o) => o.props.value);
  assert.deepEqual(options, ["everything", "itself", "b"], "side B: everything, itself or another filter, never the same one");
  assert.ok(hasText(block, "The clashes replace the open list; Detect again repeats this check."));
  find(block, (n) => n.type === "button" && hasText(n, "Check")).props.onClick();
  assert.equal(ran[0].name, "Ducts vs Everything");
});

// ---------------------------------------------------------------- the page

const ran = (id, tests) => ({ type: "done", report: { id, title: "Coordination", clashes: [], origin: "sightline", sources: ["model.ifc"] },
  coverage: [], diff: { new: [], resolved: [], no_longer_checked: [], first: true }, elements: 2, seconds: 1, tests });

test("a check from the Filters panel replaces the open list; Detect again repeats it; Check the open models runs every test", async () => {
  const sent = [];
  const host = await appHost({
    initial: { sceneFiles: ["model.ifc"], filtersOpen: true, filterState: { v: 1, colours: true, greyRest: false, rules: [ducts, beams] },
      report: { id: "report", title: "Run", clashes: [], origin: "sightline", sources: ["model.ifc"] } },
    api: { detectTests: async () => ({ tests: [], teams: {}, elements: 2, rules: {}, check: defaults }), facets: async () => index,
      detect: async (_sid, tests) => { sent.push(tests); return ran(`r${sent.length}`, tests && tests.map((t) => ({ ...t, id: "filter:abc" }))); } } });
  await host.settle();
  const fp = host.component("FiltersPanel");
  assert.deepEqual(fp.props.check.defaults, defaults);
  assert.equal(fp.props.check.busy, false);
  fp.props.check.onCheck(checks.checkTest(ducts, "everything", "hard", null, defaults));
  await host.settle();
  assert.equal(host.state.filtersOpen, false, "the sheet makes way for the clashes");
  assert.equal(sent.length, 1); assert.equal(sent[0].length, 1); assert.equal(sent[0][0].name, "Ducts vs Everything");
  assert.equal(host.state.report.id, "r1", "the check's clashes are the open list");
  assert.equal(host.state.detection.tests[0].id, "filter:abc", "the run keeps what it checked");
  const summary = () => find(host.component("ReportList").props.insights, (n) => n.type?.name === "DetectSummary");
  summary().props.onAgain();
  await host.settle();
  assert.equal(sent[1][0].name, "Ducts vs Everything", "Detect again repeats the check");
  summary().props.onWhole();
  await host.settle();
  assert.equal(sent[2], null, "the open models: the server's tests");
  summary().props.onAgain();
  await host.settle();
  assert.equal(sent[3], null, "and Detect again then repeats the whole check");
});

test("chat and an agent see the page's filters by name; Detect again repeats a check chat ran", async () => {
  const sent = [];
  const host = await appHost({
    initial: { sceneFiles: ["model.ifc"], filterState: { v: 1, colours: true, greyRest: false, rules: [ducts] },
      report: { id: "report", title: "Run", clashes: [], origin: "sightline", sources: ["model.ifc"] } },
    api: { detect: async (_sid, tests) => { sent.push(tests); return ran("again", tests); },
      report: async (id) => ({ id, title: "Coordination · Ducts vs Everything", clashes: [], origin: "sightline", sources: ["model.ifc"] }) } });
  await host.settle();
  const context = host.component("ChatPanel").props.context();
  assert.deepEqual(context.filters, [{ id: "d", name: "Ducts", when: [ducts.when[0]], invert: false, on: true, origin: null }]);
  const test0 = { ...checks.checkTest(ducts, "everything", "hard", null, defaults), id: "filter:abc" };
  host.chat({ type: "ui", action: "open_report", report_id: "chat-run", detection: { ...ran("chat-run", [test0]), report: undefined } });
  await host.settle();
  assert.equal(host.state.report.id, "chat-run");
  find(host.component("ReportList").props.insights, (n) => n.type?.name === "DetectSummary").props.onAgain();
  await host.settle();
  assert.deepEqual(sent, [[test0]], "the same check, by its id");
});
