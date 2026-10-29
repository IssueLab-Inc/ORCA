import { Bot, Check, Copy, LoaderCircle, Plug, Unplug, X } from "lucide-react";
import { useState } from "react";
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
  const snippets = link ? {
    // Muse Code's CLI adds a remote server by URL (no header option), so the token rides in the URL there.
    "muse-code": `muse mcp add --transport http orca "${link.mcp_url}?key=${link.token}"`,
    "muse-code-json": JSON.stringify({ schema_version: 1, mcpServers: { orca: { transport: "streamable_http", url: link.mcp_url,
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
          <div className="seg" role="tablist" aria-label="Agent">
            {([["muse-code", "Muse Code"], ["claude-code", "Claude Code"], ["claude-desktop", "Claude Desktop"], ["other", "Other agents"], ["local", "Local (stdio)"]] as const)
              .map(([k, label]) => <button key={k} role="tab" className={tab === k ? "on" : ""} aria-selected={tab === k} onClick={() => setTab(k)}>{label}</button>)}
          </div>
          <Snippet text={snippets![tab]} />
          {tab === "muse-code" && <>
            <p className="hint">Run it in a terminal, then <code>muse mcp list</code> to check ORCA is there. Or add it to your
              settings file instead (<code>~/.config/muse/settings.json</code>; on Windows <code>C:\Users\&lt;you&gt;\.config\muse\settings.json</code>):</p>
            <Snippet text={snippets!["muse-code-json"]} />
          </>}
          <p className="hint">{tab === "muse-code" ? <>Keep the file's <code>"schema_version": 1</code>, and merge the <code>orca</code> entry into
              whichever of <code>mcpServers</code> or the older <code>mcp_servers</code> your file already uses (only one of them).{" "}
              <code>"optional"</code> lets Muse Code carry on if this link expires. To keep the token out of the file, write{" "}
              <code>{"Bearer ${ORCA_TOKEN}"}</code> and set <code>ORCA_TOKEN</code> in your environment.</>
            : tab === "claude-code" ? "Run it in a terminal, then ask Claude about your clashes."
            : tab === "claude-desktop" ? "Add it to claude_desktop_config.json (Settings › Developer › Edit config), then restart Claude."
            : tab === "other" ? "Any MCP client that speaks Streamable HTTP."
            : "For running ORCA yourself: a local session with its own models, and no browser to follow."}</p>
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
    <span className={`hint agent-expiry${s < 1800 ? " soon" : ""}`} data-tip-side="bottom"
      data-tip={`Expires ${at(link.expires_at)}. ${capped ? "It has reached its 24-hour limit." : `Each use renews it to 12 hours, until ${at(link.max_expires_at)} at the latest.`}`}>
      · {s < 1800 ? "expiring soon: " : ""}{timeLeft(link, now)} left</span>
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
