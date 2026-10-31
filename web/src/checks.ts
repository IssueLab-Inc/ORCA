import type { CheckDefaults, CheckSummary, CheckView, DetectSelection, DetectTest, Report, SideFilter } from "./api";
import { actedOn, complete, evaluate, nameFor, withBy, type FilterState, type Prepared, type Rule } from "./filters";

/** Checks on filters (docs/filters.md, "Checks"): one clash test of what side A takes (a filter, or what the filters
 * show together) against side B (a filter, what the filters show, everything or itself), run by ORCA's own detection;
 * its clashes join the list as a check of its own (kept checks, below). A filter as a side is what it acts on: colouring
 * by value, what it colours.
 * Everything is what the full check covers (the server's `check.everything`: a site model left out). Pure: FiltersPanel
 * builds the test, App runs it. The server gives a check with no id its own (`detect.check_id`), from what it compares. */

/** "shown": what the filters show together, as on screen. */
export type Side = Rule | "shown" | "everything" | "itself";
export type CheckKind = "hard" | "clearance";

const ANY: DetectSelection = { files: [], teams: [], classes: [], exclude_classes: [], systems: [], ids: [] };

/** A filter as a side: its complete conditions, whether it inverts and, colouring by value, by what and the values
 * ticked off (it takes only what it colours). */
export function sideFilter(r: Rule): SideFilter {
  const by = r.action === "byValue" ? withBy(r).by : undefined;
  return { when: r.when.filter(complete), invert: !!r.invert, ...(by?.facet ? { by: { facet: by.facet, off: [...(by.off ?? [])] } } : {}) };
}

/** A filter as one side of a check. */
export const sideOf = (r: Rule): DetectSelection => ({ ...ANY, filter: sideFilter(r) });

/** What the filters show together, as a side: the filters that are on, and whether the rest is hidden and colours show
 * (the server finds it again on every run, as `filters.evaluate` does here). */
export function viewOf(state: FilterState): CheckView {
  return { filters: state.rules.filter((r) => r.on).map((r) => ({ ...sideFilter(r), action: r.action })),
    hide_rest: !!state.hideRest, colours: state.colours };
}

/** A side's name as the user knows it. */
export const sideName = (s: Side) => (s === "everything" ? "Everything" : s === "itself" ? "itself" : s === "shown" ? "What the filters show"
  : s.name || nameFor(s.when.filter(complete)));

/** "Ducts vs Everything", "Ducts (within)", "Ducts vs Beams", "What the filters show (within)", and the clearance. */
export function checkName(a: Rule | "shown", b: Side, kind: CheckKind = "hard", clearance_m = 0): string {
  const head = b === "itself" ? `${sideName(a)} (within)` : `${sideName(a)} vs ${sideName(b)}`;
  return kind === "clearance" ? `${head}, ${Math.round(clearance_m * 1000)} mm clearance` : head;
}

/** The detection test for a check: no id (the server's, from what it compares), the defaults for what is not given;
 * `mm` is the hard tolerance or the clearance, in millimetres; `state`, for a side of what the filters show. */
export function checkTest(a: Rule | "shown", b: Side, kind: CheckKind, mm: number | null, d: CheckDefaults, state?: FilterState): DetectTest {
  const tolerance_m = kind === "hard" && mm !== null && mm >= 0 ? mm / 1000 : d.tolerance_m;
  const clearance_m = kind === "clearance" && mm !== null && mm > 0 ? mm / 1000 : d.clearance_m;
  const side = (s: Rule | "shown"): DetectSelection => (s === "shown" ? { ...ANY, view: viewOf(state ?? { v: 1, rules: [], colours: true, greyRest: false }) } : sideOf(s));
  return { id: "", name: checkName(a, b, kind, clearance_m), a: side(a),
    b: b === "everything" ? { ...ANY, ...(d.everything ?? {}) } : b === "itself" ? null : side(b),
    kind, tolerance_m, clearance_m, rules: { ...d.rules }, enabled: true, min_size_m: d.min_size_m };
}

/** The spaces among the index's elements: a check cannot test them (no body to clash). */
function spaces(p: Prepared): Set<string> {
  const f = p.byKey.get("class");
  const k = f ? f.values.indexOf("IfcSpace") : -1;
  return new Set(f && k >= 0 ? f.items[k].map((i) => p.index.elements[i]) : []);
}

/** What a filter as a side takes, counted as the filter list counts it (`n`: what it acts on, rooms included), and
 * the `rooms` among them, which a check cannot test (no solid body). */
export function sideCounts(p: Prepared, r: Rule): { n: number; rooms: number } {
  const rooms = spaces(p), acted = actedOn(p, r);
  return { n: acted.length, rooms: acted.filter((g) => rooms.has(g)).length };
}

/** What the filters show together (`n`, rooms included), the `rooms` among them, and how many elements there are. */
export function shownCounts(p: Prepared, state: FilterState): { n: number; rooms: number; all: number } {
  const rooms = spaces(p), view = evaluate(state, p);
  let n = 0, inRooms = 0;
  for (const g of p.index.elements) {
    if (view.hide?.has(g) || (view.only && !view.only.has(g))) continue;
    n++;
    if (rooms.has(g)) inRooms++;
  }
  return { n, rooms: inRooms, all: p.index.elements.length };
}

/** The line under Check clashes when its sides take rooms: "36 rooms in By Model aren't checked: …". */
export function roomsLine(sides: { name: string; rooms: number }[]): string | null {
  const named = sides.filter((s) => s.rooms > 0);
  if (!named.length) return null;
  const word = (n: number) => (n === 1 ? "room" : "rooms");
  const parts = named.map((s, i) => `${s.rooms.toLocaleString()} ${i === 0 ? word(s.rooms) + " " : ""}in ${s.name}`);
  const one = named.length === 1 && named[0].rooms === 1;
  return `${parts.join(" and ")} ${one ? "isn't" : "aren't"} checked: rooms have no solid body to clash.`;
}

/** The check a run was, if it was one (one test with a side from the filters): its name, for the summary. */
export function checkOf(tests: DetectTest[] | null | undefined): string | null {
  if (!tests || tests.length !== 1) return null;
  const t = tests[0];
  return t.a.filter || t.a.view || t.b?.filter || t.b?.view ? t.name : null;
}

/** Kept checks (docs/detection.md, "Kept checks"): ORCA keeps each check's latest result, and the list holds them all.
 * The list as one check shows it (null: every check), each clash under its test in that check. */
export function narrow(report: Report, key: string | null): Report {
  if (!key || report.origin !== "sightline") return report;
  return { ...report, clashes: report.clashes.filter((c) => c.checks && key in c.checks).map((c) => ({ ...c, test: c.checks![key] })) };
}

/** The fixes to show after `ran` (check keys) ran again: a clash a check that ran still finds was not fixed, and one no
 * check lists any more has gone; a fixed clash only checks that did not run still list keeps its mark until they do. */
export function pruneFixes(fixes: Record<string, string>, after: Report, ran: string[]): Record<string, string> {
  const by = new Map(after.clashes.map((c) => [c.id, c]));
  return Object.fromEntries(Object.entries(fixes).filter(([id]) => {
    const c = by.get(id);
    return !!c && !ran.some((k) => !!c.checks && k in c.checks);
  }));
}

/** A kept check's line in the picker: "Ducts vs Everything · 3", and whether a fix was kept since it ran. */
export function checkLabel(c: CheckSummary): string {
  return `${c.name} · ${c.clashes.toLocaleString()}${c.stale ? " · ran before a fix" : ""}`;
}
