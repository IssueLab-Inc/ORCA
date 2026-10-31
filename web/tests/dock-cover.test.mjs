import assert from "node:assert/strict";
import test from "node:test";
import { appHost, find } from "./app-host.mjs";

// Frames run when the test says, so the cover's wait for the dock can be watched step by step.
const frames = [];
globalThis.requestAnimationFrame = (fn) => { frames.push(fn); return frames.length; };
globalThis.cancelAnimationFrame = () => {};
const frame = (host) => { const due = frames.splice(0); for (const fn of due) fn(); host.render(); };

const start = { stats: null, report: null, sceneId: null, clash: null, a: null, b: null, matches: null };
const cover = (host) => host.find((n) => typeof n.props?.className === "string" && n.props.className.startsWith("load-cover"));
const cards = (node) => { let n = 0; find(node, (x) => { if (x.type?.name === "LoadCard") n++; return false; }); return n; };

test("opening the first models on a desktop: the loading screen covers the switch into the dock until the model is in its panel", async () => {
  let finish;
  const host = await appHost({ layout: "desktop", initial: start,
    api: { open: () => new Promise((resolve) => { finish = () => resolve({ id: "new", files: ["new.ifc"] }); }) } });
  host.open(); host.render();
  assert.ok(cover(host), "the loading screen is the cover");
  assert.equal(cards(cover(host)), 1, "with the load card");
  assert.equal(cards(host.find(() => true)), 1, "the stage's own card is not drawn under it");
  finish(); await host.settle();
  assert.ok(host.state.stats, "the models are open");
  assert.equal(host.state.dockCover, "on", "the dock has come in under the cover");
  assert.equal(cards(cover(host)), 1, "the card stays as the opening ended");
  frame(host); frame(host);
  assert.equal(host.state.dockCover, "on", "the model is not in its panel yet: the cover holds");
  host.refs.host.current = { isConnected: true, clientWidth: 900, closest: (s) => (s === ".dock-host" ? {} : null) };
  frame(host); frame(host);
  assert.equal(host.state.dockCover, "on", "two frames drawn there: not yet");
  frame(host);
  assert.equal(host.state.dockCover, "out", "three frames in its panel: the cover fades");
  assert.ok(cover(host).props.className.includes("out"));
  host.runTimers();
  assert.equal(host.state.dockCover, null); assert.equal(cover(host), undefined);
  host.unmount();
});

test("models opened again over open ones, or without the dock: no cover", async () => {
  const again = await appHost({ layout: "desktop", api: { open: async () => ({ id: "new", files: ["new.ifc"] }) } });
  again.open(); again.render();
  assert.equal(cover(again), undefined, "the old models stay on screen while the new ones load");
  await again.settle(); assert.equal(cover(again), undefined); again.unmount();
  const phone = await appHost({ layout: "phone", initial: start, api: { open: async () => ({ id: "new", files: ["new.ifc"] }) } });
  assert.equal(cover(phone), undefined); phone.unmount();
});
