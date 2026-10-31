import assert from "node:assert/strict";
import test from "node:test";
import { compiled } from "./app-host.mjs";

const f = await import(await compiled("../src/filters.ts", {}));

/** A small index as the server sends it (facets.py): five elements over two files. */
const index = {
  revision: 0, files: ["S.ifc", "M.ifc"], elements: ["beam", "duct1", "duct2", "pipe", "wall"], file: [0, 1, 1, 1, 0],
  facets: [
    { key: "file", kind: "text", values: ["M.ifc", "S.ifc"], items: [[1, 2, 3], [0, 4]] },
    { key: "class", kind: "text", values: ["IfcBeam", "IfcDuctSegment", "IfcPipeSegment", "IfcWall"], items: [[0], [1, 2], [3], [4]] },
    { key: "storey", kind: "text", values: ["Level 01", "Level 02"], items: [[0, 1, 4], [2, 3]] },
    { key: "pset:Model data/System", kind: "text", values: ["Cold water", "Supply air"], items: [[3], [1, 2]] },
    { key: "pset:Model data/Length", kind: "number", unit: "m", values: [1.5, 3.6, 6], items: [[3], [1, 2], [0]] },
    { key: "pset:Pset_WallCommon/IsExternal", kind: "bool", values: [true], items: [[4]] },
    { key: "attr:Name", kind: "text", values: ["Supply air main L02", "UB beam"], items: [[1, 2], [0]] },
  ],
};
const p = f.prepare(index);
const ids = (set) => [...set].map((i) => index.elements[i]).sort();
const rule = (over) => ({ id: over.id ?? "r", name: "", on: true, when: [], action: "colour", ...over });

test("conditions find as the server's facets.matching does", () => {
  assert.deepEqual(ids(f.matching(p, { facet: "class", op: "is", values: ["ifcductsegment"] })), ["duct1", "duct2"]);
  assert.deepEqual(ids(f.matching(p, { facet: "class", op: "isNot", values: ["IfcDuctSegment"] })), ["beam", "pipe", "wall"]);
  assert.deepEqual(ids(f.matching(p, { facet: "attr:Name", op: "contains", values: ["main"] })), ["duct1", "duct2"]);
  assert.deepEqual(ids(f.matching(p, { facet: "pset:Model data/System", op: "has" })), ["duct1", "duct2", "pipe"]);
  assert.deepEqual(ids(f.matching(p, { facet: "pset:Model data/System", op: "missing" })), ["beam", "wall"]);
  assert.deepEqual(ids(f.matching(p, { facet: "pset:Model data/Length", op: "between", min: 2, max: 6 })), ["beam", "duct1", "duct2"]);
  assert.deepEqual(ids(f.matching(p, { facet: "pset:Model data/Length", op: "lt", max: 2 })), ["pipe"]);
  assert.deepEqual(ids(f.matching(p, { facet: "pset:Model data/Length", op: "gt", min: 5 })), ["beam"]);
  assert.deepEqual(ids(f.matching(p, { facet: "pset:Model data/Length", op: "is", values: ["3.6"] })), ["duct1", "duct2"]);
  assert.deepEqual(ids(f.matching(p, { facet: "pset:Pset_WallCommon/IsExternal", op: "is", values: [true] })), ["wall"]);
  assert.deepEqual(ids(f.matching(p, { facet: "nothing", op: "is", values: ["x"] })), []);
});

test("every condition holds, values in one condition are any of them, an unfinished one is left out, invert flips", () => {
  const ducts = { when: [{ facet: "class", op: "is", values: ["IfcDuctSegment", "IfcPipeSegment"] }, { facet: "storey", op: "is", values: ["Level 02"] }] };
  assert.deepEqual(ids(f.found(p, ducts)), ["duct2", "pipe"]);
  assert.deepEqual(ids(f.found(p, { ...ducts, invert: true })), ["beam", "duct1", "wall"]);
  assert.deepEqual(ids(f.found(p, { when: [...ducts.when, { facet: "", op: "is", values: [] }, { facet: "class", op: "is", values: [] }] })), ["duct2", "pipe"]);
  assert.equal(f.found(p, { when: [] }).size, 5, "no condition: everything");
});

test("hide, isolate and colour together; the top colour wins; isolates add up; grey the rest", () => {
  const view = f.evaluate({ v: 1, colours: true, greyRest: true, rules: [
    rule({ id: "a", when: [{ facet: "storey", op: "is", values: ["Level 02"] }], colour: "#318181" }),
    rule({ id: "b", when: [{ facet: "class", op: "is", values: ["IfcDuctSegment"] }], colour: "#8e234e" }),
    rule({ id: "c", action: "hide", when: [{ facet: "class", op: "is", values: ["IfcWall"] }] }),
    rule({ id: "d", action: "isolate", when: [{ facet: "file", op: "is", values: ["M.ifc"] }] }),
    rule({ id: "e", action: "isolate", when: [{ facet: "class", op: "is", values: ["IfcBeam"] }] }),
    rule({ id: "off", on: false, action: "hide", when: [{ facet: "class", op: "is", values: ["IfcBeam"] }] }),
  ] }, p);
  assert.deepEqual([...view.hide], ["wall"]);
  assert.deepEqual([...view.only].sort(), ["beam", "duct1", "duct2", "pipe"]);
  assert.deepEqual(Object.fromEntries(view.paint), { duct2: "#318181", pipe: "#318181", duct1: "#8e234e" });
  assert.equal(view.greyRest, true);
  const off = f.evaluate({ v: 1, colours: false, greyRest: true, rules: [rule({ when: [], colour: "#318181" })] }, p);
  assert.equal(off.paint, null, "Show colours off: no colour"); assert.equal(off.greyRest, false, "nothing coloured: nothing greyed");
  assert.deepEqual(f.evaluate(f.EMPTY, null), { hide: null, only: null, paint: null, greyRest: false });
});

test("hide the rest: only what a filter colours or isolates stays, in its colour; hide filters still hide within it", () => {
  const level2 = rule({ id: "a", when: [{ facet: "storey", op: "is", values: ["Level 02"] }], colour: "#318181" });
  const state = (rules, more = {}) => ({ v: 1, colours: true, greyRest: false, hideRest: true, rules, ...more });
  let view = f.evaluate(state([level2]), p);
  assert.deepEqual([...view.only].sort(), ["duct2", "pipe"]);
  assert.deepEqual(Object.fromEntries(view.paint), { duct2: "#318181", pipe: "#318181" }, "kept in their colour");
  assert.equal(view.greyRest, false);
  const beams = rule({ id: "e", action: "isolate", when: [{ facet: "class", op: "is", values: ["IfcBeam"] }] });
  assert.deepEqual([...f.evaluate(state([level2, beams]), p).only].sort(), ["beam", "duct2", "pipe"], "coloured and isolated both stay");
  view = f.evaluate(state([level2, rule({ id: "h", action: "hide", when: [{ facet: "class", op: "is", values: ["IfcPipeSegment"] }] })]), p);
  assert.deepEqual([...view.hide], ["pipe"], "a hide filter still hides what another keeps");
  const bySystem = rule({ id: "s", action: "byValue", by: { facet: "pset:Model data/System", off: ["Cold water"] } });
  assert.deepEqual([...f.evaluate(state([bySystem]), p).only].sort(), ["duct1", "duct2"], "a value ticked off is not kept");
  assert.equal(f.evaluate(state([rule({ id: "h", action: "hide", when: [] })]), p).only, null, "nothing coloured or isolated: nothing to keep");
  assert.equal(f.evaluate(state([level2], { colours: false }), p).only, null, "Show colours off: colour filters keep nothing");
  assert.deepEqual([...f.evaluate(state([level2, beams], { colours: false }), p).only], ["beam"], "isolates still do");
  assert.equal(f.evaluate(state([level2], { greyRest: true }), p).greyRest, false, "hidden, not greyed");
});

test("colour by value: a colour per value, its own if chosen, the palette's by the value's place, ticked-off values left", () => {
  const r = rule({ action: "byValue", by: { facet: "pset:Model data/System", colours: { "Cold water": "#123456" }, off: [] } });
  const view = f.evaluate({ v: 1, colours: true, greyRest: false, rules: [r] }, p);
  assert.deepEqual(Object.fromEntries(view.paint), { pipe: "#123456", duct1: f.PALETTE[1], duct2: f.PALETTE[1] });
  assert.equal(f.count(p, r), 3, "colour by value counts what it colours, not everything");
  assert.equal(f.count(p, { ...r, by: { ...r.by, off: ["Supply air"] } }), 1);
  const less = f.evaluate({ v: 1, colours: true, greyRest: false, rules: [{ ...r, by: { ...r.by, off: ["Supply air"] } }] }, p);
  assert.deepEqual(Object.fromEntries(less.paint), { pipe: "#123456" });
  // A lower rule colours what an unticked value leaves.
  const two = f.evaluate({ v: 1, colours: true, greyRest: false, rules: [{ ...r, by: { ...r.by, off: ["Supply air"] } },
    rule({ id: "x", when: [{ facet: "class", op: "is", values: ["IfcDuctSegment"] }], colour: "#e2d136" })] }, p);
  assert.equal(two.paint.get("duct1"), "#e2d136");
});

test("counts among what the other conditions find, names, sets and a new filter's colour", () => {
  const within = f.found(p, { when: [{ facet: "storey", op: "is", values: ["Level 02"] }] });
  assert.deepEqual(f.valueCounts(p, "class", within), [{ value: "IfcDuctSegment", count: 1 }, { value: "IfcPipeSegment", count: 1 }]);
  assert.deepEqual(f.describe("pset:Model data/System"), { set: "Model data", name: "System" });
  assert.deepEqual(f.describe("pset:Pset_X/Connection/Torque"), { set: "Pset_X", name: "Connection › Torque" });
  assert.deepEqual(f.describe("storey"), { set: "Element", name: "Floor" });
  assert.deepEqual(f.describe("group:IfcDistributionSystem"), { set: "Systems and groups", name: "Distribution system" });
  assert.deepEqual(f.describe("attr:PredefinedType"), { set: "Attributes", name: "Predefined type" });
  assert.deepEqual(f.sets(p).map((s) => s.set), ["Element", "Model data", "Pset_WallCommon", "Attributes"]);
  assert.equal(f.nameFor([{ facet: "class", op: "is", values: ["IfcDuctSegment"] }, { facet: "storey", op: "is", values: ["Level 02"] }]),
    "DuctSegment · Level 02");
  assert.equal(f.nameFor([], "pset:Model data/System"), "Everything by System");
  assert.equal(f.shownValue(0.1025, "m"), "102.5 mm");
  assert.equal(f.nextColour([rule({ id: "a", colour: f.PALETTE[0] })]), f.PALETTE[1]);
  assert.equal(f.nextColour([rule({ id: "a", colour: f.PALETTE[0] })], "a"), f.PALETTE[0], "its own colour is free to keep");
});

test("the key lists the colours on screen, top filter first, and none for what a filter hides", () => {
  const byClass = rule({ id: "c", action: "byValue", by: { facet: "class" } });
  const state = { v: 1, colours: true, greyRest: false, rules: [rule({ id: "a", name: "Level 02", when: [{ facet: "storey", op: "is", values: ["Level 02"] }], colour: "#123456" }),
    byClass, rule({ id: "h", action: "hide", when: [{ facet: "class", op: "is", values: ["IfcWall"] }] })] };
  assert.deepEqual(f.legend(state, p).map((k) => k.label), ["Level 02", "Beam", "DuctSegment"],
    "the pipe is Level 02's colour already; the wall is hidden");
  assert.deepEqual(f.legend({ ...state, colours: false }, p), []);
});

test("applying a filter is adding it, switching it on or changing it; not switching off, deleting, renaming or reordering", () => {
  const a = rule({ id: "a", when: [{ facet: "class", op: "is", values: ["IfcBeam"] }] }), b = rule({ id: "b", on: false, action: "hide" });
  const s0 = { v: 1, colours: true, greyRest: false, rules: [a, b] };
  const ids = (prev, next) => f.applied(prev, next).map((r) => r.id);
  assert.deepEqual(ids({ ...s0, rules: [] }, s0), ["a"], "added (an added filter that is off is not applied)");
  assert.deepEqual(ids(s0, { ...s0, rules: [a, { ...b, on: true }] }), ["b"], "switched on");
  assert.deepEqual(ids(s0, { ...s0, rules: [{ ...a, when: [{ facet: "class", op: "is", values: ["IfcWall"] }] }, b] }), ["a"], "changed");
  assert.deepEqual(ids(s0, { ...s0, rules: [{ ...a, colour: "#123456" }, b] }), ["a"], "a new colour");
  assert.deepEqual(ids(s0, { ...s0, rules: [{ ...a, on: false }, b] }), [], "switched off");
  assert.deepEqual(ids(s0, { ...s0, rules: [b, { ...a, name: "Beams" }] }), [], "renamed and reordered");
  assert.deepEqual(ids(s0, { ...s0, colours: false }), []);
  const paused = { ...s0, rules: [{ ...a, on: false, paused: true }] };
  assert.deepEqual(ids(paused, { ...s0, rules: [a] }), [], "chat giving a paused filter back");
  assert.deepEqual(ids(s0, { ...s0, rules: [a, { ...b, on: true }], hideRest: true }), ["a", "b"], "hiding the rest applies every filter that is on");
  assert.deepEqual(ids({ ...s0, hideRest: true }, s0), [], "showing the rest again applies none");
  assert.deepEqual(ids(s0, { ...s0, greyRest: true }), [], "nor does greying it");
});

test("applying frames what the filters act on that is on screen; filters that only hide frame what is left", () => {
  const all = () => true, notWall = (g) => g !== "wall";
  const ducts = rule({ id: "d", when: [{ facet: "class", op: "is", values: ["IfcDuctSegment"] }] });
  assert.deepEqual(f.zoomTarget(p, [ducts], all).sort(), ["duct1", "duct2"]);
  assert.deepEqual(f.zoomTarget(p, [rule({ id: "h", action: "hide", when: [{ facet: "class", op: "is", values: ["IfcWall"] }] })], notWall).sort(),
    ["beam", "duct1", "duct2", "pipe"]);
  const bySystem = rule({ id: "s", action: "byValue", by: { facet: "pset:Model data/System", off: ["Cold water"] } });
  assert.deepEqual(f.zoomTarget(p, [bySystem], all).sort(), ["duct1", "duct2"], "colour by value: what it colours");
  assert.deepEqual(f.zoomTarget(p, [ducts], () => false), [], "nothing on screen: nothing to frame");
});

test("a kept or saved filter state reads back, and anything unreadable gives way to none", () => {
  const good = { v: 1, colours: false, greyRest: true, rules: [rule({ id: "a" }), { id: 3 }, rule({ id: "b", action: "explode" })] };
  assert.deepEqual(f.migrate(good), { v: 1, colours: false, greyRest: true, hideRest: false, rules: [rule({ id: "a" })] });
  assert.deepEqual(f.migrate({ ...good, hideRest: true }), { v: 1, colours: false, greyRest: false, hideRest: true, rules: [rule({ id: "a" })] },
    "grey and hide are one or the other: hide is kept");
  for (const bad of [null, "x", { v: 2, rules: [] }, { v: 1 }]) assert.deepEqual(f.migrate(bad), f.EMPTY);
});

test("the palette's twenty colours and Other keep clear of every colour another role uses, and of each other", () => {
  assert.equal(f.PALETTE.length, 20);
  for (const c of [...f.PALETTE, f.OTHER]) {
    for (const r of f.RESERVED) assert.ok(f.deltaE(c, r) >= 20, `${c} too close to ${r} (${f.deltaE(c, r).toFixed(1)})`);
    for (const o of [...f.PALETTE, f.OTHER]) if (o !== c) assert.ok(f.deltaE(c, o) >= 15, `${c} too close to ${o}`);
  }
});

test("past twenty values, colour by value shares one Other colour, and the key says so", () => {
  const n = 23, values = Array.from({ length: n }, (_, i) => `V${String(i).padStart(2, "0")}`);
  const many = f.prepare({ revision: 0, files: ["a"], elements: values.map((v) => `e${v}`), file: values.map(() => 0),
    facets: [{ key: "pset:P/X", kind: "text", values, items: values.map((_, i) => [i]) }] });
  const r = rule({ action: "byValue", by: { facet: "pset:P/X" } });
  const colours = f.valueColours(r, many.byKey.get("pset:P/X"), f.found(many, r));
  assert.deepEqual([...colours.values()].slice(0, 20), f.PALETTE);
  assert.deepEqual([...colours.values()].slice(20), [f.OTHER, f.OTHER, f.OTHER]);
  const key = f.legend({ v: 1, colours: true, greyRest: false, rules: [r] }, many, 30);
  assert.equal(key.length, 21);
  assert.deepEqual(key[20], { colour: f.OTHER, label: "Other (3 values)" });
  // Ticking a value off moves no other value's colour.
  const off = f.valueColours({ ...r, by: { ...r.by, off: ["V00"] } }, many.byKey.get("pset:P/X"), f.found(many, r));
  assert.equal(off.get("V01"), f.PALETTE[1]);
});

test("a By value filter with no property picked takes its last condition's, so what shows is what is kept", () => {
  const r = rule({ action: "byValue", when: [{ facet: "class", op: "is", values: ["IfcDuctSegment"] },
    { facet: "pset:Model data/System", op: "has" }, { facet: "", op: "is", values: [] }] });
  assert.deepEqual(f.withBy(r).by, { facet: "pset:Model data/System" });
  assert.equal(f.withBy({ ...r, by: { facet: "class" } }).by.facet, "class", "a picked property stays");
  assert.equal(f.withBy({ ...r, when: [] }).by, undefined, "nothing to take");
  assert.equal(f.count(p, f.withBy(r)), 2, "the two ducts, coloured by their system");
});
