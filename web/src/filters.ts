/** Filters (docs/filters.md): named rules over the server's index (`GET /api/scenes/{id}/facets`), each finding
 * elements by what the model says about them and then colouring, colouring by value, hiding or isolating them. Several
 * are on at once; the top one wins where two colour the same element. Pure: App keeps the state, the viewer draws the
 * result (`Viewer.setRules`), FiltersPanel edits it. Viewing only: triage, fixes and captures never see it, and the
 * opening check ignores it; a check on filters takes a filter's conditions as one of its sides (checks.ts). */

export type Value = string | number | boolean;
/** One facet of the index: its key (`class`, `storey`, `pset:<Set>/<Prop>`…), its values and, per value, the
 * elements (indexes into `elements`) that have it. Numbers are SI (lengths in metres). */
export interface Facet { key: string; kind: "text" | "number" | "bool"; unit?: string; values: Value[]; items: number[][] }
export interface FacetIndex { revision: number; files: string[]; elements: string[]; file: number[]; facets: Facet[] }

export type Op = "is" | "isNot" | "contains" | "has" | "missing" | "lt" | "gt" | "between";
/** One condition on one facet. `is` / `isNot` / `contains` take any of `values` (any case); `lt`, `gt` and `between`
 * take `min` / `max` in SI. */
export interface Condition { facet: string; op: Op; values?: Value[]; min?: number; max?: number }
export type Action = "colour" | "byValue" | "hide" | "isolate";
/** A filter: what it finds (every condition holds; none finds everything), whether to invert that, and what to do. */
export interface Rule {
  id: string; name: string; on: boolean; when: Condition[]; invert?: boolean; action: Action;
  /** The colour for `colour` (else the palette's next). */
  colour?: string;
  /** For `byValue`: the facet whose values each get a colour, colours chosen by value, and values left uncoloured. */
  by?: { facet: string; colours?: Record<string, string>; off?: string[] };
  /** Who made it: chat's own filters are replaced by its next ones. */
  origin?: "user" | "chat";
  /** A user's filter switched off while chat's show; back on when chat clears its own. */
  paused?: boolean;
}
export interface FilterState { v: 1; rules: Rule[]; colours: boolean; greyRest: boolean }
/** What the viewer draws: elements hidden, the only ones shown (null: every one), colours by GlobalId. */
export interface RuleView { hide: Set<string> | null; only: Set<string> | null; paint: Map<string, string> | null; greyRest: boolean }

export const EMPTY: FilterState = { v: 1, rules: [], colours: true, greyRest: false };

/** Categorical colours for filters, chosen clear of every colour another role uses (each at least ΔE 21 from them) and
 * of each other: see RESERVED and web/tests/filters.test.mjs. */
export const PALETTE = ["#318181", "#8e234e", "#e2d136", "#2d57b7", "#dba570", "#62e8cd", "#9c3e16", "#f2a0c4",
  "#85db70", "#c6c86a",
  // A second ring, for colour by value past ten values.
  "#4e7231", "#c757a5", "#888dbf", "#6a4d39", "#da6c6c", "#29a36c", "#59396a", "#adcda2", "#c431c4", "#4e31c4"];
/** What colour-by-value values past the palette share, shown as "Other" in the key. */
export const OTHER = "#8a8273";
/** Colours other roles draw in the viewer: the pair (red, green, purple and their outlines), the selection, hits,
 * links, the "before" ghost, the section box and measure, the clash's overlap, the grey and ghost context. */
export const RESERVED = ["#d0342c", "#1f9d3a", "#8e44ad", "#ff5a5a", "#5dff8a", "#d39bff", "#2f8fdf", "#7cc0ff",
  "#e040fb", "#f48fff", "#e67e22", "#2f5d8a", "#ffb000", "#b9c2cc", "#9aa7b4", "#2563eb", "#475569", "#9a6b2f",
  "#84cc16", "#65a30d", "#38bdf8"];

/** The index made quick to read: facets by key. */
export interface Prepared { index: FacetIndex; byKey: Map<string, Facet>; n: number }
export function prepare(index: FacetIndex): Prepared {
  return { index, byKey: new Map(index.facets.map((f) => [f.key, f])), n: index.elements.length };
}

const isNum = (v: Value): v is number => typeof v === "number";
const same = (v: Value, w: Value) => {
  if (isNum(v)) {
    const x = typeof w === "number" ? w : Number(w);
    return Number.isFinite(x) && Math.abs(x - v) <= 1e-6 * Math.max(1, Math.abs(v));
  }
  return String(v).toLowerCase() === String(w).toLowerCase();
};

/** The elements (by index) one condition finds, as the server's `facets.matching` reads it. */
export function matching(p: Prepared, c: Condition): Set<number> {
  const f = p.byKey.get(c.facet);
  const every = () => new Set(Array.from({ length: p.n }, (_, i) => i));
  if (!f) return c.op === "missing" || c.op === "isNot" ? every() : new Set();
  const having = () => { const s = new Set<number>(); for (const items of f.items) for (const i of items) s.add(i); return s; };
  if (c.op === "has") return having();
  if (c.op === "missing") { const h = having(), out = every(); for (const i of h) out.delete(i); return out; }
  const wanted = c.values ?? [];
  const take = new Set<number>();
  f.values.forEach((v, k) => {
    let hit = false;
    if (c.op === "is" || c.op === "isNot") hit = wanted.some((w) => same(v, w));
    else if (c.op === "contains") hit = wanted.some((w) => String(v).toLowerCase().includes(String(w).toLowerCase()));
    else if (c.op === "lt") hit = isNum(v) && c.max !== undefined && v < c.max;
    else if (c.op === "gt") hit = isNum(v) && c.min !== undefined && v > c.min;
    else if (c.op === "between") hit = isNum(v) && (c.min === undefined || v >= c.min) && (c.max === undefined || v <= c.max);
    if (hit) for (const i of f.items[k]) take.add(i);
  });
  if (c.op !== "isNot") return take;
  const out = every();
  for (const i of take) out.delete(i);
  return out;
}

/** Whether a condition says enough to find anything by: a facet, and the values or bounds its kind of test needs. One
 * still being written in the editor is left out rather than finding nothing. */
export function complete(c: Condition): boolean {
  if (!c.facet) return false;
  if (c.op === "has" || c.op === "missing") return true;
  if (c.op === "lt") return c.max !== undefined;
  if (c.op === "gt") return c.min !== undefined;
  if (c.op === "between") return c.min !== undefined || c.max !== undefined;
  return !!c.values?.length;
}

/** The elements (by index) a rule finds: every complete condition holds (none: every element), then inverted if
 * asked. */
export function found(p: Prepared, rule: Pick<Rule, "when" | "invert">): Set<number> {
  let hit: Set<number> | undefined;
  for (const c of rule.when.filter(complete)) {
    const m = matching(p, c);
    if (hit === undefined) { hit = m; } else { const prev: Set<number> = hit; hit = new Set([...prev].filter((i) => m.has(i))); }
    if (!hit.size) break;
  }
  if (hit === undefined) hit = new Set(Array.from({ length: p.n }, (_, i) => i));
  if (!rule.invert) return hit;
  const inv = new Set<number>();
  for (let i = 0; i < p.n; i++) if (!hit.has(i)) inv.add(i);
  return inv;
}

/** The colours of a colour-by-value rule's values: the values among what it finds (`hit`), in the index's order, each
 * its chosen colour or the palette's by its place; past the palette they share OTHER. A value ticked off keeps its
 * place, so ticking one off moves no other value's colour. */
export function valueColours(rule: Rule, facet: Facet, hit: Set<number>): Map<string, string> {
  const out = new Map<string, string>();
  let at = 0;
  facet.values.forEach((v, k) => {
    if (!facet.items[k].some((i) => hit.has(i))) return;
    const key = String(v);
    out.set(key, rule.by?.colours?.[key] ?? (at < PALETTE.length ? PALETTE[at] : OTHER));
    at++;
  });
  return out;
}

/** A colour-by-value rule with its property: the one it names, else the last complete condition's (what the editor
 * shows while none is picked), so what is shown is what is kept. */
export function withBy(rule: Rule): Rule {
  if (rule.action !== "byValue" || rule.by?.facet) return rule;
  const facet = [...rule.when].reverse().find((c) => complete(c))?.facet;
  return facet ? { ...rule, by: { ...rule.by, facet } } : rule;
}

/** The user's filters as the page shares them with chat and an agent link (docs/filters.md, "Checks"): each by its
 * name (or what it finds), with only its complete conditions, within what the server takes (`app.PageFilter`: 100
 * filters, a name of 200 characters, 30 conditions), so a long name never refuses the chat turn. */
export function shareable(rules: Rule[]): { id: string; name: string; when: Condition[]; invert: boolean; on: boolean; origin: string | null }[] {
  return rules.slice(0, 100).map((r) => ({ id: r.id.slice(0, 100), name: (r.name || nameFor(r.when.filter(complete))).slice(0, 200),
    when: r.when.filter(complete).slice(0, 30), invert: !!r.invert, on: r.on, origin: r.origin ?? null }));
}

/** The first palette colour no other filter uses, for a new colour filter (it keeps it when the list is reordered). */
export function nextColour(rules: Rule[], except?: string): string {
  const used = new Set(rules.filter((r) => r.id !== except && r.colour).map((r) => r.colour!.toLowerCase()));
  return PALETTE.find((c) => !used.has(c)) ?? PALETTE[rules.length % PALETTE.length];
}

/** A colour rule's colour: its own, else the palette's for its place in the list. */
export const ruleColour = (rule: Rule, at: number) => rule.colour ?? PALETTE[at % PALETTE.length];

/** What every rule that is on does together. Hide rules hide what they find; isolate rules show only what some isolate
 * rule finds (several: what any finds); colour rules colour, the top one winning; Grey the rest greys what is left
 * uncoloured when something is coloured. */
export function evaluate(state: FilterState, p: Prepared | null): RuleView {
  const none: RuleView = { hide: null, only: null, paint: null, greyRest: false };
  if (!p) return none;
  const gid = p.index.elements;
  let hide: Set<string> | null = null, only: Set<string> | null = null, paint: Map<string, string> | null = null;
  state.rules.forEach((rule, at) => {
    if (!rule.on) return;
    if ((rule.action === "colour" || rule.action === "byValue") && !state.colours) return;
    const hit = found(p, rule);
    if (rule.action === "hide") { hide ??= new Set(); for (const i of hit) hide.add(gid[i]); return; }
    if (rule.action === "isolate") { only ??= new Set(); for (const i of hit) only.add(gid[i]); return; }
    paint ??= new Map();
    if (rule.action === "colour") {
      const c = ruleColour(rule, at);
      for (const i of hit) if (!paint.has(gid[i])) paint.set(gid[i], c);
      return;
    }
    const facet = rule.by ? p.byKey.get(rule.by.facet) : undefined;
    if (!facet) return;
    const off = new Set(rule.by?.off ?? []), colours = valueColours(rule, facet, hit);
    facet.values.forEach((v, k) => {
      const c = colours.get(String(v));
      if (!c || off.has(String(v))) return;
      for (const i of facet.items[k]) if (hit.has(i) && !paint!.has(gid[i])) paint!.set(gid[i], c);
    });
  });
  return { hide, only, paint, greyRest: !!state.greyRest && !!(paint as Map<string, string> | null)?.size };
}

/** How many elements a rule acts on now: what it finds, or for colour by value what it colours. */
export function count(p: Prepared | null, rule: Rule): number {
  if (!p) return 0;
  const hit = found(p, rule);
  if (rule.action !== "byValue") return hit.size;
  const facet = rule.by ? p.byKey.get(rule.by.facet) : undefined;
  if (!facet) return 0;
  const off = new Set(rule.by?.off ?? []), coloured = new Set<number>();
  facet.values.forEach((v, k) => { if (!off.has(String(v))) for (const i of facet.items[k]) if (hit.has(i)) coloured.add(i); });
  return coloured.size;
}

/** The key to the colours on screen, top filter first: each colour filter's colour and name, each colour-by-value
 * filter's values with their colours; one entry a colour, at most `max`. */
export function legend(state: FilterState, p: Prepared | null, max = 6): { colour: string; label: string }[] {
  if (!p || !state.colours) return [];
  // Only colours on screen: an element a hide or isolate filter takes away, or a higher filter colours, does not show it.
  const view = evaluate(state, p), gid = p.index.elements;
  const shows = (i: number, colour: string) => !view.hide?.has(gid[i]) && (!view.only || view.only.has(gid[i]))
    && view.paint?.get(gid[i]) === colour;
  const out: { colour: string; label: string }[] = [], seen = new Set<string>();
  const add = (colour: string, label: string) => { if (!seen.has(colour)) { seen.add(colour); out.push({ colour, label }); } };
  state.rules.forEach((rule, at) => {
    if (!rule.on) return;
    if (rule.action === "colour") {
      const c = ruleColour(rule, at);
      if ([...found(p, rule)].some((i) => shows(i, c))) add(c, rule.name || nameFor(rule.when));
      return;
    }
    if (rule.action !== "byValue" || !rule.by) return;
    const facet = p.byKey.get(rule.by.facet), off = new Set(rule.by.off ?? []);
    if (!facet) return;
    const hit = found(p, rule), colours = valueColours(rule, facet, hit);
    let others = 0;
    facet.values.forEach((v, k) => {
      const c = colours.get(String(v));
      if (!c || off.has(String(v)) || !facet.items[k].some((i) => hit.has(i) && shows(i, c))) return;
      if (c === OTHER && !rule.by?.colours?.[String(v)]) others++;
      else add(c, shownValue(v, facet.unit));
    });
    if (others) add(OTHER, `Other (${others} value${others === 1 ? "" : "s"})`);
  });
  return out.slice(0, max + 1);
}

/** The elements a rule acts on, by GlobalId: what it finds, or for colour by value what it colours. */
export function actedOn(p: Prepared, rule: Rule): string[] {
  const hit = found(p, rule);
  if (rule.action !== "byValue") return [...hit].map((i) => p.index.elements[i]);
  const facet = rule.by ? p.byKey.get(rule.by.facet) : undefined;
  if (!facet) return [];
  const off = new Set(rule.by?.off ?? []), out = new Set<number>();
  facet.values.forEach((v, k) => { if (!off.has(String(v))) for (const i of facet.items[k]) if (hit.has(i)) out.add(i); });
  return [...out].map((i) => p.index.elements[i]);
}

/** The filters just applied, going from one state to the next: added, switched on, or changed while on (not
 * renamed, nor paused or brought back by chat). Switching one off, deleting, reordering or Show colours applies none. */
export function applied(prev: FilterState, next: FilterState): Rule[] {
  const before = new Map(prev.rules.map((r) => [r.id, r]));
  const what = (r: Rule) => JSON.stringify([r.when, r.action, r.invert ?? false, r.colour ?? null, r.by ?? null]);
  return next.rules.filter((r) => {
    if (!r.on) return false;
    const o = before.get(r.id);
    if (!o) return true;
    if (!o.on) return !o.paused;     // chat clearing gives a paused filter back: not an apply
    return what(o) !== what(r);
  });
}

/** What applying filters frames, once the viewer shows them: what they act on that is on screen; for filters that only
 * hide, everything still on screen. Empty: nothing to frame. */
export function zoomTarget(p: Prepared, rules: Rule[], isShown: (gid: string) => boolean): string[] {
  const acting = rules.filter((r) => r.on && r.action !== "hide");
  const ids = new Set<string>();
  for (const r of acting) for (const g of actedOn(p, r)) if (isShown(g)) ids.add(g);
  if (ids.size || acting.length) return [...ids];
  return p.index.elements.filter(isShown);
}

/** A facet's values with how many elements have each, among `within` (null: all). */
export function valueCounts(p: Prepared, key: string, within: Set<number> | null = null): { value: Value; count: number }[] {
  const f = p.byKey.get(key);
  if (!f) return [];
  return f.values.map((value, k) => ({ value, count: within ? f.items[k].filter((i) => within.has(i)).length : f.items[k].length }))
    .filter((v) => v.count > 0);
}

// ---------------------------------------------------------------- facet names, as people read them

/** "PredefinedType" → "Predefined type". */
const words = (name: string) => name.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/ ([A-Z])(?=[a-z])/g, (_, c: string) => ` ${c.toLowerCase()}`);
const BUILT_IN: Record<string, string> = { file: "Model", class: "Class", storey: "Floor", type: "Type", material: "Material" };
export const ELEMENT = "Element";

/** Which set a facet belongs to in the editor's Property set list, and its own name there. */
export function describe(key: string): { set: string; name: string } {
  if (BUILT_IN[key]) return { set: ELEMENT, name: BUILT_IN[key] };
  const colon = key.indexOf(":");
  const kind = key.slice(0, colon), rest = key.slice(colon + 1);
  if (kind === "attr") return { set: "Attributes", name: words(rest) };
  if (kind === "classif") return { set: "Classification", name: rest || "Classification" };
  if (kind === "group") {
    const w = words(rest.replace(/^Ifc/, ""));
    return { set: "Systems and groups", name: w.charAt(0).toUpperCase() + w.slice(1) };
  }
  const slash = rest.indexOf("/");
  return slash < 0 ? { set: rest, name: rest } : { set: rest.slice(0, slash), name: rest.slice(slash + 1).replace(/\//g, " › ") };
}

/** The editor's Property set list: Element first, then attributes, property sets, quantity sets, classification and
 * groups, each with its facets in the index's order. */
export function sets(p: Prepared): { set: string; facets: Facet[] }[] {
  const out = new Map<string, Facet[]>();
  for (const f of p.index.facets) {
    const { set } = describe(f.key);
    if (!out.has(set)) out.set(set, []);
    out.get(set)!.push(f);
  }
  return [...out].map(([set, facets]) => ({ set, facets }));
}

/** A value as people read it: lengths in mm, yes and no. */
export function shownValue(v: Value, unit?: string): string {
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v === "number") return unit === "m" ? `${Number((v * 1000).toFixed(1))} mm` : `${Number(v.toFixed(4))}${unit ? ` ${unit}` : ""}`;
  return v.replace(/^Ifc/, "");
}

/** A rule's name from what it finds: "Ducts on Level 02 · System". */
export function nameFor(when: Condition[], by?: string): string {
  const parts = when.map((c) => {
    const d = describe(c.facet);
    const vals = (c.values ?? []).map((v) => shownValue(v));
    if (c.op === "has") return `has ${d.name}`;
    if (c.op === "missing") return `no ${d.name}`;
    if (c.op === "between" || c.op === "lt" || c.op === "gt") return d.name;
    const shown = vals.length > 2 ? `${vals.slice(0, 2).join(", ")} +${vals.length - 2}` : vals.join(", ");
    return c.op === "isNot" ? `not ${shown}` : shown;
  }).filter(Boolean);
  const head = parts.join(" · ") || "Everything";
  return by ? `${head} by ${describe(by).name}` : head;
}

let serial = 0;
export const newId = () => `f${Date.now().toString(36)}${(serial++).toString(36)}`;

/** A filter state read back from storage or a saved view, or the empty one: anything unreadable gives way. */
export function migrate(raw: unknown): FilterState {
  if (!raw || typeof raw !== "object") return EMPTY;
  const s = raw as Partial<FilterState>;
  if (s.v !== 1 || !Array.isArray(s.rules)) return EMPTY;
  const rules = s.rules.filter((r): r is Rule => !!r && typeof r === "object" && typeof (r as Rule).id === "string"
    && Array.isArray((r as Rule).when) && ["colour", "byValue", "hide", "isolate"].includes((r as Rule).action));
  return { v: 1, rules, colours: s.colours !== false, greyRest: !!s.greyRest };
}

/** CIE76 colour difference, for the palette's test. */
export function deltaE(a: string, b: string): number {
  const lab = (h: string) => {
    const [r, g, bl] = [1, 3, 5].map((i) => {
      const c = parseInt(h.slice(i, i + 2), 16) / 255;
      return c > 0.04045 ? ((c + 0.055) / 1.055) ** 2.4 : c / 12.92;
    });
    const x = (r * 0.4124 + g * 0.3576 + bl * 0.1805) / 0.95047, y = r * 0.2126 + g * 0.7152 + bl * 0.0722,
      z = (r * 0.0193 + g * 0.1192 + bl * 0.9505) / 1.08883;
    const f = (t: number) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
    return [116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))];
  };
  const p = lab(a), q = lab(b);
  return Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2]);
}
