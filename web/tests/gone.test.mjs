import assert from "node:assert/strict";
import test from "node:test";
import { appHost, compiled, option } from "./app-host.mjs";

const { api, goneOf, setGoneHandler } = await import(await compiled("../src/api.ts"));
const LOST = "Model not loaded. Open it again.";

test("a 404 naming a scene or report the server let go of reaches the page once, with the server's words", async () => {
  const told = [];
  setGoneHandler((g) => told.push(g));
  const answers = [
    new Response(JSON.stringify({ detail: LOST }), { status: 404, headers: { "X-Sightline-Gone": "scene:00f9ee9f67ff" } }),
    new Response(JSON.stringify({ detail: "No such element in these models." }), { status: 404 }),
  ];
  globalThis.fetch = async () => answers.shift();
  await assert.rejects(api.classes("00f9ee9f67ff"), new RegExp(LOST));
  await assert.rejects(api.properties("00f9ee9f67ff", "g"), /No such element/);
  assert.deepEqual(told, [{ kind: "scene", id: "00f9ee9f67ff", detail: LOST }]);
  setGoneHandler(null);

  const headers = (v) => new Headers({ "X-Sightline-Gone": v });
  assert.deepEqual(goneOf({ status: 404, headers: headers("report:ab12") }), { kind: "report", id: "ab12" });
  assert.equal(goneOf({ status: 200, headers: headers("scene:ab12") }), null);   // only on a 404
  assert.equal(goneOf({ status: 404, headers: headers("model:ab12") }), null);
  assert.equal(goneOf({ status: 404, headers: new Headers() }), null);
});

const accepted = { status: "accepted", title: "Raise the duct", kind: "move", edit: "", clearance: "", clearance_m: .05, rationale: "",
  also_needs: "", moved: ["duct"] };
const detected = (id) => ({ type: "done", report: { id, title: "Run", clashes: [], origin: "sightline", sources: ["model.ifc"] },
  coverage: {}, diff: null, elements: 2, seconds: 1 });

test("models the server let go of: one notice, kept fixes no longer claimed, and the same models and check again", async () => {
  const opened = [], checked = [];
  const host = await appHost({
    initial: { sceneFiles: ["model.ifc"], report: { id: "report", title: "Run", clashes: [], origin: "sightline", sources: ["model.ifc"] } },
    api: { open: async (names) => { opened.push(names); return { id: "scene-2", files: names }; },
           detect: async (sid) => { checked.push(sid); return detected("report-2"); } } });
  await host.settle();
  host.state.fixes = { clash: "Raise the duct" };
  host.state.evidence = { clash: accepted, other: { ...accepted, status: "proposed" } };
  host.state.error = LOST; host.render();
  const errorLine = () => host.find((n) => String(n.props?.className).includes("overlay error"));
  const exportLink = () => host.find((n) => n.props?.["data-tour"] === "export");
  assert.ok(errorLine() && exportLink());

  host.gone({ kind: "scene", id: "another-scene", detail: LOST });   // a late answer about models since replaced
  assert.equal(host.button("Open them again"), undefined);
  assert.deepEqual(host.state.fixes, { clash: "Raise the duct" });

  host.gone({ kind: "scene", id: "scene", detail: LOST });
  assert.deepEqual(host.state.fixes, {});
  assert.deepEqual(Object.keys(host.state.evidence), ["other"]);
  assert.ok(host.button("Open them again"));
  assert.equal(errorLine(), undefined);   // the call that failed said so too: the notice says it once
  assert.equal(exportLink(), undefined);   // nothing left to export from

  host.button("Open them again").props.onClick();
  await host.settle();
  assert.deepEqual(opened, [["model.ifc"]]);
  assert.deepEqual(checked, ["scene-2"]);
  assert.equal(host.state.sceneId, "scene-2");
  assert.equal(host.state.report.id, "report-2");
  assert.equal(host.find((n) => n.props?.className === "overlay gone"), undefined);
  host.gone({ kind: "report", id: "report", detail: "Clash report not loaded. Open it again." });   // the old one, late
  host.state.error = "Clash report not loaded. Open it again."; host.render();   // and the call that asked says so
  assert.equal(host.find((n) => n.props?.className === "overlay gone"), undefined);
  assert.equal(errorLine(), undefined);
  host.unmount();
});

test("the visitor's own models are picked again; a sample report is opened again; Show it built offers the reopen", async () => {
  const host = await appHost({ initial: { sceneFiles: ["mine.ifc"], builtOn: true, chosen: 0,
    proposal: { understanding: "", options: [option], attempts: [] } },
    api: { models: async () => ({ triage: { model: "m", open_weights: false }, built_views: true }) } });
  await host.settle();
  let picked = 0;
  host.refs.modelInput.current = { click() { picked++; } };
  host.state.builtRuns = { "beam|duct|move|Single fix|[[0,0,0.4],null,null,null]": { status: "failed", step: "", look: "", cut: "", error: LOST } };
  host.render();
  assert.equal(host.component("BuiltView").props.reopen, undefined);   // the models are there: Try again stands

  host.gone({ kind: "scene", id: "scene", detail: LOST });
  const built = host.component("BuiltView").props.reopen;
  assert.equal(built.label, "Pick your files again");   // not a sample: only the visitor has the files
  built.onClick();
  await host.settle();
  assert.equal(picked, 1);
  host.unmount();

  const reports = [], asked = [];
  const again = await appHost({ api: { openReport: async (s) => { reports.push(s); return { id: `r-${reports.length}`, title: s, clashes: [] }; },
    report: async () => { throw new Error("Clash report not loaded. Open it again."); },
    sceneInfo: async (sid) => { asked.push(sid); return { id: sid, files: [], detection: null }; } } });
  again.loadReport();
  await again.settle();
  const first = again.state.report.id;
  again.gone({ kind: "report", id: first, detail: "Clash report not loaded. Open it again." });
  assert.ok(again.button("Open it again"));   // the report, not the models
  assert.deepEqual(asked, ["scene"]);   // a restart drops both: the models are asked after (here still held)
  again.button("Open it again").props.onClick();
  await again.settle();
  assert.deepEqual(reports, ["sample", "sample"]);
  assert.notEqual(again.state.report.id, first);
  assert.equal(again.find((n) => n.props?.className === "overlay gone"), undefined);
  again.unmount();
});
