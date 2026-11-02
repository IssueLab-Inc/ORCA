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
  assert.equal(o.dryRun || o.headless || o.login, false);
  assert.equal(o.filters && o.xray, true, "the opening's filter beats and X-ray are on unless turned off (owner, Nov 2)");
  assert.equal(demo.parseArgs(["--no-filters"], {}).filters, false);
  assert.equal(demo.parseArgs(["--no-xray"], {}).xray, false);
  assert.equal(demo.parseArgs(["--filters"], {}).filters, true, "--filters still runs, as the default");
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
  assert.deepEqual(demo.SHOT_NAMES, ["open", "triage", "duct", "built", "accept", "revision", "cell-22", "cell-13", "voice"]);
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

const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };

test("Ctrl+C during a take detaches, then stops it once (the take's own end doesn't stop it again)", async () => {
  const order = [];
  const current = demo.takeState();
  const going = deferred();
  const running = demo.runTake({ recordly: fakeRecordly(order), page: {}, title: TITLE, log: quiet, current,
    take: async () => { order.push("take"); await going.promise; } });
  while (!order.includes("take")) await new Promise((r) => setTimeout(r, 1));
  const stopped = await demo.interruptTake(current);
  assert.deepEqual(stopped, { videoPath: "take.mp4", projectPath: "take.recordly" });
  going.resolve();
  const r = await running;
  assert.deepEqual(order, ["start", "attach", "take", "detach", "stop"]);
  assert.equal(r.result.videoPath, "take.mp4");
});

test("Ctrl+C while the start is in flight stops the take once it has started, before anything is clicked", async () => {
  const order = [];
  const starting = deferred();
  const recordly = { ...fakeRecordly(order), start: () => { order.push("start"); return starting.promise; } };
  const current = demo.takeState();
  const running = demo.runTake({ recordly, page: {}, title: TITLE, log: quiet, current, take: async () => order.push("take") });
  const interrupted = demo.interruptTake(current);
  starting.resolve({});
  assert.deepEqual(await interrupted, { videoPath: "take.mp4", projectPath: "take.recordly" });
  const r = await running;
  assert.deepEqual(order, ["start", "stop"]);
  assert.match(r.failure.message, /Ctrl\+C/);

  const refused = deferred();
  const none = [];
  const late = demo.takeState();
  const failing = demo.runTake({ recordly: { ...fakeRecordly(none), start: () => refused.promise }, page: {}, title: TITLE, log: quiet,
    current: late, take: async () => none.push("take") });
  const nothing = demo.interruptTake(late);
  refused.reject(new Error("conflict: A take is already recording; stop or cancel it first"));
  assert.equal(await nothing, null);
  await failing;
  assert.deepEqual(none, []);
  assert.equal(await demo.interruptTake(demo.takeState()), null, "nothing recording: nothing to stop");
});

test("the summary says RETAKE or FAILED with why, and either makes the exit code non-zero", () => {
  const ok = { shot: "duct", status: "ok", videoPath: "duct.mp4" };
  const again = { shot: "cell-22", status: "retake", why: "the chat's run verified no fix for #22 (0 verified of 5 tried)", videoPath: "c.mp4" };
  const broken = { shot: "built", status: "failed", why: "setup: #1 got no verified option this time: run it again" };
  assert.match(demo.summaryLine(ok), /^ {2}duct {6}ok {6}duct\.mp4$/);
  assert.match(demo.summaryLine(again), /cell-22 +RETAKE +c\.mp4 +\(the chat's run verified no fix for #22 \(0 verified of 5 tried\)\)/);
  assert.match(demo.summaryLine(broken), /built +FAILED +\(setup: #1 got no verified option/);
  assert.equal(demo.exitCodeOf([ok]), 0);
  assert.equal(demo.exitCodeOf([ok, again]), 1);
  assert.equal(demo.exitCodeOf([ok, broken]), 1);
});

test("the sign-in checklist and the built shot's refusal name Show it built (Muse Image), as the owner's settings do", () => {
  assert.equal(demo.SIGN_IN, "Sign in as owner, switch on the open-weights model and Show it built (Muse Image), then close the window");
  assert.match(demo.NO_BUILT, /"Show it built \(Muse Image\)" for you in Owner settings \(--login\)/);
});

/** What the browser keeps when the opening can start as it is: no filters, 3D only, Workings, Activity in its bar along
 * the bottom at ORCA's Workings height (the dock's saved layout, as dockview writes it). */
const tidyKept = (bottom = {}) => ({
  filters: JSON.stringify({ rules: [] }), layout: "single", workings: JSON.stringify({ on: true, view: "work" }),
  dock: JSON.stringify({ v: 1, layout: { grid: {}, panels: {}, floatingGroups: [], edgeGroups: {
    bottom: { size: 380, visible: true, group: { id: "edge-bottom", views: ["activity"] }, ...bottom } } } }),
});

test("the opening is tidied first when the browser keeps a filter, Four views, Workings off or Activity off its bar", () => {
  assert.equal(demo.WORKINGS_HEIGHT, 380, "ORCA's own Workings height (App.tsx WORKINGS_HEIGHT)");
  assert.deepEqual(demo.untidy(tidyKept()), []);
  assert.deepEqual(demo.untidy({ ...tidyKept(), filters: null, layout: null, workings: null }), [], "nothing kept yet is the default: 3D only, Workings on");
  assert.deepEqual(demo.untidy(tidyKept({ size: 377 })), [], "a few pixels off is as ORCA sized it");
  assert.deepEqual(demo.untidy({ ...tidyKept(), filters: JSON.stringify({ rules: [{ name: "Hide Site" }] }) }), ["Northbank has filters kept"]);
  assert.deepEqual(demo.untidy({ ...tidyKept(), layout: "quad" }), ["the viewer is on quad"]);
  assert.deepEqual(demo.untidy({ ...tidyKept(), workings: JSON.stringify({ on: true, view: "steps" }) }), ["Activity isn't showing Workings"]);
  assert.deepEqual(demo.untidy({ ...tidyKept(), workings: JSON.stringify({ on: false, view: "steps" }) }), ["Activity isn't showing Workings"]);
  assert.deepEqual(demo.untidy(tidyKept({ size: 120 })), ["Activity's bar is 120 px high, not 380"]);
  assert.deepEqual(demo.untidy(tidyKept({ collapsed: true })), ["Activity's bar is closed"]);
  assert.deepEqual(demo.untidy(tidyKept({ group: { views: [] } })), ["Activity isn't in its bar along the bottom"], "floated, or docked elsewhere");
  assert.deepEqual(demo.untidy({ ...tidyKept(), dock: null }), ["no panel layout kept yet"]);
  assert.deepEqual(demo.untidy({ ...tidyKept(), dock: "not json" }), ["no panel layout kept yet"]);
});

test("the chat's fix is read from the steps under its answer, as Chat lists them", () => {
  assert.equal(demo.CHAT_LINE, "Find a fix for clash #22.");
  assert.deepEqual(demo.chatFix(["Read a clash (#22) → PL-302 segment 3 × column C4", "Ran the fix agent (#22) → 2 verified of 6 tried"]),
    { ran: true, verified: 2, said: "2 verified of 6 tried" });
  assert.deepEqual(demo.chatFix(["Ran the fix agent (#22) → 0 verified of 7 tried"]), { ran: true, verified: 0, said: "0 verified of 7 tried" });
  assert.deepEqual(demo.chatFix(["Ran the fix agent (#22) → refused: allowance used"]), { ran: true, verified: 0, said: "refused: allowance used" });
  assert.deepEqual(demo.chatFix(["Ran the fix agent (#22) …"]), { ran: true, verified: 0, said: "" }, "still running: no summary yet");
  assert.deepEqual(demo.chatFix(["Read a clash (#22) → PL-302"]), { ran: false, verified: 0, said: "" });
  assert.deepEqual(demo.chatFix([]), { ran: false, verified: 0, said: "" });
});

test("the takes' window is maximized and its page size said; a window that won't maximize stops the run with why", async () => {
  const lines = [], asked = [];
  const helper = { maximizeWindow: async (page, o) => { asked.push([page, o]); return { width: 2458, height: 1291 }; } };
  assert.deepEqual(await demo.maximize(helper, "page", { log: (l) => lines.push(l) }), { width: 2458, height: 1291 });
  assert.deepEqual(asked, [["page", { timeoutMs: 5000 }]]);
  assert.deepEqual(lines, ["Window maximized: the page is 2458 × 1291"]);
  const stuck = { maximizeWindow: async () => { throw new Error("Couldn't maximize the browser window within 5000 ms"); } };
  await assert.rejects(demo.maximize(stuck, "page", quiet), /Couldn't maximize the takes' window \(Couldn't maximize the browser window within 5000 ms\): .*maximized window on the primary display/);
});

/** A page whose clash rows draw after `rowsAfter` ms; records every click on the clashes tab. */
function listPage({ rowsAfter, front = false }) {
  const t0 = Date.now(), clicks = [];
  const drawn = () => Date.now() - t0 >= rowsAfter;
  const locator = (selector) => {
    const l = {
      first: () => l,
      count: async () => (selector === "button.clash-main" ? (drawn() ? 1 : 0)
        : selector.startsWith(".dv-tab.dv-active-tab") ? (front ? 1 : 0) : 1),
      click: async () => { clicks.push(Date.now() - t0); },
      waitFor: async () => undefined,
    };
    return l;
  };
  return { clicks, page: { locator } };
}

test("listReady: the clashes tab is nudged only after the wait, never on the first poll", async () => {
  const quick = listPage({ rowsAfter: 300 });
  await demo.listReady(quick.page);
  assert.deepEqual(quick.clicks, [], "rows came inside the 2 s: nothing to nudge");
  const slow = listPage({ rowsAfter: 1000 });
  await demo.listReady(slow.page, { after: 400 });
  assert.ok(slow.clicks.length >= 1 && slow.clicks[0] >= 400, `first nudge at ${slow.clicks[0]} ms, not before the wait`);
});

test("listReady: no raw click inside a take (nudge: false), nor when the clashes tab is already in front", async () => {
  const inTake = listPage({ rowsAfter: 1000 });
  await demo.listReady(inTake.page, { nudge: false, after: 100 });
  assert.deepEqual(inTake.clicks, []);
  const infront = listPage({ rowsAfter: 1000, front: true });
  await demo.listReady(infront.page, { after: 100 });
  assert.deepEqual(infront.clicks, []);
});
