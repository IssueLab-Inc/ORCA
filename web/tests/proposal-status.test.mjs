import assert from "node:assert/strict";
import test from "node:test";
import { appHost, compiled, find, hasText, option } from "./app-host.mjs";

/** A clash's proposal on its row (owner request, Nov 1: "something needs to show on the clash that a proposal is being
 * generated and that it's ready when it is with a link to bring up the proposal section to view if its not"): it runs
 * on for its own clash while others are opened, one at a time, and a finished one is kept for the clash. */

const url = (js) => `data:text/javascript;base64,${Buffer.from(js).toString("base64")}`;
const stub = (names) => url(names.map((n) => `export function ${n}(){return null;}`).join("\n"));
const react = url("export const useState=(v)=>[typeof v==='function'?v():v,()=>{}];export const useMemo=(fn)=>fn();"
  + "export const useEffect=()=>{};export const useRef=(v)=>({current:v ?? null});");
const TRIAGE = url(`export const TRIAGE={${["real_clash", "modelling_error", "by_design", "non_physical", "unknown"]
  .map((k) => `${k}:{label:"${k}",cls:"",tip:"",colour:"",long:"${k}"}`).join(",")}};`);
const { ReportList } = await import(await compiled("../src/ReportList.tsx", { react, "react/jsx-runtime": import.meta.resolve("react/jsx-runtime"),
  "lucide-react": stub(["CircleCheck", "Eye", "Focus", "Network", "Search", "Sparkles", "Wand2", "X"]), "./api": url("export const api={imageUrl:()=>''};"),
  "./ClashPanel": stub(["ClashThumb"]), "./Triage": TRIAGE, "./noClash": await compiled("../src/noClash.ts", {}),
  "./aiNames": await compiled("../src/aiNames.ts", {}) }));

const clash = (id, number) => ({ id, number, name: `Clash ${number}`, title: null, test: "MEP vs Structure",
  a: { name: "A", global_id: `${id}-a` }, b: { name: "B", global_id: `${id}-b` }, images: [], guid: id, test_type: "hard",
  tolerance_m: 0.001, status: "active", distance_m: -0.3, point: null, grid: null, source: "sightline", ref: null });
const C1 = clash("c1", 1), C2 = clash("c2", 2), C3 = clash("c3", 3);
const report = { id: "r", title: "Coordination", sources: [], origin: "sightline", clashes: [C1, C2, C3] };
const matches = Object.fromEntries(report.clashes.map((c) => [c.id, { a: c.a.global_id, b: c.b.global_id, how: ["globalid", "globalid"] }]));

function draw(node) {
  if (Array.isArray(node)) return node.map(draw);
  if (!node || typeof node !== "object") return node;
  if (typeof node.type === "function" && node.type.name === "RowActions") { const out = node.type(node.props); return out === null ? null : draw(out); }
  return node.props?.children === undefined ? node : { ...node, props: { ...node.props, children: draw(node.props.children) } };
}
const row = (tree, id) => find(tree, (n) => n.props?.["data-clash"] === id);
const labels = (n) => { const out = []; const walk = (x) => { if (!x || typeof x !== "object") return; if (Array.isArray(x)) { x.forEach(walk); return; }
  if (x.type === "button" && x.props["aria-label"]) out.push(x.props["aria-label"]); [x.props?.children].flat(Infinity).forEach(walk); }; walk(n); return out; };

test("a row says its proposal: Proposing…, then how many fixes are ready, with View when it is not on screen", () => {
  const viewed = [];
  const list = (selected, panel) => draw(ReportList({ report, matches, selected, onSelect() {}, onImage() {}, fixes: {}, reviewed: {},
    checked: new Set(), onCheck() {}, onFixChecked() {}, insights: null, busy: true, triage: {}, triageFilter: null, onPropose() {},
    onSetAside() {}, onFocus() {}, proposing: "c1", ready: { c2: 2, c3: 0 }, panel, onViewProposal: (c) => viewed.push(c.id) }));
  const tree = list("c2", true);
  assert.ok(hasText(row(tree, "c1"), "Proposing…"));
  assert.ok(hasText(row(tree, "c2"), "2 fixes ready") && hasText(row(tree, "c3"), "No fix found"));
  assert.ok(labels(row(tree, "c1")).includes("View the proposal for #1 Clash 1"), "running, not on screen: View");
  assert.ok(!labels(row(tree, "c2")).includes("View the proposal for #2 Clash 2"), "selected with the Clash panel in front: no View");
  assert.ok(labels(list("c2", false)).includes("View the proposal for #2 Clash 2"), "another panel in front: View");
  assert.ok(labels(row(tree, "c3")).includes("View the fixes for #3 Clash 3"), "the hover actions: View instead of Propose");
  assert.ok(!labels(row(tree, "c2")).includes("View the fixes for #2 Clash 2"), "not when its proposal is on screen");
  assert.ok(!labels(tree).some((l) => l.startsWith("Propose fixes")), "one proposal at a time: no Propose while one runs");
  find(row(tree, "c3"), (n) => n.type === "button" && n.props["aria-label"] === "View the proposal for #3 Clash 3").props.onClick();
  assert.deepEqual(viewed, ["c3"]);
});

test("on the page: a proposal runs on for its clash while another is opened, is kept, and View brings it up", async () => {
  const host = await appHost({ initial: { report, matches, clash: C1, a: "c1-a", b: "c1-b", sceneFiles: ["m.ifc"] },
    api: { match: async () => matches } });
  await host.settle();
  const list = () => host.component("ReportList").props;
  list().onPropose(C1);
  await host.settle();
  assert.equal(host.requests.length, 1);
  assert.equal(list().proposing, "c1", "its row says Proposing…");
  const run = host.requests[0];
  run.onEvent({ type: "thinking", round: 1 });
  // Another clash opened mid-run: its panel shows its own (nothing), the run goes on for #1.
  list().onSelect(C2); await host.settle();
  assert.equal(host.state.clash.id, "c2");
  assert.equal(host.state.proposal, null); assert.equal(host.state.progress, null);
  run.onEvent({ type: "ideas", count: 1, seconds: 1, understanding: "The duct runs into the beam." });
  host.render();
  assert.equal(host.state.proposal, null, "#1's run does not spill onto #2's panel");
  assert.equal(host.refs.runState.current.proposal.understanding, "The duct runs into the beam.");
  // One at a time: a second proposal waits.
  list().onPropose(C2); await host.settle();
  assert.equal(host.requests.length, 1);
  // It lands for #1, while #2 is on screen.
  run.resolve({ understanding: "The duct runs into the beam.", options: [option, { ...option, title: "Second" }], attempts: [] });
  await host.settle();
  assert.equal(host.state.proposal, null);
  assert.equal(list().proposing, null);
  assert.deepEqual(list().ready, { c1: 2 }, "its row says 2 fixes ready");
  // View: #1 on screen, the Clash panel in front, its options back, with no new request.
  host.state.tab = "chat"; host.render();
  list().onViewProposal(C1); await host.settle();
  assert.equal(host.state.clash.id, "c1"); assert.equal(host.state.tab, "clash");
  assert.equal(host.state.proposal.options.length, 2); assert.equal(host.state.chosen, 0);
  assert.equal(host.requests.length, 1);
  host.unmount();
});
