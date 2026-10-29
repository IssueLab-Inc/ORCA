import { useEffect, useState } from "react";

/** The page's layout by window width (docs/mobile.md): desktop as built, a tablet with the clash list as a drawer, or a
 * phone with the model full screen and a bottom sheet. The CSS uses the same numbers. */
export type Layout = "desktop" | "tablet" | "phone";
export const PHONE_MAX = 760;
export const TABLET_MAX = 1100;

export function layoutFor(width: number): Layout {
  return width <= PHONE_MAX ? "phone" : width <= TABLET_MAX ? "tablet" : "desktop";
}

export function useLayout(): Layout {
  const [layout, setLayout] = useState<Layout>(() => layoutFor(typeof window === "undefined" ? 1600 : window.innerWidth));
  useEffect(() => {
    const on = () => setLayout(layoutFor(window.innerWidth));
    window.addEventListener("resize", on);
    on();
    return () => window.removeEventListener("resize", on);
  }, []);
  return layout;
}

/** A touch screen (no hover, a finger for a pointer): bigger targets, and no hover-only hints. */
export const isCoarse = () => typeof window !== "undefined" && (window.matchMedia?.("(pointer: coarse)").matches ?? false);

export function useCoarse(): boolean {
  const [coarse, setCoarse] = useState(isCoarse);
  useEffect(() => {
    const q = window.matchMedia?.("(pointer: coarse)");
    if (!q) return;
    const on = () => setCoarse(q.matches);
    q.addEventListener("change", on);
    return () => q.removeEventListener("change", on);
  }, []);
  return coarse;
}

/** The phone's bottom sheet: just its bar (peek), half the window, or up to the header (full). */
export type Snap = "peek" | "half" | "full";
export const SNAPS: Snap[] = ["peek", "half", "full"];

/** Where a released drag settles: a flick (|velocity| > 0.5 px/ms) goes one step its way, else the nearest height. */
export function nearestSnap(height: number, velocity: number, heights: Record<Snap, number>, from: Snap): Snap {
  if (Math.abs(velocity) > 0.5) {
    const up = velocity > 0, i = SNAPS.indexOf(from);
    const passed = SNAPS.filter((s) => (up ? heights[s] > height : heights[s] < height));
    if (passed.length) return up ? passed[0] : passed[passed.length - 1];
    return SNAPS[Math.max(0, Math.min(SNAPS.length - 1, i + (up ? 1 : -1)))];
  }
  return SNAPS.reduce((best, s) => (Math.abs(heights[s] - height) < Math.abs(heights[best] - height) ? s : best), "peek" as Snap);
}

/** A tap on the handle: peek opens to half, half to full, full drops back to peek. */
export const nextSnap = (s: Snap): Snap => (s === "peek" ? "half" : s === "half" ? "full" : "peek");

/** What the sheet does when something happens in the app, so people never hunt for the right tab: the list when a
 * report opens, the clash's panel when one is picked, out of the way (peek) while ORCA drives the model, and back up
 * when there is a result to read. `null` leaves that part as it is. */
export type Happening = "report" | "models" | "select" | "work" | "result";
export function follow(what: Happening, snap: Snap): { list: boolean | null; snap: Snap | null } {
  switch (what) {
    case "report": return { list: true, snap: snap === "peek" ? "half" : null };
    case "models": return { list: true, snap: snap === "peek" ? "half" : null };
    case "select": return { list: false, snap: snap === "peek" ? "half" : null };
    case "work": return { list: false, snap: "peek" };
    case "result": return { list: false, snap: snap === "peek" ? "half" : null };
  }
}
