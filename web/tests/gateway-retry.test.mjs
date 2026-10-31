import assert from "node:assert/strict";
import test from "node:test";
import { compiled } from "./app-host.mjs";

const { api, GATEWAY_WAITS } = await import(await compiled("../src/api.ts"));
GATEWAY_WAITS.splice(0, GATEWAY_WAITS.length, 1, 1);   // no real waiting in a test

const answer = (status, body) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

test("a patterns reading the gateway drops (502, 504, no answer) is asked for again, up to twice", async () => {
  const seen = [];
  const replies = [() => answer(502, {}), () => { throw new TypeError("Failed to fetch"); }, () => answer(200, { p1: { verdict: "real" } })];
  globalThis.fetch = async (url) => { seen.push(url); return replies[seen.length - 1](); };
  assert.deepEqual(await api.triagePatterns("r1", "s1", []), { p1: { verdict: "real" } });
  assert.equal(seen.length, 3);
  seen.length = 0;
  globalThis.fetch = async (url) => { seen.push(url); return answer(504, {}); };
  await assert.rejects(api.triagePatterns("r1", "s1", []), (e) => e.status === 504);
  assert.equal(seen.length, 3, "the first try and two more, then it gives up");
});

test("what the server itself says is not asked again: a refusal (429) or an error (500) stands", async () => {
  for (const status of [429, 500]) {
    let n = 0;
    globalThis.fetch = async () => { n++; return answer(status, { detail: "no" }); };
    await assert.rejects(api.triagePatterns("r1", "s1", []), (e) => e.status === status);
    assert.equal(n, 1);
  }
});
