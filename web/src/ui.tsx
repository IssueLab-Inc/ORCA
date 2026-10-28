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

/** A small menu that opens beside its trigger and closes on outside click or Escape. */
export function Popover({ icon, label, shortcut, children, tip = "right", text }: {
  icon: LucideIcon; label: string; shortcut?: string; children: (close: () => void) => React.ReactNode; tip?: "right" | "bottom";
  text?: string;  // show a text label beside the icon (for the few actions people look for by name)
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const off = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", off);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", off); document.removeEventListener("keydown", esc); };
  }, [open]);
  return (
    <div className={`pop pop-${tip}`} ref={ref}>
      {text
        ? <button type="button" className={`btn ghost ${open ? "on" : ""}`} aria-expanded={open} onClick={() => setOpen(!open)}>
            {(() => { const I = icon; return <I size={16} strokeWidth={1.8} aria-hidden />; })()} {text}</button>
        : <IconButton icon={icon} label={label} shortcut={shortcut} active={open} onClick={() => setOpen(!open)} tip={tip} />}
      {open && <div className="pop-menu" role="menu">{children(() => setOpen(false))}</div>}
    </div>
  );
}

type Side = "right" | "left" | "top" | "bottom";
const OPPOSITE: Record<Side, Side> = { right: "left", left: "right", top: "bottom", bottom: "top" };

/**
 * The page's one tooltip, for any element with `data-tip` (and `data-tip-side`, right by default). It sits in a layer
 * above everything, flips to the other side when there is no room, and is kept inside the window, so a tip on a
 * control near an edge or in a scrolled panel is never cut off.
 */
export function Tooltips() {
  const [tip, setTip] = useState<{ el: HTMLElement; text: string; side: Side } | null>(null);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
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
    const focus = (e: FocusEvent) => { if ((e.target as HTMLElement).matches?.(":focus-visible")) show(e.target); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") hide(); };
    document.addEventListener("pointerover", over);
    document.addEventListener("focusin", focus);
    document.addEventListener("focusout", hide);
    document.addEventListener("pointerdown", hide, true);
    document.addEventListener("scroll", hide, true);
    window.addEventListener("keydown", key);
    window.addEventListener("blur", hide);
    return () => {
      document.removeEventListener("pointerover", over);
      document.removeEventListener("focusin", focus);
      document.removeEventListener("focusout", hide);
      document.removeEventListener("pointerdown", hide, true);
      document.removeEventListener("scroll", hide, true);
      window.removeEventListener("keydown", key);
      window.removeEventListener("blur", hide);
    };
  }, []);

  // Leaving the element (or it being removed) hides the tip.
  useEffect(() => {
    if (!tip) return;
    const leave = (e: PointerEvent) => { if (!tip.el.contains(e.relatedTarget as Node | null)) setTip(null); };
    tip.el.addEventListener("pointerleave", leave);
    const gone = window.setInterval(() => { if (!tip.el.isConnected) setTip(null); }, 300);
    return () => { tip.el.removeEventListener("pointerleave", leave); window.clearInterval(gone); };
  }, [tip]);

  useLayoutEffect(() => {
    const b = box.current;
    if (!tip || !b) return;
    const r = tip.el.getBoundingClientRect();
    const w = b.offsetWidth, h = b.offsetHeight, vw = window.innerWidth, vh = window.innerHeight, gap = 8, pad = 6;
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

  return tip ? createPortal(<div ref={box} className="tooltip" role="tooltip" style={{ visibility: "hidden" }}>{tip.text}</div>, document.body) : null;
}
