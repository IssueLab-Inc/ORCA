import { useEffect, useRef, useState, type RefObject } from "react";

/** The visitor asks for less motion (and may change their mind while the page is open). */
export function useReducedMotion(): boolean {
  const query = "(prefers-reduced-motion: reduce)";
  const [reduce, setReduce] = useState(() => typeof window !== "undefined" && !!window.matchMedia?.(query).matches);
  useEffect(() => {
    const q = window.matchMedia?.(query);
    if (!q) return;
    const on = () => setReduce(q.matches);
    q.addEventListener("change", on);
    return () => q.removeEventListener("change", on);
  }, []);
  return reduce;
}

/** True once the element has scrolled into view (and stays true); without IntersectionObserver, at once. */
export function useSeen<T extends Element>(margin = "0px 0px -12% 0px"): [RefObject<T | null>, boolean] {
  const ref = useRef<T>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || seen) return;
    if (typeof IntersectionObserver === "undefined") { setSeen(true); return; }
    const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) setSeen(true); }, { rootMargin: margin, threshold: 0.01 });
    io.observe(el);
    return () => io.disconnect();
  }, [seen, margin]);
  return [ref, seen];
}

/** Fades sections up as they scroll in (each once): marks `.lp-reveal` elements under `root` with `data-in`, including
 * ones that arrive later (a demo card shown once the samples are listed). */
export function useReveal(root: RefObject<HTMLElement | null>, reduce: boolean) {
  useEffect(() => {
    const el = root.current;
    if (!el) return;
    const pending = () => Array.from(el.querySelectorAll<HTMLElement>(".lp-reveal:not([data-in])"));
    if (reduce || typeof IntersectionObserver === "undefined") {
      const show = () => pending().forEach((i) => i.setAttribute("data-in", ""));
      show();
      const mo = typeof MutationObserver === "undefined" ? null : new MutationObserver(show);
      mo?.observe(el, { childList: true, subtree: true });
      return () => mo?.disconnect();
    }
    const watched = new WeakSet<Element>();
    const io = new IntersectionObserver((es) => {
      for (const e of es) if (e.isIntersecting) { e.target.setAttribute("data-in", ""); io.unobserve(e.target); }
    }, { root: el, rootMargin: "0px 0px -8% 0px", threshold: 0.06 });
    const watch = () => pending().forEach((i) => { if (!watched.has(i)) { watched.add(i); io.observe(i); } });
    watch();
    const mo = typeof MutationObserver === "undefined" ? null : new MutationObserver(watch);
    mo?.observe(el, { childList: true, subtree: true });
    return () => { io.disconnect(); mo?.disconnect(); };
  }, [root, reduce]);
}

/** The section in the middle of the scroller's view, by id, for the header's links. */
export function useSpy(root: RefObject<HTMLElement | null>, ids: string[]): string | null {
  const [on, setOn] = useState<string | null>(null);
  const key = ids.join(",");
  useEffect(() => {
    const el = root.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver((es) => {
      for (const e of es) if (e.isIntersecting) setOn(e.target.id);
    }, { root: el, rootMargin: "-45% 0px -54% 0px", threshold: 0 });
    for (const id of key.split(",")) { const s = el.querySelector(`#${id}`); if (s) io.observe(s); }
    const top = () => { if (el.scrollTop < 200) setOn(null); };
    el.addEventListener("scroll", top, { passive: true });
    return () => { io.disconnect(); el.removeEventListener("scroll", top); };
  }, [root, key]);
  return on;
}

/** How far an element has travelled through the scroller's view: 0 as its top enters the bottom, 1 once its middle
 * reaches `end` (a fraction of the view's height from the top). Updated on scroll, at most once a frame. */
export function useScrollProgress(el: RefObject<HTMLElement | null>, end = 0.45): number {
  const [p, setP] = useState(0);
  useEffect(() => {
    const node = el.current;
    const scroller = node?.closest(".lp-page");
    if (!node || !scroller) return;
    let raf = 0;
    const read = () => {
      raf = 0;
      const box = scroller.getBoundingClientRect(), r = node.getBoundingClientRect();
      // 0 with the element's top at the bottom of the view, 1 with its middle at `end` of the way down
      const top = r.top - box.top, view = box.height;
      const v = (view - top) / Math.max(1, view - end * view + r.height / 2);
      setP(Math.max(0, Math.min(1, v)));
    };
    const on = () => { if (!raf) raf = requestAnimationFrame(read); };
    read();
    scroller.addEventListener("scroll", on, { passive: true });
    window.addEventListener("resize", on);
    return () => { scroller.removeEventListener("scroll", on); window.removeEventListener("resize", on); cancelAnimationFrame(raf); };
  }, [el, end]);
  return p;
}

/** A number that counts up once it is seen (straight to the end for less motion). */
export function useCountUp(to: number, run: boolean, reduce: boolean, ms = 1300): number {
  const [v, setV] = useState(reduce ? to : 0);
  useEffect(() => {
    if (reduce) { setV(to); return; }
    if (!run) return;
    let raf = 0;
    const t0 = performance.now();
    const step = (now: number) => {
      const x = Math.min(1, (now - t0) / ms), e = 1 - Math.pow(1 - x, 3);
      setV(Math.round(to * e));
      if (x < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [to, run, reduce, ms]);
  return v;
}
