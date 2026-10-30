/** The About ORCA page's tabs and its address: `#about` opens it on Overview, `#about/<tab>` on that tab. */
export const ABOUT_TABS = [
  { id: "overview", label: "Overview" },
  { id: "how", label: "How it works" },
  { id: "fixes", label: "The fixes" },
  { id: "ai", label: "The AI" },
  { id: "inside", label: "Under the hood" },
  { id: "proof", label: "Proof and limits" },
] as const;

export type AboutTab = (typeof ABOUT_TABS)[number]["id"];

/** The tab a location hash asks for, or null when the hash is not the About page's (an unknown tab opens Overview). */
export function aboutTabFromHash(hash: string): AboutTab | null {
  const m = /^#about(?:\/([\w-]*))?$/.exec(hash.trim());
  if (!m) return null;
  return ABOUT_TABS.find((t) => t.id === m[1])?.id ?? "overview";
}

export function aboutHash(tab: AboutTab): string {
  return tab === "overview" ? "#about" : `#about/${tab}`;
}

/** The tab `step` places from `tab` (arrow keys in the tab bar), wrapping round. */
export function nextTab(tab: AboutTab, step: number): AboutTab {
  const i = ABOUT_TABS.findIndex((t) => t.id === tab);
  const n = ABOUT_TABS.length;
  return ABOUT_TABS[(((i + step) % n) + n) % n].id;
}

/** The page's hash, or "" where there is no location (tests). */
export function currentHash(): string {
  return typeof window !== "undefined" ? window.location?.hash ?? "" : "";
}

/** Put the About page's tab in the address bar: a new history entry when it opens (Back closes it), else in place. */
export function showAboutHash(tab: AboutTab | null, push: boolean): void {
  if (typeof window === "undefined" || !window.history || !window.location) return;
  const base = window.location.pathname + window.location.search;
  if (tab === null) {
    if (aboutTabFromHash(window.location.hash)) window.history.replaceState(window.history.state, "", base);
    return;
  }
  if (push) window.history.pushState(window.history.state, "", base + aboutHash(tab));
  else window.history.replaceState(window.history.state, "", base + aboutHash(tab));
}
