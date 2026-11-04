import { ArrowRight, Box, Crop, MoveVertical, Redo2, Scissors, SquareDashed, Trash2, Undo2 } from "lucide-react";
import type { ReactNode } from "react";
import { FORMATS, LOGO, type LogoKey } from "./logos";

/**
 * The small pictures on the landing's "Everything around the fix" tiles, and the logos of what ORCA works with. Each is
 * decoration beside words that say the same (aria-hidden, or an empty alt); they move with CSS only (landing.css,
 * "Platform"), and stand still for less motion.
 */

export function Logo({ name, size = 24 }: { name: LogoKey; size?: number }) {
  return <img className={`lp-logo ${name}`} src={LOGO[name]} alt="" width={size} height={size} loading="lazy" decoding="async" draggable={false} />;
}

/** What ORCA reads and writes, each by its logo (`FORMATS`): the strip under the hero. */
export function Formats() {
  return (
    <section className="lp-formats" aria-labelledby="lp-formats-h">
      <div className="lp-wrap lp-formats-in lp-reveal">
        <p id="lp-formats-h">Works with the files and tools your teams already use</p>
        <ul>
          {FORMATS.map((f) => <li key={f.key}><Logo name={f.key} size={34} /><span><b>{f.name}</b>{f.what}</span></li>)}
        </ul>
      </div>
    </section>
  );
}

export function Tile({ cls = "", icon, title, art, children }: { cls?: string; icon: ReactNode; title: string; art?: ReactNode; children: ReactNode }) {
  return (
    <article className={`lp-tile lp-reveal ${cls}`}>
      {art && <div className="lp-tile-art" aria-hidden>{art}</div>}
      <div className="lp-tile-text">
        <h3><span className="lp-tile-icon" aria-hidden>{icon}</span>{title}</h3>
        <p>{children}</p>
      </div>
    </article>
  );
}

export function TriageArt() {
  const rows: [string, string, string][] = [
    ["Supply air main × transfer girder", "Real problem", "real"],
    ["Column × floor slab", "By design", "design"],
    ["Two copies of one beam", "Model error", "error"],
    ["Room space × wall", "Not physical", "space"],
  ];
  return (
    <ul className="lp-triage">
      {rows.map(([what, verdict, cls], i) => (
        <li key={what} style={{ ["--i" as string]: i }}><span>{what}</span><b className={cls}>{verdict}</b></li>
      ))}
    </ul>
  );
}

export function RootArt() {
  const spokes: [number, number, string][] = [[52, 34, "#1 duct"], [52, 96, "#2 tray"], [52, 158, "#3 water"]];
  return (
    <svg className="lp-root" viewBox="0 0 320 192">
      {spokes.map(([x, y, label], i) => (
        <g key={label} style={{ ["--i" as string]: i }}>
          <path className="lp-root-line" d={`M${x + 50} ${y} C ${x + 110} ${y}, 150 96, 196 96`} />
          <circle className="lp-root-pulse" r="4"><animateMotion dur="2.4s" begin={`${i * 0.5}s`} repeatCount="indefinite" path={`M${x + 50} ${y} C ${x + 110} ${y}, 150 96, 196 96`} /></circle>
          <rect className="lp-root-node" x={x - 44} y={y - 15} width="94" height="30" rx="8" />
          <text x={x + 3} y={y + 5} textAnchor="middle">{label}</text>
        </g>
      ))}
      <rect className="lp-root-hub" x="196" y="74" width="112" height="44" rx="10" />
      <text className="lp-root-hubtext" x="252" y="93" textAnchor="middle">TB-L02-01</text>
      <text className="lp-root-sub" x="252" y="108" textAnchor="middle">one plan, kept together</text>
    </svg>
  );
}

export function LanesArt() {
  return (
    <svg className="lp-lanes" viewBox="0 0 320 150">
      {["You", "Muse Spark", "ORCA"].map((l, i) => (
        <g key={l}><line x1="0" x2="320" y1={25 + i * 50} y2={25 + i * 50} className="lp-lane" /><text x="6" y={18 + i * 50} className="lp-lane-name">{l}</text></g>
      ))}
      <path className="lp-lane-flow" d="M40 25 C 70 25, 70 75, 100 75 C 130 75, 130 125, 160 125 C 190 125, 190 75, 220 75 C 250 75, 250 125, 280 125 C 300 125, 300 25, 312 25" />
      {[[40, 25, "req"], [100, 75, "ai"], [160, 125, "fail"], [220, 75, "ai"], [280, 125, "ok"]].map(([x, y, c], i) => (
        <circle key={i} cx={x} cy={y} r="7" className={`lp-lane-node ${c}`} style={{ ["--i" as string]: i }} />
      ))}
    </svg>
  );
}

export function ChatArt() {
  return (
    <div className="lp-chat">
      <p className="lp-chat-q">“Why are there so many clashes on Level 02? Fix the root cause.”</p>
      <div className="lp-chat-a"><span className="lp-wave">{Array.from({ length: 16 }, (_, i) => <i key={i} style={{ ["--i" as string]: i }} />)}</span>
        <span>One girder: plan for 3 clashes…</span></div>
    </div>
  );
}

export function ReqArt() {
  return (
    <div className="lp-req">
      <div className="lp-req-levels">{["L1", "L2", "L3", "L4", "L5"].map((l) => <span key={l} className={l === "L4" ? "on" : ""}>{l}</span>)}</div>
      <div className="lp-req-slider"><span>Lenient</span><i><b /></i><span>Exacting</span></div>
    </div>
  );
}

export function ViewsArt() {
  return (
    <div className="lp-views">
      <svg viewBox="0 0 80 54"><path className="v3d" d="M20 34 L40 24 L60 34 L40 44 Z M20 34 V20 L40 10 L60 20 V34 M40 24 V10" /></svg>
      <svg viewBox="0 0 80 54"><path className="vplan" d="M10 8H70V46H10Z M10 27H70 M40 8V46" /><circle cx="40" cy="27" r="3" className="vdot" /></svg>
      <svg viewBox="0 0 80 54"><path className="vsec" d="M26 8H54V12H42V42H54V46H26V42H38V12H26Z" /></svg>
      <svg viewBox="0 0 80 54"><path className="velev" d="M8 46H72 M14 46V18H66V46 M14 30H66" /><path className="vmeasure" d="M14 12H66 M14 9V15 M66 9V15" /></svg>
    </div>
  );
}

export function EditArt() {
  const tools = [MoveVertical, Box, SquareDashed, Scissors, Crop, Trash2];
  return (
    <div className="lp-edit">
      <div className="lp-edit-tools">{tools.map((I, i) => <span key={i} style={{ ["--i" as string]: i }}><I size={16} /></span>)}</div>
      <div className="lp-edit-log"><span><Undo2 size={13} /> Undo</span><span><Redo2 size={13} /> Redo</span><em>checked before Keep</em></div>
    </div>
  );
}

export function BuiltArt() {
  return (
    <div className="lp-built">
      <svg viewBox="0 0 200 110" className="lines"><path d="M10 80H190 M30 80V40H170V80 M30 52H170 M60 40V80 M100 40V80 M140 40V80 M80 20H120V40" /></svg>
      <div className="paint"><svg viewBox="0 0 200 110"><rect x="30" y="40" width="140" height="40" rx="2" /><rect x="80" y="20" width="40" height="20" rx="2" className="b" /><path d="M10 80H190" /></svg></div>
      <i className="wipe" />
    </div>
  );
}

export function McpArt() {
  return (
    <pre className="lp-code" aria-label="An MCP client's settings for ORCA">
      <span className="k">"orca"</span>: {"{"}{"\n"}
      {"  "}<span className="k">"transport"</span>: <span className="s">"streamable_http"</span>,{"\n"}
      {"  "}<span className="k">"url"</span>: <span className="s">"https://&lt;host&gt;/mcp"</span>,{"\n"}
      {"  "}<span className="k">"headers"</span>: {"{ "}<span className="k">"Authorization"</span>: <span className="s">"Bearer &lt;token&gt;"</span>{" }"}{"\n"}
      {"}"}
    </pre>
  );
}

export function FilesArt() {
  const files: [LogoKey, string, string][] = [["ifc", "IFC", "Edited models"], ["step", "STEP", "Written back"], ["pdf", "PDF", "Report, per team"], ["bcf", "BCF", "Issues, 2.1"]];
  return (
    <ul className="lp-files">
      {files.map(([key, ext, what], i) => (
        <li key={ext} className={key} style={{ ["--i" as string]: i }}><Logo name={key} size={30} /><b>{ext}</b><span>{what}</span></li>
      ))}
    </ul>
  );
}

/** A Navisworks clash report coming in: its XML and pictures, each clash given ORCA's #N (its own name kept) and triaged. */
export function NavisArt() {
  const rows: [string, string, string, string][] = [
    ["Clash39", "#1", "Real problem", "real"],
    ["Clash40", "#2", "By design", "design"],
    ["Clash41", "#3", "Model error", "error"],
  ];
  return (
    <div className="lp-navis">
      <div className="lp-navis-src">
        <Logo name="navisworks" size={38} />
        <span className="lp-navis-file"><b>Clash report, XML</b>
          <span className="lp-navis-pics">{[0, 1, 2].map((i) => <i key={i} style={{ ["--i" as string]: i }} />)}<em>and its pictures</em></span></span>
      </div>
      <ul className="lp-navis-rows">
        {rows.map(([ref, n, verdict, cls], i) => (
          <li key={ref} style={{ ["--i" as string]: i }}><s>{ref}</s><ArrowRight size={12} /><b>{n}</b><em className={cls}>{verdict}</em></li>
        ))}
      </ul>
    </div>
  );
}

export function PhoneArt() {
  return (
    <div className="lp-phone"><div className="lp-phone-body"><i className="model" /><i className="sheet"><b /></i></div></div>
  );
}
