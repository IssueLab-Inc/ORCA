import { Bot, Check, Copy, LoaderCircle, Plug, Unplug, X } from "lucide-react";
import { useState } from "react";
import type { AgentLink } from "./api";

/** One thing the agent did, as the page shows it. */
export interface AgentLogEntry { at: number; tool: string; text: string }

/**
 * "Connect an agent": a link that lets an MCP client (Claude, Meta's coding agent, an IDE) work on this session, with
 * copy-ready settings for each, what the agent has done, and Revoke. The page follows what the agent does (App.tsx).
 */
export function AgentDialog({ link, log, now, creating, error, canCreate, onCreate, onRevoke, onClose }: {
  link: AgentLink | null; log: AgentLogEntry[]; now: number; creating: boolean; error: string | null; canCreate: boolean;
  onCreate: () => void; onRevoke: () => void; onClose: () => void;
}) {
  const [tab, setTab] = useState<"claude-code" | "claude-desktop" | "other" | "local">("claude-code");
  const snippets = link ? {
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
        <p className="hint">Give an AI agent (Claude, Meta's coding agent, your IDE) this session over MCP. It sees what you see:
          the models, the clashes and their pictures. It can check its own ideas against the model, run ORCA's fix agent,
          apply fixes, triage and build the report. This page follows what it does.</p>

        {!link ? <>
          <button className="btn primary big" disabled={creating || !canCreate} onClick={onCreate}>
            {creating ? <LoaderCircle size={15} className="spin" aria-hidden /> : <Plug size={15} aria-hidden />} Make a link for this session</button>
          {!canCreate && <p className="hint">Open models first: the agent works on what you have open.</p>}
          <p className="hint">The link is a secret: whoever has it can act on this session until it expires (12 hours after
            its last use) or you revoke it. Fixes it asks for count against the demo's allowance, like yours.</p>
        </> : <>
          <div className="agent-status">
            <span className={`dot ${last && now / 1000 - last.at < 60 ? "on" : ""}`} aria-hidden />
            {last ? <span><Bot size={14} aria-hidden /> Agent connected · last call <b>{last.tool}</b> {ago(now / 1000 - last.at)}</span>
              : <span><LoaderCircle size={13} className="spin" aria-hidden /> Waiting for an agent…</span>}
            <span className="hint">· expires {new Date(link.expires_at * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
          </div>
          <div className="seg" role="tablist" aria-label="Agent">
            {([["claude-code", "Claude Code"], ["claude-desktop", "Claude Desktop"], ["other", "Other agents"], ["local", "Local (stdio)"]] as const)
              .map(([k, label]) => <button key={k} role="tab" className={tab === k ? "on" : ""} aria-selected={tab === k} onClick={() => setTab(k)}>{label}</button>)}
          </div>
          <Snippet text={snippets![tab]} />
          <p className="hint">{tab === "claude-code" ? "Run it in a terminal, then ask Claude about your clashes."
            : tab === "claude-desktop" ? "Add it to claude_desktop_config.json (Settings › Developer › Edit config), then restart Claude."
            : tab === "other" ? "Any MCP client that speaks Streamable HTTP, Meta's coding agent included."
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
