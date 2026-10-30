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
  combined: "Combined",
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

/** A move in words, on the model's axes (+X east, +Y north, +Z up, as the server names them): "north 250 mm",
 * "west 100 mm, up 400 mm". */
export function moveWords(delta: number[]) {
  const names = [["east", "west"], ["north", "south"], ["up", "down"]];
  const out = delta.map((v, k) => Math.abs(v) >= 0.0005 ? `${names[k][v > 0 ? 0 : 1]} ${Math.abs(Math.round(v * 1000))} mm` : "").filter(Boolean);
  return out.join(", ") || "0 mm";
}

/** The edit a fix makes, in a few words: "move up 400 mm", "offset 1.10–2.30 m by +400 mm", "trim one end 60 mm", or
 * the server's summary for the newer kinds. */
export const editText = (t: EditLike) => t.edit?.summary
  ? t.edit.summary
  : t.kind === "offset" && t.split_m
    ? `offset ${t.split_m.map((v) => v.toFixed(2)).join("–")} m by ${mm(t.delta_m[2])}`
    : t.kind === "trim"
      ? t.trim ? `trim one end ${Math.round(t.trim.by_m * 1000)} mm` : "trim at the joint"
      : `move ${moveWords(t.delta_m)}`;

/** What a fix leaves between the elements: a trim butts them, anything else keeps a measured clearance (a gap, so
 * unsigned; a verified fix never overlaps). */
export const clearanceText = (o: Pick<Option, "kind" | "min_clearance_m">) => o.kind === "trim" ? "butt joint"
  : o.min_clearance_m == null ? "nothing within 500 mm" : o.min_clearance_m < 0 ? mm(o.min_clearance_m) : `${Math.round(o.min_clearance_m * 1000)} mm`;

/** What else a fix needs, without the "none" Muse copies from the prompt's examples ("re-fix anchors; none"). */
export const needsText = (text: string | null | undefined) => (text ?? "").split(";").map((x) => x.trim())
  .filter((x) => x && !["none", "nothing", "n/a", "-"].includes(x.replace(/\.$/, "").toLowerCase())).join("; ");

/** The new pieces to frame when showing a fix: the risers, bends and middle of a split run (not its shortened ends),
 * an opening's provision for void (not the whole wall it goes through). Empty: frame where the moved element meets
 * the other side instead. */
export function framePieces<M>(o: { kind: string; preview: M[] | null }): M[] {
  if (!o.preview) return [];
  if (o.kind === "offset" || o.kind === "route" || o.kind === "resize") return o.preview.slice(1, -1);
  if (o.kind === "penetration") return o.preview.slice(0, 1);
  if (o.kind === "combined") return o.preview;   // every element it changes, where it now is
  return [];
}

/** An opening's host, for the option card: what may be done to it (ORCA's reading of that kind of host, or the
 * requirements) and the hole against its limits. */
export function hostRows(o: Pick<Option, "kind" | "edit">): [string, string][] {
  if (o.kind !== "penetration" || !o.edit) return [];
  const out: [string, string][] = [];
  const { host_reading: reading, numbers, reading_source: source } = o.edit;
  if (typeof reading === "string" && reading) {
    out.push(["Host", reading + (source === "requirements" ? " (requirements)" : source === "muse" ? " (the AI's reading)" : "")]);
  }
  if (Array.isArray(numbers) && numbers.length) out.push(["Hole", numbers.join("; ")]);
  return out;
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
