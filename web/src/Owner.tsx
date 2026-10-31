import { KeyRound, Lock, Settings2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api, setOwnerSettings, type Effort, type EscalationMode, type EveryoneSettings, type OwnerSettings, type SettingsState } from "./api";
import { Popover } from "./ui";
import { aiName } from "./aiNames";

const KEY = "sightline.owner";
const EFFORTS: Effort[] = ["minimal", "low", "medium", "high"];
/** Second tries on Muse Wonder (docs/escalation.md): off, offered as a button, or automatic after no fix. */
const ESCALATION: [EscalationMode, string][] = [["off", "Off"], ["button", "Offered (a button)"], ["auto", "Automatic after no fix"]];

function stored(): OwnerSettings {
  try { return JSON.parse(localStorage.getItem(KEY) ?? "{}") as OwnerSettings; } catch { return {}; }
}

/**
 * Settings for the deployment's owner, in two scopes. "For me": reasoning effort, the open-weights model and the demo
 * caps for the owner's own requests (this browser, sent with each request). "For everyone": reasoning effort and the
 * open-weights model for every visitor (kept on the server). The owner's own win for the owner. Hidden from visitors: the gear shows once
 * unlocked, or on a page opened with #owner. The token is sent once; the server answers with a cookie this page's
 * scripts cannot read, so the token is never kept in the browser.
 */
export function OwnerSettingsMenu({ onChange, onEveryone, note }: { onChange: (s: OwnerSettings | null) => void;
  /** A setting for everyone changed: this page asks again what it gets (second tries, Show it built). */
  onEveryone?: () => void;
  /** The owner's settings in force, in a few words: on the button's tip, which is marked while they are on. */
  note?: string }) {
  const [state, setState] = useState<{ available: boolean; owner: boolean } | null>(null);
  const [settings, setSettings] = useState<OwnerSettings>(stored);
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const asked = typeof location !== "undefined" && location.hash.includes("owner");
  const [scope, setScope] = useState<"me" | "everyone">("me");
  const [everyone, setEveryone] = useState<SettingsState | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  useEffect(() => { api.owner().then(setState).catch(() => setState(null)); }, []);
  useEffect(() => {
    const s = state?.owner ? settings : null;
    setOwnerSettings(s);
    onChange(s);
  }, [state?.owner, settings]);  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (state?.owner) api.settings().then(setEveryone).catch((e) => setError((e as Error).message));
  }, [state?.owner]);

  if (!state?.available || (!state.owner && !asked)) return null;

  const change = (next: OwnerSettings) => {
    setSettings(next);
    try { localStorage.setItem(KEY, JSON.stringify(next)); } catch { /* private window */ }
  };
  const saveEveryone = async (changes: Partial<EveryoneSettings>) => {
    setError(null); setSaved(null);
    try { setEveryone(await api.saveSettings(changes)); setSaved("Saved for everyone"); onEveryone?.(); }
    catch (e) { setError((e as Error).message); }
  };
  const ow = (v: boolean) => (v ? "on" : "off");
  const unlock = async () => {
    setError(null);
    try { await api.unlock(token); setToken(""); setState({ available: true, owner: true }); }
    catch (e) { setError((e as Error).message); }
  };

  return (
    <Popover icon={Settings2} label="Owner settings" tip="bottom" note={note}>
      {() => state.owner ? (
        <div className="owner-menu">
          <b>Owner settings</b>
          <div className="seg" role="group" aria-label="Who these settings are for">
            <button className={scope === "me" ? "on" : ""} aria-pressed={scope === "me"} onClick={() => setScope("me")}>For me</button>
            <button className={scope === "everyone" ? "on" : ""} aria-pressed={scope === "everyone"} onClick={() => setScope("everyone")}>For everyone</button>
          </div>
          {scope === "me" ? (<>
            <label>{aiName("proposal")} reasoning
              <select value={settings.effort ?? ""} onChange={(e) => change({ ...settings, effort: (e.target.value || undefined) as Effort | undefined })}>
                <option value="">Same as everyone</option>
                {EFFORTS.map((x) => <option key={x}>{x}</option>)}
              </select>
            </label>
            <label>Triage reasoning
              <select value={settings.triage_effort ?? ""} onChange={(e) => change({ ...settings, triage_effort: (e.target.value || undefined) as Effort | undefined })}>
                <option value="">Same as everyone</option>
                {EFFORTS.map((x) => <option key={x}>{x}</option>)}
              </select>
            </label>
            <label>Open-weights model (titles, triage)
              <select value={settings.open_weights == null ? "" : ow(settings.open_weights)}
                onChange={(e) => change({ ...settings, open_weights: e.target.value === "" ? undefined : e.target.value === "on" })}>
                <option value="">Same as everyone</option>
                <option value="on">On: the open-weights model</option>
                <option value="off">Off: {aiName("proposal")}</option>
              </select>
            </label>
            <label>Second try on {aiName("escalation")}
              <select value={settings.escalation ?? ""} onChange={(e) => change({ ...settings, escalation: (e.target.value || undefined) as EscalationMode | undefined })}>
                <option value="">Same as everyone</option>
                {ESCALATION.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
              </select>
            </label>
            <label>{aiName("escalation")} reasoning
              <select value={settings.escalation_effort ?? ""} onChange={(e) => change({ ...settings, escalation_effort: (e.target.value || undefined) as Effort | undefined })}>
                <option value="">Same as everyone</option>
                {EFFORTS.map((x) => <option key={x}>{x}</option>)}
              </select>
            </label>
            <label>Show it built ({aiName("image")} pictures of fixes)
              <select value={settings.built_views == null ? "" : ow(settings.built_views)}
                onChange={(e) => change({ ...settings, built_views: e.target.value === "" ? undefined : e.target.value === "on" })}>
                <option value="">Same as everyone</option>
                <option value="on">On</option>
                <option value="off">Off</option>
              </select>
            </label>
            <label className="check"><input type="checkbox" checked={settings.no_caps !== false}
              onChange={(e) => change({ ...settings, no_caps: e.target.checked })} /> Skip the demo caps</label>
            <p className="hint">Only your requests use these, and they win over the settings for everyone. A triage run you
              start uses your triage settings for everyone following it.</p>
          </>) : everyone ? (<>
            <label>{aiName("proposal")} reasoning
              <select value={everyone.everyone.effort ?? ""} onChange={(e) => void saveEveryone({ effort: (e.target.value || null) as Effort | null })}>
                <option value="">Default ({everyone.defaults.effort ?? "the API's"})</option>
                {EFFORTS.map((x) => <option key={x}>{x}</option>)}
              </select>
            </label>
            <label>Triage reasoning
              <select value={everyone.everyone.triage_effort ?? ""} onChange={(e) => void saveEveryone({ triage_effort: (e.target.value || null) as Effort | null })}>
                <option value="">Default ({everyone.defaults.triage_effort ?? "the host's"})</option>
                {EFFORTS.map((x) => <option key={x}>{x}</option>)}
              </select>
            </label>
            <label>Open-weights model (titles, triage)
              <select disabled={!everyone.host} value={everyone.everyone.open_weights == null ? "" : ow(everyone.everyone.open_weights)}
                onChange={(e) => void saveEveryone({ open_weights: e.target.value === "" ? null : e.target.value === "on" })}>
                <option value="">Default ({everyone.defaults.open_weights ? "on" : "off"})</option>
                <option value="on">On: the open-weights model</option>
                <option value="off">Off: {aiName("proposal")}</option>
              </select>
            </label>
            {!everyone.host && <p className="hint">No open-weights host is configured (TRIAGE_API_KEY), so titles and triage
              use {aiName("proposal")}.</p>}
            <label>Second try on {aiName("escalation")}
              <select value={everyone.everyone.escalation ?? ""} onChange={(e) => void saveEveryone({ escalation: (e.target.value || null) as EscalationMode | null })}>
                <option value="">Default ({ESCALATION.find(([v]) => v === everyone.defaults.escalation)?.[1].toLowerCase() ?? "offered"})</option>
                {ESCALATION.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
              </select>
            </label>
            <label>{aiName("escalation")} reasoning
              <select value={everyone.everyone.escalation_effort ?? ""} onChange={(e) => void saveEveryone({ escalation_effort: (e.target.value || null) as Effort | null })}>
                <option value="">Default ({everyone.defaults.escalation_effort ?? "medium"})</option>
                {EFFORTS.map((x) => <option key={x}>{x}</option>)}
              </select>
            </label>
            <p className="hint">{aiName("escalation")} bills every token (about $0.3 to $1 a second try), within the day's budget and
              each visitor's caps.</p>
            <label>Show it built ({aiName("image")} pictures of fixes)
              <select value={everyone.everyone.built_views == null ? "" : ow(everyone.everyone.built_views)}
                onChange={(e) => void saveEveryone({ built_views: e.target.value === "" ? null : e.target.value === "on" })}>
                <option value="">Default ({everyone.defaults.built_views ? "on" : "off"})</option>
                <option value="on">On</option>
                <option value="off">Off</option>
              </select>
            </label>
            <p className="hint">A picture costs about $0.3 (two drawings, four {aiName("escalation")} judgements; up to $0.6 with a
              second pair), and every accepted fix gets one for the PDF while it is on.</p>
            <p className="hint">Every visitor's requests use these, kept on the server across restarts. Runs already going
              keep their model.</p>
            {saved && <p className="ok small" role="status">{saved}</p>}
          </>) : <p className="hint">Reading the settings for everyone…</p>}
          {error && <p className="bad small">{error}</p>}
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
