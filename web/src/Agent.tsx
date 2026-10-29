import { Bot, Check, Copy, Eye, EyeOff, LoaderCircle, Plug, Unplug, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { AgentLink } from "./api";

/** One thing the agent did, as the page shows it. */
export interface AgentLogEntry { at: number; tool: string; text: string }

/**
 * "Connect an agent": a link that lets an MCP client (Muse Code, Claude, an IDE) work on this session, with
 * copy-ready settings for each, what the agent has done, and Revoke. The page follows what the agent does (App.tsx).
 */
export function AgentDialog({ link, log, now, creating, error, canCreate, onCreate, onRevoke, onClose }: {
  link: AgentLink | null; log: AgentLogEntry[]; now: number; creating: boolean; error: string | null; canCreate: boolean;
  onCreate: () => void; onRevoke: () => void; onClose: () => void;
}) {
  const [tab, setTab] = useState<"muse-code" | "claude-code" | "claude-desktop" | "other" | "local">("muse-code");
  // The client settings are for the first time; after that only the token changes, so they fold away.
  const [setupOpen, setSetupOpen] = useState(() => { try { return !localStorage.getItem(SETUP_KEY); } catch { return true; } });
  useEffect(() => { if (link) { try { localStorage.setItem(SETUP_KEY, "1"); } catch { /* private window */ } } }, [link]);
  const snippets = link ? {
    "muse-code": JSON.stringify({ schema_version: 1, mcpServers: { orca: { transport: "streamable_http", url: link.mcp_url,
      headers: { Authorization: `Bearer ${link.token}` }, mode: "optional" } } }, null, 2),
    "claude-code": `claude mcp add --transport http orca ${link.mcp_url} --header "Authorization: Bearer ${link.token}"`,
    "claude-desktop": JSON.stringify({ mcpServers: { orca: { command: "npx", args: ["-y", "mcp-remote", link.mcp_url,
      "--header", `Authorization: Bearer ${link.token}`] } } }, null, 2),
    other: `MCP server (Streamable HTTP): ${link.mcp_url}\nHeader: Authorization: Bearer ${link.token}\n\nNo headers? Use: ${link.mcp_url}?key=${link.token}`,
    local: "cd server && uv run python -m sightline.mcp_server   # stdio, its own session, no browser",
  } : null;
  const last = link?.last_call;
  return (
    <div className="about-dialog" role="dialog" aria-modal="true" aria-label="Connect an agent" onClick={onClose}>
      <div className="report-dialog agent-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="row"><h2><Plug size={18} aria-hidden /> Connect an agent</h2>
          <button className="ibtn" aria-label="Close" onClick={onClose}><X size={16} aria-hidden /></button></div>
        <p className="hint">Give an AI agent (Muse Code, Claude, your IDE) this session over MCP. It sees what you see:
          the models, the clashes and their pictures. It can check its own ideas against the model, run ORCA's fix agent,
          apply fixes, triage and build the report. This page follows what it does.</p>

        {!link ? <>
          <button className="btn primary big" disabled={creating || !canCreate} onClick={onCreate}>
            {creating ? <LoaderCircle size={15} className="spin" aria-hidden /> : <Plug size={15} aria-hidden />} Make a link for this session</button>
          {!canCreate && <p className="hint">Open models first: the agent works on what you have open.</p>}
          <p className="hint">The link is a secret: whoever has it can act on this session until it expires (12 hours after
            it was last used, 24 hours at most) or you revoke it. Fixes it asks for count against the demo's allowance, like yours.</p>
        </> : <>
          <div className="agent-status">
            <span className={`dot ${last && now / 1000 - last.at < 60 ? "on" : ""}`} aria-hidden />
            {last ? <span><Bot size={14} aria-hidden /> Agent connected · last call <b>{last.tool}</b> {ago(now / 1000 - last.at)}</span>
              : <span><LoaderCircle size={13} className="spin" aria-hidden /> Waiting for an agent…</span>}
            <ExpiryChip link={link} now={now} />
          </div>
          <div className="agent-fields">
            <CopyField label="Token" value={link.token} secret />
            <CopyField label="Server" value={link.mcp_url} />
          </div>
          <p className="hint">Only the token changes between sessions: paste it into your agent's settings in place of the old
            one.</p>
          <details className="agent-setup" open={setupOpen} onToggle={(e) => setSetupOpen((e.target as HTMLDetailsElement).open)}>
          <summary>First time? Set up your agent</summary>
          <div className="seg" role="tablist" aria-label="Agent">
            {([["muse-code", "Muse Code"], ["claude-code", "Claude Code"], ["claude-desktop", "Claude Desktop"], ["other", "Other agents"], ["local", "Local (stdio)"]] as const)
              .map(([k, label]) => <button key={k} role="tab" className={tab === k ? "on" : ""} aria-selected={tab === k} onClick={() => setTab(k)}>{label}</button>)}
          </div>
          <Snippet text={snippets![tab]} />
          <p className="hint">{tab === "muse-code" ? <>Add it to Muse Code's settings file: <code>~/.config/muse/settings.json</code> (on
              Windows <code>C:\Users\&lt;you&gt;\.config\muse\settings.json</code>), then check with <code>muse mcp list</code>. Keep the file's <code>"schema_version": 1</code>, and merge the <code>orca</code> entry into
              whichever of <code>mcpServers</code> or the older <code>mcp_servers</code> your file already uses (only one of them).{" "}
              <code>"optional"</code> lets Muse Code carry on if this link expires. Set up once: write{" "}
              <code>{"Bearer ${ORCA_TOKEN}"}</code> in the file, and each new session only changes <code>ORCA_TOKEN</code> in your
              environment.</>
            : tab === "claude-code" ? <>Run it in a terminal, then ask Claude about your clashes. For a new session, run{" "}
              <code>claude mcp remove orca</code> first.</>
            : tab === "claude-desktop" ? "Add it to claude_desktop_config.json (Settings › Developer › Edit config), then restart Claude. For a new session, replace the token and restart."
            : tab === "other" ? "Any MCP client that speaks Streamable HTTP."
            : "For running ORCA yourself: a local session with its own models, and no browser to follow."}</p>
          </details>
          {log.length > 0 && <>
            <h3>What the agent did</h3>
            <ol className="agent-log">
              {log.slice(-8).reverse().map((e, i) => <li key={`${e.at}-${i}`}><b>{e.tool}</b> {e.text}<span className="hint"> {ago(now / 1000 - e.at)}</span></li>)}
            </ol>
          </>}
          <div className="actions"><button className="btn" onClick={onRevoke}><Unplug size={14} aria-hidden /> Revoke this link</button></div>
        </>}
        {error && <p className="agent-error" role="alert">{error}</p>}
      </div>
    </div>
  );
}

/** Seconds this link has left, on the server's clock (the visitor's may be off). */
export function secondsLeft(link: AgentLink, now: number): number {
  return link.expires_at - (now / 1000 + (link.clock_offset ?? 0));
}

/** "11 h 52 min", "40 min", "under a minute". */
export function timeLeft(link: AgentLink, now: number): string {
  const s = secondsLeft(link, now);
  if (s <= 60) return "under a minute";
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h ? `${h} h ${String(m).padStart(2, "0")} min` : `${m} min`;
}

function ExpiryChip({ link, now }: { link: AgentLink; now: number }) {
  const s = secondsLeft(link, now);
  const at = (t: number) => new Date((t - (link.clock_offset ?? 0)) * 1000)
    .toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  const capped = link.expires_at >= link.max_expires_at - 1;
  return (
    <span className={`hint agent-expiry${s < 1800 ? " soon" : ""}`} data-tip-tap data-tip-side="bottom"
      data-tip={`Expires ${at(link.expires_at)}. ${capped ? "It has reached its 24-hour limit." : `Each use renews it to 12 hours, until ${at(link.max_expires_at)} at the latest.`}`}>
      · {s < 1800 ? "expiring soon: " : ""}{timeLeft(link, now)} left</span>
  );
}

const SETUP_KEY = "sightline.agent.setup";

/** One value to copy on its own line: the token (masked unless shown) or the server URL. */
function CopyField({ label, value, secret = false }: { label: string; value: string; secret?: boolean }) {
  const [shown, setShown] = useState(!secret);
  const [copied, setCopied] = useState(false);
  const masked = `${value.slice(0, 5)}${"•".repeat(10)}${value.slice(-4)}`;
  return (
    <div className="copy-field">
      <span className="copy-label">{label}</span>
      <code className="mono" aria-label={label}>{shown ? value : masked}</code>
      {secret && <button className="ibtn" aria-label={shown ? "Hide the token" : "Show the token"} data-tip={shown ? "Hide" : "Show"}
        onClick={() => setShown((v) => !v)}>{shown ? <EyeOff size={14} aria-hidden /> : <Eye size={14} aria-hidden />}</button>}
      <button className="ibtn" aria-label={`Copy the ${label.toLowerCase()}`} data-tip={copied ? "Copied" : "Copy"} onClick={() => {
        void navigator.clipboard?.writeText(value).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); });
      }}>{copied ? <Check size={14} aria-hidden /> : <Copy size={14} aria-hidden />}</button>
    </div>
  );
}

function Snippet({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="snippet">
      <pre className="mono">{text}</pre>
      <button className="ibtn" aria-label="Copy" data-tip={copied ? "Copied" : "Copy"} onClick={() => {
        void navigator.clipboard?.writeText(text).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); });
      }}>{copied ? <Check size={14} aria-hidden /> : <Copy size={14} aria-hidden />}</button>
    </div>
  );
}

function ago(s: number): string {
  if (s < 5) return "just now";
  if (s < 60) return `${Math.round(s)} s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  return `${Math.round(s / 3600)} h ago`;
}
