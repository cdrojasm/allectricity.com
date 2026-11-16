import React, { Suspense, lazy, useEffect, useState } from "react";
import { Activity, Box, ChevronRight, ExternalLink, Eye, FileText, PencilRuler, RefreshCw, Rotate3d, Settings2, Sparkles, Undo2, X } from "lucide-react";
import { SurfacePotentialMap } from "./GroundingCalculations.jsx";
import { evaluateResult, formatNumber, verdictLabels } from "../resultInterpretation.js";
import { fieldLabels, fieldValueLabel } from "../labels.js";

const calculationFreshnessLabels = { al_dia: "Resultado al día", desactualizado: "Resultado desactualizado", calculando: "Cálculo en curso", sin_calculo: "Sin cálculo", error: "Cálculo con error" };
const chipLabels = { claim: "Extraído", document: "Documento", user: "Confirmado", tool: "Calculado", assumption: "Supuesto", schema_default: "Predeterminado" };

function ProvenanceChip({ provenance, path, onOpen }) {
  const source = provenance?.[path] || Object.entries(provenance || {}).find(([key]) => key.startsWith(`${path}.`))?.[1];
  if (!source?.kind) return null;
  const detail = [source.ref, source.note].filter(Boolean).join(" · ");
  const label = chipLabels[source.kind] || source.kind;
  return <button type="button" className="provenance-chip" title={detail || `Origen: ${label}`} onClick={() => onOpen?.(source)}>{label}<ChevronRight size={11}/></button>;
}

function ArtifactEvidencePanel({ project, token, source, onClose, onOpenGraph }) {
  const [claim, setClaim] = useState(null);
  const [loading, setLoading] = useState(Boolean(source?.kind === "claim" && source.ref));
  useEffect(() => {
    if (source?.kind !== "claim" || !source.ref) { setClaim(null); setLoading(false); return undefined; }
    let live = true;
    setLoading(true);
    fetch(`/api/v1/projects/${project.id}/knowledge-graph/claims/${source.ref}`, { headers: { Authorization: `Bearer ${token}` } })
      .then((response) => response.ok ? response.json() : null).then((data) => { if (live) setClaim(data); })
      .catch(() => { if (live) setClaim(null); }).finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [project.id, source, token]);
  async function openEvidence(evidence) {
    const uploadId = evidence.upload_id || claim?.upload_id;
    if (!uploadId) return;
    const response = await fetch(`/api/v1/projects/${project.id}/knowledge-graph/documents/${uploadId}/source`, { headers: { Authorization: `Bearer ${token}` } });
    if (!response.ok) return;
    const document = await response.json();
    const page = evidence.locator?.page || evidence.page;
    window.open(document.mime_type === "application/pdf" && page ? `${document.url}#page=${page}` : document.url, "_blank", "noopener,noreferrer");
  }
  return <aside className="artifact-evidence-panel" aria-label="Evidencia del valor extraído">
    <div className="artifact-evidence-header"><div><FileText size={16}/><strong>Evidencia del valor</strong></div><button className="icon-button" aria-label="Cerrar evidencia" onClick={onClose}><X size={15}/></button></div>
    {loading ? <p className="no-information">Cargando afirmación y citas…</p> : claim ? <>
      <div className="artifact-evidence-claim"><strong>{claim.attribute || claim.subject || "Afirmación extraída"}</strong><span>{claim.value ?? claim.object ?? "—"}{claim.unit ? ` ${claim.unit}` : ""}</span></div>
      {claim.evidence?.length ? <div className="artifact-evidence-list">{claim.evidence.map((evidence, index) => <div className="artifact-evidence-item" key={`${evidence.evidence_id || index}`}><blockquote>“{evidence.quote || "Sin cita textual"}”</blockquote><small>{claim.filename || evidence.filename || "Documento"}{evidence.locator?.page || evidence.page ? ` · página ${evidence.locator?.page || evidence.page}` : ""}</small><button className="button" onClick={() => openEvidence(evidence)}><ExternalLink size={13}/> Abrir documento</button></div>)}</div> : <p className="no-information">La afirmación no tiene una cita disponible.</p>}
      {(claim.conflicts?.length || claim.duplicates?.length) ? <div className="artifact-evidence-candidates"><strong>Otras candidatas</strong><span>{claim.conflicts?.length || claim.duplicates?.length} afirmación(es) relacionadas</span><button className="button primary" onClick={onOpenGraph}>Ver y cambiar en el grafo</button></div> : null}
    </> : <p className="no-information">No se pudo cargar el detalle de esta fuente. <button className="link-button" onClick={onOpenGraph}>Abrir grafo de conocimiento</button></p>}
  </aside>;
}

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

function ArtifactGrid({ geometry }) {
  const length = geometry.length_m;
  const width = geometry.width_m;
  const { lines, rods } = gridPlan(geometry);
  const structures = geometry.structures || [];
  const areas = geometry.areas || [];
  const scale = Math.min(380 / length, 240 / width);
  const w = length * scale, h = width * scale, x0 = (490 - w) / 2, y0 = (330 - h) / 2;
  // Plan y grows upward from the origin corner: draw it bottom-up.
  const px = (x, y) => [x0 + x * scale, y0 + h - y * scale];
  const rodNote = geometry.rods?.length ? "posiciones del artefacto" : "repartidas en el perímetro";
  return <svg className="agent-grid-svg" viewBox="0 0 490 350" role="img" aria-label={`Terreno de ${length} por ${width} m, ${areas.length} zonas, ${gridDescription(geometry)}, ${rods.length} varillas y ${structures.length} elementos constructivos`}>
    <defs><pattern id="artifact-grid-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="6" stroke="#9aa0a3" strokeWidth="1.2"/></pattern></defs>
    <rect x={x0} y={y0} width={w} height={h} fill="#fbfcfb" stroke="#b7c8c0" strokeDasharray="4 3"/>
    {areas.map((area, i) => { const [ax, ay] = px(area.x_min, area.y_max), aw = (area.x_max - area.x_min) * scale, ah = (area.y_max - area.y_min) * scale, open = area.type === "intervenible"; return <g key={`area-${i}`}><rect x={ax} y={ay} width={aw} height={ah} fill={open ? "rgba(63,154,98,.16)" : "#e3e5e6"} stroke={open ? "#3f9a62" : "#7d8487"} strokeWidth="1"/>{!open && <rect x={ax} y={ay} width={aw} height={ah} fill="url(#artifact-grid-hatch)"/>}<text x={ax + aw / 2} y={ay + ah / 2 + 3} textAnchor="middle" fill={open ? "#2f5f43" : "#5f6d66"} fontSize="8.5" transform={aw < 50 && ah > aw ? `rotate(-90 ${ax + aw / 2} ${ay + ah / 2})` : undefined}>{area.label || (open ? "Área intervenible" : "No intervenible")}</text></g>; })}
    {structures.map((item, i) => { const [cx, cy] = px(item.x, item.y), sx = cx - item.width * scale / 2, sy = cy - item.height * scale / 2; return <g key={`structure-${i}`}><rect x={sx} y={sy} width={item.width * scale} height={item.height * scale} rx="2" fill="#e3e5e6" stroke="#7d8487" strokeWidth="1.2"/><rect x={sx} y={sy} width={item.width * scale} height={item.height * scale} rx="2" fill="url(#artifact-grid-hatch)"/><text x={cx} y={cy - 2} textAnchor="middle" fill="#4f5a55" fontSize="9" fontWeight="600">{item.label || "Elemento constructivo"}</text><text x={cx} y={cy + 9} textAnchor="middle" fill="#5f6d66" fontSize="8">No intervenible</text></g>; })}
    {lines.map(([a, b], i) => { const [ax, ay] = px(...a), [bx, by] = px(...b); return <line key={i} x1={ax} y1={ay} x2={bx} y2={by} stroke="#2563c9" strokeWidth="1.6" strokeLinecap="round"/>; })}
    {rods.map(([x, y], i) => { const [cx, cy] = px(x, y); return <circle key={i} cx={cx} cy={cy} r="4.5" fill="#c98a2b" stroke="#fff" strokeWidth="1.5"/>; })}
    <text x={x0 + w / 2} y={y0 + h + 22} textAnchor="middle" fill="#5f6f68" fontSize="11">{formatValue(length)} m (X)</text>
    <text x={x0 - 12} y={y0 + h / 2} textAnchor="middle" fill="#5f6f68" fontSize="11" transform={`rotate(-90 ${x0 - 12} ${y0 + h / 2})`}>{formatValue(width)} m (Y)</text>
    <text x="245" y="342" textAnchor="middle" fill="#93a09a" fontSize="9">{gridDescription(geometry)} · {rods.length} varillas ({rodNote})</text>
  </svg>;
}

function AgentArtifactPanel({ project, conversation, token, refreshKey, onOpenGraph }) {
  const [artifact, setArtifact] = useState(null);
  const [planWarnings, setPlanWarnings] = useState([]);
  const [error, setError] = useState("");
  const [evidenceSource, setEvidenceSource] = useState(null);
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
        // A user-created artifact may predate the conversation state. The API returns
        // latest versions first, so keep the workspace useful while a valid version exists.
        setArtifact(artifacts.find((a) => a.artifact_id === state.artifact_id) || artifacts[0] || null);
      } catch (e) { if (live) setError("No se pudo cargar el artefacto."); }
    })();
    return () => { live = false; };
  }, [project.id, conversation?.id, token, refreshKey]);
  const snapshot = artifact?.snapshot;
  useEffect(() => {
    if (!snapshot?.geometry) { setPlanWarnings([]); return undefined; }
    let live = true;
    // Saved geometry is always valid; the backend still reports warnings such as a split grid.
    fetch(`/api/v1/projects/${project.id}/artefactos-diseno-tierras/geometria/validar`, { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ geometry: snapshot.geometry }) })
      .then((r) => (r.ok ? r.json() : { warnings: [] })).then((check) => { if (live) setPlanWarnings(check.warnings || []); }).catch(() => {});
    return () => { live = false; };
  }, [project.id, token, artifact?.artifact_id, artifact?.version]);
  const provenance = artifact?.origin?.provenance || {};
  const soilSource = provenance.soil_layers;
  const soilNote = snapshot?.soil_measurements ? `${formatValue(snapshot.soil_measurements)}${soilSource?.kind === "tool" && soilSource.note ? ` · ${soilSource.note}` : ""}` : "";
  const origin = artifact?.origin?.kind === "agent" ? "Creada por el agente" : "Creada por el usuario";
  const openEvidence = (source) => setEvidenceSource(source);
  return <aside className="panel artifact-side-panel"><div className="panel-heading"><div><Box size={17}/><h2>Artefacto de puesta a tierra</h2></div>{artifact && <span className="muted-label">Versión {artifact.version}</span>}</div>
    {snapshot ? <>
      {snapshot.geometry ? <div className="agent-grid-preview"><ArtifactGrid geometry={snapshot.geometry}/>{planWarnings.map((warning, i) => <p key={i} className="artifact-update-warning">{warning.kind === "disconnected" ? `La malla tiene ${warning.parts} partes separadas: el cálculo las trata como un solo conductor, lo que solo es cierto si un conductor de unión las conecta.` : warning.message}</p>)}</div> : <div className="artifact-preview-empty"><Box size={22}/><strong>Sin malla todavía</strong><span>Pídele al agente la geometría, por ejemplo: «malla de 40 × 30 m con retícula de 5 m».</span></div>}
      <div className="artifact-status"><strong>{artifact.name}</strong><span>{origin} · {new Date(artifact.created_at * 1000).toLocaleString("es-CO")}</span></div>
      {artifact.draft_watermark && <div className="artifact-status agent-fails"><strong>{artifact.draft_watermark}</strong><span>Confirma los supuestos antes de presentar el estudio como final.</span></div>}
      {artifact.calculation_verdict && artifact.calculation_verdict !== "no_evaluado" && <div className={`agent-verdict ${artifact.calculation_verdict}`} data-testid="artifact-verdict">{verdictLabels[artifact.calculation_verdict] || artifact.calculation_verdict}{artifact.calculation_status === "desactualizado" ? " · del cálculo anterior" : ""}</div>}
      {artifact.calculation_status && <div className={`artifact-status${artifact.calculation_status === "desactualizado" ? " agent-fails" : ""}`}><strong>Vigencia</strong><span>{calculationFreshnessLabels[artifact.calculation_status] || artifact.calculation_status}{artifact.calculation_version && artifact.calculation_status === "desactualizado" ? ` · cálculo de versión ${artifact.calculation_version}` : ""}</span></div>}
      {snapshot.geometry && <div className="artifact-status"><strong>Malla <ProvenanceChip provenance={provenance} path="geometry" onOpen={openEvidence}/></strong><span>{formatValue(snapshot.geometry.length_m)} × {formatValue(snapshot.geometry.width_m)} m · {gridDescription(snapshot.geometry)} · profundidad {formatValue(snapshot.geometry.burial_depth_m)} m · {snapshot.geometry.rods_count} varillas de {formatValue(snapshot.geometry.rod_length_m)} m</span></div>}
      <div className="artifact-status"><strong>Suelo <ProvenanceChip provenance={provenance} path="soil_layers" onOpen={openEvidence}/></strong>{snapshot.soil_layers?.length ? <div className="artifact-soil-layers">{snapshot.soil_layers.map((layer, index) => <span key={index}>C{index + 1}: {formatValue(layer.resistivity_ohm_m)} Ω·m · {layer.depth_m ? `${formatValue(layer.depth_m)} m` : "semiespacio"}{layer.material ? ` · ${layer.material}` : ""}</span>)}{soilNote && <small>{soilNote}</small>}</div> : <span className="no-information">Pendiente: resistividad del suelo. Puedes pegar un sondeo Wenner o Schlumberger en el chat o subir un CSV/XLSX.</span>}</div>
      <div className="artifact-status"><strong>Falla <ProvenanceChip provenance={provenance} path="fault" onOpen={openEvidence}/></strong>{snapshot.fault?.current_a && snapshot.fault?.clearing_time_s ? <span>{formatValue(snapshot.fault.current_a)} A · {formatValue(snapshot.fault.clearing_time_s)} s · capa superficial {formatValue(snapshot.fault.surface_resistivity_ohm_m)} Ω·m, {formatValue(snapshot.fault.surface_thickness_m)} m</span> : <span className="no-information">Pendiente: {[!snapshot.fault?.current_a && "corriente de falla", !snapshot.fault?.clearing_time_s && "tiempo de despeje"].filter(Boolean).join(", ")}. Se necesitan para el cálculo de seguridad.</span>}</div>
      {snapshot.conductor && <div className="artifact-status"><strong>Conductor <ProvenanceChip provenance={provenance} path="conductor" onOpen={openEvidence}/></strong><span>{fieldValueLabel("conductor.material_id", snapshot.conductor.material_name || snapshot.conductor.material_id)} · {formatValue(snapshot.conductor.cross_section_mm2)} mm² · unión {fieldValueLabel("conductor.joint_type", snapshot.conductor.joint_type)}</span></div>}
      {evidenceSource && <ArtifactEvidencePanel project={project} token={token} source={evidenceSource} onClose={() => setEvidenceSource(null)} onOpenGraph={onOpenGraph}/>}
    </> : <div className="artifact-preview-empty"><Box size={25}/><strong>Aún no hay un artefacto de malla</strong><span>{error || "Pídele al agente en el chat que diseñe la malla, por ejemplo: «créame una malla de 40 × 30 m con retícula de 5 m»."}</span></div>}
  </aside>;
}

function ArtifactUpdateCard({ message, token, project, onView, onUndone }) {
  const update = message.payload;
  const [state, setState] = useState("");
  const [stale, setStale] = useState(false);
  useEffect(() => {
    // The warning is only true while the newest version has no calculation of its own.
    let live = true;
    fetch(`/api/v1/projects/${project.id}/artefactos-diseno-tierras`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => (r.ok ? r.json() : [])).then((rows) => {
        const row = rows.find((item) => item.artifact_id === update.artifact_id);
        if (live) setStale(Boolean(row && row.version === update.version && row.calculation_status === "desactualizado"));
      }).catch(() => {});
    return () => { live = false; };
  }, [project.id, token, update.artifact_id, update.version, message.id]);
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
    <div className="artifact-update-changes">{update.changes.slice(0, 8).map((change) => <div key={change.path}><span>{fieldLabels[change.path] || change.path}</span><small>{change.confirmed ? <><b>{formatValue(fieldValueLabel(change.path, change.after))}</b> · confirmado</> : <>{created ? "" : `${formatValue(fieldValueLabel(change.path, change.before))} → `}<b>{formatValue(fieldValueLabel(change.path, change.after))}</b></>}</small></div>)}{update.changes.length > 8 && <div><span>+{update.changes.length - 8} cambios más</span></div>}</div>
    {!created && stale && <p className="artifact-update-warning">El resultado quedó desactualizado · recalcula para esta versión.</p>}
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


function AgentResultsPanel({ project, conversation, token, refreshKey, onSuggestion }) {
  const [artifact, setArtifact] = useState(null);
  const [calculation, setCalculation] = useState(null);
  const [geometry, setGeometry] = useState(null);
  const [freshness, setFreshness] = useState(null);
  const [show3d, setShow3d] = useState(false);
  const [state, setState] = useState("loading");
  const [recalculating, setRecalculating] = useState(false);
  const [actionError, setActionError] = useState("");
  const [optimizing, setOptimizing] = useState(false);
  const [solverConfig, setSolverConfig] = useState({ discretization_m: 1, segmentation: "graded", surface_spacing_m: 0.5, touch_reach_m: 0, estimate_uncertainty: false, justification: "Discretización validada para la geometría actual y segmentación graduada en nodos críticos." });
  useEffect(() => {
    if (!conversation) return undefined;
    let live = true;
    const auth = { Authorization: `Bearer ${token}` };
    // PR-05: a failed request is an error, never an empty list. Treating a 5xx or an expired token as "no artifact"
    // made this panel say "Sin cálculo" while the plan and the version list showed a design.
    const get = async (url) => {
      const response = await fetch(url, { headers: auth });
      if (response.status === 404) return null;
      if (!response.ok) throw new Error(`HTTP ${response.status} ${url}`);
      return response.json();
    };
    (async () => {
      try {
        const root = `/api/v1/projects/${project.id}/artefactos-diseno-tierras`;
        const [agentState, artifacts] = await Promise.all([get(`/api/v1/conversations/${conversation.id}/agent-state`), get(root)]);
        const artifact = (artifacts || []).find((a) => a.artifact_id === agentState?.artifact_id) || artifacts?.[0] || null;
        if (!artifact) { if (live) { setArtifact(null); setCalculation(null); setState("empty"); } return; }
        if (live) setArtifact(artifact);
        if (live) setFreshness(artifact.calculation_status || null);
        // Prefer the current version, then keep the latest historical result visible with a stale warning.
        const versions = (await get(`${root}/${artifact.artifact_id}/versions`)) || [];
        let fallback = null;
        for (const version of versions.slice(0, 5)) {
          const rows = (await get(`${root}/${artifact.artifact_id}/versions/${version.version}/calculos-potencial`)) || [];
          if (!rows.length) continue;
          if (version.version === artifact.version) { if (live) { setCalculation(rows[0]); setGeometry(version.snapshot?.geometry || null); setState("ready"); } return; }
          if (!fallback) fallback = { calculation: rows[0], geometry: version.snapshot?.geometry || null };
        }
        if (live) { setCalculation(fallback?.calculation || null); setGeometry(fallback?.geometry || null); setState(fallback ? "ready" : "empty"); }
      } catch { if (live) setState("error"); }
    })();
    return () => { live = false; };
  }, [project.id, conversation?.id, token, refreshKey]);
  useEffect(() => {
    if (!calculation?.parameters) return;
    setSolverConfig((current) => ({ ...current, ...Object.fromEntries(["discretization_m", "segmentation", "surface_spacing_m", "touch_reach_m", "estimate_uncertainty", "justification"].filter((key) => calculation.parameters[key] !== undefined).map((key) => [key, calculation.parameters[key]])) }));
  }, [calculation?.id]);
  useEffect(() => {
    if (!calculation || !artifact || !["pending", "running"].includes(calculation.status)) return undefined;
    const timer = setInterval(async () => {
      try {
        const response = await fetch(`/api/v1/projects/${project.id}/artefactos-diseno-tierras/${artifact.artifact_id}/calculos-potencial/${calculation.id}`, { headers: { Authorization: `Bearer ${token}` } });
        if (!response.ok) return;
        const next = await response.json();
        setCalculation(next);
        if (!["pending", "running"].includes(next.status)) setFreshness(null);
      } catch (_) { /* The next poll or the normal refresh can recover. */ }
    }, 1500);
    return () => clearInterval(timer);
  }, [artifact, calculation?.id, calculation?.status, project.id, token]);
  async function optimizeUntilCompliant() {
    // Attach the failing calculation and artifact to the autonomous run so its iteration loop has a deterministic starting point.
    if (!conversation || !artifact || !calculation || calculation.artifact_version !== artifact.version || freshness === "desactualizado" || recalculating || optimizing) return;
    setOptimizing(true);
    setActionError("");
    try {
      const response = await fetch(`/api/v1/conversations/${conversation.id}/agent-state`, { method: "PUT", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ mode: "autonomo", artifact_id: artifact.artifact_id }) });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || "No se pudo activar la optimización automática.");
      await onSuggestion?.("Optimiza el diseño hasta que cumpla la norma; parte del último cálculo de esta versión, crea una versión nueva por cada ajuste y vuelve a calcular. Detente al cumplir, al llegar al límite de iteraciones o si no hay una mejora viable; explica el resultado.");
    } catch (error) { setActionError(error.message); }
    finally { setOptimizing(false); }
  }
  async function recalculate() {
    if (!artifact || recalculating) return;
    if (solverConfig.justification.trim().length < 10) { setActionError("Escribe una justificación de al menos 10 caracteres para registrar la configuración."); return; }
    setRecalculating(true); setActionError("");
    try {
      const response = await fetch(`/api/v1/projects/${project.id}/artefactos-diseno-tierras/${artifact.artifact_id}/versions/${artifact.version}/calculos-potencial`, { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ ...solverConfig, discretization_m: Number(solverConfig.discretization_m), surface_spacing_m: Number(solverConfig.surface_spacing_m), touch_reach_m: Number(solverConfig.touch_reach_m), safety_standards: ["IEEE 80-2013"] }) });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail?.message || body.detail || "No se pudo iniciar el cálculo.");
      setCalculation(body); setFreshness("calculando"); setState("ready");
    } catch (error) { setActionError(error.message); }
    finally { setRecalculating(false); }
  }
  const result = calculation?.result;
  const { verdict, interpretation, safety } = evaluateResult(result);
  const value = formatNumber;
  const freshnessLabel = freshness === "desactualizado" ? "El resultado quedó desactualizado · recalcula para esta versión" : freshness === "calculando" ? "Calculando la versión vigente…" : null;
  const recalculateButton = <button className="button primary" disabled={!artifact || recalculating || ["pending", "running"].includes(calculation?.status)} onClick={recalculate}><RefreshCw size={14}/> {recalculating || ["pending", "running"].includes(calculation?.status) ? "Calculando…" : "Recalcular"}</button>;
  return <aside className="panel artifact-side-panel agent-results-panel"><div className="panel-heading"><div><Activity size={17}/><h2>Resultados</h2></div><div className="artifact-results-heading-actions">{calculation && <span className="muted-label">Versión {calculation.artifact_version}</span>}{recalculateButton}</div></div>
    {actionError && <p className="artifact-update-warning">{actionError}</p>}
    {!calculation ? <div className="artifact-results-empty"><p className="no-information">{state === "error" ? "No se pudieron cargar los resultados." : "Sin cálculo para esta versión del artefacto."}</p>{artifact && <p className="no-information">Completa y confirma los parámetros eléctricos antes de recalcular.</p>}</div>
      : calculation.status !== "completed" ? <div className="artifact-status"><strong>Cálculo {calculation.status === "pending" || calculation.status === "running" ? "en curso…" : calculation.status}</strong>{calculation.error && <span className="no-information">{calculation.error}</span>}</div>
      : <>
        {freshnessLabel && <div className="artifact-update-warning">{freshnessLabel} {recalculateButton}</div>}
        <details className="solver-config-panel"><summary><Settings2 size={14}/> Configuración del solver</summary><div className="solver-config-grid"><label>Discretización (m)<select value={solverConfig.discretization_m} onChange={(event) => setSolverConfig((current) => ({ ...current, discretization_m: event.target.value }))}>{[0.25, 0.5, 1, 2, 5].map((value) => <option value={value} key={value}>{value}</option>)}</select></label><label>Segmentación<select value={solverConfig.segmentation} onChange={(event) => setSolverConfig((current) => ({ ...current, segmentation: event.target.value }))}><option value="graded">Graduada en nodos críticos</option><option value="uniform">Uniforme</option></select></label><label>Raster de superficie<select value={solverConfig.surface_spacing_m} onChange={(event) => setSolverConfig((current) => ({ ...current, surface_spacing_m: event.target.value }))}>{[0.25, 0.5, 1].map((value) => <option value={value} key={value}>{value} m</option>)}</select></label><label title="Margen alrededor de la malla donde se busca la tensión de contacto; 0 = dentro del perímetro (IEEE 80)">Alcance de contacto<select value={solverConfig.touch_reach_m} onChange={(event) => setSolverConfig((current) => ({ ...current, touch_reach_m: event.target.value }))}>{[0, 0.5, 1, 2].map((value) => <option value={value} key={value}>{value === 0 ? "Perímetro de la malla" : `${value} m fuera de la malla`}</option>)}</select></label><label className="solver-config-check"><input type="checkbox" checked={solverConfig.estimate_uncertainty} onChange={(event) => setSolverConfig((current) => ({ ...current, estimate_uncertainty: event.target.checked }))}/> Estimar incertidumbre numérica</label><label className="solver-config-justification">Justificación registrada<textarea value={solverConfig.justification} maxLength={500} onChange={(event) => setSolverConfig((current) => ({ ...current, justification: event.target.value }))}/></label><small>Capas del modelo: {artifact?.snapshot?.soil_layers?.length || "pendientes en Entradas"}. La cantidad de capas se define en el modelador de suelo y se valida antes de calcular.</small></div></details>
        <div className={`agent-verdict ${verdict}`}>{verdictLabels[verdict]}</div>
        <div className="result-interpretation"><div className="result-interpretation-title"><strong>Interpretación</strong><span>{interpretation.title}</span></div><div><small>Restricción dominante</small><strong>{interpretation.constraint}</strong></div><div><small>Por qué</small><span>{interpretation.explanation}</span></div><div className="result-interpretation-actions"><small>Siguiente acción</small>{verdict === "no_cumple" && conversation && calculation.artifact_version === artifact?.version && freshness !== "desactualizado" && <button className="button primary" data-testid="optimize-until-compliant" disabled={optimizing || recalculating} onClick={optimizeUntilCompliant}><Sparkles size={14}/> {optimizing ? "Iniciando optimización…" : "Optimizar hasta cumplir"}</button>}{interpretation.actions.map((action) => <button className="button" key={action} onClick={() => onSuggestion?.(action)}>{action}</button>)}</div></div>
        <div className="artifact-status"><strong>Malla</strong><span>R = {Number(result.grid_resistance_ohm).toLocaleString("es-CO", { maximumFractionDigits: 3 })} Ω · GPR = {value(result.gpr_v)} V · I = {value(result.injected_current_a)} A</span></div>
        {safety.map((standard) => <div className="artifact-status" key={standard.standard}><strong>{standard.standard}</strong>{(standard.criteria || []).map((c) => <span key={c.criterion} className={c.status === "cumple" ? "" : "agent-fails"}>{c.criterion === "touch" ? "Contacto" : "Paso"}: {value(c.actual_v)} V / {value(c.tolerable_v)} V tolerable ({(100 * c.margin_rel).toLocaleString("es-CO", { maximumFractionDigits: 1 })} %)</span>)}{standard.reason && <span className="no-information">{standard.reason}</span>}</div>)}
        {result.conductor_thermal && <div className="artifact-status"><strong>Conductor (térmico)</strong><span className={result.conductor_thermal.status === "cumple" ? "" : "agent-fails"}>Sección {value(result.conductor_thermal.selected_section_mm2)} mm² · mínima {value(result.conductor_thermal.minimum_section_mm2)} mm²</span></div>}
        {result.surface_potential && <div className="agent-grid-preview"><SurfacePotentialMap field={result.surface_potential}/></div>}
        {result.surface_potential && <p className="no-information">Contacto evaluado sobre la malla ({value(result.surface_potential.grid_width_m)} × {value(result.surface_potential.grid_height_m)} m{Number(calculation.parameters?.touch_reach_m) > 0 ? `, ${calculation.parameters.touch_reach_m} m fuera del perímetro` : ", dentro del perímetro"}); paso en todo el terreno, salvo dentro de construcciones.</p>}
        {result.surface_potential && geometry && <button className="button primary agent-3d-button" onClick={() => setShow3d(true)}><Rotate3d size={15}/> Ver en 3D</button>}
        {show3d && <Suspense fallback={<div className="surface3d-backdrop"><div className="surface3d-loading">Cargando vista 3D…</div></div>}>
          <Surface3D calculation={calculation} onClose={() => setShow3d(false)} plan={{ ...gridPlan(geometry), length: geometry.length_m, width: geometry.width_m, burialDepth: geometry.burial_depth_m || 0.5, rodLength: geometry.rod_length_m || 2.4 }}/>
        </Suspense>}
        {result.model_warnings?.length > 0 && <div className="artifact-status"><strong>Advertencias del modelo</strong>{result.model_warnings.map((w) => <span key={w} className="no-information">{w}</span>)}</div>}
        <p className="no-information agent-results-note">Verificación de prefactibilidad; requiere revisión de un ingeniero competente.</p>
      </>}
  </aside>;
}

export { AgentArtifactPanel, AgentResultsPanel, ArtifactGrid, ArtifactUpdateCard };
