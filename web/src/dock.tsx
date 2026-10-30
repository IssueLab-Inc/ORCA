import { createContext, useContext, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { DockviewReact, type DockviewApi, type DockviewGroupPanelApi, type DockviewReadyEvent, type DockviewTheme, type GetTabContextMenuItemsParams,
  type IDockviewHeaderActionsProps, type IDockviewPanel, type IDockviewPanelHeaderProps, type IDockviewPanelProps,
  type SerializedDockview } from "dockview-react";
import "dockview-react/dist/styles/dockview.css";
import { Activity as Pulse, AppWindow, Box, List, LocateFixed, MessageSquare, Network, PanelBottomClose, PanelBottomOpen,
  PanelLeftClose, PanelRightClose, PictureInPicture2, Undo2, type LucideIcon } from "lucide-react";
import { EDGE_GROUP, EDGE_SIZE, PANELS, PANEL_IDS, homeOf, isPanel, readLayout, showSteps, titleOf, writeLayout,
  type Edge, type PanelId, type SavedLayout, type Where } from "./dockLayout";

/*
 * The desktop's panels (docs/panels.md). dockview's free core lays them out: side bars that collapse to a strip,
 * floating windows, pop-out windows, tabs dragged anywhere. App does not hand its state to the dock: it draws each
 * panel's content into a slot of its own (`inSlot`), one element made once for the page's life, and the dock only
 * moves that element. Nothing App draws is remounted when a panel moves, floats, pops out or comes back, so the chat,
 * the list's place and a running proposal carry on. Phones and tablets keep the classic layout, which places the same
 * slots with `SlotHost`.
 */

export type Slots = Record<PanelId, HTMLDivElement>;

// Moving an element resets its scroll. Each slot remembers where every scroller inside it was, to put them back.
const scrolls = new WeakMap<HTMLElement, Map<Element, number>>();

function makeSlot(id: PanelId): HTMLDivElement {
  const slot = document.createElement("div");
  slot.className = `slot slot-${id}`;
  slot.dataset.panel = id;
  const seen = new Map<Element, number>();
  // A collapsed bar squeezes its scrollers to nothing, which scrolls them to the top: that is not where they were.
  slot.addEventListener("scroll", (e) => { const t = e.target as Element; if (typeof t.scrollTop === "number" && t.clientHeight > 0) seen.set(t, t.scrollTop); }, true);
  scrolls.set(slot, seen);
  return slot;
}

function restoreScroll(slot: HTMLElement) {
  for (const [el, top] of scrolls.get(slot) ?? []) {
    if (!slot.contains(el)) scrolls.get(slot)!.delete(el);
    else if (el.scrollTop !== top) el.scrollTop = top;
  }
}

/** One slot per panel, made once for the page's life: what App draws each panel's content into. */
export function usePanelSlots(): Slots {
  const slots = useRef<Slots | null>(null);
  slots.current ??= Object.fromEntries(PANEL_IDS.map((id) => [id, makeSlot(id)])) as Slots;
  return slots.current;
}

/** Draw `node` into a panel's slot, wherever the slot is. */
export function inSlot(slot: HTMLElement, node: ReactNode) {
  return createPortal(node, slot);
}

/** Where a slot sits: an element that takes it in while mounted. In the classic layout the host and the slot are
 * `display: contents`, so what App draws stays a direct item of the page's grid and the classic CSS is unchanged. */
export function SlotHost({ slot, docked = false }: { slot: HTMLElement; docked?: boolean }) {
  const host = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const h = host.current;
    if (!h) return;
    slot.classList.toggle("in-dock", docked);
    h.appendChild(slot);
    restoreScroll(slot);
    return () => { if (slot.parentNode === h) h.removeChild(slot); };
  }, [slot, docked]);
  return <div ref={host} className={`slot-host ${docked ? "in-dock" : ""}`} />;
}

/** What App can ask of the dock. */
export interface DockHandle {
  /** Show a panel: reopen it if closed, open its collapsed side bar, bring its window forward; with `dock`, bring it
   *  back from a pop-out window (the tour reads the main page). */
  show(id: PanelId, opts?: { dock?: boolean }): void;
  /** Back to the default layout. */
  reset(): void;
  /** Every panel back in this window, every side bar open (the tour, which reads the main page). */
  gather(): void;
  isOpen(id: PanelId): boolean;
}

type Tabs = Partial<Record<PanelId, ReactNode>>;
interface Context { slots: Slots; tabs: Tabs; onTab: (id: PanelId) => void }
const DockContext = createContext<Context | null>(null);

const ICONS: Record<PanelId, LucideIcon> = { model: Box, clashes: List, clash: LocateFixed, plan: Network, chat: MessageSquare, activity: Pulse };
const TOUR_TAG: Partial<Record<PanelId, string>> = { plan: "tab-plan", chat: "tab-chat" };
const THEME: DockviewTheme = { name: "orca", className: "dockview-theme-orca", colorScheme: "light" };
const SAVE_MS = 400;

/** Each panel is its slot. */
function PanelView({ api }: IDockviewPanelProps) {
  const ctx = useContext(DockContext)!;
  const slot = ctx.slots[api.id as PanelId];
  useEffect(() => {
    // A move into another group, a floating window or a pop-out re-parents the slot: put its scrollers back after.
    const later = () => { window.setTimeout(() => restoreScroll(slot), 0); };
    const subs = [api.onDidGroupChange(later), api.onDidLocationChange(later), api.onDidVisibilityChange(later)];
    return () => { for (const s of subs) s.dispose(); };
  }, [api, slot]);
  return <SlotHost slot={slot} docked />;
}

/** A panel's tab: its icon, title and what App says about it (a count, a spinner). A click is the user choosing it.
 *  In a side bar a click opens the bar and never closes it (dockview toggles it on the active tab): the bar's own
 *  button collapses it, so a tab never hides the panel it names. */
function Tab({ api }: IDockviewPanelHeaderProps) {
  const ctx = useContext(DockContext)!;
  const id = api.id as PanelId;
  const Icon = ICONS[id] ?? Box;
  const click = (e: React.MouseEvent) => {
    const g = api.group.api;
    if (g.location.type === "edge") {
      e.preventDefault();
      if (g.isCollapsed()) g.expand();
    }
    api.setActive();
    ctx.onTab(id);
  };
  return (
    <div className="dock-tab" data-tour={TOUR_TAG[id]} data-panel-tab={id} onClick={click}>
      <Icon size={14} aria-hidden /><span className="dock-tab-title">{api.title ?? titleOf(id)}</span>{ctx.tabs[id]}
    </div>
  );
}

/** The buttons at the end of a group's tabs: collapse the side bar, float, pop out, or put back where it lives. */
function Actions({ api, containerApi, activePanel }: IDockviewHeaderActionsProps) {
  const [, redraw] = useState(0);
  useEffect(() => {
    const again = () => redraw((n) => n + 1);
    const subs = [api.onDidCollapsedChange(again), api.onDidLocationChange(again)];
    return () => { for (const s of subs) s.dispose(); };
  }, [api]);
  if (!activePanel || !isPanel(activePanel.id) || activePanel.id === "model") return null;
  const where = api.location;
  const edge = where.type === "edge" ? where.position as Edge : null;
  const collapsed = !!edge && api.isCollapsed();
  if (collapsed && edge !== "bottom") return null;   // a side bar's strip: its tabs open it
  const away = edge !== homeOf(activePanel.id);
  const button = (icon: LucideIcon, label: string, run: () => void) => {
    const I = icon;
    return <button type="button" className="ibtn" aria-label={label} data-tip={label} data-tip-side="bottom"
      onClick={(e) => { e.stopPropagation(); run(); }}><I size={15} strokeWidth={1.8} aria-hidden /></button>;
  };
  return (
    <div className="dock-actions">
      {edge === "bottom" && collapsed && button(PanelBottomOpen, "Open the bottom bar", () => api.expand())}
      {edge && !collapsed && button(edge === "left" ? PanelLeftClose : edge === "right" ? PanelRightClose : PanelBottomClose,
        `Collapse the ${edge} bar`, () => collapseEdge(api, edge))}
      {where.type !== "floating" && where.type !== "popout" && button(PictureInPicture2, `Float ${activePanel.title ?? "this panel"}`,
        () => floatPanel(containerApi, activePanel))}
      {where.type !== "popout" && button(AppWindow, `Open ${activePanel.title ?? "this panel"} in its own window`,
        () => void containerApi.addPopoutGroup(activePanel))}
      {away && button(Undo2, "Put it back", () => moveHome(containerApi, activePanel))}
    </div>
  );
}

/** A floating window at the model's top right, about the size of a side bar. */
function floatPanel(api: DockviewApi, panel: IDockviewPanel) {
  api.addFloatingGroup(panel, { position: { top: 56, right: 16 }, width: 360, height: Math.round(Math.min(560, Math.max(260, api.height - 112))) });
}

/** A side bar collapses to a strip of its tabs down its outer edge: the tabs move there first, so the strip is as
 *  narrow as they are. */
function collapseEdge(group: DockviewGroupPanelApi, edge: Edge) {
  group.setHeaderPosition(edge === "bottom" ? "top" : edge);
  group.collapse();
}

function edgeGroup(api: DockviewApi, edge: Edge, size?: number) {
  if (!api.getEdgeGroup(edge)) {
    const [min, max, fallback] = EDGE_SIZE[edge];
    api.addEdgeGroup(edge, { id: EDGE_GROUP[edge], initialSize: size ?? fallback, minimumSize: min, maximumSize: max });
  }
  return api.getGroup(EDGE_GROUP[edge]);
}

function addHome(api: DockviewApi, id: PanelId) {
  const home = homeOf(id);
  if (home === "centre") return;
  edgeGroup(api, home);
  api.addPanel({ id, component: "panel", title: titleOf(id), position: { referenceGroup: EDGE_GROUP[home] }, renderer: "always" });
}

function moveHome(api: DockviewApi, panel: IDockviewPanel) {
  if (!isPanel(panel.id)) return;
  const home = homeOf(panel.id);
  if (home === "centre") return;
  const group = edgeGroup(api, home);
  // In its place among the bar's tabs (Clash, Plan, Chat), not at the end.
  const order = PANELS.filter((p) => p.home === home).map((p) => p.id as string);
  const index = group ? group.panels.filter((p) => p !== panel && order.indexOf(p.id) < order.indexOf(panel.id)).length : 0;
  if (group && group !== panel.group) panel.api.moveTo({ group: group as never, index });
  if (group?.api.location.type === "edge" && group.api.isCollapsed()) group.api.expand();
}

/** Empty the dock, side bars too (dockview's clear() leaves them, collapsed). */
function clearAll(api: DockviewApi) {
  api.clear();
  for (const edge of ["left", "right", "bottom"] as Edge[]) if (api.getEdgeGroup(edge)) api.removeEdgeGroup(edge);
}

/** The default layout: the classic one, as panels. The model in the middle (no tab, nothing docks into it, it never
 *  floats); the clash list on the left; Clash, Plan and Chat as tabs on the right; Activity along the bottom. */
function build(api: DockviewApi, sizes: { left: number; right: number }) {
  const model = api.addPanel({ id: "model", component: "panel", title: "Model" });
  model.group.locked = "no-drop-target";
  model.group.header.hidden = true;
  for (const edge of ["left", "right", "bottom"] as Edge[]) edgeGroup(api, edge, edge === "bottom" ? undefined : sizes[edge]);
  for (const p of PANELS) {
    if (p.home === "centre") continue;
    // "always": a panel behind another tab stays in the page, hidden, so the tour finds what it points at and shows it.
    api.addPanel({ id: p.id, component: "panel", title: p.title, position: { referenceGroup: EDGE_GROUP[p.home] },
      inactive: p.id === "plan" || p.id === "chat", renderer: "always" });
  }
  api.getPanel("clash")?.api.setActive();
  model.api.setActive();
}

/** A side bar's tabs run along the top while it is open, as the classic panes' did (and down its outer edge while it
 *  is collapsed: `collapseEdge`). `changed` runs when a bar collapses or opens. */
function wireEdges(api: DockviewApi, changed: (collapsed: boolean) => void) {
  const subs: { dispose(): void }[] = [];
  for (const edge of ["left", "right", "bottom"] as Edge[]) {
    const g = api.getEdgeGroup(edge);
    if (!g) continue;
    if (!g.isCollapsed()) g.setHeaderPosition("top");
    subs.push(g.onDidCollapsedChange(({ isCollapsed }) => {
      if (!isCollapsed) g.setHeaderPosition("top");
      changed(isCollapsed);
    }));
  }
  return () => { for (const s of subs) s.dispose(); };
}

function menu({ panel, api }: GetTabContextMenuItemsParams) {
  if (!isPanel(panel.id) || panel.id === "model") return [];
  const where = panel.group.api.location;
  const home = homeOf(panel.id);
  const away = where.type !== "edge" || where.position !== home;
  return ["float" as const, "popout" as const,
    ...(away ? [{ label: "Put it back", action: () => moveHome(api, panel) }] : []), "separator" as const, "close" as const];
}

const storage = () => { try { return window.localStorage; } catch { return null; } };

export function DockHost({ slots, sizes, tabs, onReady, onTab, onWindows }: {
  slots: Slots; sizes: { left: number; right: number }; tabs: Tabs;
  onReady: (dock: DockHandle | null) => void;
  /** The user picked a panel's tab. */
  onTab: (id: PanelId) => void;
  /** The pop-out windows open now: App listens for its keys there, and draws tooltips there. */
  onWindows: (windows: Window[]) => void;
}) {
  const live = useRef({ onReady, onWindows, sizes });
  live.current = { onReady, onWindows, sizes };
  const cleanup = useRef<(() => void) | null>(null);
  // Let go of the dock only when this really unmounts: StrictMode runs an effect's cleanup and the effect again at
  // once, and the dock (with its subscriptions) lives on through that.
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      window.setTimeout(() => { if (!mounted.current) { cleanup.current?.(); cleanup.current = null; live.current.onReady(null); } }, 0);
    };
  }, []);

  function ready({ api }: DockviewReadyEvent) {
    cleanup.current?.();
    let unwire = () => {}, timer = 0;
    // Kept in this browser a moment after each change (a collapse is not a layout change to dockview).
    const save = () => { window.clearTimeout(timer); timer = window.setTimeout(() => writeLayout(storage(), api.toJSON() as unknown as SavedLayout), SAVE_MS); };
    // A bar opening again shows what it held where it was scrolled to.
    const changed = (collapsed: boolean) => {
      save();
      if (!collapsed) window.setTimeout(() => { for (const id of PANEL_IDS) restoreScroll(slots[id]); }, 0);
    };
    const rewire = () => { unwire(); unwire = wireEdges(api, changed); };
    const saved = readLayout(storage());
    let loaded = false;
    if (saved) {
      try { api.fromJSON(saved as unknown as SerializedDockview); loaded = !!api.getPanel("model"); } catch { loaded = false; }
      if (!loaded) clearAll(api);
    }
    if (!loaded) build(api, live.current.sizes);
    rewire();
    const windows = () => live.current.onWindows(api.getPopouts().map((p) => p.window).filter((w): w is Window => !!w));
    const subs = [api.onDidLayoutChange(save), api.onDidLayoutFromJSON(rewire), api.onDidAddPopoutGroup(windows),
      api.onDidRemovePopoutGroup(windows)];
    cleanup.current = () => { window.clearTimeout(timer); unwire(); for (const s of subs) s.dispose(); };

    const handle: DockHandle = {
      show(id, opts) {
        const p = api.getPanel(id);
        const loc = p?.group.api.location;
        const where: Where = !p || !loc ? { open: false }
          : { open: true, location: loc.type, collapsed: loc.type === "edge" && p.group.api.isCollapsed() };
        for (const step of showSteps(where, opts?.dock)) {
          const panel = api.getPanel(id);
          if (step === "add") addHome(api, id);
          else if (step === "home" && panel) moveHome(api, panel);
          else if (step === "expand" && panel?.group.api.location.type === "edge" && panel.group.api.isCollapsed()) panel.group.api.expand();
          else if (step === "window") panel?.group.api.getWindow().focus();
          else if (step === "activate" && panel && !panel.api.isActive) panel.api.setActive();
        }
      },
      reset() {
        clearAll(api);
        build(api, live.current.sizes);
        rewire();
      },
      gather() {
        for (const p of api.panels) if (p.group.api.location.type === "popout") moveHome(api, p);
        for (const edge of ["left", "right", "bottom"] as Edge[]) {
          const g = api.getEdgeGroup(edge);
          if (g?.isCollapsed()) g.expand();
        }
      },
      isOpen: (id) => !!api.getPanel(id),
    };
    live.current.onReady(handle);
  }

  return (
    <DockContext.Provider value={{ slots, tabs, onTab }}>
      <DockviewReact className="dock-host" theme={THEME} components={{ panel: PanelView }} defaultTabComponent={Tab}
        rightHeaderActionsComponent={Actions} onReady={ready} getTabContextMenuItems={menu}
        floatingGroupBounds="boundedWithinViewport" floatingGroupDragHandle="tabbar" />
    </DockContext.Provider>
  );
}
