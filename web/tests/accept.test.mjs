import assert from "node:assert/strict";
import test from "node:test";
import { compiled } from "./app-host.mjs";

const { api, ApiError } = await import(await compiled("../src/api.ts"));

test("every kind is kept through fix/apply with the clash it was verified for, and a refusal says why", async () => {
  const posted = [];
  globalThis.fetch = async (url, init) => {
    posted.push([url, JSON.parse(init.body).option]);
    return new Response(JSON.stringify({ files: [0], pieces: [] }), { status: 200 });
  };
  const offset = { title: "Up 400", kind: "offset", moved: ["duct"], delta_m: [0, 0, 0.4], split_m: [2.6, 3.4],
    preview: [{ global_id: "duct" }], before: [{ global_id: "duct" }] };
  await api.accept("s1", offset, ["duct", "beam"]);                                   // a recorded run: no pair of its own
  await api.accept("s1", { ...offset, kind: "move", pair: ["duct", "girder"] }, ["duct", "beam"]);   // its own wins
  assert.deepEqual(posted.map(([url]) => url), ["/api/scenes/s1/fix/apply", "/api/scenes/s1/fix/apply"]);
  assert.deepEqual(posted.map(([, o]) => o.pair), [["duct", "beam"], ["duct", "girder"]]);
  assert.equal(posted[0][1].preview, null); assert.equal(posted[0][1].before, null);

  const why = "'Up 400' does not pass ORCA's check on the model as it is now (collision with IfcSlab (-50 mm)), so nothing was kept.";
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: why }), { status: 409 });
  await assert.rejects(api.accept("s1", offset, ["duct", "beam"]),
    (e) => e instanceof ApiError && e.status === 409 && e.message === why);
});
