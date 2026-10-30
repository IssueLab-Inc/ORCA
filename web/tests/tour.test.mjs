import assert from "node:assert/strict";
import test from "node:test";
import { compiled, hasText } from "./app-host.mjs";

const module = (js) => `data:text/javascript;base64,${Buffer.from(js).toString("base64")}`;
const react = module("export const useState=()=>[null,()=>{}],useRef=()=>({current:null}),useEffect=()=>{},useLayoutEffect=()=>{};");
const icons = module(["ArrowLeft", "ArrowRight", "Hand", "PlayCircle", "X"].map((n) => `export function ${n}(){return null;}`).join("\n"));
const tour = await import(await compiled("../src/Tour.tsx", {
  "react/jsx-runtime": import.meta.resolve("react/jsx-runtime"), react, "lucide-react": icons }));

const state = (over = {}) => ({ busy: false, reportOpen: true, modelsOpen: true, triageStarted: true, triageDone: true,
  triageCount: 112, triageTotal: 112, realCount: 5, filter: null, clashId: null, tab: "clash", triageOpen: false,
  fixHidden: false, proposing: false, proposingFor: 0, options: 0, optionKinds: [], proposalDone: false, error: null,
  replaying: false, compare: "after", fixed: [], planRunning: false, planFor: 0, planReady: false, planError: null,
  patternsRead: false, reviewedCount: 0, signoffs: 0, docOpen: false, docReady: false, reqOpen: false, requirements: null,
  reqRules: 0, duct: null, joint: null, cellOpen: true, ladder: { id: "s1", number: 61 }, pipes: [], ...over });
const step = (steps, title) => steps.find((s) => s.title === title);

test("the cell tour says what the current cell holds", () => {
  assert.ok(hasText(tour.CELL_STEPS[0].body(state()), "161 parts"));
  assert.ok(hasText(step(tour.CELL_STEPS, "What ORCA found").body(state()), "Eight problems"));
  const last = tour.CELL_STEPS.at(-1).body(state());
  assert.ok(hasText(last, "17 of 17") && hasText(last, "161") && !hasText(last, "144"));
});

test("the ladder's fix is described as the option shown, live or recorded", () => {
  const ask = step(tour.CELL_STEPS, "Ask for a fix");
  const offset = ask.body(state({ proposalDone: true, options: 2, optionKinds: ["offset", "move"] }));
  assert.ok(hasText(offset, "local offset") && hasText(offset, "Another option raises the whole ladder"));
  const move = ask.body(state({ proposalDone: true, options: 1, optionKinds: ["move"] }));
  assert.ok(hasText(move, "whole ladder goes up") && hasText(move, "move as one") && !hasText(move, "Another option"));
  const alone = ask.body(state({ proposalDone: true, options: 1, optionKinds: ["offset"] }));
  assert.ok(!hasText(alone, "whole ladder"));
});

test("accepting says the viewer patches in place, not that it reloads", () => {
  for (const s of [...tour.BUILDING_STEPS, ...tour.CELL_STEPS].filter((x) => x.title === "Accept it"))
    assert.ok(hasText(s.body(state()), "without reloading") && !hasText(s.body(state()), "reloads"));
});

test("a live proposal that failed or found nothing offers the recorded run", () => {
  for (const [steps, title] of [[tour.CELL_STEPS, "Ask for a fix"], [tour.BUILDING_STEPS, "ORCA takes the camera"], [tour.BUILDING_STEPS, "Ask again"]]) {
    const offer = step(steps, title).fallback.when;
    assert.equal(offer(state({ proposalDone: true, options: 0, error: "Request failed (503)" })), true, title);
    assert.equal(offer(state({ proposalDone: true, options: 0 })), true, title);
    assert.equal(offer(state({ proposalDone: true, options: 2 })), false, title);
    assert.equal(offer(state({ proposing: true, proposingFor: 10 })), false, title);
    assert.equal(offer(state({ proposing: true, proposingFor: 50 })), true, title);
    assert.equal(offer(state({ proposalDone: true, options: 0, replaying: true })), false, title);
  }
});

test("a plan that failed to start moves on to the step that offers its recording", () => {
  for (const [steps, title] of [[tour.CELL_STEPS, "One pipe, two rails"], [tour.BUILDING_STEPS, "Why so many on Level 02?"]]) {
    const s = step(steps, title);
    assert.equal(s.done(state()), false, title);
    assert.equal(s.done(state({ planError: "Request failed (503)" })), true, title);
  }
  assert.equal(step(tour.CELL_STEPS, "One fix for both rails").fallback.when(state({ planError: "Request failed (503)" })), true);
});
