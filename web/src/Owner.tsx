import { KeyRound, Lock, Settings2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api, setOwnerSettings, type Effort, type OwnerSettings } from "./api";
import { Popover } from "./ui";

const KEY = "sightline.owner";
const EFFORTS: Effort[] = ["minimal", "low", "medium", "high"];

function stored(): OwnerSettings {
  try { return JSON.parse(localStorage.getItem(KEY) ?? "{}") as OwnerSettings; } catch { return {}; }
}

/**
 * Settings for the deployment's owner: reasoning effort and the demo caps. Hidden from visitors: the gear shows once
 * unlocked, or on a page opened with #owner. The token is sent once; the server answers with a cookie this page's
 * scripts cannot read, so the token is never kept in the browser.
 */
export function OwnerSettingsMenu({ onChange }: { onChange: (s: OwnerSettings | null) => void }) {
  const [state, setState] = useState<{ available: boolean; owner: boolean } | null>(null);
  const [settings, setSettings] = useState<OwnerSettings>(stored);
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const asked = typeof location !== "undefined" && location.hash.includes("owner");

  useEffect(() => { api.owner().then(setState).catch(() => setState(null)); }, []);
  useEffect(() => {
    const s = state?.owner ? settings : null;
    setOwnerSettings(s);
    onChange(s);
  }, [state?.owner, settings]);  // eslint-disable-line react-hooks/exhaustive-deps

  if (!state?.available || (!state.owner && !asked)) return null;

  const change = (next: OwnerSettings) => {
    setSettings(next);
    try { localStorage.setItem(KEY, JSON.stringify(next)); } catch { /* private window */ }
  };
  const unlock = async () => {
    setError(null);
    try { await api.unlock(token); setToken(""); setState({ available: true, owner: true }); }
    catch (e) { setError((e as Error).message); }
  };

  return (
    <Popover icon={Settings2} label="Owner settings" tip="bottom">
      {() => state.owner ? (
        <div className="owner-menu">
          <b>Owner settings</b>
          <label>Muse Spark reasoning
            <select value={settings.effort ?? ""} onChange={(e) => change({ ...settings, effort: (e.target.value || undefined) as Effort | undefined })}>
              <option value="">Default (server: low)</option>
              {EFFORTS.map((x) => <option key={x}>{x}</option>)}
            </select>
          </label>
          <label>Triage reasoning
            <select value={settings.triage_effort ?? ""} onChange={(e) => change({ ...settings, triage_effort: (e.target.value || undefined) as Effort | undefined })}>
              <option value="">Default (the host's)</option>
              {EFFORTS.map((x) => <option key={x}>{x}</option>)}
            </select>
          </label>
          <label className="check"><input type="checkbox" checked={settings.no_caps !== false}
            onChange={(e) => change({ ...settings, no_caps: e.target.checked })} /> Skip the demo caps</label>
          <p className="hint">Only your requests use these. A triage run started now uses your triage setting for everyone
            following it.</p>
          <button className="btn small" onClick={async () => { await api.lock().catch(() => undefined); setState({ available: true, owner: false }); }}>
            <Lock size={13} aria-hidden /> Lock this browser</button>
        </div>
      ) : (
        <form className="owner-menu" onSubmit={(e) => { e.preventDefault(); void unlock(); }}>
          <b><KeyRound size={14} aria-hidden /> Unlock owner settings</b>
          <input type="password" autoComplete="off" spellCheck={false} value={token} onChange={(e) => setToken(e.target.value)}
            placeholder="Owner token" aria-label="Owner token" />
          <button className="btn small primary" disabled={!token.trim()}>Unlock</button>
          {error && <p className="bad small">{error}</p>}
          <p className="hint">Sent once. The server answers with a sign-in cookie this page's scripts cannot read, kept 30 days.</p>
        </form>
      )}
    </Popover>
  );
}
