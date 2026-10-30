// Review sign-offs, kept in this browser (no login yet): clash id → each team's review. The PDF stays DRAFT until every
// page has a review from every team involved, so a report must only ever see its own.
import type { Report, Signoff } from "./api";

export type Signoffs = Record<string, Signoff[]>;
type Scoped = Pick<Report, "title" | "sources" | "origin">;

const PREFIX = "sightline.signoffs:";
/** Until Oct 30 the key was the report's title, which every detection run shares ("Coordination · 4 models"). */
const TITLE_KEYED = "sightline.signoffs.";

/** Which report a page is on, for keeping its sign-offs (and for starting its evidence afresh when that changes).
 * - A detection run: the models it checked. Its sign-offs are kept per clash (below), so this only says when the page
 *   moved to other models.
 * - An imported report: its title and files. A Navisworks clash id is the clash's place in its file, so it means
 *   something only within that report; opening the same report again finds its sign-offs. */
export function signoffScope(report: Scoped | null): string | null {
  if (!report) return null;
  const files = JSON.stringify([...(report.sources ?? [])].sort());
  return report.origin === "sightline" ? `run:${files}` : `import:${report.title}:${files}`;
}

/** A detection run's clash ids are a hash of the test and the two elements' GlobalIds (detect.clash_id): the same on
 * every rerun of those models, whatever the requirements or the other models open, and never the same in another
 * project. So each clash's reviews are kept under its id alone. */
const perClash = (scope: string) => scope.startsWith("run:");
const clashKey = (id: string) => `${PREFIX}clash:${id}`;

function read(key: string): unknown {
  try { return JSON.parse(localStorage.getItem(key) ?? "null"); } catch { return null; }
}
const isMap = (v: unknown): v is Signoffs => !!v && typeof v === "object" && !Array.isArray(v);

/** The sign-offs of the clashes `ids` (the report's own). */
export function loadSignoffs(scope: string | null, ids: string[]): Signoffs {
  if (!scope) return {};
  if (perClash(scope)) {
    const out: Signoffs = {};
    for (const id of ids) {
      const l = read(clashKey(id));
      if (Array.isArray(l) && l.length) out[id] = l as Signoff[];
    }
    return out;
  }
  const saved = read(PREFIX + scope);
  if (!isMap(saved)) return {};
  const mine = new Set(ids);
  return Object.fromEntries(Object.entries(saved).filter(([id, l]) => mine.has(id) && Array.isArray(l) && l.length));
}

/** Clashes with no review left are dropped, and an imported report's key when none has any. */
export function saveSignoffs(scope: string | null, all: Signoffs) {
  if (!scope) return;
  try {
    if (perClash(scope)) {
      for (const [id, l] of Object.entries(all)) {
        if (l.length) localStorage.setItem(clashKey(id), JSON.stringify(l));
        else localStorage.removeItem(clashKey(id));
      }
      return;
    }
    const kept = Object.fromEntries(Object.entries(all).filter(([, l]) => l.length));
    if (Object.keys(kept).length) localStorage.setItem(PREFIX + scope, JSON.stringify(kept));
    else localStorage.removeItem(PREFIX + scope);
  } catch { /* private window */ }
}

/** Sign-offs kept under the report's title before Oct 30 move to where they belong now: only the clashes this report
 * has (a detection run's ids name their elements, so another project's never match), never over newer ones. What is
 * left for other reports of the same title stays until they open. */
export function migrateTitleKeyed(report: Scoped & Pick<Report, "clashes"> | null) {
  const scope = signoffScope(report);
  if (!report || !scope) return;
  const oldKey = TITLE_KEYED + report.title;
  const old = read(oldKey);
  if (!isMap(old)) return;
  const ids = new Set((report.clashes ?? []).map((c) => c.id));
  const moving = Object.fromEntries(Object.entries(old).filter(([id, l]) => ids.has(id) && Array.isArray(l) && l.length));
  if (!Object.keys(moving).length) return;
  const now = loadSignoffs(scope, Object.keys(moving));
  saveSignoffs(scope, { ...loadSignoffs(scope, [...ids]), ...Object.fromEntries(Object.entries(moving).filter(([id]) => !now[id])) });
  const rest = Object.fromEntries(Object.entries(old).filter(([id]) => !(id in moving)));
  try {
    if (Object.keys(rest).length) localStorage.setItem(oldKey, JSON.stringify(rest));
    else localStorage.removeItem(oldKey);
  } catch { /* private window */ }
}
