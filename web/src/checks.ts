import type { CheckDefaults, CheckView, DetectSelection, DetectTest, SideFilter } from "./api";
import { actedOn, complete, evaluate, nameFor, withBy, type FilterState, type Prepared, type Rule } from "./filters";

/** Checks on filters (docs/filters.md, "Checks"): one clash test of what side A takes (a filter, or what the filters
 * show together) against side B (a filter, what the filters show, everything or itself), run by ORCA's own detection;
 * its clashes replace the open list. A filter as a side is what it acts on: colouring by value, what it colours.
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

/** How many elements a filter as a side takes that a check can test: what it acts on, spaces left out. */
export function sideCount(p: Prepared, r: Rule): number {
  const skip = spaces(p);
  return actedOn(p, r).filter((g) => !skip.has(g)).length;
}

/** How many elements the filters show together that a check can test, and how many there are in all. */
export function shownCount(p: Prepared, state: FilterState): { shown: number; all: number } {
  const skip = spaces(p), view = evaluate(state, p);
  let shown = 0, all = 0;
  for (const g of p.index.elements) {
    if (skip.has(g)) continue;
    all++;
    if (!view.hide?.has(g) && (!view.only || view.only.has(g))) shown++;
  }
  return { shown, all };
}

/** The check a run was, if it was one (one test with a side from the filters): its name, for the summary. */
export function checkOf(tests: DetectTest[] | null | undefined): string | null {
  if (!tests || tests.length !== 1) return null;
  const t = tests[0];
  return t.a.filter || t.a.view || t.b?.filter || t.b?.view ? t.name : null;
}
