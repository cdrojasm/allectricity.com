import React, { useEffect, useRef, useState } from "react";
import { ACTIVE_RUN, RUN_STATUS_LABELS, apiRequest } from "../optimization.js";

// Matherra in the plan editor: set up and launch a topology search and follow it. Its alternatives are reviewed,
// previewed and applied in Resultado, next to the verdict, so they live in one place only.

// Rates every candidate is priced with (backend: optimizer_topology_job.RATE_UNITS).
const RATE_FIELDS = [
  ["material.conductor.unspecified", "Conductor (material)", "por m"],
  ["material.rod.unspecified", "Varilla (material)", "por m de varilla"],
  ["excavation.trench", "Excavación de zanja", "por m³"],
  ["installation.conductor", "Tendido de conductor", "por m"],
  ["installation.rod", "Hincado de varilla", "por varilla"],
  ["installation.connection", "Conexiones", "por conexión"],
];
const STANDARDS = ["IEEE 80-2013", "RETIE 2026 (Resolución 40284)"];
const BUDGETS = [["60", "60 · rápido"], ["150", "150 · recomendado"], ["300", "300 · exhaustivo"]];
const EMPTY_FORM = { injection: "", clearingTime: "", bodyWeight: "", surfaceRho: "", surfaceThickness: "", exposureClass: "", surfaceLayerPresent: "", standards: [] };
const number = (value, digits = 1) => (typeof value === "number" ? value.toLocaleString("es-CO", { maximumFractionDigits: digits }) : "—");

function readableError(error) {
  const text = error?.message || "";
  if (text.includes("normative_profile_not_selected")) return "Falta fijar al proyecto un perfil normativo revisado.";
  if (text.includes("mandatory_safety_profile_not_selected")) return "El perfil elegido no define criterios obligatorios de contacto y paso.";
  if (text.includes("jurisdiction_profile_mismatch")) return "La jurisdicción del perfil no coincide con el país del proyecto.";
  if (text.startsWith("OP-05 context is blocked:")) return "El contexto normativo todavía no permite optimizar; revisa los perfiles del proyecto.";
  return text;
}
const isEmpty = (value) => value === "" || value == null || (Array.isArray(value) && !value.length);
/** Fill only the fields the user has not typed; a value they typed is never overwritten. */
const fillEmpty = (current, values) => Object.fromEntries(Object.entries(current).map(([key, value]) =>
  [key, isEmpty(value) && !isEmpty(values[key]) ? (Array.isArray(values[key]) ? values[key] : String(values[key])) : value]));

function soilSummary(snapshot) {
  const layers = snapshot?.soil_layers || [];
  if (layers.length === 1 && layers[0].resistivity_ohm_m != null) return `homogéneo, ${number(layers[0].resistivity_ohm_m)} Ω·m`;
  if (layers.length === 2) return `dos capas, ${number(layers[0].resistivity_ohm_m)} / ${number(layers[1].resistivity_ohm_m)} Ω·m`;
  return "sin modelo en el plano; complétalo en Suelo";
}

function TopologyOptimizerPanel({ projectId, token, artifact, canRun, onShowResults }) {
  const root = `/api/v1/projects/${encodeURIComponent(projectId)}/optimizer-runs`;
  const [form, setForm] = useState(EMPTY_FORM);
  const [rates, setRates] = useState(() => Object.fromEntries(RATE_FIELDS.map(([key]) => [key, ""])));
  const [picks, setPicks] = useState({});                // cost line → approved catalog item
  const [catalogOptions, setCatalogOptions] = useState({});
  const [rateSource, setRateSource] = useState("");
  const [currency, setCurrency] = useState("COP");
  const [trenchWidth, setTrenchWidth] = useState("");
  const [trenchSource, setTrenchSource] = useState("");
  const [budget, setBudget] = useState("150");
  const [orthogonal, setOrthogonal] = useState(true);
  const [profiles, setProfiles] = useState([]);
  const [pinned, setPinned] = useState([]);
  const [profileBusy, setProfileBusy] = useState(false);
  const [run, setRun] = useState(null);
  const [alternatives, setAlternatives] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);

  // The plan carries the fault; the project's last run carries what the plan does not (exposure, standards, rates).
  useEffect(() => {
    const fault = artifact?.snapshot?.fault || {};
    setForm((current) => fillEmpty(current, {
      injection: fault.current_a, clearingTime: fault.clearing_time_s, bodyWeight: fault.body_weight_kg,
      surfaceRho: fault.surface_resistivity_ohm_m, surfaceThickness: fault.surface_thickness_m,
      exposureClass: fault.exposure_class, surfaceLayerPresent: typeof fault.surface_layer_present === "boolean" ? fault.surface_layer_present : "",
    }));
  }, [artifact?.artifact_id, artifact?.version]);

  useEffect(() => {
    if (!token) return undefined;
    let live = true;
    apiRequest(token, root).then((body) => {
      if (!live) return;
      const rows = (body.runs || []).filter((row) => row.request_snapshot?.algorithm === "topology_alns");
      remember(rows[0]?.request_snapshot?.request);
      const active = rows.find((row) => ACTIVE_RUN.has(row.status));
      if (active) follow(active.id);
    }).catch(() => { /* Sin historial el formulario empieza vacío. */ });
    Promise.all([apiRequest(token, "/api/v1/constraint-profiles"), apiRequest(token, `/api/v1/projects/${encodeURIComponent(projectId)}/constraint-profiles`)])
      .then(([catalog, selection]) => {
        if (!live) return;
        const latest = new Map();
        for (const item of (catalog.profiles || []).filter((entry) => entry.status === "reviewed"))
          if (!latest.has(item.profile_id) || item.version > latest.get(item.profile_id).version) latest.set(item.profile_id, item);
        setProfiles([...latest.values()]);
        setPinned((selection.profiles || []).map((item) => ({ profile_id: item.profile_id, version: item.profile_version })));
      }).catch(() => { if (live) setError("No se pudieron cargar los perfiles normativos."); });
    return () => { live = false; };
  }, [projectId, token]);

  useEffect(() => {
    setCatalogOptions({});
    if (!token || !/^[A-Z]{3}$/.test(currency)) return undefined;
    let live = true;
    apiRequest(token, `${root}/rate-options?currency=${currency}`).then((body) => {
      if (!live) return;
      setCatalogOptions(body.options || {});
      // A remembered pick that is no longer offered (expired, retired) falls back to a typed amount.
      setPicks((current) => Object.fromEntries(Object.entries(current).filter(([key, id]) => (body.options?.[key] || []).some((item) => item.id === id))));
    }).catch(() => { /* Sin catálogo las tarifas se escriben a mano. */ });
    return () => { live = false; };
  }, [projectId, token, currency]);

  function remember(request) {
    if (!request) return;
    const exposure = request.exposure || {};
    setForm((current) => fillEmpty(current, {
      exposureClass: exposure.exposure_class,
      surfaceLayerPresent: typeof exposure.surface_layer_present === "boolean" ? exposure.surface_layer_present : "",
      standards: (request.standards || []).filter((standard) => STANDARDS.includes(standard)),
    }));
    if (request.rates) {
      setRates((current) => Object.fromEntries(Object.keys(current).map((key) => [key, request.rates[key]?.amount != null ? String(request.rates[key].amount) : current[key]])));
      setRateSource(Object.values(request.rates).find((rate) => rate.source)?.source || "");
      setPicks(Object.fromEntries(Object.entries(request.rates).filter(([, rate]) => rate.catalog_item_id).map(([key, rate]) => [key, rate.catalog_item_id])));
    }
    if (request.cost_currency) setCurrency(request.cost_currency);
    if (request.trench_width_m) setTrenchWidth(String(request.trench_width_m));
    if (request.trench_width_source) setTrenchSource(request.trench_width_source);
    if (BUDGETS.some(([value]) => value === String(request.max_solver_calls))) setBudget(String(request.max_solver_calls));
    if (typeof request.orthogonal_only === "boolean") setOrthogonal(request.orthogonal_only);
  }

  async function follow(runId) {
    clearTimeout(timer.current);
    try {
      const body = await apiRequest(token, `${root}/${encodeURIComponent(runId)}`, { fallback: "No se pudo consultar la búsqueda." });
      setRun(body.run);
      setAlternatives((body.alternatives || []).length);
      if (ACTIVE_RUN.has(body.run.status)) timer.current = setTimeout(() => follow(runId), 2000);
    } catch (failure) { setError(readableError(failure)); }
  }

  // Pinning a profile is saved at once: there is no separate "save" step to forget.
  async function toggleProfile(profile, checked) {
    const next = checked
      ? [...pinned.filter((item) => item.profile_id !== profile.profile_id), { profile_id: profile.profile_id, version: profile.version }]
      : pinned.filter((item) => item.profile_id !== profile.profile_id);
    const previous = pinned;
    setPinned(next); setProfileBusy(true); setError("");   // the box responds at once; a failed save puts it back
    try {
      const body = await apiRequest(token, `/api/v1/projects/${encodeURIComponent(projectId)}/constraint-profiles`, { method: "PUT", body: { profiles: next }, fallback: "No se pudo fijar el perfil al proyecto." });
      setPinned((body.profiles || []).map((item) => ({ profile_id: item.profile_id, version: item.profile_version })));
    } catch (failure) { setPinned(previous); setError(readableError(failure)); }
    finally { setProfileBusy(false); }
  }

  function payload() {
    if (!artifact || !canRun) throw new Error("Guarda primero una versión del plano.");
    if (!pinned.length) throw new Error("Fija al proyecto un perfil normativo revisado.");
    for (const [label, value] of [["la corriente de falla", form.injection], ["el tiempo de despeje", form.clearingTime], ["el peso corporal", form.bodyWeight], ["la resistividad superficial", form.surfaceRho], ["el espesor superficial", form.surfaceThickness]])
      if (value === "" || !Number.isFinite(Number(value))) throw new Error(`Indica ${label}.`);
    if (!form.exposureClass || form.surfaceLayerPresent === "") throw new Error("Indica la clase de exposición y si existe capa superficial.");
    if (!form.standards.length) throw new Error("Selecciona al menos un estándar.");
    if (!/^[A-Z]{3}$/.test(currency)) throw new Error("La moneda debe ser un código de tres letras, por ejemplo COP.");
    const rateBody = {};
    for (const [key, label] of RATE_FIELDS) {
      if (picks[key]) { rateBody[key] = { catalog_item_id: picks[key] }; continue; }
      if (rates[key] === "" || !Number.isFinite(Number(rates[key])) || Number(rates[key]) < 0) throw new Error(`Ingresa la tarifa de ${label.toLowerCase()}.`);
      rateBody[key] = { amount: Number(rates[key]), source: rateSource.trim() };
    }
    if (RATE_FIELDS.some(([key]) => !picks[key]) && !rateSource.trim()) throw new Error("Indica la fuente de las tarifas (cotización, lista de precios…).");
    if (!(Number(trenchWidth) > 0) || !trenchSource.trim()) throw new Error("Indica el ancho de zanja y su fuente.");
    return {
      artifact_id: artifact.artifact_id, artifact_version: artifact.version, injection_a: Number(form.injection),
      exposure: { clearing_time_s: Number(form.clearingTime), body_weight_kg: Number(form.bodyWeight), surface_resistivity_ohm_m: Number(form.surfaceRho), surface_thickness_m: Number(form.surfaceThickness), exposure_class: form.exposureClass, surface_layer_present: form.surfaceLayerPresent === "true" },
      standards: form.standards, cost_currency: currency, rates: rateBody,
      trench_width_m: Number(trenchWidth), trench_width_source: trenchSource.trim(), seed: 0, max_solver_calls: Number(budget), orthogonal_only: orthogonal,
    };
  }

  async function start(event) {
    event.preventDefault(); setError(""); setBusy(true);
    try {
      const body = await apiRequest(token, `${root}/topology`, { method: "POST", body: payload(), fallback: "No se pudo poner la búsqueda en cola." });
      setRun(body.run); setAlternatives(0);
      follow(body.run.id);
    } catch (failure) { setError(readableError(failure)); }
    finally { setBusy(false); }
  }

  async function cancel() {
    try {
      const body = await apiRequest(token, `${root}/${encodeURIComponent(run.id)}/cancel`, { method: "POST", fallback: "No se pudo cancelar." });
      setRun(body.run);
    } catch (failure) { setError(readableError(failure)); }
  }

  const set = (key) => (event) => setForm((current) => ({ ...current, [key]: event.target.value }));
  const active = run && ACTIVE_RUN.has(run.status);
  const progress = run?.result_summary?.progress;
  const blocker = (() => { try { payload(); return ""; } catch (failure) { return failure.message; } })();
  return <form className="optimizer-run-form topology-optimizer" onSubmit={start}>
    <p className="matherra-intro">Busca trazados de conductores y varillas dentro de las áreas intervenibles y los compara por costo y seguridad. Puede concluir que no hay una alternativa factible.</p>

    <fieldset><legend>Perfil normativo del proyecto</legend>
      {profiles.length ? profiles.map((profile) => <label className="checkbox-row" key={`${profile.profile_id}-${profile.version}`}>
        <input type="checkbox" disabled={profileBusy} checked={pinned.some((item) => item.profile_id === profile.profile_id)} onChange={(event) => toggleProfile(profile, event.target.checked)}/>
        {profile.definition?.title || profile.profile_id} · v{profile.version} · {profile.definition?.jurisdiction || "jurisdicción sin indicar"}
      </label>) : <small>No hay perfiles normativos revisados disponibles. Un administrador debe publicar uno antes de optimizar.</small>}
    </fieldset>

    <fieldset><legend>Falla y exposición</legend>
      <small>Suelo del plano guardado: {soilSummary(artifact?.snapshot)}.</small>
      <label>Corriente de falla inyectada (A)<input required type="number" min="0.001" step="any" value={form.injection} onChange={set("injection")}/></label>
      <label>Tiempo de despeje (s)<input required type="number" min="0.001" step="any" value={form.clearingTime} onChange={set("clearingTime")}/></label>
      <label>Peso corporal (kg)<select required value={form.bodyWeight} onChange={set("bodyWeight")}><option value="">Seleccionar…</option><option value="50">50</option><option value="70">70</option></select></label>
      <label>Clase de exposición<select required value={form.exposureClass} onChange={set("exposureClass")}><option value="">Seleccionar…</option><option value="public">Público</option><option value="occupational">Ocupacional</option></select></label>
      <label>¿Existe capa superficial?<select required value={form.surfaceLayerPresent} onChange={set("surfaceLayerPresent")}><option value="">Seleccionar…</option><option value="true">Sí</option><option value="false">No</option></select></label>
      <label>Resistividad superficial (Ω·m)<input required type="number" min="0.001" step="any" value={form.surfaceRho} onChange={set("surfaceRho")}/></label>
      <label>Espesor superficial (m)<input required type="number" min="0" step="any" value={form.surfaceThickness} onChange={set("surfaceThickness")}/></label>
    </fieldset>

    <fieldset><legend>Estándares a evaluar</legend>
      {STANDARDS.map((standard) => <label className="checkbox-row" key={standard}><input type="checkbox" checked={form.standards.includes(standard)} onChange={(event) => setForm((current) => ({ ...current, standards: event.target.checked ? [...current.standards, standard] : current.standards.filter((item) => item !== standard) }))}/>{standard}</label>)}
    </fieldset>

    <fieldset><legend>Tarifas ({currency || "moneda"})</legend>
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
      <label>Fuente de las tarifas escritas a mano<input value={rateSource} placeholder="Cotización, lista de precios o APU" onChange={(e) => setRateSource(e.target.value)}/></label>
      <label>Ancho de zanja (m)<input required type="number" min="0.01" step="any" value={trenchWidth} onChange={(e) => setTrenchWidth(e.target.value)}/></label>
      <label>Fuente del ancho de zanja<input required value={trenchSource} onChange={(e) => setTrenchSource(e.target.value)}/></label>
    </fieldset>

    <label className="checkbox-row"><input type="checkbox" checked={orthogonal} onChange={(e) => setOrthogonal(e.target.checked)}/> Solo trazados ortogonales (sin diagonales nuevas)</label>
    <label>Presupuesto de llamadas al solver<select value={budget} onChange={(e) => setBudget(e.target.value)}>{BUDGETS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
    <button className="button primary" type="submit" disabled={busy || active || Boolean(blocker)} aria-describedby={blocker ? "topology-start-blocker" : undefined}>{busy ? "Iniciando Matherra…" : "Iniciar búsqueda con Matherra"}</button>
    {blocker && !active && <small id="topology-start-blocker" className="topology-start-blocker">Para iniciar: {blocker}</small>}
    {error && <p className="optimizer-context-error" role="alert">{error}</p>}

    {run && <div className="optimizer-run-result" aria-live="polite">
      <strong>Matherra · {RUN_STATUS_LABELS[run.status] || run.status}</strong>
      {active && <><small>{progress?.verdicts ? `${progress.verdicts} de ${progress.budget || budget} evaluaciones eléctricas` : "Esperando al worker del optimizador…"}</small>
        <progress max={progress?.budget || Number(budget)} value={progress?.verdicts || 0}/>
        <button type="button" className="button" onClick={cancel}>Cancelar</button></>}
      {run.error && <small className="optimizer-context-error">{run.error}</small>}
      {run.status === "completed" && <>
        <small>{alternatives ? `${alternatives} alternativa${alternatives === 1 ? "" : "s"} verificada${alternatives === 1 ? "" : "s"} en el nivel más fino.` : "Ninguna topología pasó la verificación más fina con este presupuesto."}</small>
        <button type="button" className="button primary" data-testid="matherra-show-results" onClick={() => onShowResults?.(run.id)}>{alternatives ? "Revisar alternativas en Resultado" : "Ver el detalle en Resultado"}</button>
      </>}
    </div>}
  </form>;
}

export default TopologyOptimizerPanel;
