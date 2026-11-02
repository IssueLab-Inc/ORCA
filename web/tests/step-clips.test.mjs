import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { compiled } from "./app-host.mjs";

const { webpDuration } = await import(await compiled("../src/stepClips.ts"));
const bytes = async (name) => { const b = await readFile(new URL(`../public/demos/${name}`, import.meta.url)); return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength); };

/** A RIFF/WEBP file of the given chunks: [tag, payload bytes]. */
function webp(chunks) {
  const body = chunks.flatMap(([tag, data]) => {
    const pad = data.length & 1 ? [0] : [];
    const size = [data.length & 255, (data.length >> 8) & 255, (data.length >> 16) & 255, 0];
    return [...Buffer.from(tag), ...size, ...data, ...pad];
  });
  const total = 4 + body.length;
  return new Uint8Array([...Buffer.from("RIFF"), total & 255, (total >> 8) & 255, (total >> 16) & 255, 0, ...Buffer.from("WEBP"), ...body]).buffer;
}
// An ANMF payload: x, y, width-1, height-1 (3 bytes each), then the duration (3 bytes), flags, and the frame's data.
const frame = (ms) => [0, 0, 0, 0, 0, 0, 9, 0, 0, 9, 0, 0, ms & 255, (ms >> 8) & 255, (ms >> 16) & 255, 0, 1, 2, 3];

test("an animated WebP lasts as long as its frames together", () => {
  assert.equal(webpDuration(webp([["VP8X", new Array(10).fill(0)], ["ANIM", [0, 0, 0, 0, 0, 0]], ["ANMF", frame(100)], ["ANMF", frame(2600)]])), 2700);
});

test("odd-sized chunks are padded, and frames after them still count", () => {
  assert.equal(webpDuration(webp([["VP8X", new Array(10).fill(0)], ["ANMF", frame(100)], ["EXIF", [1, 2, 3]], ["ANMF", frame(250)]])), 350);
});

test("a still WebP and anything else have no length", () => {
  assert.equal(webpDuration(webp([["VP8 ", [1, 2, 3, 4]]])), null);
  assert.equal(webpDuration(new TextEncoder().encode("not a picture at all").buffer), null);
  assert.equal(webpDuration(new ArrayBuffer(4)), null);
});

test("the landing's step clips are read as the encoder wrote them", async () => {
  // keep.webp: 9.9 s by the encoder (frames at 10 a second, held frames merged, 2.5 s on the last).
  const ms = webpDuration(await bytes("keep.webp"));
  assert.ok(ms > 9000 && ms < 11000, `keep.webp lasts ${ms} ms`);
  assert.equal(webpDuration(await bytes("keep-still.webp")), null);
});
