import { useEffect, useRef, useState } from "react";
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
