import assert from "node:assert/strict";
import test from "node:test";
import { appHost } from "./app-host.mjs";

const mine = { id: "u1", name: "My ducts", on: true, when: [{ facet: "class", op: "is", values: ["IfcDuctSegment"] }], action: "colour", colour: "#318181" };
const off = { ...mine, id: "u2", name: "Off already", on: false };
const chats = { id: "chat0", name: "", on: true, when: [{ facet: "storey", op: "is", values: ["Level 02"] }], action: "isolate", origin: "chat" };

test("chat's filters replace its own, pause the user's that were on, and give them back when it clears", async () => {
  const host = await appHost({ initial: { filterState: { v: 1, colours: false, greyRest: false, rules: [mine, off] } } });
  host.chat({ type: "ui", action: "filters", mode: "replace", filters: [chats], grey_rest: true });
  let st = host.state.filterState;
  assert.deepEqual(st.rules.map((r) => [r.id, r.on, !!r.paused]), [["chat0", true, false], ["u1", false, true], ["u2", false, false]]);
  assert.equal(st.colours, true, "chat's colours show"); assert.equal(st.greyRest, true);
  host.chat({ type: "ui", action: "filters", mode: "replace", filters: [{ ...chats, id: "chat1" }] });
  st = host.state.filterState;
  assert.deepEqual(st.rules.map((r) => r.id), ["chat1", "u1", "u2"], "its next filters replace its own");
  host.chat({ type: "ui", action: "filters", mode: "clear" });
  st = host.state.filterState;
  assert.deepEqual(st.rules.map((r) => [r.id, r.on, !!r.paused]), [["u1", true, false], ["u2", false, false]]);
});

test("chat can hide the rest, which stops greying it, and grey it again, which stops hiding it", async () => {
  const host = await appHost({ initial: { filterState: { v: 1, colours: true, greyRest: true, hideRest: false, rules: [mine] } } });
  host.chat({ type: "ui", action: "filters", mode: "replace", filters: [chats], hide_rest: true });
  assert.deepEqual([host.state.filterState.greyRest, host.state.filterState.hideRest], [false, true]);
  host.chat({ type: "ui", action: "filters", mode: "replace", filters: [chats], grey_rest: true });
  assert.deepEqual([host.state.filterState.greyRest, host.state.filterState.hideRest], [true, false]);
  host.chat({ type: "ui", action: "filters", mode: "replace", filters: [chats] });
  assert.deepEqual([host.state.filterState.greyRest, host.state.filterState.hideRest], [true, false], "not said: kept");
  host.chat({ type: "ui", action: "filters", mode: "replace", filters: [chats], hide_rest: false });
  assert.deepEqual([host.state.filterState.greyRest, host.state.filterState.hideRest], [true, false], "hide_rest false leaves grey as it is");
});
