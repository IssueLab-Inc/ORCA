import type { CheckDefaults, DetectSelection, DetectTest } from "./api";
import { complete, found, nameFor, type Prepared, type Rule } from "./filters";

/** Checks on filters (docs/filters.md, "Checks"): one clash test of what side A takes (a filter) against side B (a
 * filter, everything or itself), run by ORCA's own detection; its clashes replace the open list. Pure: FiltersPanel
 * builds the test, App runs it. The server gives a check with no id its own (`detect.check_id`), from what it compares. */

export type Side = Rule | "everything" | "itself";
export type CheckKind = "hard" | "clearance";

const ANY: DetectSelection = { files: [], teams: [], classes: [], exclude_classes: [], systems: [], ids: [] };

/** A filter as one side of a check: its complete conditions and whether it inverts. */
export const sideOf = (r: Rule): DetectSelection => ({ ...ANY, filter: { when: r.when.filter(complete), invert: !!r.invert } });

/** A side's name as the user knows it. */
export const sideName = (s: Side) => (s === "everything" ? "Everything" : s === "itself" ? "itself" : s.name || nameFor(s.when.filter(complete)));

/** "Ducts vs Everything", "Ducts (within)", "Ducts vs Beams", and the clearance it keeps. */
export function checkName(a: Rule, b: Side, kind: CheckKind = "hard", clearance_m = 0): string {
  const head = b === "itself" ? `${sideName(a)} (within)` : `${sideName(a)} vs ${sideName(b)}`;
  return kind === "clearance" ? `${head}, ${Math.round(clearance_m * 1000)} mm clearance` : head;
}

/** The detection test for a check: no id (the server's, from what it compares), the defaults for what is not given;
 * `mm` is the hard tolerance or the clearance, in millimetres. */
export function checkTest(a: Rule, b: Side, kind: CheckKind, mm: number | null, d: CheckDefaults): DetectTest {
  const tolerance_m = kind === "hard" && mm !== null && mm >= 0 ? mm / 1000 : d.tolerance_m;
  const clearance_m = kind === "clearance" && mm !== null && mm > 0 ? mm / 1000 : d.clearance_m;
  return { id: "", name: checkName(a, b, kind, clearance_m), a: sideOf(a), b: b === "everything" ? { ...ANY } : b === "itself" ? null : sideOf(b),
    kind, tolerance_m, clearance_m, rules: { ...d.rules }, enabled: true, min_size_m: d.min_size_m };
}

/** How many elements a side takes that a check can test (spaces have no body to clash). */
export function sideCount(p: Prepared, r: Rule): number {
  const spaces = new Set(p.byKey.get("class")?.items[p.byKey.get("class")!.values.indexOf("IfcSpace")] ?? []);
  let n = 0;
  for (const i of found(p, r)) if (!spaces.has(i)) n++;
  return n;
}

/** The check a run was, if it was one (one test with a filter side): its name, for the summary. */
export function checkOf(tests: DetectTest[] | null | undefined): string | null {
  if (!tests || tests.length !== 1) return null;
  const t = tests[0];
  return t.a.filter || t.b?.filter ? t.name : null;
}
