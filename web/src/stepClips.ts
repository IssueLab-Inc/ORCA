/**
 * The landing's step clips ("What ORCA does", About.tsx): animated WebP time-lapses made by
 * web/scripts/capture-proposals.cjs --landing. The player shows one at a time and moves on when it has played once, so
 * it needs each clip's length, and needs it to start from its first frame every time its step comes round.
 */

/** The length of an animated WebP in milliseconds, its frames' durations added up (ANMF chunks); null when it is not
 * one. Read from the file, so a recaptured clip needs no change here. */
export function webpDuration(buf: ArrayBuffer): number | null {
  const v = new DataView(buf);
  const tag = (o: number) => String.fromCharCode(v.getUint8(o), v.getUint8(o + 1), v.getUint8(o + 2), v.getUint8(o + 3));
  if (buf.byteLength < 12 || tag(0) !== "RIFF" || tag(8) !== "WEBP") return null;
  let total = 0, frames = 0;
  for (let o = 12; o + 8 <= buf.byteLength;) {
    const size = v.getUint32(o + 4, true);
    if (tag(o) === "ANMF" && o + 8 + 15 <= buf.byteLength) {
      // The frame's x, y, width - 1 and height - 1 (3 bytes each), then its duration (3 bytes, little-endian).
      const p = o + 8 + 12;
      total += v.getUint8(p) | (v.getUint8(p + 1) << 8) | (v.getUint8(p + 2) << 16);
      frames++;
    }
    o += 8 + size + (size & 1);   // chunks are padded to an even size
  }
  return frames ? total : null;
}

export interface LoadedClip { blob: Blob; ms: number | null }
const loaded = new Map<string, Promise<LoadedClip | null>>();

/** A clip's bytes and length, fetched once. The player shows each playing from a fresh object URL of these bytes: a new
 * picture to the browser, so it starts from its first frame (the same URL again would carry on where it was), with no
 * second download. Null when it cannot be fetched (the player then shows it plainly and does not move on by itself). */
export function loadClip(src: string): Promise<LoadedClip | null> {
  let clip = loaded.get(src);
  if (!clip) {
    clip = fetch(src)
      .then((r) => (r.ok ? r.arrayBuffer() : Promise.reject(new Error(`${r.status}`))))
      .then((b) => ({ blob: new Blob([b], { type: "image/webp" }), ms: webpDuration(b) }))
      .catch(() => null);
    loaded.set(src, clip);
  }
  return clip;
}
