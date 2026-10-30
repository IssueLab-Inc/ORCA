/** The desktop's panels and the layout saved for them (docs/panels.md): what each panel is, where it lives by
 * default, which saved layouts can be loaded, and what showing a panel takes. Pure: `dock.tsx` does the drawing. */

export type PanelId = "model" | "clashes" | "clash" | "plan" | "chat" | "activity" | "properties";
export type Edge = "left" | "right" | "bottom";

/** Every panel, in the order the Layout menu lists them. `home` is where it docks by default and goes back to; a
 *  `float` panel floats over the model and appears when it is needed (Properties, on a selection). */
export const PANELS: { id: PanelId; title: string; home: Edge | "centre" | "float" }[] = [
  { id: "model", title: "Model", home: "centre" },
  { id: "clashes", title: "Coordination", home: "left" },  // the clash list and Insights (their own tabs inside)
  { id: "clash", title: "Clash", home: "right" },
  { id: "plan", title: "Plan", home: "right" },
  { id: "chat", title: "Chat", home: "right" },
  { id: "activity", title: "Activity", home: "bottom" },
  { id: "properties", title: "Properties", home: "float" },
];
export const PANEL_IDS: PanelId[] = PANELS.map((p) => p.id);
export const isPanel = (id: string): id is PanelId => (PANEL_IDS as string[]).includes(id);
export const homeOf = (id: PanelId) => PANELS.find((p) => p.id === id)!.home;
export const titleOf = (id: PanelId) => PANELS.find((p) => p.id === id)!.title;

/** The side panes' widths in pixels (least, most, default): the classic layout's dragged panes and the dock's left and
 * right side bars, which start at the widths the panes were dragged to (`sightline.left-w`, `sightline.right-w`). */
export const PANE = { left: [240, 640, 310], right: [300, 720, 380] } as const;
/** The three side bars' group ids and sizes (least, most, default). */
export const EDGE_GROUP: Record<Edge, string> = { left: "edge-left", right: "edge-right", bottom: "edge-bottom" };
export const EDGE_SIZE: Record<Edge, readonly [number, number, number]> = { ...PANE, bottom: [80, 480, 120] };

/** Where the layout is kept in this browser, and the switch back to the classic layout. */
export const LAYOUT_KEY = "sightline.dock.v1";
export const CLASSIC_KEY = "sightline.dock.classic";

/** A saved layout, as far as ORCA reads it (dockview's `toJSON`; the rest is passed through untouched). */
export interface SavedLayout {
  grid?: { root?: unknown };
  panels?: Record<string, { id?: string; contentComponent?: string }>;
  floatingGroups?: WindowEntry[];
  popoutGroups?: WindowEntry[];
  edgeGroups?: Partial<Record<Edge, EdgeEntry>>;
  [key: string]: unknown;
}
/** A floating or pop-out window: one group (`data`), or several split in a grid of their own (`grid`). */
type WindowEntry = { data?: { views?: string[] }; grid?: { root?: unknown }; [key: string]: unknown };
const windowViews = (g: WindowEntry) => g.data?.views ?? gridViews(g.grid?.root);
type EdgeEntry = { size?: number; visible?: boolean; collapsed?: boolean; group?: { id?: string; views?: string[]; activeView?: string; [key: string]: unknown }; [key: string]: unknown };

/** The panels in the grid's leaves (the centre: the model, and whatever was docked beside it). */
export function gridViews(node: unknown): string[] {
  if (!node || typeof node !== "object") return [];
  const n = node as { type?: string; data?: unknown };
  if (n.type === "leaf") return (n.data as { views?: string[] } | undefined)?.views ?? [];
  return n.type === "branch" && Array.isArray(n.data) ? n.data.flatMap(gridViews) : [];
}

/** Every panel placed anywhere in a layout: the grid, floating groups, pop-out windows and the side bars. */
export function placedViews(layout: SavedLayout): string[] {
  return [...gridViews(layout.grid?.root), ...(layout.floatingGroups ?? []).flatMap(windowViews),
    ...(layout.popoutGroups ?? []).flatMap(windowViews),
    ...Object.values(layout.edgeGroups ?? {}).flatMap((e) => e?.group?.views ?? [])];
}

/** A layout that can be loaded: only ORCA's panels, each drawn by the one panel component and placed exactly once,
 * and the model in the grid (it never floats or pops out: WebGL cannot move to another window). A panel the user
 * closed is simply absent. Anything else (an older layout, a hand edit) gives way to the default. */
export function validLayout(layout: unknown): layout is SavedLayout {
  if (!layout || typeof layout !== "object") return false;
  const l = layout as SavedLayout;
  if (!l.panels || typeof l.panels !== "object" || !l.grid) return false;
  const ids = Object.keys(l.panels);
  if (!ids.every((id) => isPanel(id) && l.panels![id]?.contentComponent === "panel")) return false;
  const placed = placedViews(l);
  if (placed.length !== new Set(placed).size || placed.some((id) => !ids.includes(id)) || ids.some((id) => !placed.includes(id))) return false;
  return gridViews(l.grid.root).includes("model");
}

/** A browser opens a window only on a click, so a saved layout puts what was in pop-out windows back in its side
 * bar: after a reload those panels are docked where they came from. A floating panel's (Properties) is left closed: it
 * comes back on the next selection. */
export function withoutPopouts(layout: SavedLayout): SavedLayout {
  if (!layout.popoutGroups?.length) return layout;
  const edgeGroups: Partial<Record<Edge, EdgeEntry>> = structuredClone(layout.edgeGroups ?? {});
  const panels = { ...layout.panels };
  for (const id of layout.popoutGroups.flatMap(windowViews)) {
    if (!isPanel(id)) continue;
    const home = homeOf(id);
    if (home === "float") { delete panels[id]; continue; }
    if (home === "centre") continue;
    const entry = edgeGroups[home] ??= { size: EDGE_SIZE[home][2], visible: true };
    entry.visible = true;   // a bar left empty by the pop-out was hidden (an empty bar gives its room to the model)
    entry.group ??= { id: EDGE_GROUP[home], views: [] };
    entry.group.views = [...(entry.group.views ?? []), id];
    entry.group.activeView ??= id;
  }
  return { ...layout, panels, popoutGroups: [], edgeGroups };
}

/** The layout kept in this browser, or null when there is none or it can't be loaded. */
export function readLayout(storage: Pick<Storage, "getItem"> | null): SavedLayout | null {
  try {
    const saved = JSON.parse(storage?.getItem(LAYOUT_KEY) ?? "null") as { v?: number; layout?: unknown } | null;
    return saved?.v === 1 && validLayout(saved.layout) ? saved.layout : null;
  } catch { return null; }
}

export function writeLayout(storage: Pick<Storage, "setItem"> | null, layout: SavedLayout) {
  try { storage?.setItem(LAYOUT_KEY, JSON.stringify({ v: 1, layout: withoutPopouts(layout) })); } catch { /* private window: kept for this visit */ }
}

/** Where a panel is now. */
export type Where = { open: boolean; location?: "grid" | "edge" | "floating" | "popout"; collapsed?: boolean };
export type ShowStep = "add" | "home" | "expand" | "window" | "activate";

/** What showing a panel takes, in order: a closed panel comes back at home; a collapsed side bar opens; a pop-out
 * window is brought forward, or with `dock` (the tour, which reads the main page) the panel comes back home. */
export function showSteps(where: Where, dock = false): ShowStep[] {
  if (!where.open) return ["add", "expand", "activate"];
  if (where.location === "popout") return dock ? ["home", "expand", "activate"] : ["window", "activate"];
  if (where.location === "edge" && where.collapsed) return ["expand", "activate"];
  return ["activate"];
}
