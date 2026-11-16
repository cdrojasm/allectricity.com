import React, { useEffect, useRef, useState } from "react";
import TopologyPreview from "./TopologyPreview.jsx";

// Rates the topological optimizer prices every candidate with (backend: optimizer_topology_job.RATE_UNITS).
const RATE_FIELDS = [
  ["material.conductor.unspecified", "Conductor (material)", "por m"],
  ["material.rod.unspecified", "Varilla (material)", "por m de varilla"],
  ["excavation.trench", "Excavación de zanja", "por m³"],
  ["installation.conductor", "Tendido de conductor", "por m"],
  ["installation.rod", "Hincado de varilla", "por varilla"],
  ["installation.connection", "Conexiones", "por conexión"],
];
const TERMINAL = new Set(["completed", "failed", "cancelled", "rejected"]);
const STATUS_TEXT = { queued: "En cola", running: "Buscando topologías", completed: "Completada", failed: "Falló", cancelled: "Cancelada", rejected: "Rechazada" };
const money = (value, currency) => (typeof value === "number" ? `${currency || ""} ${value.toLocaleString("es-CO", { maximumFractionDigits: 0 })}`.trim() : "—");
const number = (value, digits = 1) => (typeof value === "number" ? value.toLocaleString("es-CO", { maximumFractionDigits: digits }) : "—");
function baseStatus(electrical) {
  if (!electrical || typeof electrical !== "object") return "Cumplimiento del diseño base sin evaluar.";
  const ratio = typeof electrical.ratio === "number" ? ` (utilización ${number(electrical.ratio * 100, 0)} %)` : "";
  if (electrical.status === "VIOLATED") return `No cumple en el nivel más fino${ratio}.`;
  if (electrical.feasible === true) return `Sin violaciones en el nivel más fino${ratio}; no certificado.`;
  return "No se pudo evaluar su cumplimiento.";
}
const detailText = (body, fallback) => {
  const detail = typeof body?.detail === "string" ? body.detail : "";
  if (detail.includes("normative_profile_not_selected")) return "Falta fijar un perfil normativo revisado al proyecto. Selecciónalo arriba y guarda los cambios.";
  if (detail.includes("mandatory_safety_profile_not_selected")) return "El perfil seleccionado no define criterios obligatorios de seguridad. Elige un perfil que incluya contacto y paso.";
  if (detail.includes("jurisdiction_profile_mismatch")) return "La jurisdicción del perfil no coincide con el país del proyecto. Revisa el país o elige un perfil aplicable.";
  if (detail.startsWith("OP-05 context is blocked:")) return "El contexto normativo todavía no permite optimizar. Revisa los perfiles seleccionados y sus criterios obligatorios.";
  return detail || fallback;
};

// The run form (exposure, standards) is shared with the discrete optimizer in GroundingPlanDrawer.
function TopologyOptimizerPanel({ projectId, token, artifact, canRun, runForm, onApplied }) {
  const [rates, setRates] = useState(() => Object.fromEntries(RATE_FIELDS.map(([key]) => [key, ""])));
  const [rateSource, setRateSource] = useState("");
  const [currency, setCurrency] = useState("COP");
  const [trenchWidth, setTrenchWidth] = useState("");
  const [trenchSource, setTrenchSource] = useState("");
  const [budget, setBudget] = useState("150");
  const [orthogonal, setOrthogonal] = useState(true);
  // Approved catalog items offered per cost line (the server applies the same tests as the run), and the line's pick.
  const [catalogOptions, setCatalogOptions] = useState({});
  const [picks, setPicks] = useState({});
  const [run, setRun] = useState(null);
  const [comparison, setComparison] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [applied, setApplied] = useState(null);
  const [geometries, setGeometries] = useState({});
  const [previewId, setPreviewId] = useState(null);
  const timer = useRef(null);
  const root = `/api/v1/projects/${encodeURIComponent(projectId)}/optimizer-runs`;
  const auth = { Authorization: `Bearer ${token}` };

  const [history, setHistory] = useState([]);
  const [remembered, setRemembered] = useState(false);
  const [profiles, setProfiles] = useState([]);
  const [selectedProfiles, setSelectedProfiles] = useState([]);
  const [profileBusy, setProfileBusy] = useState(false);

  useEffect(() => () => clearTimeout(timer.current), []);

  // Historial: lista las corridas de topología y retoma la que siga activa tras recargar la página.
  // «Tarifa del proyecto»: las de la última corrida del proyecto (el servidor las guarda con cada corrida).
  function rememberRates(request) {
    if (!request?.rates) return;
    setRates((current) => Object.fromEntries(Object.keys(current).map((key) => [key, request.rates[key]?.amount != null ? String(request.rates[key].amount) : current[key]])));
    setRateSource(Object.values(request.rates).find((rate) => rate.source)?.source || "");
    setPicks(Object.fromEntries(Object.entries(request.rates).filter(([, rate]) => rate.catalog_item_id).map(([key, rate]) => [key, rate.catalog_item_id])));
    if (request.cost_currency) setCurrency(request.cost_currency);
    if (request.trench_width_m) setTrenchWidth(String(request.trench_width_m));
    if (request.trench_width_source) setTrenchSource(request.trench_width_source);
    setRemembered(true);
  }
  async function loadHistory(resume) {
    try {
      const response = await fetch(root, { headers: auth });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) return;
      const rows = (body.runs || []).filter((row) => row.request_snapshot?.algorithm === "topology_alns");
      setHistory(rows);
      if (resume) rememberRates(rows[0]?.request_snapshot?.request);
      const live = resume && rows.find((row) => !TERMINAL.has(row.status));
      if (live) { setRun(live); poll(live.id); }
    } catch { /* El historial es una ayuda; el panel funciona sin él. */ }
  }
  useEffect(() => { if (token) loadHistory(true); }, [projectId, token]);

  useEffect(() => {
    if (!token) return;
    let live = true;
    Promise.all([
      fetch("/api/v1/constraint-profiles", { headers: auth }).then(async (r) => r.ok ? r.json() : Promise.reject(new Error("No se pudieron cargar los perfiles normativos."))),
      fetch(`/api/v1/projects/${encodeURIComponent(projectId)}/constraint-profiles`, { headers: auth }).then(async (r) => r.ok ? r.json() : Promise.reject(new Error("No se pudo cargar la selección normativa del proyecto."))),
    ]).then(([catalog, pinned]) => {
      if (!live) return;
      const latestReviewed = new Map();
      for (const item of (catalog.profiles || []).filter((entry) => entry.status === "reviewed")) {
        const previous = latestReviewed.get(item.profile_id);
        if (!previous || item.version > previous.version) latestReviewed.set(item.profile_id, item);
      }
      setProfiles([...latestReviewed.values()]);
      setSelectedProfiles((pinned.profiles || []).map((item) => ({ profile_id: item.profile_id, version: item.profile_version })));
    }).catch((failure) => { if (live) setError(failure.message); });
    return () => { live = false; };
  }, [projectId, token]);

  async function saveProfiles() {
    setProfileBusy(true); setError("");
    try {
      const response = await fetch(`/api/v1/projects/${encodeURIComponent(projectId)}/constraint-profiles`, {
        method: "PUT", headers: { ...auth, "Content-Type": "application/json" },
        body: JSON.stringify({ profiles: selectedProfiles }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(detailText(body, "No se pudieron fijar los perfiles al proyecto."));
      setSelectedProfiles((body.profiles || []).map((item) => ({ profile_id: item.profile_id, version: item.profile_version })));
    } catch (failure) { setError(failure.message); }
    finally { setProfileBusy(false); }
  }

  useEffect(() => {
    setCatalogOptions({});
    if (!token || !/^[A-Z]{3}$/.test(currency)) return undefined;
    let live = true;
    fetch(`${root}/rate-options?currency=${currency}`, { headers: auth })
      .then((response) => (response.ok ? response.json() : null))
      .then((body) => {
        if (!live || !body) return;
        setCatalogOptions(body.options || {});
        // A remembered pick that is no longer offered (expired, retired) falls back to a typed amount.
        setPicks((current) => Object.fromEntries(Object.entries(current).filter(([key, id]) => (body.options?.[key] || []).some((item) => item.id === id))));
      })
      .catch(() => { /* Sin catálogo se escriben a mano, como siempre. */ });
    return () => { live = false; };
  }, [projectId, token, currency]);

  function openRun(row) { setError(""); setComparison(null); setApplied(null); setRun(row); poll(row.id); }

  async function poll(runId) {
    clearTimeout(timer.current);
    try {
      const response = await fetch(`${root}/${encodeURIComponent(runId)}`, { headers: auth });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(detailText(body, "No se pudo consultar la corrida."));
      setRun(body.run);
      setGeometries(Object.fromEntries((body.alternatives || []).map((alt) => [alt.id, alt.evaluation_snapshot?.geometry || alt.candidate_snapshot?.geometry]).filter(([, g]) => g)));
      if (!TERMINAL.has(body.run.status)) { timer.current = setTimeout(() => poll(runId), 2000); return; }
      if (body.run.status === "completed") {
        const compared = await fetch(`${root}/${encodeURIComponent(runId)}/comparison`, { headers: auth });
        const data = await compared.json().catch(() => ({}));
        if (!compared.ok) throw new Error(detailText(data, "No se pudo cargar la comparación."));
        setComparison(data);
      }
    } catch (failure) { setError(failure.message); }
  }

  function payload() {
    if (!artifact || !canRun) throw new Error("Guarda primero una versión del plano.");
    for (const [label, value] of [["corriente de falla", runForm.injection], ["tiempo de despeje", runForm.clearingTime], ["peso corporal", runForm.bodyWeight], ["resistividad superficial", runForm.surfaceRho], ["espesor superficial", runForm.surfaceThickness]])
      if (value === "" || !Number.isFinite(Number(value))) throw new Error(`Ingresa ${label} en el formulario de la corrida.`);
    if (!runForm.exposureClass || runForm.surfaceLayerPresent === "") throw new Error("Indica clase de exposición y presencia de capa superficial.");
    if (!runForm.standards.length) throw new Error("Selecciona al menos un estándar.");
    if (!/^[A-Z]{3}$/.test(currency)) throw new Error("La moneda debe ser un código de tres letras, por ejemplo COP.");
    if (RATE_FIELDS.some(([key]) => !picks[key]) && !rateSource.trim()) throw new Error("Indica la fuente de las tarifas (cotización, lista de precios…).");
    const rateBody = {};
    for (const [key, label] of RATE_FIELDS) {
      if (picks[key]) { rateBody[key] = { catalog_item_id: picks[key] }; continue; }
      if (rates[key] === "" || !Number.isFinite(Number(rates[key])) || Number(rates[key]) < 0) throw new Error(`Ingresa la tarifa de ${label.toLowerCase()}.`);
      rateBody[key] = { amount: Number(rates[key]), source: rateSource.trim() };
    }
    if (!(Number(trenchWidth) > 0) || !trenchSource.trim()) throw new Error("Indica el ancho de zanja y su fuente.");
    return {
      artifact_id: artifact.artifact_id, artifact_version: artifact.version, injection_a: Number(runForm.injection),
      exposure: { clearing_time_s: Number(runForm.clearingTime), body_weight_kg: Number(runForm.bodyWeight), surface_resistivity_ohm_m: Number(runForm.surfaceRho), surface_thickness_m: Number(runForm.surfaceThickness), exposure_class: runForm.exposureClass, surface_layer_present: runForm.surfaceLayerPresent === "true" },
      standards: runForm.standards, cost_currency: currency, rates: rateBody,
      trench_width_m: Number(trenchWidth), trench_width_source: trenchSource.trim(), seed: 0, max_solver_calls: Number(budget), orthogonal_only: orthogonal,
    };
  }

  async function start(event) {
    event.preventDefault(); setError(""); setComparison(null); setApplied(null); setBusy(true);
    try {
      const response = await fetch(`${root}/topology`, { method: "POST", headers: { ...auth, "Content-Type": "application/json" }, body: JSON.stringify(payload()) });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(detailText(body, "No se pudo poner la corrida en cola."));
      setRun(body.run);
      poll(body.run.id);
      loadHistory(false);
    } catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  }

  async function cancel() {
    try {
      const response = await fetch(`${root}/${encodeURIComponent(run.id)}/cancel`, { method: "POST", headers: auth });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(detailText(body, "No se pudo cancelar."));
      setRun(body.run);
    } catch (failure) { setError(failure.message); }
  }

  async function apply(alternativeId) {
    setError("");
    try {
      const response = await fetch(`${root}/${encodeURIComponent(run.id)}/alternatives/${encodeURIComponent(alternativeId)}/apply`, { method: "POST", headers: auth });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(detailText(body, "No se pudo aplicar la alternativa."));
      setApplied(body);
      onApplied?.(body);
    } catch (failure) { setError(failure.message); }
  }

  const progress = run?.result_summary?.progress;
  const active = run && !TERMINAL.has(run.status);
  return <form className="optimizer-run-form topology-optimizer" onSubmit={start}>
    <h4>Búsqueda de topologías</h4>
    <small>Explora trazados de conductores y varillas dentro de las áreas intervenibles. Antes de buscar, fija al proyecto un perfil normativo revisado que corresponda a esta instalación.</small>
    <fieldset><legend>Perfiles normativos del proyecto</legend>
      {profiles.length ? profiles.map((profile) => {
        const selected = selectedProfiles.some((item) => item.profile_id === profile.profile_id);
        return <label className="checkbox-row" key={`${profile.profile_id}-${profile.version}`}><input type="checkbox" checked={selected} onChange={(event) => setSelectedProfiles((current) => event.target.checked
          ? [...current.filter((item) => item.profile_id !== profile.profile_id), { profile_id: profile.profile_id, version: profile.version }]
          : current.filter((item) => item.profile_id !== profile.profile_id))}/>
          {profile.definition?.title || profile.profile_id} · v{profile.version} · {profile.definition?.jurisdiction || "jurisdicción sin indicar"}
        </label>;
      }) : <small>No hay perfiles normativos revisados disponibles para seleccionar.</small>}
      <button type="button" className="button" disabled={profileBusy || !profiles.length} onClick={saveProfiles}>{profileBusy ? "Guardando…" : "Guardar perfiles del proyecto"}</button>
      {selectedProfiles.length === 0 && <small>Selecciona al menos un perfil; debe incluir los criterios obligatorios de seguridad aplicables.</small>}
    </fieldset>
    <fieldset><legend>Tarifas ({currency || "moneda"})</legend>
      {remembered && <small>Precargadas con la tarifa de la última corrida de este proyecto; revísalas antes de buscar.</small>}
      <label>Moneda<input value={currency} maxLength={3} onChange={(e) => setCurrency(e.target.value.toUpperCase())}/></label>
      {RATE_FIELDS.map(([key, label, unit]) => {
        const options = catalogOptions[key] || [];
        const picked = options.find((item) => item.id === picks[key]);
        return <div className="rate-line" key={key}>
          {options.length > 0 && <label>{label}: origen<select value={picks[key] || ""} onChange={(e) => setPicks((current) => ({ ...current, [key]: e.target.value }))}>
            <option value="">Escribir a mano</option>
            {options.map((item) => <option key={item.id} value={item.id}>{item.name}{item.supplier ? ` · ${item.supplier}` : ""} · {number(Number(item.price_per_unit), 0)} {currency}/{item.quantity_unit}</option>)}
          </select></label>}
          {picked
            ? <small data-testid={`rate-catalog-${key}`}>{label}: {number(Number(picked.price_per_unit), 0)} {currency} {unit} · catálogo aprobado{picked.expires_at ? ` · vigente hasta ${new Date(picked.expires_at * 1000).toLocaleDateString("es-CO")}` : ""}</small>
            : <label>{label} <small>{unit}</small><input required type="number" min="0" step="any" value={rates[key]} onChange={(e) => setRates((current) => ({ ...current, [key]: e.target.value }))}/></label>}
        </div>;
      })}
      <label>Fuente de las tarifas escritas a mano<input required={RATE_FIELDS.some(([key]) => !picks[key])} value={rateSource} placeholder="Cotización, lista de precios o APU" onChange={(e) => setRateSource(e.target.value)}/></label>
      <label>Ancho de zanja (m)<input required type="number" min="0.01" step="any" value={trenchWidth} onChange={(e) => setTrenchWidth(e.target.value)}/></label>
      <label>Fuente del ancho de zanja<input required value={trenchSource} onChange={(e) => setTrenchSource(e.target.value)}/></label>
    </fieldset>
    <label className="checkbox-row"><input type="checkbox" checked={orthogonal} onChange={(e) => setOrthogonal(e.target.checked)}/> Solo trazados ortogonales (sin diagonales nuevas)</label>
    <label>Presupuesto de llamadas al solver<select value={budget} onChange={(e) => setBudget(e.target.value)}><option value="60">60 · rápido</option><option value="150">150 · recomendado</option><option value="300">300 · exhaustivo</option></select></label>
    <button className="button primary" type="submit" disabled={busy || active || !canRun || selectedProfiles.length === 0}>{busy ? "Enviando…" : "Buscar topologías"}</button>
    {error && <p className="optimizer-context-error" role="alert">{error}</p>}
    {run && <div className="optimizer-run-result" aria-live="polite">
      <strong>{STATUS_TEXT[run.status] || run.status}</strong>
      {active && <small>{progress?.verdicts ? `${progress.verdicts} evaluaciones eléctricas de ${progress.budget || budget}` : "Esperando al worker del optimizador…"}</small>}
      {active && <button type="button" className="button" onClick={cancel}>Cancelar</button>}
      {run.error && <small className="optimizer-context-error">{run.error}</small>}
    </div>}
    {history.length > 0 && <details className="topology-history"><summary>Corridas anteriores ({history.length})</summary>
      <ul>{history.slice(0, 10).map((row) => <li key={row.id}><button type="button" className="button" onClick={() => openRun(row)}>{new Date(row.created_at * 1000).toLocaleString("es-CO")} · {STATUS_TEXT[row.status] || row.status} · v{row.artifact_version}</button></li>)}</ul>
    </details>}
    {comparison && <div className="topology-comparison">
      {comparison.base && <div className="topology-card base">
        <strong>Diseño base · {money(comparison.base.cost, comparison.currency)}</strong>
        <small>{number(comparison.base.complexity?.conductor_length_m, 0)} m de conductor · {comparison.base.complexity?.rods ?? "—"} varillas</small>
        <small>{baseStatus(comparison.base.electrical)}</small>
      </div>}
      {comparison.saving_vs_base && <small>{comparison.saving_vs_base.kind === "saving"
        ? `Ahorro de la recomendada: ${money(comparison.saving_vs_base.amount, comparison.currency)} (${number(comparison.saving_vs_base.fraction * 100)} %)`
        : `Diferencia con el diseño base: ${money(-comparison.saving_vs_base.amount, comparison.currency)}${comparison.saving_vs_base.base_status === "violates" ? " — lo que cuesta cumplir" : ""}`}</small>}
      {comparison.alternatives.length ? comparison.alternatives.map((row) => <div key={row.alternative_id} className={`topology-card${row.recommended ? " recommended" : ""}`}>
        <strong>{row.rank}{row.pareto ? " ◆" : ""} · {money(row.cost, comparison.currency)}{row.recommended ? " · recomendada" : ""}</strong>
        <small>Rg {number(row.Rg_ohm, 2)} Ω · contacto {number(row.Vt_v, 0)} V · paso {number(row.Vs_v, 0)} V · utilización {typeof row.utilization_ratio === "number" ? `${number(row.utilization_ratio * 100, 0)} %` : "—"}</small>
        <small>{number(row.complexity?.conductor_length_m, 0)} m de conductor · {row.complexity?.rods ?? "—"} varillas · {row.complexity?.connections ?? "—"} conexiones · validada en {row.validated_at_level || "—"}</small>
        <button type="button" className="button" aria-expanded={previewId === row.alternative_id} onClick={() => setPreviewId(previewId === row.alternative_id ? null : row.alternative_id)}>{previewId === row.alternative_id ? "Ocultar vista previa" : "Vista previa sobre el diseño base"}</button>
        {previewId === row.alternative_id && (geometries[row.alternative_id] && (run?.request_snapshot?.initial_geometry || artifact?.snapshot?.geometry)
          ? <TopologyPreview base={run?.request_snapshot?.initial_geometry || artifact.snapshot.geometry} alternative={geometries[row.alternative_id]}/>
          : <small>Esta alternativa no trae geometría para previsualizar.</small>)}
        <button type="button" className="button" onClick={() => apply(row.alternative_id)}>Aplicar como versión nueva</button>
      </div>)
        : <small>Ninguna topología pasó la verificación más fina con este presupuesto.</small>}
      {comparison.alternatives.some((row) => row.pareto) && <small>◆ Frente de Pareto costo–utilización entre las alternativas validadas.</small>}
      {applied && <small data-testid="topology-applied">Se creó la versión {applied.version} del plano con la alternativa elegida.{" "}
        {applied.revalidation?.status === "pending"
          ? "Se encoló su cálculo completo con malla fina; el veredicto del estudio será el de ese cálculo, no el de la búsqueda."
          : applied.revalidation?.status === "blocked"
            ? `No se pudo encolar la revalidación: ${applied.revalidation.detail?.message || "el diseño no está listo para calcular"}. Calcula la versión cuando lo esté.`
            : applied.revalidation?.status === "failed"
              ? "No se pudo encolar la revalidación; calcula la versión manualmente."
              : ""}</small>}
      <ul>{comparison.warnings.map((warning) => <li key={warning}><small>{warning}</small></li>)}</ul>
    </div>}
  </form>;
}

export default TopologyOptimizerPanel;
