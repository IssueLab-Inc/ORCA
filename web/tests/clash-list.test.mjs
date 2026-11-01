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
const { ReportList } = await import(await compiled("../src/ReportList.tsx", { react, "react/jsx-runtime": import.meta.resolve("react/jsx-runtime"),
  "lucide-react": stub(["CircleCheck", "Search", "Sparkles", "Wand2", "X"]), "./api": url("export const api={imageUrl:()=>''};"),
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
