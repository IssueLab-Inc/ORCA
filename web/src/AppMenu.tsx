import { X } from "lucide-react";
import { useEffect, useRef } from "react";

/** The header's menu on phones and tablets: every header action in one panel from the right, each with its name,
 * in the order of the work (models, coordinate, this session's outputs, help). Escape or the scrim closes it. */
export function MenuSheet({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  const panel = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") close.current(); };
    window.addEventListener("keydown", esc);
    panel.current?.querySelector<HTMLElement>(".menu-head .ibtn")?.focus({ preventScroll: true });
    return () => window.removeEventListener("keydown", esc);
  }, []);
  return (
    <div className="menu-sheet" role="dialog" aria-modal="true" aria-label={title} onClick={onClose}>
      <div className="menu-panel" ref={panel} onClick={(e) => e.stopPropagation()}>
        <div className="menu-head">
          <span className="brand"><span className="logo" aria-hidden>◎</span><b>{title}</b></span>
          <button type="button" className="ibtn" aria-label="Close the menu" onClick={onClose}><X size={20} aria-hidden /></button>
        </div>
        {children}
      </div>
    </div>
  );
}
