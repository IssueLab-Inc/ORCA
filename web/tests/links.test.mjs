import assert from "node:assert/strict";
import test from "node:test";
import { compiled } from "./app-host.mjs";

const links = await import(await compiled("../src/links.ts", {}));

// PL-302 as the cell has it: segment 1 - bend 1 - segment 2 - bend 2 - segment 3 - bend 3 - segment 4 - FRL-302, with
// segment 3 resting on a stand and a valve that is part of an assembly with its actuator.
const graph = {
  revision: 3,
  edges: [
    ["s1", "b1", "joint", "geometry"], ["b1", "s2", "joint", "geometry"], ["s2", "b2", "joint", "geometry"],
    ["b2", "s3", "joint", "geometry"], ["s3", "b3", "joint", "geometry"], ["b3", "s4", "joint", "geometry"],
    ["s4", "frl", "joint", "geometry"], ["frl", "out", "joint", "geometry"],
    ["s3", "stand", "rests_on", "geometry"], ["s3", "c3", "contact", "check"], ["s3", "b2", "contact", "check"],
    ["valve", "actuator", "assembly", "IfcRelAggregates"],
  ],
  stops: ["frl"],
  systems: { s3: ["Compressed air"] },
  assemblies: { cabinet: { name: "Valve set", parts: ["valve", "actuator", "gauge"] } },
};

test("an element's direct links come by kind, and rests on reads the other way round as supports", () => {
  const ix = links.indexGraph(graph);
  assert.deepEqual(links.linksOf(ix, "s3"), { joint: ["b2", "b3"], rests_on: ["stand"], contact: ["c3", "b2"] });
  assert.deepEqual(links.linksOf(ix, "stand"), { supports: ["s3"] });
  assert.deepEqual(links.linksOf(ix, "nothing"), {});
});

test("an element linked two ways is lit once, in the first kind; the colours are the kinds' own", () => {
  const ix = links.indexGraph(graph);
  const groups = links.highlightGroups(ix, "s3", false);
  assert.deepEqual(groups.map((g) => [g.kind, g.ids]), [["joint", ["b2", "b3"]], ["rests_on", ["stand"]], ["contact", ["c3"]]]);
  assert.equal(groups[0].color, links.LINK_COLOURS.joint);
  assert.equal(links.countsText(groups), "2 joined · 1 rests on · 1 touches");
  assert.equal(links.countsText([]), "nothing linked");
});

test("Shift walks the run through its joints, stopping at equipment (lit, not walked through)", () => {
  const ix = links.indexGraph(graph);
  assert.deepEqual(new Set(links.runOf(ix, "s3")), new Set(["s1", "b1", "s2", "b2", "b3", "s4", "frl"]));
  assert.ok(!links.runOf(ix, "s3").includes("out"));
  assert.deepEqual(links.runOf(ix, "s3", 3).length, 2);   // bounded
  const wide = links.highlightGroups(ix, "s3", true);
  assert.equal(wide[0].kind, "joint");
  assert.equal(wide[0].ids.length, 7);
});

test("Shift on part of an assembly lights the whole assembly", () => {
  const ix = links.indexGraph(graph);
  assert.deepEqual(links.highlightGroups(ix, "valve", false).map((g) => g.ids), [["actuator"]]);
  assert.deepEqual(links.highlightGroups(ix, "valve", true).map((g) => [g.kind, g.ids]), [["assembly", ["actuator", "gauge"]]]);
});
