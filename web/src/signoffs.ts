// Review sign-offs, kept in this browser per report (no login yet): clash id → each team's review. The PDF stays
// DRAFT until every page has a review from every team involved, so a report must only ever see its own.
import type { Report, Signoff } from "./api";

export type Signoffs = Record<string, Signoff[]>;

const PREFIX = "sightline.signoffs:";
/** Until Oct 30 the key was the report's title, which every detection run shares ("Coordination · 4 models"). */
const TITLE_KEYED = "sightline.signoffs.";

/** Where a report's sign-offs are kept. An imported report: its id. A detection run, which is a new report each time
 * while its clash ids stay the same: the models it checked and the requirements it ran under, so a rerun keeps them
 * and other models, or the same models under other requirements, start with none. */
export function signoffKeyOf(report: Pick<Report, "id" | "sources" | "origin" | "requirements_id"> | null): string | null {
  if (!report) return null;
  if (report.origin !== "sightline") return `${PREFIX}report:${report.id}`;
  return `${PREFIX}run:${report.requirements_id ?? "defaults"}:${JSON.stringify([...report.sources].sort())}`;
}

export function loadSignoffs(key: string | null): Signoffs {
  if (!key) return {};
  try {
    const saved = JSON.parse(localStorage.getItem(key) ?? "{}");
    return saved && typeof saved === "object" && !Array.isArray(saved) ? saved : {};
  } catch { return {}; }
}

/** Clashes with no review left are dropped, and so is the key when none has any. */
export function saveSignoffs(key: string | null, all: Signoffs) {
  if (!key) return;
  const kept = Object.fromEntries(Object.entries(all).filter(([, l]) => l.length));
  try {
    if (Object.keys(kept).length) localStorage.setItem(key, JSON.stringify(kept));
    else localStorage.removeItem(key);
  } catch { /* private window */ }
}

/** Title-keyed sign-offs can't be told apart by report (that was the fault), so they are dropped, not carried over. */
export function dropTitleKeyed() {
  try {
    const old = Array.from({ length: localStorage.length }, (_, i) => localStorage.key(i))
      .filter((k): k is string => !!k?.startsWith(TITLE_KEYED));
    for (const k of old) localStorage.removeItem(k);
  } catch { /* private window */ }
}
