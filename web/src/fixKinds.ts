import type { Attempt, FixKind, Option, Recommendation } from "./api";

/** Every kind of fix, described in one place: its name, the edit in a few words, what to frame, who must review it.
 * The newer kinds (route, resize, penetration) carry the server's own `edit.summary`, so the words match what Muse
 * was told. */

/** Signed millimetres, as the rest of the app shows them ("+400 mm"); no "-0 mm" for touching elements. */
function mm(m: number | null | undefined) {
  if (m == null) return "—";
  const v = Math.round(m * 1000) || 0;
  return `${v > 0 ? "+" : ""}${v} mm`;
}

export const KIND_LABEL: Record<FixKind, string> = {
  move: "Move", offset: "Offset", trim: "Trim", route: "Reroute", resize: "Resize", penetration: "Opening",
};
export const kindLabel = (kind: string) => KIND_LABEL[kind as FixKind] ?? kind;

/** Who must review a fix before it is built, in plain words (server: Option.review). */
const REVIEW: Record<string, string> = {
  structure: "Needs the structural engineer's review",
  services: "Needs the services designer's review",
  architecture: "Needs the architect's review",
  fire: "Needs the fire engineer's review",
  safety: "Needs a machine safety review",
};
export const reviewText = (review: string | null | undefined) => review ? REVIEW[review] ?? `Needs ${review} review` : "";

type EditLike = Pick<Attempt, "kind" | "split_m" | "delta_m" | "trim"> & { edit?: Option["edit"] };

/** The edit a fix makes, in a few words: "move 0 · 0 · +400 mm", "offset 1.10–2.30 m by +400 mm", "trim one end
 * 60 mm", or the server's summary for the newer kinds. */
export const editText = (t: EditLike) => t.edit?.summary
  ? t.edit.summary
  : t.kind === "offset" && t.split_m
    ? `offset ${t.split_m.map((v) => v.toFixed(2)).join("–")} m by ${mm(t.delta_m[2])}`
    : t.kind === "trim"
      ? t.trim ? `trim one end ${Math.round(t.trim.by_m * 1000)} mm` : "trim at the joint"
      : `move ${t.delta_m.map((v) => mm(v)).join(" · ")}`;

/** What a fix leaves between the elements: a trim butts them, anything else keeps a measured clearance. */
export const clearanceText = (o: Pick<Option, "kind" | "min_clearance_m">) => o.kind === "trim" ? "butt joint" : mm(o.min_clearance_m);

/** The new pieces to frame when showing a fix: the risers, bends and middle of a split run (not its shortened ends),
 * all of an opening. Empty: frame where the moved element meets the other side instead. */
export function framePieces<M>(o: { kind: string; preview: M[] | null }): M[] {
  if (!o.preview) return [];
  if (o.kind === "offset" || o.kind === "route" || o.kind === "resize") return o.preview.slice(1, -1);
  if (o.kind === "penetration") return o.preview;
  return [];
}

function offsetParts(pieces: number) {
  return pieces > 5 ? `4 bends${pieces === 9 ? " and 2 short risers" : ""}` : "square corners";
}

/** The "Change" line of the before/after summary. */
export function changeText(o: Option) {
  if (o.kind === "offset" && o.split_m) {
    return `${(o.split_m[1] - o.split_m[0]).toFixed(2)} m of it ${o.delta_m[2] > 0 ? "raised" : "lowered"} ${Math.abs(Math.round(o.delta_m[2] * 1000))} mm; ${offsetParts(o.preview?.length ?? 5)}`;
  }
  if (o.kind === "trim" && o.trim) return `one end cut back ${Math.round(o.trim.by_m * 1000)} mm; nothing moves`;
  if (o.edit?.summary) return o.edit.summary;
  return `${o.moved.length} element${o.moved.length > 1 ? "s" : ""} moved ${o.delta_m.map((v) => mm(v)).join(" · ")}`;
}

/** A recommendation's change, in a few words (never tried: the requirements allowed no edit). */
export function recEditText(r: Pick<Recommendation, "kind" | "delta_m" | "edit">) {
  const d = r.delta_m ?? [0, 0, 0];
  if (r.edit?.summary) return r.edit.summary;
  if (r.kind === "trim") return "trim at the joint";
  if (r.kind === "offset") return `offset the middle ${d[2] >= 0 ? "up" : "down"} ${Math.abs(Math.round(d[2] * 1000))} mm`;
  if (r.kind !== "move") return kindLabel(r.kind).toLowerCase();
  const size = Math.round(Math.max(...d.map(Math.abs)) * 1000);
  return size ? `move ${size} mm` : "";
}
