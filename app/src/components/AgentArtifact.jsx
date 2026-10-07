import React, { Suspense, lazy, useEffect, useState } from "react";
import { Activity, Box, Eye, PencilRuler, Rotate3d, Undo2 } from "lucide-react";
import { SurfacePotentialMap } from "./GroundingCalculations.jsx";

const fieldLabels = {
  name: "Nombre",
  soil_layers: "Capas de suelo",
  soil_measurements: "Mediciones de resistividad",
  geometry: "Malla",
  "geometry.length_m": "Largo (m)",
  "geometry.width_m": "Ancho (m)",
  "geometry.conductor_spacing_m": "Retícula (m)",
  "geometry.conductor_spacing_x_m": "Separación en X (m)",
  "geometry.conductor_spacing_y_m": "Separación en Y (m)",
  "geometry.conductors": "Conductores trazados",
  "geometry.rods": "Posición de varillas",
  "geometry.burial_depth_m": "Profundidad (m)",
  "geometry.rods_count": "Varillas",
  "geometry.rod_length_m": "Longitud de varilla (m)",
  "fault.current_a": "Corriente de falla (A)",
  "fault.clearing_time_s": "Tiempo de despeje (s)",
  "fault.surface_resistivity_ohm_m": "Resistividad capa superficial (Ω·m)",
  "fault.surface_thickness_m": "Espesor capa superficial (m)",
  "fault.body_weight_kg": "Peso corporal (kg)",
  "conductor.material_id": "Material del conductor",
  "conductor.cross_section_mm2": "Sección del conductor (mm²)",
  "conductor.joint_type": "Tipo de unión",
  "conductor.maximum_temperature_c": "Temperatura máxima (°C)",
  "conductor.thermal_duration_s": "Duración térmica t_c (s)",
  "conductor.ambient_temperature_c": "Temperatura ambiente (°C)",
};

function formatValue(value) {
  if (value === null || value === undefined) return "—";
  if (value.measurements) return `${value.measurements.length} lecturas ${value.array === "schlumberger" ? "Schlumberger" : "Wenner"}`;
  if (Array.isArray(value)) {
    if (!value.length) return "—";
    if (value[0].start) return `${value.length} conductores`;
    if ("x" in value[0]) return `${value.length} varillas`;
    return value.map((layer) => `${Number(layer.resistivity_ohm_m).toLocaleString("es-CO", { maximumFractionDigits: 1 })} Ω·m${layer.depth_m ? ` · ${Number(layer.depth_m).toLocaleString("es-CO", { maximumFractionDigits: 2 })} m` : ""}`).join(" / ");
  }
  if (typeof value === "number") return value.toLocaleString("es-CO", { maximumFractionDigits: 3 });
  return String(value);
}

// Same rules as backend/src/domain/spat/grid_geometry.py.
function axisPositions(span, spacing) {
  const count = Math.max(2, Math.ceil(span / spacing) + 1);
  return Array.from({ length: count }, (_, i) => (i * span) / (count - 1));
}

function perimeterRods(count, length, width) {
  const perimeter = 2 * (length + width);
  return Array.from({ length: count }, (_, index) => {
    const d = (perimeter * index) / Math.max(count, 1);
    if (d < length) return [d, 0];
    if (d < length + width) return [length, d - length];
    if (d < 2 * length + width) return [length - (d - length - width), width];
    return [0, width - (d - 2 * length - width)];
  });
}

function gridPlan(geometry) {
  const { length_m: length, width_m: width } = geometry;
  let lines;
  if (geometry.conductors?.length) {
    lines = geometry.conductors.map((c) => [[c.start.x, c.start.y], [c.end.x, c.end.y]]);
  } else {
    const sx = geometry.conductor_spacing_x_m || geometry.conductor_spacing_m;
    const sy = geometry.conductor_spacing_y_m || geometry.conductor_spacing_m;
    lines = [...axisPositions(width, sy).map((y) => [[0, y], [length, y]]), ...axisPositions(length, sx).map((x) => [[x, 0], [x, width]])];
  }
  const rods = geometry.rods?.length ? geometry.rods.map((r) => [r.x, r.y]) : perimeterRods(geometry.rods_count || 0, length, width);
  return { lines, rods };
}

function gridDescription(geometry) {
  if (geometry.conductors?.length) return `${geometry.conductors.length} conductores trazados`;
  const sx = geometry.conductor_spacing_x_m || geometry.conductor_spacing_m;
  const sy = geometry.conductor_spacing_y_m || geometry.conductor_spacing_m;
  return sx === sy ? `retícula ${formatValue(sx)} m` : `retícula ${formatValue(sx)} m en X × ${formatValue(sy)} m en Y`;
}

function ArtifactGrid({ geometry, draftPlan }) {
  const length = draftPlan?.length || geometry.length_m;
  const width = draftPlan?.width || geometry.width_m;
  const drafted = draftPlan?.items?.length > 0;
  const effectiveGeometry = { ...geometry, length_m: length, width_m: width, conductor_spacing_m: draftPlan?.spacing || geometry.conductor_spacing_m };
  const lines = drafted ? draftPlan.items.filter((item) => item.type === "conductor").map((item) => [[item.from.x, item.from.y], [item.to.x, item.to.y]]) : gridPlan(effectiveGeometry).lines;
  const rods = drafted ? draftPlan.items.filter((item) => item.type === "electrode").map((item) => [item.x, item.y]) : gridPlan(effectiveGeometry).rods;
  const scale = Math.min(380 / length, 240 / width);
  const w = length * scale, h = width * scale, x0 = (490 - w) / 2, y0 = (330 - h) / 2;
  // Plan y grows upward from the origin corner: draw it bottom-up.
  const px = (x, y) => [x0 + x * scale, y0 + h - y * scale];
  const rodNote = geometry.rods?.length ? "posiciones del artefacto" : "repartidas en el perímetro";
  return <svg className="agent-grid-svg" viewBox="0 0 490 350" role="img" aria-label={`Malla de ${length} por ${width} m, ${gridDescription(geometry)}, ${rods.length} varillas`}>
    <rect x={x0} y={y0} width={w} height={h} fill="#f3f8f5" stroke="#cfe0d8" strokeDasharray="4 3"/>
    {lines.map(([a, b], i) => { const [ax, ay] = px(...a), [bx, by] = px(...b); return <line key={i} x1={ax} y1={ay} x2={bx} y2={by} stroke="#2f7f72" strokeWidth="1.6" strokeLinecap="round"/>; })}
    {rods.map(([x, y], i) => { const [cx, cy] = px(x, y); return <circle key={i} cx={cx} cy={cy} r="4.5" fill="#c98a2b" stroke="#fff" strokeWidth="1.5"/>; })}
    <text x={x0 + w / 2} y={y0 + h + 22} textAnchor="middle" fill="#5f6f68" fontSize="11">{formatValue(length)} m (X)</text>
    <text x={x0 - 12} y={y0 + h / 2} textAnchor="middle" fill="#5f6f68" fontSize="11" transform={`rotate(-90 ${x0 - 12} ${y0 + h / 2})`}>{formatValue(width)} m (Y)</text>
    <text x="245" y="342" textAnchor="middle" fill="#93a09a" fontSize="9">{gridDescription(geometry)} · {rods.length} varillas ({rodNote})</text>
  </svg>;
}

function AgentArtifactPanel({ project, conversation, token, refreshKey }) {
  const [artifact, setArtifact] = useState(null);
  const [error, setError] = useState("");
  const [draftPlan, setDraftPlan] = useState(() => readDraftPlan(project.id));
  useEffect(() => {
    const sync = (event) => { if (!event?.detail || event.detail.projectId === project.id) setDraftPlan(event?.detail?.plan || readDraftPlan(project.id)); };
    window.addEventListener("grounding-plan-updated", sync);
    return () => window.removeEventListener("grounding-plan-updated", sync);
  }, [project.id]);
  useEffect(() => {
    if (!conversation) return undefined;
    let live = true;
    const auth = { Authorization: `Bearer ${token}` };
    (async () => {
      try {
        const [state, artifacts] = await Promise.all([
          fetch(`/api/v1/conversations/${conversation.id}/agent-state`, { headers: auth }).then((r) => r.json()),
          fetch(`/api/v1/projects/${project.id}/artefactos-diseno-tierras`, { headers: auth }).then((r) => (r.ok ? r.json() : [])),
        ]);
        if (!live) return;
        setArtifact(artifacts.find((a) => a.artifact_id === state.artifact_id) || (artifacts.length === 1 ? artifacts[0] : null));
      } catch (e) { if (live) setError("No se pudo cargar el artefacto."); }
    })();
    return () => { live = false; };
  }, [project.id, conversation?.id, token, refreshKey]);
  const snapshot = artifact?.snapshot;
  const soilSource = artifact?.origin?.provenance?.soil_layers;
  const soilNote = snapshot?.soil_measurements ? `${formatValue(snapshot.soil_measurements)}${soilSource?.kind === "tool" && soilSource.note ? ` · ${soilSource.note}` : ""}` : "";
  const origin = artifact?.origin?.kind === "agent" ? "Creada por el agente" : "Creada por el usuario";
  return <aside className="panel artifact-side-panel"><div className="panel-heading"><div><Box size={17}/><h2>Artefacto de puesta a tierra</h2></div>{artifact && <span className="muted-label">Versión {artifact.version}</span>}</div>
    {snapshot ? <>
      {snapshot.geometry ? <div className="agent-grid-preview"><ArtifactGrid geometry={snapshot.geometry} draftPlan={draftPlan}/></div> : <div className="artifact-preview-empty"><Box size={22}/><strong>Sin malla todavía</strong><span>Pídele al agente la geometría, por ejemplo: «malla de 40 × 30 m con retícula de 5 m».</span></div>}
      <div className="artifact-status"><strong>{artifact.name}</strong><span>{origin} · {new Date(artifact.created_at * 1000).toLocaleString("es-CO")}</span></div>
      {snapshot.geometry && <div className="artifact-status"><strong>Malla</strong><span>{formatValue(snapshot.geometry.length_m)} × {formatValue(snapshot.geometry.width_m)} m · {gridDescription(snapshot.geometry)} · profundidad {formatValue(snapshot.geometry.burial_depth_m)} m · {snapshot.geometry.rods_count} varillas de {formatValue(snapshot.geometry.rod_length_m)} m</span></div>}
      <div className="artifact-status"><strong>Suelo</strong>{snapshot.soil_layers?.length ? <div className="artifact-soil-layers">{snapshot.soil_layers.map((layer, index) => <span key={index}>C{index + 1}: {formatValue(layer.resistivity_ohm_m)} Ω·m · {layer.depth_m ? `${formatValue(layer.depth_m)} m` : "semiespacio"}{layer.material ? ` · ${layer.material}` : ""}</span>)}{soilNote && <small>{soilNote}</small>}</div> : <span className="no-information">Pendiente: resistividad del suelo. Puedes pegar un sondeo Wenner o Schlumberger en el chat o subir un CSV/XLSX.</span>}</div>
      <div className="artifact-status"><strong>Falla</strong>{snapshot.fault?.current_a && snapshot.fault?.clearing_time_s ? <span>{formatValue(snapshot.fault.current_a)} A · {formatValue(snapshot.fault.clearing_time_s)} s · capa superficial {formatValue(snapshot.fault.surface_resistivity_ohm_m)} Ω·m, {formatValue(snapshot.fault.surface_thickness_m)} m</span> : <span className="no-information">Pendiente: {[!snapshot.fault?.current_a && "corriente de falla", !snapshot.fault?.clearing_time_s && "tiempo de despeje"].filter(Boolean).join(", ")}. Se necesitan para el cálculo de seguridad.</span>}</div>
      {snapshot.conductor && <div className="artifact-status"><strong>Conductor</strong><span>{snapshot.conductor.material_id} · {formatValue(snapshot.conductor.cross_section_mm2)} mm² · unión {snapshot.conductor.joint_type}</span></div>}
    </> : <div className="artifact-preview-empty"><Box size={25}/><strong>Aún no hay un artefacto de malla</strong><span>{error || "Pídele al agente en el chat que diseñe la malla, por ejemplo: «créame una malla de 40 × 30 m con retícula de 5 m»."}</span></div>}
  </aside>;
}

function ArtifactUpdateCard({ message, token, project, onView, onUndone }) {
  const update = message.payload;
  const [state, setState] = useState("");
  async function undo() {
    setState("busy");
    const auth = { Authorization: `Bearer ${token}` };
    const root = `/api/v1/projects/${project.id}/artefactos-diseno-tierras/${update.artifact_id}`;
    try {
      const response = update.previous_version
        ? await fetch(`${root}/versions/${update.previous_version}/restaurar`, { method: "POST", headers: auth })
        : await fetch(`${root}/versions/${update.version}`, { method: "DELETE", headers: auth });
      if (!response.ok) throw new Error();
      setState("undone"); onUndone();
    } catch { setState("error"); }
  }
  const created = update.previous_version == null;
  return <article className="artifact-update-card">
    <div className="artifact-update-head"><PencilRuler size={15}/><strong>{created ? "Se creó el artefacto" : "Se editó el artefacto"}</strong><span>{update.name} · versión {update.version}</span></div>
    <p>{update.summary}</p>
    <div className="artifact-update-changes">{update.changes.slice(0, 8).map((change) => <div key={change.path}><span>{fieldLabels[change.path] || change.path}</span><small>{change.confirmed ? <><b>{formatValue(change.after)}</b> · confirmado</> : <>{created ? "" : `${formatValue(change.before)} → `}<b>{formatValue(change.after)}</b></>}</small></div>)}{update.changes.length > 8 && <div><span>+{update.changes.length - 8} cambios más</span></div>}</div>
    {update.missing_for_calculation?.length > 0 && <p className="artifact-update-warning">Para el cálculo de seguridad faltan: {update.missing_for_calculation.map((path) => fieldLabels[path] || path).join(", ")}.</p>}
    <div className="artifact-update-actions">
      <button className="button" disabled={state === "busy" || state === "undone"} onClick={undo}><Undo2 size={14}/> {state === "undone" ? "Deshecho" : created ? "Deshacer (eliminar)" : `Deshacer (volver a v${update.previous_version})`}</button>
      <button className="button primary" onClick={onView}><Eye size={14}/> Ver artefacto</button>
    </div>
    {state === "error" && <p className="artifact-update-warning">No se pudo deshacer el cambio.</p>}
  </article>;
}

// three.js loads only when the 3D view opens.
const Surface3D = lazy(() => import("./Surface3D.jsx"));

const verdictLabels = { cumple: "Cumple", no_cumple: "No cumple", no_evaluable: "No evaluable" };

function AgentResultsPanel({ project, conversation, token, refreshKey }) {
  const [calculation, setCalculation] = useState(null);
  const [geometry, setGeometry] = useState(null);
  const [show3d, setShow3d] = useState(false);
  const [state, setState] = useState("loading");
  const [draftPlan, setDraftPlan] = useState(() => readDraftPlan(project.id));
  useEffect(() => {
    const sync = (event) => { if (!event?.detail || event.detail.projectId === project.id) setDraftPlan(event?.detail?.plan || readDraftPlan(project.id)); };
    window.addEventListener("grounding-plan-updated", sync);
    return () => window.removeEventListener("grounding-plan-updated", sync);
  }, [project.id]);
  useEffect(() => {
    if (!conversation) return undefined;
    let live = true;
    const auth = { Authorization: `Bearer ${token}` };
    const get = (url) => fetch(url, { headers: auth }).then((r) => (r.ok ? r.json() : null));
    (async () => {
      try {
        const root = `/api/v1/projects/${project.id}/artefactos-diseno-tierras`;
        const [agentState, artifacts] = await Promise.all([get(`/api/v1/conversations/${conversation.id}/agent-state`), get(root)]);
        const artifact = (artifacts || []).find((a) => a.artifact_id === agentState?.artifact_id) || (artifacts?.length === 1 ? artifacts[0] : null);
        if (!artifact) { if (live) { setCalculation(null); setState("empty"); } return; }
        // Latest calculation of any version, newest version first.
        const versions = (await get(`${root}/${artifact.artifact_id}/versions`)) || [];
        for (const version of versions.slice(0, 5)) {
          const rows = (await get(`${root}/${artifact.artifact_id}/versions/${version.version}/calculos-potencial`)) || [];
          if (rows.length) { if (live) { setCalculation(rows[0]); setGeometry(version.snapshot?.geometry || null); setState("ready"); } return; }
        }
        if (live) { setCalculation(null); setState("empty"); }
      } catch { if (live) setState("error"); }
    })();
    return () => { live = false; };
  }, [project.id, conversation?.id, token, refreshKey]);
  const result = calculation?.result;
  const safety = result?.safety || [];
  const verdict = safety.some((s) => s.status === "no_cumple") || result?.conductor_thermal?.status === "no_cumple" ? "no_cumple" : safety.length && safety.every((s) => s.status === "cumple") ? "cumple" : "no_evaluable";
  const value = (field) => Number(field?.value ?? field).toLocaleString("es-CO", { maximumFractionDigits: 1 });
  return <aside className="panel artifact-side-panel agent-results-panel"><div className="panel-heading"><div><Activity size={17}/><h2>Resultados</h2></div>{calculation && <span className="muted-label">Versión {calculation.artifact_version}</span>}</div>
    {!calculation ? <p className="no-information">{state === "error" ? "No se pudieron cargar los resultados." : "Sin información: pídele al agente «calcula la seguridad» o usa el panel Parámetros eléctricos."}</p>
      : calculation.status !== "completed" ? <div className="artifact-status"><strong>Cálculo {calculation.status === "pending" || calculation.status === "running" ? "en curso…" : calculation.status}</strong>{calculation.error && <span className="no-information">{calculation.error}</span>}</div>
      : <>
        <div className={`agent-verdict ${verdict}`}>{verdictLabels[verdict]}</div>
        <div className="artifact-status"><strong>Malla</strong><span>R = {Number(result.grid_resistance_ohm).toLocaleString("es-CO", { maximumFractionDigits: 3 })} Ω · GPR = {value(result.gpr_v)} V · I = {value(result.injected_current_a)} A</span></div>
        {safety.map((standard) => <div className="artifact-status" key={standard.standard}><strong>{standard.standard}</strong>{(standard.criteria || []).map((c) => <span key={c.criterion} className={c.status === "cumple" ? "" : "agent-fails"}>{c.criterion === "touch" ? "Contacto" : "Paso"}: {value(c.actual_v)} V / {value(c.tolerable_v)} V tolerable ({(100 * c.margin_rel).toLocaleString("es-CO", { maximumFractionDigits: 1 })} %)</span>)}{standard.reason && <span className="no-information">{standard.reason}</span>}</div>)}
        {result.conductor_thermal && <div className="artifact-status"><strong>Conductor (térmico)</strong><span className={result.conductor_thermal.status === "cumple" ? "" : "agent-fails"}>Sección {value(result.conductor_thermal.selected_section_mm2)} mm² · mínima {value(result.conductor_thermal.minimum_section_mm2)} mm²</span></div>}
        {result.surface_potential && <div className="agent-grid-preview"><SurfacePotentialMap field={result.surface_potential}/></div>}
        {result.surface_potential && geometry && <button className="button primary agent-3d-button" onClick={() => setShow3d(true)}><Rotate3d size={15}/> Ver en 3D</button>}
        {show3d && <Suspense fallback={<div className="surface3d-backdrop"><div className="surface3d-loading">Cargando vista 3D…</div></div>}>
          <Surface3D calculation={calculation} onClose={() => setShow3d(false)} plan={{ ...gridPlan({ ...geometry, length_m: draftPlan?.length || geometry.length_m, width_m: draftPlan?.width || geometry.width_m, conductor_spacing_m: draftPlan?.spacing || geometry.conductor_spacing_m }), ...(draftPlan?.items?.length ? { lines: draftPlan.items.filter((item) => item.type === "conductor").map((item) => [[item.from.x, item.from.y], [item.to.x, item.to.y]]), rods: draftPlan.items.filter((item) => item.type === "electrode").map((item) => [item.x, item.y]) } : {}), length: draftPlan?.length || geometry.length_m, width: draftPlan?.width || geometry.width_m, burialDepth: geometry.burial_depth_m || 0.5, rodLength: geometry.rod_length_m || 2.4 }}/>
        </Suspense>}
        {result.model_warnings?.length > 0 && <div className="artifact-status"><strong>Advertencias del modelo</strong>{result.model_warnings.map((w) => <span key={w} className="no-information">{w}</span>)}</div>}
        <p className="no-information agent-results-note">Verificación de prefactibilidad; requiere revisión de un ingeniero competente.</p>
      </>}
  </aside>;
}

function readDraftPlan(projectId) {
  try { return JSON.parse(localStorage.getItem(`grounding-plan:${projectId}`) || "null"); }
  catch { return null; }
}

export { AgentArtifactPanel, AgentResultsPanel, ArtifactGrid, ArtifactUpdateCard };
