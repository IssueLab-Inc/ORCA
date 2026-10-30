import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { compiled } from "./app-host.mjs";

const log = await import(await compiled("../src/runlog.ts", {}));
const workings = await import(await compiled("../src/workingsGraph.ts", { "./runlog": "data:text/javascript,", "./fixKinds": await compiled("../src/fixKinds.ts", {}) }));

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
const texts = (parts) => parts.map((p) => p.text ?? p.items?.map((i) => [i.text, i.note].filter(Boolean).join(" ")).join(" | ") ?? "").join(" / ");

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
  const triage = runs.start("triage");
  runs.start("plan").end(); runs.start("built");
  assert.deepEqual(runs.runs().map((r) => r.kind), ["triage", "plan", "built"], "the finished proposal went first");
  runs.start("detect");
  assert.deepEqual(runs.runs().map((r) => r.kind), ["triage", "built", "detect"], "then the finished plan; live runs stay");
  runs.start("propose");
  assert.equal(runs.runs().length, 4, "never a live run let go of: the log grows while more are live");
  triage.add({ type: "start", total: 3 });
  assert.equal(runs.runs()[0].events.length, 1);
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

test("a recorded root cause (the girder) draws the cause, a row per service with its checks, and the plan checked as a whole", async () => {
  const g = workings.graphOf(runOf("plan", await recording("girder-plan.json"), { origin: "replay", meta: { kind: "root_cause" } }));
  assert.deepEqual(g.lanes.map((l) => l.id), ["you", "muse", "orca", "it0", "it1", "it2"]);
  assert.deepEqual(g.lanes.slice(3).map((l) => l.label), ["Supply air main L02", "Cable tray L02", "Cold water main L02 DN54"]);
  assert.match(texts(step(g, "cause").body), /routed in a Level 02 service zone/);
  assert.equal(step(g, "cause").time, "6.8 s");
  assert.match(texts(step(g, "jobs").body), /not in the report/);
  assert.deepEqual(["it0-c0", "it0-c1", "it0-c2"].map((id) => step(g, id).status), ["ok", "fail", "ok"]);
  assert.equal(step(g, "it1-c2"), undefined, "the tray tried two ideas");
  assert.equal(step(g, "it2-d").title, "Kept for the plan");
  assert.match(texts(step(g, "it2-d").detail), /53 mm clear in the plan/);
  assert.equal(step(g, "check").status, "ok");
  assert.equal(step(g, "plan").title, "Plan: 3 verified fixes");
  assert.ok(["it0-d", "it1-d", "it2-d"].every((id) => g.edges.some((e) => e.from === id && e.to === "check" && e.win)));
  const cols = new Set(["it0-d", "it1-d", "it2-d"].map((id) => step(g, id).col));
  assert.equal(cols.size, 1, "the rows end in one column");
  const mid = workings.graphOf(runOf("plan", await recording("girder-plan.json"), { meta: { kind: "root_cause" } }), 20);
  assert.equal(step(mid, "it0-t").status, "run"); assert.equal(step(mid, "it1-t").status, "done");
  assert.equal(step(mid, "check"), undefined);
});

test("triage counts what rules settled, the model's calls and the verdicts, and carries clashes along while it runs", () => {
  const events = [
    { type: "start", total: 6, model: "meta-models/muse-spark-open", open_weights: true },
    { type: "clash", id: "c1", verdict: "by_design", source: "rule", basis: "touch" },
    { type: "clash", id: "c2", verdict: "non_physical", source: "rule", basis: "non_physical" },
    { type: "reasoning", id: "c3", text: "The duct runs through " }, { type: "reasoning", id: "c4", text: "Bolt in its plate" },
    { type: "reasoning", id: "c3", text: "the girder's web." },
    { type: "clash", id: "c3", verdict: "real_clash", source: "model", seconds: 3 },
    { type: "clash", id: "c4", verdict: "by_design", source: "model", alike: 3, seconds: 2 },
    { type: "clash", id: "c5", verdict: "by_design", source: "model", alike_of: "c4", alike: 3 },
    { type: "clash", id: "c6", verdict: "by_design", source: "model", alike_of: "c4", alike: 3 },
    { type: "done", summary: {}, seconds: 11 },
  ];
  const mid = workings.graphOf(runOf("triage", events, { end: false, meta: { names: { c3: "#3 Supply air main × girder" } } }), 6.5);
  assert.equal(step(mid, "pool").status, "run");
  assert.deepEqual(step(mid, "pool").detail[0].rows.map((r) => r.title), ["#3 Supply air main × girder", "c4"]);
  assert.match(step(mid, "pool").detail[0].rows[0].note, /through the girder's web/);
  assert.ok(mid.flows.length >= 3, "clashes on their way while it runs");
  const g = workings.graphOf(runOf("triage", events));
  assert.equal(step(g, "start").title, "Triage all 6 clashes");
  assert.match(texts(step(g, "rules").body), /2 clashes/);
  assert.match(texts(step(g, "rules").detail), /a touch within 1 mm 1 · not physical 1/);
  assert.match(texts(step(g, "alike").body), /3 clashes in 1 group/);
  assert.equal(step(g, "pool").title, "2 calls read");
  const bars = step(g, "verdicts").body[0].rows;
  assert.deepEqual(bars.map((r) => [r.label, r.n]), [["Real", 1], ["By design", 4], ["Not physical", 1], ["Modelling error", 0]]);
  assert.match(texts(step(g, "done").body), /1 real clash of 6/);
  assert.equal(g.rows[2].subs, 2, "two calls overlapped");
});

test("Show it built draws each round, the gate's numbers, the judges and the retry, then the picture kept", () => {
  const g = workings.graphOf(runOf("built", [
    { type: "drawing", round: 1, pictures: 2 },
    { type: "gate", round: 1, picture: 0, f: 0.71, tile: 0.24, passed: true }, { type: "gate", round: 1, picture: 1, f: 0.49, tile: 0.3, passed: false },
    { type: "judging", round: 1, picture: 0 }, { type: "judged", round: 1, picture: 0, verdicts: ["faithful", "unfaithful"] },
    { type: "retry", why: "a second web opening" },
    { type: "drawing", round: 2, pictures: 2 }, { type: "gate", round: 2, picture: 0, f: 0.74, tile: 0.21, passed: true },
    { type: "judging", round: 2, picture: 0 }, { type: "judged", round: 2, picture: 0, verdicts: ["faithful", "faithful"] },
    { type: "result", status: "done", image_url: "/api/built/x.jpg", gate: { f: 0.74, tile: 0.21 }, judge: "Muse Wonder", seconds: 68, tried: 3 },
  ], { meta: { look: "data:image/png;base64,AA" } }));
  assert.deepEqual(g.lanes.map((l) => l.id), ["you", "orca", "image", "judges"]);
  assert.match(texts(step(g, "gate1").body), /✓ F 0\.71 · worst tile 0\.24 \| ✗ F 0\.49/);
  assert.equal(step(g, "judge1").status, "fail"); assert.equal(step(g, "judge2").status, "ok");
  assert.ok(g.edges.some((e) => e.to === "draw2" && e.kind === "feedback"));
  assert.match(texts(step(g, "retry1").body), /a second web opening/);
  assert.equal(step(g, "ready").body[0].src, "/api/built/x.jpg");
  const odd = workings.graphOf(runOf("built", [{ type: "drawing", round: 1, pictures: 1 }, { type: "gate", round: 1, picture: 0, f: 0.7, tile: 0.2, passed: true },
    { type: "judging", round: 1, picture: 0 }, { type: "judged", round: 1, picture: 0, verdicts: [null, "faithful"] }]));
  assert.match(texts(step(odd, "judge1").body), /no verdict, faithful/, "a judge reply without a verdict draws, never throws");
});

test("ORCA's check draws each phase and test with its clashes, then what it found", () => {
  const g = workings.graphOf(runOf("detect", [
    { type: "phase", text: "Reading the models" }, { type: "phase", text: "Building geometry for 1732 elements" },
    { type: "start", elements: 1732, tests: [{ id: "a", name: "MEP vs Structure", kind: "hard" }, { id: "b", name: "Architecture (within)", kind: "hard" }] },
    { type: "test", index: 0, id: "a", name: "MEP vs Structure", candidates: 40 },
    { type: "test_done", index: 0, coverage: { clashes: 3, seconds: 1.2, touching: 4 } },
    { type: "test", index: 1, id: "b", name: "Architecture (within)", candidates: 90 },
    { type: "test_done", index: 1, coverage: { clashes: 0, seconds: 0.8, touching: 0 } },
    { type: "done", coverage: [{ clashes: 3 }, { clashes: 0 }], diff: { new: [], resolved: [], first: true }, elements: 1732, seconds: 4.1 },
  ]));
  assert.equal(step(g, "phase0").title, "Reading the models");
  assert.equal(step(g, "phase1").time, "1.0 s", "building lasts until the first test, not until the start before it");
  const building = workings.graphOf(runOf("detect", [{ type: "phase", text: "Reading the models" }, { type: "start", elements: 9, tests: [] },
    { type: "phase", text: "Building geometry for 9 elements" }], { end: false }), 3.5);
  assert.equal(step(building, "phase1").status, "run"); assert.equal(step(building, "phase1").time, "0.5 s");
  assert.equal(step(building, "phase0").status, "done");
  assert.equal(step(g, "test0").status, "fail"); assert.match(texts(step(g, "test0").body), /3 clashes/);
  assert.equal(step(g, "test1").status, "ok");
  assert.equal(step(g, "found").title, "3 clashes in 1,732 elements");
  assert.match(texts(step(g, "found").body), /first check/);
});

test("ideas the server names with `ideas` appear at once, then each is checked in its own column", () => {
  const events = [
    { type: "thinking", round: 1 },
    { type: "ideas", round: 1, seconds: 12, understanding: "", count: 2, candidates: [{ title: "Offset up", kind: "offset" }, { title: "Drop under", kind: "move" }] },
    { type: "checking", index: 0, title: "Offset up", kind: "offset" },
    { type: "attempt", index: 0, title: "Offset up", passed: true, reason: "", kind: "offset", delta_m: [0, 0, 0.4], split_m: [1, 2] },
    { type: "checking", index: 1, title: "Drop under", kind: "move" },
  ];
  const g = workings.graphOf(runOf("propose", events, { end: false }), 2.5);
  assert.deepEqual(["i0-0", "i0-1"].map((id) => step(g, id)?.title), ["Offset up", "Drop under"]);
  assert.match(texts(step(g, "i0-1").body), /waiting its turn/);
  assert.equal(step(g, "k0-0"), undefined);
  const later = workings.graphOf(runOf("propose", events, { end: false }), 5.5);
  assert.equal(step(later, "k0-1").col, step(later, "i0-1").col);
  assert.equal(later.edges.filter((e) => e.to === "i0-1").length, 1, "one edge from the round to each idea");
  assert.equal(step(later, "k0-1").status, "run");
});

test("the run log drops the meshes Workings never reads, and the server's check times and counts show", () => {
  let now = 0;
  const runs = new log.RunLog(() => now);
  const h = runs.start("propose");
  h.add({ type: "trial", index: 0, kind: "offset", pieces: [{ verts: [1, 2, 3] }] });
  h.add({ type: "result", options: [{ title: "O", kind: "offset", preview: [{}], before: [{}], placements: {}, min_clearance_m: 0.05 }] });
  const [trial, result] = runs.runs()[0].events.map((x) => x.e);
  assert.equal("pieces" in trial, false);
  assert.deepEqual(result.options[0], { title: "O", kind: "offset", min_clearance_m: 0.05 });
  const g = workings.graphOf(runOf("propose", [
    { type: "thinking", round: 1 }, { type: "ideas", round: 1, seconds: 5, understanding: "", count: 1 },
    { type: "checking", index: 0, title: "Raise", kind: "move" },
    { type: "attempt", index: 0, title: "Raise", passed: true, reason: "", kind: "move", delta_m: [0, 0, 0.4], split_m: null, seconds: 0.48, checked: 214 },
    { type: "result", options: [{ title: "Raise", kind: "move", min_clearance_m: 0.05 }] },
  ]));
  assert.equal(step(g, "k0-0").time, "0.48 s");
  assert.match(texts(step(g, "k0-0").detail), /Checked against 214 elements in 0\.48 s/);
  assert.match(texts(step(g, "rank").body), /Move · 50 mm clear/);
  const plan = workings.graphOf(runOf("plan", [
    { type: "plan_items", items: [{ key: "k", label: "IfcPipeSegment 'Pipe' x IfcBeam 'Beam'" }], skipped: [] },
    { type: "item", key: "k", status: "thinking" },
    { type: "item", key: "k", status: "checking", attempt: "Lift", passed: false, seconds: 0.61, reason: "collision with IfcWall (-200 mm)" },
  ], { meta: { kind: "batch" } }));
  assert.equal(step(plan, "it0-c0").time, "0.61 s");
  assert.match(texts(step(plan, "it0-c0").body), /collision with IfcWall/);
});
