import assert from "node:assert/strict";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import demo from "../scripts/record-demo.cjs";

const quiet = { log() {}, warn() {}, error() {} };
const TITLE = "ORCA · AI design coordination";

test("arguments: the defaults, shots by name, and refusals that say what to do", () => {
  const o = demo.parseArgs([], { LOCALAPPDATA: path.join("C:", "Users", "x", "AppData", "Local") });
  assert.equal(o.url, "http://localhost:8765");
  assert.equal(o.profile, path.join("C:", "Users", "x", "AppData", "Local", "orca-demo-profile"));
  assert.equal(o.only, null);
  assert.equal(o.dryRun || o.headless || o.login || o.filters, false);
  assert.deepEqual(demo.parseArgs(["--only", "duct, built", "--filters"], {}).only, ["duct", "built"]);
  assert.equal(demo.parseArgs([], { RECORDLY_DIR: "D:\\Recordly" }).recordly, "D:\\Recordly");
  assert.throws(() => demo.parseArgs(["--only", "duct,nope"], {}), /No shot called nope/);
  assert.throws(() => demo.parseArgs(["--url"], {}), /--url needs a value/);
  assert.throws(() => demo.parseArgs(["--url", "not a url"], {}), /--url is not a URL/);
  assert.throws(() => demo.parseArgs(["--headless"], {}), /--headless needs --dry-run/);
  assert.throws(() => demo.parseArgs(["--login", "--dry-run"], {}), /--login/);
  assert.throws(() => demo.parseArgs(["--bogus"], {}), /Unknown argument: --bogus/);
});

test("shots run in the script's order whatever order --only gives, each with a setup and a take", () => {
  assert.deepEqual(demo.SHOT_NAMES, ["open", "triage", "duct", "built", "accept", "revision", "cell-29", "cell-13", "voice"]);
  assert.deepEqual(demo.selectShots(demo.SHOTS, ["voice", "duct", "open"]).map((s) => s.name), ["open", "duct", "voice"]);
  assert.equal(demo.selectShots(demo.SHOTS, null).length, demo.SHOTS.length);
  for (const s of demo.SHOTS) assert.equal(typeof s.setup === "function" && typeof s.take === "function", true, s.name);
  for (const name of demo.SHOT_NAMES) assert.match(demo.USAGE, new RegExp(`\\n\\s+${name}\\s`), `--help names ${name}`);
});

test("a missing Recordly checkout is named, with the flag that fixes it", () => {
  const nowhere = path.join(os.tmpdir(), "no-recordly-checkout-here");
  assert.throws(() => demo.loadRecordly(nowhere), (e) => e.message.includes(nowhere) && e.message.includes("--recordly"));
});

test("an ambiguous window title falls back to the one window named exactly so; other refusals stand", async () => {
  const asked = [];
  const recordly = {
    async start(o) {
      asked.push(o.source);
      if (o.source.windowTitle) throw new Error(`bad_request: Ambiguous window title "${o.source.windowTitle}": multiple windows match`);
      return { source: o.source, agentCursor: o.agentCursor };
    },
    sources: async () => [
      { id: "chrome", kind: "window", name: `${TITLE} - Google Chrome` },
      { id: "app", kind: "window", name: TITLE },
      { id: "screen", kind: "screen", name: TITLE },
    ],
  };
  const started = await demo.startTake(recordly, TITLE);
  assert.deepEqual(asked, [{ windowTitle: TITLE }, { id: "app" }]);
  assert.equal(started.agentCursor, true);

  const twins = { ...recordly, sources: async () => [{ id: "a", kind: "window", name: TITLE }, { id: "b", kind: "window", name: TITLE }] };
  await assert.rejects(demo.startTake(twins, TITLE), /close the others/);

  let listed = false;
  const busy = { start: async () => { throw new Error("conflict: A take is already recording; stop or cancel it first"); },
    sources: async () => { listed = true; return []; } };
  await assert.rejects(demo.startTake(busy, TITLE), /^Error: conflict: .*stop or cancel it first/);
  assert.equal(listed, false);
});

function fakeRecordly(order, { detach } = {}) {
  const cursor = {
    detach: async () => { order.push("detach"); if (detach) throw detach; },
    stats: () => ({ sent: 4, accepted: 4, rejected: 0, dropped409: 0, failed: 0, queued: 0, lastError: null }),
  };
  return {
    start: async () => { order.push("start"); return {}; },
    attachCursor: async () => { order.push("attach"); return cursor; },
    stop: async () => { order.push("stop"); return { videoPath: "take.mp4", projectPath: "take.recordly" }; },
  };
}

test("a take that fails is still detached, then stopped, and its footage kept", async () => {
  const order = [];
  const r = await demo.runTake({ recordly: fakeRecordly(order), page: {}, title: TITLE, log: quiet,
    take: async () => { order.push("take"); throw new Error("#1 got no verified option"); } });
  assert.deepEqual(order, ["start", "attach", "take", "detach", "stop"]);
  assert.equal(r.failure.message, "#1 got no verified option");
  assert.deepEqual(r.result, { videoPath: "take.mp4", projectPath: "take.recordly" });
  assert.equal(r.cursor.accepted, 4);
});

test("a final cursor flush that fails still stops the take; a take that never started is not stopped", async () => {
  const order = [];
  const r = await demo.runTake({ recordly: fakeRecordly(order, { detach: new Error("socket hang up") }), page: {}, title: TITLE,
    log: quiet, take: async () => order.push("take") });
  assert.deepEqual(order, ["start", "attach", "take", "detach", "stop"]);
  assert.equal(r.failure, null);
  assert.equal(r.result.videoPath, "take.mp4");

  const none = [];
  const refused = { ...fakeRecordly(none), start: async () => { none.push("start"); throw new Error("conflict: A take is already recording; stop or cancel it first"); } };
  const s = await demo.runTake({ recordly: refused, page: {}, title: TITLE, log: quiet, take: async () => none.push("take") });
  assert.deepEqual(none, ["start"]);
  assert.equal(s.started, false);
  assert.match(s.failure.message, /^conflict:/);
  assert.equal(s.result, null);
});
