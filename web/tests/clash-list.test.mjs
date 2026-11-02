import assert from "node:assert/strict";
import test from "node:test";
import { compiled, find } from "./app-host.mjs";

/** The clash list under a triage verdict filter: a fixed clash keeps its verdict when it is selected (owner report,
 * Nov 1: "when i click on a fixed clash, the item disappears from the list"), and the row on screen never leaves the
 * list from under the click. */

const clash = (id, number) => ({ id, number, name: id, title: null, test: "Structure (within)", a: { name: "A", global_id: `${id}-a` },
  b: { name: "B", global_id: `${id}-b` }, images: [], guid: id, test_type: "hard", tolerance_m: 0.001, status: "active",
  distance_m: -0.4, point: null, grid: null, source: "sightline", ref: null });
const FIXED = clash("c17", 17), OPEN = clash("c3", 3);
const report = { id: "r", title: "Coordination", sources: ["model.ifc"], origin: "sightline", clashes: [OPEN, FIXED] };
const matches = { c17: { a: "c17-a", b: "c17-b", how: [] }, c3: { a: "c3-a", b: "c3-b", how: [] } };
const real = { verdict: "real_clash", source: "model", understanding: "Wall into footing." };

const { shownVerdicts } = await import(await compiled("../src/noClash.ts", {}));
const NOW = { matched: true, physical: true, distance_m: null };   // the live measure: no overlap here now

test("a fixed clash keeps its verdict when selected; an unfixed one with no overlap here is still read as not a clash", () => {
  const triage = { c17: real, c3: real };
  const fixed = shownVerdicts(report.clashes, triage, {}, matches, "c17", NOW, { c17: "Move the wall" });
  assert.equal(fixed.c17.verdict, "real_clash", "the fix is why the overlap went: the verdict stays");
  const before = shownVerdicts(report.clashes, triage, {}, matches, "c17", NOW, {});
  assert.equal(before.c17.verdict, "by_design", "without the fix (the old reading): no overlap here, not a clash");
  const open = shownVerdicts(report.clashes, triage, {}, matches, "c3", NOW, { c17: "Move the wall" });
  assert.deepEqual([open.c3.verdict, open.c3.basis, open.c17.verdict], ["by_design", "no_overlap", "real_clash"]);
  const marked = shownVerdicts(report.clashes, triage, { c17: { kind: "by_design", note: "meant to meet" } }, matches, null, null,
    { c17: "Move the wall" });
  assert.equal(marked.c17.basis, "reviewed", "a mark still applies to a fixed clash");
});

// ---------------------------------------------------------------- the list itself

const url = (js) => `data:text/javascript;base64,${Buffer.from(js).toString("base64")}`;
const stub = (names) => url(names.map((n) => `export function ${n}(){return null;}`).join("\n"));
const react = url("export const useState=(v)=>[typeof v==='function'?v():v,()=>{}];export const useMemo=(fn)=>fn();"
  + "export const useEffect=()=>{};export const useRef=(v)=>({current:v ?? null});");
const TRIAGE = url(`export const TRIAGE={${["real_clash", "modelling_error", "by_design", "non_physical", "unknown"]
  .map((k) => `${k}:{label:"${k}",cls:"",tip:"",colour:"",long:"${k}"}`).join(",")}};`);
const { ReportList, rowWindow, FIRST_ROWS, OVERSCAN } = await import(await compiled("../src/ReportList.tsx", { react, "react/jsx-runtime": import.meta.resolve("react/jsx-runtime"),
  "lucide-react": stub(["CircleCheck", "Eye", "Focus", "Network", "Search", "Sparkles", "Wand2", "X"]), "./api": url("export const api={imageUrl:()=>''};"),
  "./ClashPanel": stub(["ClashThumb"]), "./Triage": TRIAGE, "./noClash": await compiled("../src/noClash.ts", {}),
  "./aiNames": await compiled("../src/aiNames.ts", {}) }));

function rows(selected) {
  const tree = ReportList({ report, matches: null, selected, onSelect() {}, onImage() {}, fixes: {}, reviewed: {}, checked: new Set(),
    onCheck() {}, onFixChecked() {}, insights: null, busy: false, triage: { c17: { verdict: "by_design", source: "rule" }, c3: real },
    triageFilter: "real_clash" });
  const out = [];
  const walk = (n) => {
    if (!n || typeof n !== "object") return;
    if (Array.isArray(n)) { n.forEach(walk); return; }
    if (n.props?.["data-clash"]) out.push(n.props["data-clash"]);
    [n.props?.children].flat(Infinity).forEach(walk);
  };
  walk(tree);
  return out;
}

test("under a verdict filter the selected row stays, though its shown verdict changed; the others are filtered", () => {
  assert.deepEqual(rows(null), ["c3"], "c17 reads by design now: the real filter leaves it out");
  assert.deepEqual(rows("c17"), ["c3", "c17"], "selected, it stays");
  assert.ok(find, "app-host helpers load");
});

// ---------------------------------------------------------------- only the rows on screen are drawn

test("a group draws the rows in view and a few either side; one off screen draws none", () => {
  // 2,471 rows of 40 px; 600 px of the list on screen, 4,000 px down the group.
  assert.deepEqual(rowWindow(4000, 4600, 2471, 40), [100 - OVERSCAN, 115 + OVERSCAN]);
  assert.deepEqual(rowWindow(-200, 400, 2471, 40), [0, 10 + OVERSCAN], "the group starts part way down the screen");
  assert.deepEqual(rowWindow(98000, 98600, 2471, 40), [2450 - OVERSCAN, 2471], "its end");
  assert.deepEqual(rowWindow(200000, 200600, 2471, 40), [0, 0], "scrolled past: nothing");
  assert.deepEqual(rowWindow(-9000, -8400, 2471, 40), [0, 0], "far below the screen: nothing");
  assert.deepEqual(rowWindow(0, 600, 0, 40), [0, 0]);
  assert.deepEqual(rowWindow(0, 600, 10, 0), [0, 0], "not measured: no division by nothing");
});

test("a long list draws its first rows until measured, and keeps its full height with padding", () => {
  const many = Array.from({ length: 2471 }, (_, i) => clash(`m${i}`, i + 1));
  const tree = ReportList({ report: { ...report, clashes: many }, matches: null, selected: null, onSelect() {}, onImage() {}, fixes: {},
    reviewed: {}, checked: new Set(), onCheck() {}, onFixChecked() {}, insights: null, busy: false, triage: {}, triageFilter: null });
  const ids = [];
  const walk = (n) => {
    if (!n || typeof n !== "object") return;
    if (Array.isArray(n)) { n.forEach(walk); return; }
    if (n.props?.["data-clash"]) ids.push(n.props["data-clash"]);
    [n.props?.children].flat(Infinity).forEach(walk);
  };
  walk(tree);
  assert.equal(ids.length, FIRST_ROWS, "not 2,471 rows: every title, thumbnail and click re-rendered them all");
  assert.equal(ids[0], "m0");
  const body = find(tree, (n) => n.props?.["data-rows"] === "Structure (within)");
  assert.equal(body.props["data-count"], 2471);
  assert.deepEqual(body.props.style, { paddingTop: 0, paddingBottom: (2471 - FIRST_ROWS) * 40 }, "the rest of the group's height");
});
