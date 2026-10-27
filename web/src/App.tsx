import { useEffect, useRef, useState } from "react";
import { api, type Proposal, type Verdict } from "./api";
import { Viewer } from "./viewer/Viewer";

type Stats = { elements: number; triangles: number; parseMs: number };

const mm = (m: number | null | undefined) => (m == null ? "—" : `${m >= 0 ? "+" : ""}${(m * 1000).toFixed(1)} mm`);

export function App() {
  const host = useRef<HTMLDivElement>(null);
  const viewer = useRef<Viewer | null>(null);
  const [samples, setSamples] = useState<string[]>([]);
  const [sceneId, setSceneId] = useState<string | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [fps, setFps] = useState(0);
  const [a, setA] = useState<string | null>(null);
  const [b, setB] = useState<string | null>(null);
  const [isolate, setIsolate] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [chosen, setChosen] = useState<number | null>(null);
  const [manualDz, setManualDz] = useState(-0.25);
  const [manual, setManual] = useState<Verdict | null>(null);

  useEffect(() => {
    if (!host.current) return;
    const v = new Viewer(host.current);
    viewer.current = v;
    api.samples().then(setSamples).catch((e) => setError(`Can't reach the Sightline server: ${e.message}`));
    let frames = 0;
    let last = performance.now();
    let raf = 0;
    const tick = () => {
      frames++;
      const now = performance.now();
      if (now - last > 1000) { setFps(Math.round((frames * 1000) / (now - last))); frames = 0; last = now; }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => { cancelAnimationFrame(raf); v.dispose(); };
  }, []);

  useEffect(() => viewer.current?.highlight(a, b, isolate), [a, b, isolate]);

  useEffect(() => {
    const opt = chosen == null ? null : proposal?.options[chosen];
    viewer.current?.preview(opt ? [{ globalIds: opt.moved, deltaM: opt.delta_m }] : []);
  }, [chosen, proposal]);

  async function open(sample: string) {
    setBusy("Loading model…"); setError(null); setProposal(null); setA(null); setB(null);
    try {
      const { id } = await api.open(sample);
      setSceneId(id);
      setStats(await viewer.current!.load(await api.file(id)));
    } catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  }

  function onClick(ev: React.MouseEvent) {
    if (ev.detail !== 2) return; // double-click picks, so orbiting never selects by accident
    const gid = viewer.current?.pick(ev.nativeEvent);
    if (!gid || gid === a) return;
    if (!a || (a && b)) { setA(gid); setB(null); } else setB(gid);
    setProposal(null); setChosen(null); setManual(null);
  }

  async function propose() {
    if (!sceneId || !a || !b) return;
    setBusy("Sightline is looking at the clash…"); setError(null);
    try { const p = await api.propose(sceneId, a, b); setProposal(p); setChosen(p.options.length ? 0 : null); }
    catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  }

  async function checkManual() {
    if (!sceneId || !a) return;
    const v = await api.verify(sceneId, [a], [0, 0, manualDz]);
    setManual(v);
    viewer.current?.preview([{ globalIds: [a], deltaM: [0, 0, manualDz] }]);
  }

  return (
    <div className="app">
      <header className="bar">
        <b className="brand">ClashWise Sightline</b>
        <select id="sample" value="" onChange={(e) => e.target.value && open(e.target.value)} aria-label="Open a model">
          <option value="">{samples.length ? "Open a model…" : "No models in samples/"}</option>
          {samples.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        {stats && <span className="stat mono">{stats.elements} elements · {Math.round(stats.triangles / 1000)}k triangles · parsed in {(stats.parseMs / 1000).toFixed(1)} s · {fps} fps</span>}
        <span className="spacer" />
        {sceneId && <a className="btn primary" href={api.exportUrl(sceneId)}>Export edited IFC</a>}
      </header>

      <aside className="pane left">
        <h2>Clash</h2>
        <p className="hint">Double-click element A, then element B.</p>
        <dl className="kv">
          <dt><i className="sw red" />A</dt><dd className="mono">{a ?? "—"}</dd>
          <dt><i className="sw green" />B</dt><dd className="mono">{b ?? "—"}</dd>
        </dl>
        <label className="check"><input id="isolate" type="checkbox" checked={isolate} onChange={(e) => setIsolate(e.target.checked)} /> Isolate the pair</label>
        <button className="btn" disabled={!a || !b} onClick={() => viewer.current?.frame([a!, b!])}>Fit to pair</button>
        <button className="btn primary" disabled={!a || !b || !!busy} onClick={propose}>Propose fixes</button>

        <h2>Try a move</h2>
        <label className="field">Move A vertically (m)
          <input id="manual-dz" type="number" step="0.05" value={manualDz} onChange={(e) => setManualDz(Number(e.target.value))} />
        </label>
        <button className="btn" disabled={!a} onClick={checkManual}>Check this move</button>
        {manual && <p className={manual.passed ? "ok" : "bad"}>{manual.passed ? `Clear · nearest ${mm(manual.min_clearance_m)}` : manual.hits.map((h) => `${h.kind} with ${h.other_class} ${mm(h.distance_m)}`).join("; ")}</p>}
      </aside>

      <main className="stage" ref={host} onClick={onClick}>
        {busy && <div className="overlay">{busy}</div>}
        {error && <div className="overlay error">{error}</div>}
      </main>

      <aside className="pane right">
        <h2>Understanding</h2>
        <p>{proposal?.understanding || "Pick a clash and ask Sightline to propose fixes."}</p>
        <h2>Verified options</h2>
        {proposal && !proposal.options.length && <p className="bad">No move passed the check. This clash needs a person.</p>}
        {proposal?.options.map((o, i) => (
          <button key={i} className={`card ${chosen === i ? "pick" : ""}`} onClick={() => setChosen(chosen === i ? null : i)}>
            <span className="row"><b>{i + 1} · {o.title}</b><span className="chip ok">verified</span></span>
            <span className="row"><span>Clearance</span><span className="mono">{mm(o.min_clearance_m)}</span></span>
            <span className="row"><span>Also needs</span><span>{o.also_needs || "nothing"}</span></span>
            <span className="why">{o.rationale}</span>
          </button>
        ))}
      </aside>

      <footer className="dock">
        {proposal?.attempts.map((t, i) => (
          <span key={i} className={`step ${t.passed ? "ok" : "fail"}`}><i>{i + 1}</i>{t.title}{t.passed ? "" : `: ${t.reason}`}</span>
        )) ?? <span className="hint">The agent's steps appear here, failed attempts included.</span>}
      </footer>
    </div>
  );
}
