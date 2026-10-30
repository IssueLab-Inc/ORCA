import { createContext, useContext, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { DockviewReact, type DockviewApi, type DockviewGroupPanelApi, type DockviewReadyEvent, type DockviewTheme, type GetTabContextMenuItemsParams,
  type IDockviewHeaderActionsProps, type IDockviewPanel, type IDockviewPanelHeaderProps, type IDockviewPanelProps,
  type SerializedDockview } from "dockview-react";
import "dockview-react/dist/styles/dockview.css";
import { Activity as Pulse, AppWindow, Box, Info, List, LocateFixed, MessageSquare, Network, PanelBottomClose, PanelBottomOpen,
  PanelLeftClose, PanelRightClose, PictureInPicture2, Undo2, X, type LucideIcon } from "lucide-react";
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
  slot.addEventListener("scroll", (e) => {
    const t = e.target as Element;
    if (typeof t.scrollTop !== "number" || t.clientHeight <= 0) return;
    for (const el of seen.keys()) if (!slot.contains(el)) seen.delete(el);  // a scroller React removed is let go
    seen.set(t, t.scrollTop);
  }, true);
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
  /** Size the bottom side bar holding a panel to `height` (Workings needs more room than a table): with `below`, only
   *  when the bar is shorter than that; with `at`, only when it is still about that height (nobody resized it since).
   *  Returns the height it had, or null when nothing changed (the panel is elsewhere, its bar collapsed, or the
   *  condition not met). */
  fitBar(id: PanelId, height: number, when?: { below?: number; at?: number }): number | null;
}

type Tabs = Partial<Record<PanelId, ReactNode>>;
interface Context { slots: Slots; tabs: Tabs; onTab: (id: PanelId) => void }
const DockContext = createContext<Context | null>(null);

const ICONS: Record<PanelId, LucideIcon> = { model: Box, clashes: List, clash: LocateFixed, plan: Network, chat: MessageSquare,
  activity: Pulse, properties: Info };
const TOUR_TAG: Partial<Record<PanelId, string>> = { plan: "tab-plan", chat: "tab-chat" };
const THEME: DockviewTheme = { name: "orca", className: "dockview-theme-orca", colorScheme: "light" };
const SAVE_MS = 400;
const RIGHT: PanelId[] = ["clash", "plan", "chat"];

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

// One object for the page's life: a new one on each render makes dockview re-apply its options and lay out again.
const COMPONENTS = { panel: PanelView };

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
  const away = !atHome(activePanel);
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
        () => popOut(containerApi, activePanel))}
      {away && button(Undo2, "Put it back", () => moveHome(containerApi, activePanel))}
      {activePanel.id === "properties" && button(X, "Close Properties", () => activePanel.api.close())}
    </div>
  );
}

/** A floating window at the model's top right, about the size of a side bar; each one floated while others are out
 *  steps down and left, so none hides another's tabs. */
const floatBox = (api: DockviewApi) => {
  const step = 32 * (api.groups.filter((g) => g.api.location.type === "floating").length % 6);
  return { position: { top: 56 + step, right: 16 + step }, width: 360,
    height: Math.round(Math.min(560, Math.max(260, api.height - 112 - step))) };
};
function floatPanel(api: DockviewApi, panel: IDockviewPanel) {
  api.addFloatingGroup(panel, floatBox(api));
}

/** Side bars' only panels that are in a window of their own: back to their bar when the window closes. */
const backToBar = new Set<string>();

/** Open a panel in a window of its own. dockview does nothing for a side bar's only panel (it won't take the bar
 *  out), so that one floats first, and goes back to its bar when the window closes, as the others do. */
function popOut(api: DockviewApi, panel: IDockviewPanel) {
  const alone = panel.group.api.location.type === "edge" && panel.group.panels.length === 1;
  if (alone) { floatPanel(api, panel); backToBar.add(panel.id); }
  void api.addPopoutGroup(panel).then((opened) => {
    if (opened || !alone) return;
    backToBar.delete(panel.id);   // blocked: back in its bar at once
    if (api.getPanel(panel.id)) moveHome(api, panel);
  });
}

/** After a pop-out window closed: what came from a side bar alone goes back there (dockview floats it). */
function returnToBars(api: DockviewApi) {
  for (const id of [...backToBar]) {
    const panel = api.getPanel(id);
    if (panel?.group.api.location.type === "popout") continue;
    backToBar.delete(id);
    if (panel) moveHome(api, panel);
  }
}

/** Whether a panel is where it lives: its side bar, or floating for a floating one. */
function atHome(panel: IDockviewPanel) {
  if (!isPanel(panel.id)) return true;
  const home = homeOf(panel.id), where = panel.group.api.location;
  return home === "float" ? where.type === "floating" : where.type === "edge" && where.position === home;
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
  if (home === "float") {
    api.addPanel({ id, component: "panel", title: titleOf(id), renderer: "always", floating: floatBox(api) });
    return;
  }
  edgeGroup(api, home);
  api.addPanel({ id, component: "panel", title: titleOf(id), position: { referenceGroup: EDGE_GROUP[home] }, renderer: "always" });
}

function moveHome(api: DockviewApi, panel: IDockviewPanel) {
  if (!isPanel(panel.id)) return;
  const home = homeOf(panel.id);
  if (home === "centre") return;
  if (home === "float") {
    if (panel.group.api.location.type !== "floating") floatPanel(api, panel);
    return;
  }
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

/** A side bar with nothing in it (its panels floated, popped out, closed or docked beside the model) gives its room to
 *  the model, and takes it back, at the width it had, when a panel docks there again (Put it back, the Layout menu). */
function fitEdges(api: DockviewApi) {
  for (const edge of ["left", "right", "bottom"] as Edge[]) {
    const bar = api.getEdgeGroup(edge);
    if (!bar) continue;
    const used = (api.getGroup(bar.id)?.panels.length ?? 0) > 0;
    if (api.isEdgeGroupVisible(edge) !== used) api.setEdgeGroupVisible(edge, used);
  }
}

/** The default layout: the classic one, as panels. The model in the middle (no tab, nothing docks into it, it never
 *  floats); the clash list on the left; Clash, Plan and Chat as tabs on the right; Activity along the bottom. */
function build(api: DockviewApi, sizes: { left: number; right: number }) {
  const model = api.addPanel({ id: "model", component: "panel", title: "Model" });
  model.group.locked = "no-drop-target";
  model.group.header.hidden = true;
  for (const edge of ["left", "right", "bottom"] as Edge[]) edgeGroup(api, edge, edge === "bottom" ? undefined : sizes[edge]);
  for (const p of PANELS) {
    if (p.home === "centre" || p.home === "float") continue;  // a floating panel appears when it is needed
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
  return ["float" as const,
    ...(panel.group.api.location.type === "popout" ? [] : [{ label: "Open in New Window", action: () => popOut(api, panel) }]),
    ...(atHome(panel) ? [] : [{ label: "Put it back", action: () => moveHome(api, panel) }]), "separator" as const, "close" as const];
}

const storage = () => { try { return window.localStorage; } catch { return null; } };

export function DockHost({ slots, sizes, tabs, onReady, onGone, onTab, onShown, onWindows }: {
  slots: Slots; sizes: { left: number; right: number }; tabs: Tabs;
  onReady: (dock: DockHandle) => void;
  /** This dock is gone: App lets go of its handle, unless a newer dock has given it another. */
  onGone: (dock: DockHandle) => void;
  /** One of Clash, Plan and Chat is now the panel in front, however it got there (a tab, a closed neighbour, a
   *  restored layout, Put it back): App's `tab` follows. */
  onShown: (id: "clash" | "plan" | "chat") => void;
  /** The user picked a panel's tab. */
  onTab: (id: PanelId) => void;
  /** The pop-out windows open now: App listens for its keys there, and draws tooltips there. */
  onWindows: (windows: Window[]) => void;
}) {
  const live = useRef({ onReady, onGone, onShown, onWindows, sizes });
  live.current = { onReady, onGone, onShown, onWindows, sizes };
  const cleanup = useRef<(() => void) | null>(null);
  const published = useRef<DockHandle | null>(null);
  // Let go of the dock only when this really unmounts: StrictMode runs an effect's cleanup and the effect again at
  // once, and the dock (with its subscriptions) lives on through that.
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      // dockview closes its pop-out windows without saying so: App lets go of them here.
      window.setTimeout(() => {
        if (mounted.current) return;
        cleanup.current?.(); cleanup.current = null;
        if (published.current) live.current.onGone(published.current);
        published.current = null;
        live.current.onWindows([]);
      }, 0);
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
      try {
        api.fromJSON(saved as unknown as SerializedDockview);
        const model = api.getPanel("model");
        loaded = !!model;
        // fromJSON brings the lock back as `true` (no drops in the middle only): nothing docks into the model at all.
        if (model) { model.group.locked = "no-drop-target"; model.group.header.hidden = true; }
      } catch { loaded = false; }
      if (!loaded) clearAll(api);
    }
    if (!loaded) build(api, live.current.sizes);
    rewire();
    let building = false;
    const fit = () => { if (!building) fitEdges(api); };
    fit();
    // A pop-out window opens after its panel has left (and closes after it is back): the bars are fitted then too.
    const windows = () => {
      fit();
      window.setTimeout(() => returnToBars(api), 0);   // a closed window's panels are back by then
      live.current.onWindows(api.getPopouts().map((p) => p.window).filter((w): w is Window => !!w));
    };
    const front = (id?: string) => { if (id && (RIGHT as string[]).includes(id)) live.current.onShown(id as "clash" | "plan" | "chat"); };
    const subs = [api.onDidLayoutChange(() => { fit(); save(); }), api.onDidLayoutFromJSON(() => { rewire(); fit(); }),
      api.onDidAddPanel(fit), api.onDidRemovePanel(fit), api.onDidMovePanel(fit), api.onDidAddPopoutGroup(windows),
      api.onDidRemovePopoutGroup(windows), api.onDidActivePanelChange((e) => front(e.panel?.id))];
    front(api.getGroup(EDGE_GROUP.right)?.activePanel?.id);   // a restored layout may have Plan or Chat in front
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
        building = true;   // the bars are empty for a moment while they fill: they stay as they are made
        try { clearAll(api); build(api, live.current.sizes); } finally { building = false; }
        rewire();
        fit();
      },
      gather() {
        // Closed ones too (Properties, which floats in on a selection, stays as it is).
        for (const p of PANELS) if (p.home !== "centre" && p.home !== "float" && !api.getPanel(p.id)) addHome(api, p.id);
        for (const p of api.panels) if (p.group.api.location.type === "popout") moveHome(api, p);
        for (const edge of ["left", "right", "bottom"] as Edge[]) {
          const g = api.getEdgeGroup(edge);
          if (g?.isCollapsed()) g.expand();
        }
      },
      isOpen: (id) => !!api.getPanel(id),
      fitBar(id, height, when = {}) {
        const g = api.getPanel(id)?.group.api, where = g?.location;
        if (!g || where?.type !== "edge" || where.position !== "bottom" || g.isCollapsed()) return null;
        const was = g.height;
        if ((when.below != null && was >= when.below) || (when.at != null && Math.abs(was - when.at) > 6) || Math.abs(was - height) < 2) return null;
        g.setSize({ height });
        return was;
      },
    };
    published.current = handle;
    live.current.onReady(handle);
  }

  return (
    <DockContext.Provider value={{ slots, tabs, onTab }}>
      <DockviewReact className="dock-host" theme={THEME} components={COMPONENTS} defaultTabComponent={Tab}
        rightHeaderActionsComponent={Actions} onReady={ready} getTabContextMenuItems={menu}
        floatingGroupBounds="boundedWithinViewport" floatingGroupDragHandle="tabbar" />
    </DockContext.Provider>
  );
}
