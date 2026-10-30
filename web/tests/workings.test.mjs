import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { compiled } from "./app-host.mjs";

const log = await import(await compiled("../src/runlog.ts", {}));
const workings = await import(await compiled("../src/workings.ts", { "./runlog": "data:text/javascript," }));

/** A run as the page logs it, from a recording's events ({t, event}) or plain events (one second apart). */
function runOf(kind, events, { origin = "you", end = true, error = null, meta = {} } = {}) {
  let now = 0;
  const runs = new log.RunLog(() => now);
  const h = runs.start(kind, { origin, title: "#53 Supply air main × girder", meta });
  events.forEach((x, i) => { now = (x.t ?? i + 1) * 1000; h.add(x.event ?? x); });
  if (end) { now += 1; h.end(error); }
  return runs.runs()[0];
}
const recording = async (name) => JSON.parse(await readFile(new URL(`../public/tour/${name}`, import.meta.url), "utf8")).events;
const step = (g, id) => g.steps.find((s) => s.id === id);
const texts = (parts) => parts.map((p) => p.text ?? p.items?.map((i) => i.text).join(" | ") ?? "").join(" / ");

test("the run log keeps each run's events with when they arrived, ends a run once, and keeps the last few", () => {
  let now = 1000;
  const runs = new log.RunLog(() => now, 3);
  let heard = 0;
  runs.subscribe(() => { heard++; });
  const a = runs.start("propose", { origin: "chat", title: "A" });
  now = 2500; a.add({ type: "thinking", round: 1 });
  now = 4000; a.end();
  a.add({ type: "late" }); a.end("again");
  const [run] = runs.runs();
  assert.deepEqual(run.events, [{ t: 1.5, e: { type: "thinking", round: 1 } }]);
  assert.equal(run.ended, 3); assert.equal(run.error, null); assert.equal(run.origin, "chat");
  assert.equal(heard, 3);
  const b = runs.start("triage");
  const dropped = runs.runs().at(-1);
  runs.start("plan"); runs.start("built");
  assert.deepEqual(runs.runs().map((r) => r.kind), ["triage", "plan", "built"]);
  runs.start("detect");
  assert.deepEqual(runs.runs().map((r) => r.kind), ["plan", "built", "detect"]);
  assert.equal(dropped.error, "Not followed any more", "a running run let go of is ended");
  b.add({ type: "start" });
  assert.equal(dropped.events.length, 0, "and takes nothing more");
  const kept = runs.runs();
  assert.equal(runs.runs(), kept, "the same snapshot until something changes");
  runs.stopAll("The models were opened again");
  assert.ok(runs.runs().every((r) => r.ended !== null && r.error === "The models were opened again"));
});

test("a recorded proposal (#042 on the girder) draws its round, three ideas, three checks and how it ended", async () => {
  const g = workings.graphOf(runOf("propose", await recording("c0053.json"), { origin: "replay" }));
  assert.deepEqual(g.lanes.map((l) => l.id), ["you", "muse", "orca"]);
  assert.equal(g.lanes[0].label, "Recorded");
  const round = step(g, "r0-1");
  assert.equal(round.status, "done"); assert.equal(round.time, "15.6 s");
  assert.match(texts(round.body), /Replied with 3 ideas/);
  assert.equal(round.detail[0].kind, "thoughts"); assert.equal(round.detail[0].items.length, 2);
  assert.match(round.detail[1].text, /600x300 supply duct crosses a 1000-deep transfer girder/);
  assert.deepEqual(["k0-0", "k0-1", "k0-2"].map((id) => step(g, id).status), ["ok", "ok", "fail"]);
  assert.match(texts(step(g, "k0-0").body), /✓ Verified · 50 mm clear/);
  assert.match(texts(step(g, "k0-2").body), /collision with IfcCovering \(-300 mm\)/);
  assert.equal(step(g, "k0-0").time, "1.70 s");
  assert.equal(step(g, "i0-0").fix, "offset");
  assert.match(texts(step(g, "i0-0").body), /offset 1\.05–2\.35 m by \+400 mm/);
  assert.match(texts(step(g, "stop").body), /A fix passed by round 1/);
  assert.equal(step(g, "options").title, "2 verified options");
  assert.equal(step(g, "accept").status, "ghost");
  assert.equal(step(g, "better").status, "ghost");
  assert.ok(g.edges.some((e) => e.from === "stop" && e.to === "better" && e.kind === "feedback"));
  assert.ok(g.edges.some((e) => e.from === "k0-0" && e.to === "k0-1" && e.kind === "seq"));
  assert.equal(new Set(g.steps.map((s) => `${s.lane}:${s.col}`)).size, g.steps.length, "no two steps share a lane and column");
  assert.equal(g.done, true); assert.ok(Math.abs(g.duration - 18.26) < 0.01);
  assert.deepEqual(g.bars.map((b) => b.tone), ["spark", "ok", "ok", "fail"]);
});

test("part way through, a proposal shows what is happening now and nothing that hasn't", async () => {
  const g = workings.graphOf(runOf("propose", await recording("c0053.json")), 16.5);
  assert.equal(g.done, false);
  assert.equal(step(g, "k0-0").status, "run");
  assert.match(texts(step(g, "k0-0").body), /In place, checking against the model/);
  assert.equal(step(g, "k0-0").time, "0.8 s");
  assert.equal(step(g, "k0-1"), undefined);
  assert.equal(step(g, "options"), undefined);
  const early = workings.graphOf(runOf("propose", await recording("c0053.json")), 5);
  assert.equal(step(early, "r0-1").status, "run");
  assert.equal(step(early, "r0-1").detail[0].items.length, 1, "the reasoning summary that has arrived");
});

test("refused and moved ideas from the cell's recording, and a trim from the curtain wall's", async () => {
  const g = workings.graphOf(runOf("propose", await recording("cell-ladder.json")));
  assert.deepEqual(["k0-0", "k0-1", "k0-2", "k0-3"].map((id) => step(g, id).status), ["fail", "ok", "ok", "ok"]);
  assert.match(texts(step(g, "k0-0").body), /cannot trim this element/);
  assert.match(texts(step(g, "i0-2").body), /reroute 250 mm west/);
  const trim = workings.graphOf(runOf("propose", await recording("c0051.json")));
  assert.equal(step(trim, "i0-0").fix, "trim");
  assert.match(texts(step(trim, "i0-0").body), /trim one end 60 mm/);
});

test("a second try is its own branch on Muse Wonder, numbered after the first try's ideas", () => {
  const first = { understanding: "u", advice: "Use the opening", attempts: [{ title: "a", passed: false }, { title: "b", passed: false }] };
  const g = workings.graphOf(runOf("propose", [
    { type: "escalating", model: "Muse Wonder", first: true, first_try: first },
    { type: "thinking", round: 1, model: "Muse Wonder" },
    { type: "ideas", round: 1, seconds: 30, understanding: "Wider", count: 1, model: "Muse Wonder" },
    { type: "checking", index: 0, title: "Combined lift", kind: "combined", model: "Muse Wonder" },
    { type: "attempt", index: 0, title: "Combined lift", passed: true, reason: "", kind: "combined", delta_m: [0, 0, 0.3], edit: { summary: "two steps" }, model: "Muse Wonder" },
    { type: "result", options: [{ title: "Combined lift", kind: "combined", min_clearance_m: 0.04 }], attempts: [], escalated: true, usage: { usd: 0.42 } },
  ]));
  assert.match(texts(step(g, "try1").body), /2 ideas, 0 passed/);
  assert.equal(step(g, "r1-1").actor, "wonder"); assert.equal(step(g, "r1-1").title, "Muse Wonder, round 1");
  assert.equal(step(g, "i1-0").time, "idea 3"); assert.equal(step(g, "k1-0").seq, 2);
  assert.match(texts(step(g, "k1-0").body), /40 mm clear/);
  assert.equal(step(g, "better"), undefined, "no further try after a second one");
  assert.match(texts(step(g, "options").detail), /\$0\.42/);
});

test("a later round reads why the first failed; a stopped run and a recommendation end as they did", () => {
  const r2 = workings.graphOf(runOf("propose", [
    { type: "thinking", round: 1 }, { type: "ideas", round: 1, seconds: 9, understanding: "", count: 1 },
    { type: "checking", index: 0, title: "Raise", kind: "move" }, { type: "attempt", index: 0, title: "Raise", passed: false, reason: "collision with IfcWall (-200 mm)", kind: "move", delta_m: [0, 0, 0.3] },
    { type: "thinking", round: 2 }, { type: "ideas", round: 2, seconds: 8, understanding: "", count: 1 },
    { type: "checking", index: 1, title: "Offset", kind: "offset" }, { type: "attempt", index: 1, title: "Offset", passed: true, reason: "", kind: "offset", delta_m: [0, 0, 0.3], split_m: [1, 2] },
    { type: "result", options: [{ title: "Offset", kind: "offset", min_clearance_m: 0.05 }], attempts: [] },
  ]));
  assert.ok(r2.edges.some((e) => e.from === "k0-0" && e.to === "b0-2" && e.kind === "feedback" && e.label === "what failed, and why"));
  assert.equal(step(r2, "b0-2").title, "Brief for round 2");
  assert.match(texts(step(r2, "stop").body), /by round 2/);
  const stopped = workings.graphOf(runOf("propose", [{ type: "thinking", round: 1 }], { error: "Another run took its place" }));
  assert.equal(step(stopped, "stopped").status, "fail");
  assert.match(texts(step(stopped, "r0-1").body), /Stopped before it replied/);
  const failed = workings.graphOf(runOf("propose", [{ type: "thinking", round: 1 }, { type: "error", detail: "Model timed out" }]));
  assert.match(texts(step(failed, "stopped").body), /Model timed out/);
  const rec = workings.graphOf(runOf("propose", [{ type: "thinking", round: 1 }, { type: "ideas", round: 1, seconds: 4, understanding: "", count: 1 },
    { type: "result", options: [], attempts: [], recommendation: { title: "Lower the duct 200 mm", rationale: "Structure may not move" } }]));
  assert.equal(step(rec, "options").title, "A recommendation");
  assert.equal(step(rec, "stop"), undefined); assert.equal(step(rec, "better"), undefined);
});
