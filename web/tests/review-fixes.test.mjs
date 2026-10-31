import assert from "node:assert/strict";
import test from "node:test";
import { appHost, checks, contextProposal, contextResult, option, flush, compiled, find, hasText } from "./app-host.mjs";

async function completed(host) {
  const work = host.button("Propose fixes").props.onClick(); host.render();
  host.requests.at(-1).onEvent({ type: "ideas", round: 1, seconds: 3, understanding: "A fix", count: 1 });
  host.requests.at(-1).resolve({ understanding: "A fix", options: [option], attempts: [] });
  await work; host.render();
}
async function wider(host) {
  host.button("Explore wider fix").props.onClick(); host.render();
  host.contextRequests.at(-1).onEvent(contextResult); host.contextRequests.at(-1).resolve();
  await host.settle();
  host.component("ContextPlan").props.onAcknowledge("review", true); host.render();
}

test("actual preview effect retains the verified manual snapshot and completed activity after selected option cleanup", async () => {
  const host = await appHost(); await completed(host);
  const progress = host.state.progress;
  assert.equal(host.state.chosen, 0);
  const work = host.button("Check this move").props.onClick();
  host.input("manual-dz").props.onChange({ target: { value: "0.9" } }); host.render();
  host.verifyRequests[0].resolve({ passed: false, hits: [], min_clearance_m: null }); await work; host.render();
  assert.deepEqual(host.actions.at(-1), ["preview", [{ globalIds: ["duct"], deltaM: [0, 0, -.25] }]]);
  assert.equal(host.state.progress, progress);
  assert.deepEqual(host.state.progress.modelSeconds, [3]);
  host.unmount();
});

test("late manual response cannot take the viewer back from a newer wider search", async () => {
  const host = await appHost();
  const work = host.button("Check this move").props.onClick(); host.render();
  await wider(host); const context = host.state.context;
  host.verifyRequests[0].resolve({ passed: true, hits: [], min_clearance_m: .05 }); await work; host.render();
  assert.equal(host.state.viewContext, true); assert.equal(host.state.context, context); assert.equal(host.state.manual, null);
  host.unmount();
});

test("choosing another option replaces manual state and deselecting cannot resurrect its preview", async () => {
  const host = await appHost(); await completed(host);
  const work = host.button("Check this move").props.onClick();
  host.verifyRequests[0].resolve({ passed: true, hits: [], min_clearance_m: .05 }); await work; host.render();
  host.button("Single fix").props.onClick(); host.render();
  assert.equal(host.state.manual, null); assert.equal(host.state.manualPreview, null);
  assert.equal(host.actions.at(-1)[0], "showOption");
  host.button("Single fix").props.onClick(); host.render();
  assert.deepEqual(host.actions.at(-1), ["preview", []]); host.unmount();
});

test("returning to a completed wider plan replaces manual ownership instead of reviving it on the Clash tab", async () => {
  const host = await appHost(); await wider(host); await completed(host);
  const work = host.button("Check this move").props.onClick();
  host.verifyRequests[0].resolve({ passed: true, hits: [], min_clearance_m: .05 }); await work; host.render();
  host.button("Plan").props.onClick(); host.render();
  assert.equal(host.state.manual, null); assert.equal(host.state.manualPreview, null); assert.equal(host.state.viewContext, true);
  host.button("Clash").props.onClick(); host.render();
  // The manual preview stays gone; back on the clash, a drag orbits round it again (the viewer is told after).
  assert.deepEqual(host.actions.filter(([k]) => k === "preview").at(-1), ["preview", []]);
  assert.deepEqual(host.actions.filter(([k]) => k === "setOrbitClash").at(-1), ["setOrbitClash", true]); host.unmount();
});

test("an actual accept invalidates a pending manual result before API completion", async () => {
  const host = await appHost(); await completed(host);
  const manual = host.button("Check this move").props.onClick(); host.render();
  await host.button("Accept this fix").props.onClick(); host.render();
  host.verifyRequests[0].resolve({ passed: true, hits: [], min_clearance_m: .05 }); await manual; host.render();
  assert.equal(host.state.manual, null); assert.equal(host.state.manualPreview, null); assert.equal(host.state.chosen, null);
  assert.equal(host.state.evidence.clash.status, "accepted"); host.unmount();
});

test("wider acceptance retires direct pending single and batch callbacks and removes old accept options", async () => {
  for (const kind of ["single", "batch"]) {
    const host = await appHost({ api: { applyContext: async () => ({ files: [0], edits: contextProposal.edits,
      resolved_pairs: [{ element_a: "duct", element_b: "beam" }], checks }) } }); await wider(host);
    let work;
    if (kind === "single") work = host.button("Propose fixes").props.onClick();
    else { host.state.checked = new Set(["clash"]); host.render(); work = host.component("ReportList").props.onFixChecked(); }
    host.render();
    if (kind === "batch") { host.button("Wider fix").props.onClick(); host.render(); }
    await host.component("ContextPlan").props.onAccept(); host.render();
    if (kind === "single") {
      host.requests[0].onEvent({ type: "ideas", seconds: 20, understanding: "Old", count: 1 });
      host.requests[0].resolve({ understanding: "Old result", options: [option], attempts: [] });
    } else {
      host.planRequests[0].onEvent({ type: "checking_plan" });
      host.planRequests[0].resolve({ title: "Old plan", items: [{ key: "old", option }], check: { passed: true, items: {} } });
    }
    await work; await host.settle();
    assert.equal(host.state.proposal, null); assert.equal(host.state.plan, null); assert.equal(host.state.planRun, null);
    assert.equal(host.state.progress?.phase === "done" || host.state.progress === null, true);
    assert.equal(host.button("Accept this fix"), undefined);
    host.unmount();
  }
});

test("accepted coordinated evidence covers confirmed duplicate pairs and survives a viewer reload failure", async () => {
  const c = (id) => ({ id, name: id, a: {}, b: {}, images: [] });
  const report = { id: "report", title: "Report", clashes: [c("clash"), c("duplicate"), c("unrelated")] };
  const matches = { clash: { a: "duct", b: "beam" }, duplicate: { a: "beam", b: "duct" }, unrelated: { a: "other", b: "beam" } };
  const host = await appHost({ initial: { report, matches }, api: { match: async () => matches,
    applyContext: async () => ({ files: [0], edits: contextProposal.edits, resolved_pairs: [{ element_a: "duct", element_b: "beam" }], checks }),
    file: async () => { throw new Error("Download failed"); } } });
  await completed(host); const obsoleteCapture = [...host.timers.values()][0];
  host.runTimers(); assert.equal(host.state.evidence.clash.status, "proposed");
  await wider(host); await host.component("ContextPlan").props.onAccept(); host.render(); host.runTimers();
  const captureBoundary = host.actions.length; obsoleteCapture(); host.render();
  assert.equal(host.actions.length, captureBoundary, "an already-queued old proposal capture cannot repaint the accepted view");
  for (const id of ["clash", "duplicate"]) {
    const ev = host.state.evidence[id]; assert.equal(ev.status, "accepted"); assert.equal(ev.title, "Coordinated fix");
    assert.match(ev.edit, /duct/); assert.match(ev.edit, /blocker/);
    assert.match(ev.rationale, /Enabling reason 1/); assert.match(ev.rationale, /Enabling reason 2/);
    assert.match(ev.also_needs, /Designer review required/); assert.match(ev.rationale, /Retained frame warning/);
    assert.equal(ev.clearance_m, .025); assert.ok(ev.before_img); assert.ok(ev.after_img);
  }
  assert.equal(host.state.evidence.unrelated, undefined); assert.equal(host.state.fixes.unrelated, undefined);
  assert.equal(host.state.context.accepted, true); assert.match(host.state.context.error, /Download failed/);
  host.unmount();
});

test("a failed wider accept ends pending single work without claiming a commit or restoring late options", async () => {
  const host = await appHost({ api: { applyContext: async () => { throw new Error("Fresh check rejected"); } } }); await wider(host);
  const single = host.button("Propose fixes").props.onClick(); host.render();
  await host.component("ContextPlan").props.onAccept(); host.render();
  assert.equal(host.state.progress.phase, "done");
  host.requests[0].resolve({ understanding: "Obsolete", options: [option], attempts: [] }); await single; host.render();
  assert.equal(host.state.context.accepted, false); assert.match(host.state.context.error, /Fresh check rejected/);
  assert.deepEqual(host.state.fixes, {}); assert.deepEqual(host.state.evidence, {}); assert.equal(host.state.chosen, null);
  assert.equal(host.state.proposal.options.length, 0); host.unmount();
});

test("wider commit removes completed single accept options while preserving historical timing", async () => {
  const host = await appHost(); await wider(host); await completed(host);
  assert.equal(host.button("Accept this fix").props.disabled, false);
  const progress = host.state.progress;
  await host.component("ContextPlan").props.onAccept(); host.render();
  assert.equal(host.state.progress, progress); assert.equal(host.state.proposal, null); assert.equal(host.state.chosen, null);
  assert.equal(host.button("Accept this fix"), undefined); host.unmount();
});

test("retired direct wider search aborts its signal and ignores buffered events on chat takeover and unmount", async () => {
  const host = await appHost(); host.button("Explore wider fix").props.onClick(); host.render();
  const old = host.contextRequests[0]; host.chat({ type: "tool", name: "explore_wider_fix", args: { clash_id: "clash" } });
  assert.equal(old.signal?.aborted, true); const current = host.state.context;
  old.onEvent(contextResult); old.reject(new DOMException("Aborted", "AbortError")); await host.settle();
  assert.equal(host.state.context, current); assert.equal(host.state.error, null);
  host.component("ContextPlan").props.onRegenerate(); host.render(); const next = host.contextRequests[1];
  host.unmount(); assert.equal(next.signal?.aborted, true); next.resolve(); await flush();
});

test("model and report replacement abort direct wider streams before IO resolves", async () => {
  for (const replacement of ["model", "report"]) {
    let finish;
    const host = await appHost({ api: { open: () => new Promise((resolve) => { finish = () => resolve({ id: "new", files: ["new.ifc"] }); }),
      openReport: () => new Promise((resolve) => { finish = () => resolve({ id: "new-report", title: "New", clashes: [] }); }) } });
    host.button("Explore wider fix").props.onClick(); host.render(); const old = host.contextRequests[0];
    if (replacement === "model") host.open(); else host.loadReport();
    assert.equal(old.signal.aborted, true); old.onEvent(contextResult); old.resolve();
    assert.equal(host.state.context, null); finish(); await host.settle();
    assert.equal(host.state.context, null); host.unmount();
  }
});

test("accepting a completed batch plan aborts a pending direct wider stream and marks its result stale", async () => {
  const plan = { kind: "batch", title: "Batch", items: [{ key: "one", element_a: "duct", element_b: "beam", clash_ids: ["clash"], option }],
    check: { passed: true, items: {} } };
  const host = await appHost({ initial: { plan }, api: { applyPlan: async () => ({ files: [], pieces: [] }) } });
  host.button("Explore wider fix").props.onClick(); host.render(); const request = host.contextRequests[0];
  host.button("Clash plan").props.onClick(); host.render();
  await host.component("PlanPanel").props.onAccept(); host.render();
  assert.equal(request.signal.aborted, true); assert.equal(host.state.context.stale, true);
  request.onEvent(contextResult); request.resolve(); await host.settle();
  assert.equal(host.state.context.result, null); host.unmount();
});

test("a wider objective only attributes the report when the selected clash matches its unordered pair", async () => {
  for (const [a, b, expected] of [["duct", "beam", true], ["beam", "duct", true], ["blocker", "beam", false]]) {
    const host = await appHost(); host.state.a = a; host.state.b = b; host.render();
    host.button("Explore wider fix").props.onClick(); host.render();
    const objective = host.contextRequests[0].objective;
    assert.equal(objective.report_id, expected ? "report" : undefined); assert.equal(objective.clash_id, expected ? "clash" : undefined);
    host.contextRequests[0].resolve(); host.unmount();
  }
  const host = await appHost({ initial: { report: null, clash: null, matches: null } });
  host.button("Explore wider fix").props.onClick(); host.render();
  assert.deepEqual(host.contextRequests[0].objective, { element_a: "duct", element_b: "beam" });
  host.contextRequests[0].resolve(); host.unmount();
});

test("an actual parse failure preserves prior App state and a stale load cannot publish stats or scene identity", async () => {
  const host = await appHost({ api: { open: async () => ({ id: "replacement", files: ["new.ifc"] }) } });
  host.viewer.load = async () => { throw new Error("Invalid IFC"); };
  const stats = host.state.stats; host.open(); await host.settle();
  assert.equal(host.state.sceneId, "scene"); assert.equal(host.state.stats, stats); assert.equal(host.state.a, "duct");
  assert.equal(host.button("Check this move").props.disabled, false);
  const loads = []; let n = 0;
  host.api.open = async () => ({ id: `scene-${++n}`, files: ["next.ifc"] });
  host.viewer.load = (_bytes, _names, isCurrent) => new Promise((resolve) => loads.push({ isCurrent, resolve }));
  host.open(); await host.settle(); assert.equal(host.button("Check this move").props.disabled, true);
  host.open(); await host.settle(); assert.equal(loads[0].isCurrent(), false); assert.equal(loads[1].isCurrent(), true);
  const currentStats = { elements: 42, triangles: 42, parseMs: 42 };
  loads[1].resolve(currentStats); await host.settle(); loads[0].resolve({ elements: 99 }); await host.settle();
  assert.equal(host.state.sceneId, "scene-2"); assert.equal(host.state.stats, currentStats); host.unmount();
});

test("a wider response after scene replacement cannot write evidence, files or busy state into its successor", async () => {
  let finishApply, finishOpen, fetched = [];
  const host = await appHost({ api: { applyContext: () => new Promise((resolve) => { finishApply = resolve; }),
    open: () => new Promise((resolve) => { finishOpen = () => resolve({ id: "new-scene", files: ["new.ifc"] }); }),
    file: async (sid) => { fetched.push(sid); return new Uint8Array([1]); } } });
  await wider(host); const accept = host.component("ContextPlan").props.onAccept(); host.render();
  host.open(); const busy = host.state.busy;
  finishApply({ files: [0], edits: contextProposal.edits, resolved_pairs: [{ element_a: "duct", element_b: "beam" }], checks });
  await accept; host.render(); assert.equal(host.state.busy, busy); assert.deepEqual(host.state.evidence, {}); assert.deepEqual(fetched, []);
  finishOpen(); await host.settle(); assert.equal(host.state.sceneId, "new-scene"); assert.deepEqual(fetched, ["new-scene"]);
  host.unmount();
});

test("sample and upload report replacement cannot interrupt wider apply, download or parse in the same scene", async () => {
  for (const window of ["apply", "download", "parse"]) for (const path of ["sample", "folder", "files"]) {
    let finishApply, finishFile, finishParse, reportRequests = 0, downloads = 0, replacements = 0, predicate;
    const applied = { files: [0], edits: contextProposal.edits, resolved_pairs: [{ element_a: "duct", element_b: "beam" }], checks };
    const nextReport = { id: "report-two", title: "Report two", clashes: [] };
    const host = await appHost({ api: {
      applyContext: () => window === "apply" ? new Promise((resolve) => { finishApply = () => resolve(applied); }) : Promise.resolve(applied),
      file: () => { downloads++; return window === "download" ? new Promise((resolve) => { finishFile = () => resolve(new Uint8Array([1])); }) : Promise.resolve(new Uint8Array([1])); },
      openReport: async () => { reportRequests++; return nextReport; }, uploadReport: async () => { reportRequests++; return nextReport; },
    } });
    host.viewer.replace = async (_index, _bytes, isCurrent) => {
      predicate = isCurrent;
      if (window === "parse") await new Promise((resolve) => { finishParse = resolve; });
      if (isCurrent()) replacements++;
    };
    await wider(host); const accept = host.component("ContextPlan").props.onAccept(); await host.settle();
    const report = host.state.report, busy = host.state.busy, epoch = host.refs.sceneEpoch.current, request = host.refs.contextRequest.current;
    const menu = host.reportMenu();
    const entry = find(menu, (n) => n.type === "button" && hasText(n, path === "sample" ? "sample" : path === "folder" ? "Upload an export folder" : "Upload XML files"));
    // Drive the actual handler even when disabled: file dialogs opened before apply may return during it.
    if (path === "sample") entry.props.onClick();
    else host.fileInput(path).props.onChange({ target: { files: [{ name: "report.xml" }], value: "report.xml" } });
    await host.settle();
    assert.equal(reportRequests, 0, `${window}/${path}: report IO must not start`);
    assert.equal(entry.props.disabled, true); assert.equal(host.fileInput("folder").props.disabled, true); assert.equal(host.fileInput("files").props.disabled, true);
    assert.equal(host.state.report, report); assert.equal(host.state.busy, busy);
    assert.equal(host.refs.sceneEpoch.current, epoch); assert.equal(host.refs.contextRequest.current, request);
    if (window === "apply") finishApply(); else if (window === "download") finishFile(); else { assert.equal(predicate(), true); finishParse(); }
    await accept; await host.settle();
    assert.equal(downloads, 1); assert.equal(replacements, 1); assert.equal(host.state.sceneId, "scene");
    assert.equal(host.state.context.accepted, true); assert.equal(host.state.evidence.clash.status, "accepted"); assert.equal(host.state.busy, null);
    // The same entry point works again after committed geometry has been adopted.
    if (path === "sample") host.loadReport();
    else host.fileInput(path).props.onChange({ target: { files: [{ name: "report.xml" }], value: "report.xml" } });
    await host.settle(); assert.equal(reportRequests, 1); assert.equal(host.state.report.id, "report-two");
    host.unmount();
  }
});

test("failed API open or download preserves the prior scene id, selection, stats and usability", async () => {
  for (const failure of ["open", "file"]) {
    const host = await appHost({ api: { open: async () => { if (failure === "open") throw new Error("Open failed"); return { id: "new", files: ["new.ifc"] }; },
      file: async () => { throw new Error("Download failed"); } } });
    const stats = host.state.stats; host.open(); await host.settle();
    assert.equal(host.state.sceneId, "scene"); assert.equal(host.state.a, "duct"); assert.equal(host.state.b, "beam"); assert.equal(host.state.stats, stats);
    assert.equal(host.button("Propose fixes").props.disabled, false); assert.equal(host.button("Explore wider fix").props.disabled, false);
    host.unmount();
  }
});

test("actual wider NDJSON receives the request signal and cancels an aborted reader without publishing buffered events", async (t) => {
  const { api } = await import(await compiled("../src/api.ts"));
  const controller = new AbortController(), events = []; let stream, cancelled = false, signal;
  t.mock.method(globalThis, "fetch", async (_url, init) => { signal = init.signal;
    return new Response(new ReadableStream({ start(c) { stream = c; }, cancel() { cancelled = true; } })); });
  const work = api.contextStream("scene", contextProposal.objective, (e) => events.push(e), controller.signal);
  await flush(); controller.abort(); stream.enqueue(new TextEncoder().encode(`${JSON.stringify(contextResult)}\n`));
  await work; assert.equal(signal, controller.signal); assert.equal(cancelled, true); assert.deepEqual(events, []);
});

test("actual wider API treats a fetch abort as intentional and reports unexpected truncated streams", async (t) => {
  const { api } = await import(await compiled("../src/api.ts")); const controller = new AbortController();
  t.mock.method(globalThis, "fetch", async (_url, init) => new Promise((_resolve, reject) => {
    init.signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
  }));
  const work = api.contextStream("scene", contextProposal.objective, () => {}, controller.signal); controller.abort(); await work;
  globalThis.fetch = async () => new Response("");
  await assert.rejects(api.contextStream("scene", contextProposal.objective, () => {}), /stopped before/);
});

test("actual model download rejects HTTP failure before handing bytes to the IFC loader", async (t) => {
  const { api } = await import(await compiled("../src/api.ts"));
  t.mock.method(globalThis, "fetch", async () => new Response("Server error", { status: 500 }));
  await assert.rejects(api.file("scene", 0), /Model download failed \(500\)/);
});
