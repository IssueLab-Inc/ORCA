import { useEffect, useRef, useState } from "react";
import { api, type Matches, type Measure, type Option, type Proposal, type Report, type ReportClash, type Verdict } from "./api";
import { ClashPanel, Lightbox } from "./ClashPanel";
import { ReportList, mm } from "./ReportList";
import { Viewer } from "./viewer/Viewer";

type Stats = { elements: number; triangles: number; parseMs: number };

export function App() {
  const host = useRef<HTMLDivElement>(null);
  const viewer = useRef<Viewer | null>(null);
  const folderInput = useRef<HTMLInputElement>(null);
  const filesInput = useRef<HTMLInputElement>(null);
  const [samples, setSamples] = useState<string[]>([]);
  const [picked, setPicked] = useState<string[]>([]);
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
  // Clash reports (Navisworks XML).
  const [reportSamples, setReportSamples] = useState<string[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [matches, setMatches] = useState<Matches | null>(null);
  const [clash, setClash] = useState<ReportClash | null>(null);
  const [measure, setMeasure] = useState<Measure | null | "busy">(null);
  const [image, setImage] = useState<number | null>(null);
  const [accepted, setAccepted] = useState<string[]>([]);  // titles of fixes kept in the server's model
  const [remeasure, setRemeasure] = useState(0);

  useEffect(() => {
    if (!host.current) return;
    const v = new Viewer(host.current);
    viewer.current = v;
    api.samples().then((list) => {
      setSamples(list);
      // Default to the coordination set: the building disciplines, not site context, grids or a later revision.
      const set = list.filter((f) => /(structure|mep|architecture)\.ifc$/i.test(f));
      setPicked(set.length ? set : list.slice(0, 1));
    }).catch((e) => setError(`Can't reach the Sightline server: ${e.message}`));
    api.reportSamples().then(setReportSamples).catch(() => undefined);
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

  // Pieces an accepted offset added, drawn with the side they belong to.
  const [group, setGroup] = useState<Record<string, "a" | "b">>({});
  useEffect(() => viewer.current?.highlight(a, b, isolate, group), [a, b, isolate, group]);

  // Link the report to the open model whenever either changes.
  useEffect(() => {
    setMatches(null);
    if (!report || !sceneId) return;
    api.match(report.id, sceneId).then(setMatches).catch((e) => setError((e as Error).message));
  }, [report, sceneId]);

  // A selected report clash: its pair in the viewer, and Sightline's own measure of it.
  useEffect(() => {
    setMeasure(null);
    if (!clash || !report || !sceneId || !matches) return;
    const m = matches[clash.id];
    setA(m?.a ?? null); setB(m?.b ?? null);
    if (m?.a || m?.b) viewer.current?.frame([m.a, m.b].filter((g): g is string => !!g));
    if (!m?.a || !m?.b) return;
    let live = true;
    setMeasure("busy");
    api.measure(report.id, clash.id, sceneId).then((x) => live && setMeasure(x)).catch(() => live && setMeasure(null));
    return () => { live = false; };
  }, [clash, report, sceneId, matches, remeasure]);

  // Dev-only hook for smoke tests: select a clash pair by GlobalId without hunting for it with the mouse.
  useEffect(() => {
    if (!import.meta.env.DEV) return;
    (window as unknown as { sightline: object }).sightline = {
      selectPair: (ga: string, gb: string) => { setA(ga); setB(gb); setProposal(null); setChosen(null); setManual(null); viewer.current?.frame([ga, gb]); },
    };
  }, []);

  useEffect(() => {
    const opt = chosen == null ? null : proposal?.options[chosen];
    if (opt?.kind === "offset" && opt.preview) viewer.current?.previewPieces(opt.moved, opt.preview, opt.moved[0] === a ? "#d0342c" : "#1f9d3a");
    else viewer.current?.preview(opt ? [{ globalIds: opt.moved, deltaM: opt.delta_m }] : []);
  }, [chosen, proposal, a]);

  function resetWork() { setProposal(null); setChosen(null); setManual(null); }

  async function open() {
    if (!picked.length) return;
    setBusy(`Loading ${picked.length} model${picked.length > 1 ? "s" : ""}…`); setError(null); resetWork(); setA(null); setB(null);
    try {
      const { id, files } = await api.open(picked);
      setSceneId(id);
      const bytes = await Promise.all(files.map((_, i) => api.file(id, i)));
      setStats(await viewer.current!.load(bytes));
    } catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  }

  async function loadReport(get: () => Promise<Report>, what: string) {
    setBusy(`Reading ${what}…`); setError(null);
    try { const r = await get(); setReport(r); setClash(null); resetWork(); }
    catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  }

  function upload(list: FileList | null) {
    const files = [...(list ?? [])].filter((f) => /\.(xml|png|jpe?g)$/i.test(f.name));
    if (!files.length) return setError("Choose a Navisworks XML report, or the folder it was exported to.");
    loadReport(() => api.uploadReport(files), `${files.length} file${files.length > 1 ? "s" : ""}`);
  }

  function selectClash(c: ReportClash) {
    setClash(c); resetWork(); setImage(null); setGroup({});
    if (!matches) { setA(null); setB(null); }
  }

  function onClick(ev: React.MouseEvent) {
    if (ev.detail !== 2) return; // double-click picks, so orbiting never selects by accident
    const gid = viewer.current?.pick(ev.nativeEvent);
    if (!gid || gid === a) return;
    if (!a || (a && b)) { setA(gid); setB(null); } else setB(gid);
    setClash(null); resetWork(); setGroup({});
  }

  async function propose() {
    if (!sceneId || !a || !b) return;
    setBusy("Sightline is looking at the clash…"); setError(null);
    const from = clash && report ? { report_id: report.id, clash_id: clash.id } : undefined;
    try { const p = await api.propose(sceneId, a, b, from); setProposal(p); setChosen(p.options.length ? 0 : null); }
    catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  }

  async function accept(o: Option) {
    if (!sceneId) return;
    setBusy("Applying the fix…"); setError(null);
    try {
      const { files, pieces } = await api.accept(sceneId, o);
      viewer.current?.preview([]);
      for (const i of files) await viewer.current!.replace(i, await api.file(sceneId, i));
      const side = o.moved[0] === a ? "a" : "b";
      const next = { ...group, ...Object.fromEntries((pieces ?? []).map((g) => [g, side] as const)) };
      setGroup(next);
      viewer.current?.highlight(a, b, isolate, next);
      setAccepted([...accepted, o.title]); resetWork(); setRemeasure(remeasure + 1);
    } catch (e) { setError((e as Error).message); } finally { setBusy(null); }
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
        <details className="models">
          <summary>{picked.length ? `${picked.length} model${picked.length > 1 ? "s" : ""} selected` : samples.length ? "Choose models" : "No models in samples/"}</summary>
          <div className="menu">
            {samples.map((f) => (
              <label key={f} className="check">
                <input type="checkbox" value={f} checked={picked.includes(f)}
                  onChange={(e) => setPicked(e.target.checked ? [...picked, f] : picked.filter((x) => x !== f))} /> {f}
              </label>
            ))}
          </div>
        </details>
        <button id="open" className="btn" disabled={!picked.length || !!busy} onClick={open}>Open</button>
        <details className="models">
          <summary>Clash report</summary>
          <div className="menu">
            {reportSamples.map((s) => (
              <button key={s} className="link" onClick={(e) => { (e.currentTarget.closest("details") as HTMLDetailsElement).open = false; loadReport(() => api.openReport(s), s); }}>{s}</button>
            ))}
            <button className="link" onClick={() => folderInput.current?.click()}>Upload an export folder…</button>
            <button className="link" onClick={() => filesInput.current?.click()}>Upload XML files…</button>
            <span className="hint">Navisworks XML report. Upload the whole export folder to get its images.</span>
          </div>
        </details>
        <input ref={folderInput} type="file" hidden multiple {...{ webkitdirectory: "" }} onChange={(e) => { upload(e.target.files); e.target.value = ""; }} />
        <input ref={filesInput} type="file" hidden multiple accept=".xml,.png,.jpg,.jpeg" onChange={(e) => { upload(e.target.files); e.target.value = ""; }} />
        {stats && <span className="stat mono">{stats.elements} elements · {Math.round(stats.triangles / 1000)}k triangles · parsed in {(stats.parseMs / 1000).toFixed(1)} s · {fps} fps</span>}
        <span className="spacer" />
        {sceneId && <a className="btn primary" href={api.exportUrl(sceneId)}>Export edited IFC</a>}
      </header>

      <aside className="pane left">
        {report
          ? <ReportList report={report} matches={matches} selected={clash?.id ?? null} onSelect={selectClash} />
          : <>
              <h2>Clashes</h2>
              <p className="hint">Open a Navisworks clash report from the header, or double-click element A, then element B, in the model.</p>
            </>}
      </aside>

      <main className="stage" ref={host} onClick={onClick}>
        {busy && <div className="overlay">{busy}</div>}
        {error && <div className="overlay error" onClick={() => setError(null)}>{error}</div>}
      </main>

      <aside className="pane right">
        {clash && report
          ? <ClashPanel reportId={report.id} clash={clash} match={matches?.[clash.id]} measure={measure} onImage={setImage} />
          : <>
              <h2>Pair</h2>
              <dl className="kv">
                <dt><i className="sw red" />A</dt><dd className="mono">{a ?? "—"}</dd>
                <dt><i className="sw green" />B</dt><dd className="mono">{b ?? "—"}</dd>
              </dl>
            </>}
        <div className="actions">
          <label className="check"><input id="isolate" type="checkbox" checked={isolate} onChange={(e) => setIsolate(e.target.checked)} /> Isolate the pair</label>
          <button className="btn" disabled={!a || !b} onClick={() => viewer.current?.frame([a!, b!])}>Fit to pair</button>
          <button className="btn primary" disabled={!a || !b || !sceneId || !!busy} onClick={propose}>Propose fixes</button>
        </div>

        <details className="try">
          <summary>Try a move</summary>
          <label className="field">Move A vertically (m)
            <input id="manual-dz" type="number" step="0.05" value={manualDz} onChange={(e) => setManualDz(Number(e.target.value))} />
          </label>
          <button className="btn" disabled={!a || !sceneId} onClick={checkManual}>Check this move</button>
          {manual && <p className={manual.passed ? "ok" : "bad"}>{manual.passed ? `Clear · nearest ${mm(manual.min_clearance_m)}` : manual.hits.map((h) => `${h.kind} with ${h.other_class} ${mm(h.distance_m)}`).join("; ")}</p>}
        </details>

        <h2>Understanding</h2>
        <p>{proposal?.understanding || "Pick a clash and ask Sightline to propose fixes."}</p>
        <h2>Verified options</h2>
        {proposal && !proposal.options.length && <p className="bad">No move passed the check. This clash needs a person.</p>}
        {proposal?.options.map((o, i) => (
          <div key={i} className={`card ${chosen === i ? "pick" : ""}`}>
            <button className="card-body" onClick={() => setChosen(chosen === i ? null : i)}>
              <span className="row"><b>{i + 1} · {o.title}</b><span className="chip ok">verified</span></span>
              <span className="row"><span>Edit</span><span className="mono">{o.kind === "offset" && o.split_m
                ? `offset ${o.split_m.map((v) => v.toFixed(2)).join("–")} m, ${mm(o.delta_m[2])}`
                : `move ${o.delta_m.map((v) => mm(v)).join(", ")}`}</span></span>
              <span className="row"><span>Clearance</span><span className="mono">{mm(o.min_clearance_m)}</span></span>
              <span className="row"><span>Also needs</span><span>{o.also_needs || "nothing"}</span></span>
              <span className="why">{o.rationale}</span>
            </button>
            {chosen === i && <button className="btn primary" disabled={!!busy} onClick={() => accept(o)}>Accept this fix</button>}
          </div>
        ))}
        {accepted.length > 0 && <p className="ok">Accepted: {accepted.join("; ")}. Export edited IFC to download.</p>}
      </aside>

      <footer className="dock">
        {proposal?.attempts.map((t, i) => (
          <span key={i} className={`step ${t.passed ? "ok" : "fail"}`}><i>{i + 1}</i>{t.kind === "offset" ? "Offset · " : ""}{t.title}{t.passed ? "" : `: ${t.reason}`}</span>
        )) ?? <span className="hint">The agent's steps appear here, failed attempts included.</span>}
      </footer>

      {clash && report && image != null && clash.images[image] &&
        <Lightbox reportId={report.id} clash={clash} index={image} onClose={() => setImage(null)} onMove={setImage} />}
    </div>
  );
}
