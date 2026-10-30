// ORCA's identity in the app (docs/brand-assets.md): the wordmark, the split-O symbol, the notch at the top of the
// model and the loading card. The paths are copied from assets/brand/orca/source/master.json via the kit's
// currentColor SVGs; the motion follows the kit's timings (Orbit 1.6 s, Settle 0.76 s, Reveal 1.6 s).

const O_A = "M 31.35038 211.9217 C -12.70846 161.18071 -10.02719 85.00785 37.49033 37.49033 C 85.00785 -10.02719 161.18071 -12.70846 211.9217 31.35038 L 172.14842 71.12366 C 143.48543 48.87496 102.74539 51.43123 77.08831 77.08831 C 51.43123 102.74539 48.87496 143.48543 71.12366 172.14842 Z";
const O_B = "M 224.64962 44.0783 C 268.70846 94.81929 266.02719 170.99215 218.50967 218.50967 C 170.99215 266.02719 94.81929 268.70846 44.0783 224.64962 L 83.85158 184.87634 C 112.51457 207.12504 153.25461 204.56877 178.91169 178.91169 C 204.56877 153.25461 207.12504 112.51457 184.87634 83.85158 Z";
const R = ["M 292 0 L 441 0 C 499 0 530 30 530 80 C 530 126 504 154 455 162 L 543 256 L 466 256 L 347 143 L 320 115 L 435 115 C 460 115 473 102 473 82 C 473 63 458 54 435 54 L 292 54 Z",
  "M 292 121 L 351 180 L 351 256 L 292 256 Z"];
const C = "M 791.05369 45.72319 C 756.46465 4.50157 699.78721 -10.6851 649.22142 7.71934 C 598.65563 26.12379 565 74.18901 565 128 C 565 181.81099 598.65563 229.87621 649.22142 248.28066 C 699.78721 266.6851 756.46465 251.49843 791.05369 210.27681 L 748.1552 174.28071 C 728.69887 197.46786 696.81781 206.01037 668.37455 195.65787 C 639.93129 185.30537 621 158.26868 621 128 C 621 97.73132 639.93129 70.69463 668.37455 60.34213 C 696.81781 49.98963 728.69887 58.53214 748.1552 81.71929 Z";
const A = ["M 805 256 L 941 0 L 975 64 L 877 256 Z", "M 988 88 L 1077 256 L 1004 256 L 951 157 Z"];

/** The ORCA wordmark in the current text colour. `height` is the cap height in px (28 is the guide's minimum for
 *  the wordmark: 128 px wide with its clear space; the notch uses 20, an owner decision). */
export function Wordmark({ height = 28, title = "ORCA" }: { height?: number; title?: string }) {
  return (
    <svg className="wordmark" width={Math.round(height * 1077 / 256)} height={height} viewBox="0 0 1077 256" fill="currentColor"
      role="img" aria-label={title}>
      <path d={O_A} /><path d={O_B} />{R.map((d) => <path key={d} d={d} />)}<path d={C} />{A.map((d) => <path key={d} d={d} />)}
    </svg>
  );
}

/** The split-O. `motion`: orbit (indeterminate work), settle (once, after a confirmed action) or none. */
export function OrcaMark({ size = 24, motion = "none" }: { size?: number; motion?: "none" | "orbit" | "settle" }) {
  return (
    <svg className={`orca-mark ${motion}`} width={size} height={size} viewBox="0 0 256 256" fill="currentColor" aria-hidden>
      <g><path d={O_A} /><path d={O_B} /></g>
    </svg>
  );
}

/** The app icon: the white split-O on a navy tile (phones and tablets, where the wordmark has no room). */
export function AppIcon({ size = 30 }: { size?: number }) {
  return (
    <svg className="app-icon" width={size} height={size} viewBox="0 0 256 256" role="img" aria-label="ORCA">
      <rect width="256" height="256" rx="56" fill="var(--navy)" />
      <g transform="translate(48 48) scale(.625)" fill="#fff"><path d={O_A} /><path d={O_B} /></g>
    </svg>
  );
}

/** What the notch says while ORCA works: a title, a detail line and, when the work has countable parts (models
 *  drawn), one bar segment per part. Every value comes from a real event; nothing advances on a timer. */
export interface NotchStatus { title: string; detail?: string; parts?: { done: number; total: number } }

/** The logo hanging from the top edge of the model. While ORCA works it grows to show what is happening, and folds
 *  back to the wordmark when the work ends. */
export function Notch({ status, onLogo }: { status: NotchStatus | null; onLogo: () => void }) {
  return (
    <div className={`notch ${status ? "working" : ""}`} onClick={(e) => e.stopPropagation()} onPointerDown={(e) => e.stopPropagation()}>
      <span className="notch-shoulder left" aria-hidden />
      {status ? (
        <div className="notch-body" role="status" aria-live="polite">
          <div className="notch-line">
            <OrcaMark size={24} motion="orbit" />
            <span className="notch-text"><b>{status.title}</b>{status.detail && <span>{status.detail}</span>}</span>
          </div>
          {status.parts && status.parts.total > 1 && <Parts {...status.parts} />}
        </div>
      ) : (
        <button type="button" className="notch-body notch-logo" onClick={onLogo} aria-label="About ORCA" data-tip="About ORCA" data-tip-side="bottom">
          <Wordmark height={20} />
        </button>
      )}
      <span className="notch-shoulder right" aria-hidden />
    </div>
  );
}

function Parts({ done, total }: { done: number; total: number }) {
  return (
    <div className="parts" aria-hidden style={{ gridTemplateColumns: `repeat(${total}, minmax(0, 1fr))` }}>
      {Array.from({ length: total }, (_, i) => <span key={i} className={i < done ? "done" : i === done ? "now" : ""} />)}
    </div>
  );
}

/** Opening models, step by step: the server opens them, the page downloads each file, then draws each one. */
export interface LoadProgress {
  title: string;
  files: string[];
  step: "server" | "download" | "draw";
  /** The server's own words while it works (an upload's stages); else the step's. */
  line?: string;
  fetched: number;
  bytes: number;
  drawn: number;
  elements: number;
  /** When each step ended, ms since `started`. */
  started: number;
  ends: Partial<Record<"server" | "download", number>>;
}

const STEPS = ["server", "download", "draw"] as const;

/** The checklist card in the middle of an empty model while the first models open. */
export function LoadCard({ load, now }: { load: LoadProgress; now: number }) {
  const at = STEPS.indexOf(load.step);
  const n = load.files.length;
  const secs = (ms?: number) => (ms == null ? "" : `${(ms / 1000).toFixed(1)} s`);
  const rows: { text: string; aside: string; extra?: React.ReactNode }[] = [
    { text: at > 0 ? "Opened on the server" : load.line ?? "Opening on the server", aside: at > 0 ? secs(load.ends.server) : "" },
    { text: at > 1 ? `Downloaded ${n} of ${n} model${n === 1 ? "" : "s"}` : `Downloading model${n === 1 ? "" : "s"}: ${load.fetched} of ${n}`,
      aside: load.bytes ? `${(load.bytes / 1e6).toFixed(1)} MB` : "" },
    { text: at === 2 && load.drawn < n ? `Drawing model ${load.drawn + 1} of ${n}: ${load.files[load.drawn]}` : `Drawing the model${n === 1 ? "" : "s"}`,
      aside: load.elements ? `${load.elements.toLocaleString()} elements` : "",
      extra: at === 2 && n > 1 ? <><Parts done={load.drawn} total={n} />
        <p className="hint">{load.files.map((f, i) => `${f}${i < load.drawn ? " ✓" : ""}`).join(" · ")}</p></> : null },
  ];
  return (
    <section className="load-card" role="status" aria-live="polite" onClick={(e) => e.stopPropagation()}>
      <div className="load-head">
        <OrcaMark size={44} motion="orbit" />
        <div><h2>{load.title}</h2>
          <p className="hint">{n} model{n === 1 ? "" : "s"} · {Math.max(0, Math.round((now - load.started) / 1000))} s</p></div>
      </div>
      <ol className="load-steps">
        {rows.map((r, i) => (
          <li key={i} className={i < at ? "done" : i === at ? "now" : "next"}>
            <span className="tick" aria-hidden />
            <div className="load-row">
              <div className="row"><span>{r.text}</span><span className="mono why">{i <= at ? r.aside : ""}</span></div>
              {i === at && r.extra}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

/** A confirmed, completed action (a fix kept in the model): the mark settles once beside the words. */
export function KeptToast({ text, detail }: { text: string; detail?: string }) {
  return (
    <div className="toast kept" role="status">
      <OrcaMark size={28} motion="settle" />
      <span><b>{text}</b>{detail && <><br /><span className="why">{detail}</span></>}</span>
    </div>
  );
}
