import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { LucideIcon } from "lucide-react";

/** An icon button with a tooltip (label + shortcut) that also serves as its accessible name. */
export function IconButton({ icon: Icon, label, shortcut, active, disabled, onClick, tip = "right", size = 18, className = "" }: {
  icon: LucideIcon; label: string; shortcut?: string; active?: boolean; disabled?: boolean; onClick?: () => void;
  tip?: "right" | "bottom" | "top" | "left"; size?: number; className?: string;
}) {
  return (
    <button type="button" className={`ibtn ${active ? "on" : ""} ${className}`} aria-label={label} aria-pressed={active}
      disabled={disabled} onClick={onClick} data-tip={shortcut ? `${label}  ·  ${shortcut}` : label} data-tip-side={tip}>
      <Icon size={size} strokeWidth={1.8} aria-hidden />
    </button>
  );
}

/** A small menu that opens beside its trigger and closes on outside click or Escape. On a phone it opens as a sheet
 * from the bottom of the screen, with its title and a close button (index.css, "Responsive"). */
export function Popover({ icon, label, shortcut, children, tip = "right", text, note }: {
  icon: LucideIcon; label: string; shortcut?: string; children: (close: () => void) => React.ReactNode; tip?: "right" | "bottom";
  text?: string;  // show a text label beside the icon (for the few actions people look for by name)
  note?: string;  // what is set now: added to the trigger's name and tip, and the icon trigger marked `set`
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const off = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!ref.current?.contains(t) && !menu.current?.contains(t)) setOpen(false);
    };
    // Esc closes the menu and nothing else (not the viewer's selection or clash, which listen on the window).
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") { e.stopPropagation(); setOpen(false); } };
    const doc = ref.current?.ownerDocument ?? document;  // a panel in its own window has its own document
    doc.addEventListener("pointerdown", off);
    doc.addEventListener("keydown", esc);
    return () => { doc.removeEventListener("pointerdown", off); doc.removeEventListener("keydown", esc); };
  }, [open]);
  // Kept inside what shows it: a menu that would run off the right edge opens to the left of its trigger's edge instead,
  // and one that would run off the bottom moves up (scrolling inside when taller than the room). The room is the window,
  // or a dock panel that clips what overflows it (docs/panels.md); past the window's bottom a menu would make the whole
  // page scroll, past a panel's it would be cut off.
  useLayoutEffect(() => {
    const m = menu.current;
    if (!open || !m || getComputedStyle(m).position === "fixed") return;
    m.style.translate = ""; m.style.maxHeight = ""; m.style.overflowY = "";
    const room = roomFor(m), r = m.getBoundingClientRect();
    const overX = r.right - (room.right - 8), overY = r.bottom - (room.bottom - 8);
    const up = overY > 0 ? Math.min(overY, Math.max(r.top - room.top - 8, 0)) : 0;
    if (overX > 0 || up > 0) m.style.translate = `${overX > 0 ? -Math.round(overX) : 0}px ${-Math.round(up)}px`;
    if (r.height > room.bottom - room.top - 16) { m.style.maxHeight = `${room.bottom - room.top - 16}px`; m.style.overflowY = "auto"; }
  }, [open]);
  const close = () => setOpen(false);
  // On a phone the menu is a sheet over the whole page, so it goes to the body: inside the viewer's rail it would sit
  // under the page's own bottom sheet, whatever its z-index.
  const sheet = typeof window !== "undefined" && !!window.matchMedia?.("(max-width: 760px)").matches;
  const body = open && <>
    <div className="pop-scrim" aria-hidden onClick={close} />
    <div className="pop-menu" role="menu" aria-label={label} ref={menu}>
      <div className="pop-sheet-head"><b>{text ?? label}</b>
        <button type="button" className="ibtn" aria-label="Close" onClick={close}><span aria-hidden>✕</span></button></div>
      {children(close)}
    </div>
  </>;
  return (
    <div className={`pop pop-${tip} ${open ? "open" : ""}`} ref={ref}>
      {text
        ? <button type="button" className={`btn ghost ${open ? "on" : ""}`} aria-expanded={open} onClick={() => setOpen(!open)}>
            {(() => { const I = icon; return <I size={16} strokeWidth={1.8} aria-hidden />; })()} {text}</button>
        : <IconButton icon={icon} label={note ? `${label} · ${note}` : label} shortcut={shortcut} active={open} onClick={() => setOpen(!open)}
            tip={tip} className={note ? "set" : ""} />}
      {body && (sheet ? createPortal(body, document.body) : body)}
    </div>
  );
}

/** The box a menu can show in: its window (a panel in its own window: that one), narrowed by every ancestor that clips
 *  what overflows it. */
function roomFor(m: HTMLElement) {
  const view = m.ownerDocument.defaultView ?? window;
  const room = { top: 0, left: 0, right: view.innerWidth, bottom: view.innerHeight };
  for (let e = m.parentElement; e; e = e.parentElement) {
    const cs = view.getComputedStyle(e);
    if (!/hidden|clip|auto|scroll/.test(`${cs.overflowX} ${cs.overflowY}`)) continue;
    const r = e.getBoundingClientRect();
    room.top = Math.max(room.top, r.top); room.left = Math.max(room.left, r.left);
    room.right = Math.min(room.right, r.right); room.bottom = Math.min(room.bottom, r.bottom);
  }
  return room;
}

type Side = "right" | "left" | "top" | "bottom";
const OPPOSITE: Record<Side, Side> = { right: "left", left: "right", top: "bottom", bottom: "top" };

/**
 * The page's one tooltip, for any element with `data-tip` (and `data-tip-side`, right by default). It sits in a layer
 * above everything, flips to the other side when there is no room, and is kept inside the window, so a tip on a
 * control near an edge or in a scrolled panel is never cut off. A panel in its own window (dock.tsx) gets one of its
 * own, on that window's document.
 */
export function Tooltips({ doc = document }: { doc?: Document }) {
  const [tip, setTip] = useState<{ el: HTMLElement; text: string; side: Side } | null>(null);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const document = doc, window = doc.defaultView ?? globalThis.window;  // the page, or a pop-out window's
    let current: HTMLElement | null = null;
    const show = (target: EventTarget | null) => {
      const el = (target as HTMLElement | null)?.closest?.("[data-tip]") as HTMLElement | null;
      if (el === current) return;
      current = el;
      // A popover's trigger while its menu is open says nothing.
      if (!el || !el.dataset.tip || (el.classList.contains("on") && el.closest(".pop"))) { setTip(null); return; }
      setTip({ el, text: el.dataset.tip, side: (el.dataset.tipSide as Side) || "right" });
    };
    const hide = () => { current = null; setTip(null); };
    const over = (e: PointerEvent) => { if (e.pointerType !== "touch") show(e.target); };
    // Touch has no hover. A tap on a purely informational element (data-tip-tap: an info icon, a chip) shows its tip
    // for a few seconds; pressing and holding any control with a tip (an icon button) shows what it does, as phones do,
    // without doing it.
    let touched = false, timer = 0, hold = 0, held: HTMLElement | null = null;
    const showFor = (el: HTMLElement) => {
      current = el; setTip({ el, text: el.dataset.tip!, side: (el.dataset.tipSide as Side) || "top" });
      window.clearTimeout(timer); timer = window.setTimeout(hide, 3500);
    };
    const press = (e: PointerEvent) => {
      touched = e.pointerType === "touch"; held = null; window.clearTimeout(hold);
      const el = touched ? (e.target as HTMLElement | null)?.closest?.("[data-tip]") as HTMLElement | null : null;
      if (el?.dataset.tip && !el.closest(".stage canvas")) hold = window.setTimeout(() => { held = el; showFor(el); navigator.vibrate?.(8); }, 500);
    };
    const release = () => window.clearTimeout(hold);
    const swallow = (e: Event) => { if (held) { e.preventDefault(); e.stopPropagation(); if (e.type === "click") held = null; } };
    const tap = (e: MouseEvent) => {
      if (!touched) return;
      const el = (e.target as HTMLElement | null)?.closest?.("[data-tip-tap]") as HTMLElement | null;
      if (el?.dataset.tip) showFor(el);
    };
    const focus = (e: FocusEvent) => { if ((e.target as HTMLElement).matches?.(":focus-visible")) show(e.target); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") hide(); };
    document.addEventListener("pointerover", over);
    document.addEventListener("pointerdown", press, true);
    document.addEventListener("pointerup", release, true);
    document.addEventListener("pointercancel", release, true);
    document.addEventListener("click", swallow, true);
    document.addEventListener("contextmenu", swallow, true);
    document.addEventListener("click", tap);
    document.addEventListener("focusin", focus);
    document.addEventListener("focusout", hide);
    document.addEventListener("pointerdown", hide, true);
    document.addEventListener("scroll", hide, true);
    window.addEventListener("keydown", key);
    window.addEventListener("blur", hide);
    return () => {
      document.removeEventListener("pointerover", over);
      document.removeEventListener("pointerdown", press, true);
      document.removeEventListener("pointerup", release, true);
      document.removeEventListener("pointercancel", release, true);
      document.removeEventListener("click", swallow, true);
      document.removeEventListener("contextmenu", swallow, true);
      document.removeEventListener("click", tap);
      window.clearTimeout(timer); window.clearTimeout(hold);
      document.removeEventListener("focusin", focus);
      document.removeEventListener("focusout", hide);
      document.removeEventListener("pointerdown", hide, true);
      document.removeEventListener("scroll", hide, true);
      window.removeEventListener("keydown", key);
      window.removeEventListener("blur", hide);
    };
  }, [doc]);

  // Leaving the element (or it being removed) hides the tip.
  useEffect(() => {
    if (!tip) return;
    const leave = (e: PointerEvent) => { if (e.pointerType !== "touch" && !tip.el.contains(e.relatedTarget as Node | null)) setTip(null); };
    tip.el.addEventListener("pointerleave", leave);
    const gone = globalThis.setInterval(() => { if (!tip.el.isConnected) setTip(null); }, 300);
    return () => { tip.el.removeEventListener("pointerleave", leave); globalThis.clearInterval(gone); };
  }, [tip]);

  useLayoutEffect(() => {
    const b = box.current;
    if (!tip || !b) return;
    const r = tip.el.getBoundingClientRect();
    const view = doc.defaultView ?? window;
    const w = b.offsetWidth, h = b.offsetHeight, vw = view.innerWidth, vh = view.innerHeight, gap = 8, pad = 6;
    const at = (side: Side) => side === "right" ? { x: r.right + gap, y: r.top + r.height / 2 - h / 2 }
      : side === "left" ? { x: r.left - gap - w, y: r.top + r.height / 2 - h / 2 }
        : side === "top" ? { x: r.left + r.width / 2 - w / 2, y: r.top - gap - h }
          : { x: r.left + r.width / 2 - w / 2, y: r.bottom + gap };
    const fits = (side: Side) => {
      const p = at(side);
      return side === "right" ? p.x + w <= vw - pad : side === "left" ? p.x >= pad : side === "top" ? p.y >= pad : p.y + h <= vh - pad;
    };
    const order: Side[] = [tip.side, OPPOSITE[tip.side], ...(["bottom", "top", "right", "left"] as Side[])];
    const side = order.find(fits) ?? tip.side;
    const p = at(side);
    b.style.left = `${Math.round(Math.min(Math.max(pad, p.x), vw - w - pad))}px`;
    b.style.top = `${Math.round(Math.min(Math.max(pad, p.y), vh - h - pad))}px`;
    b.style.visibility = "visible";
  }, [tip]);

  return tip ? createPortal(<div ref={box} className="tooltip" role="tooltip" style={{ visibility: "hidden" }}>{tip.text}</div>, doc.body) : null;
}
