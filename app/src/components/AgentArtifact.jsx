import React, { Suspense, lazy, useEffect, useState } from "react";
import { Activity, Box, ChevronRight, ExternalLink, Eye, FileText, PencilRuler, RefreshCw, Rotate3d, Settings2, Sparkles, Undo2, X } from "lucide-react";
import { SurfacePotentialMap } from "./GroundingCalculations.jsx";
import TopologyPreview from "./TopologyPreview.jsx";
import { criterionLabel, evaluateResult, formatNumber, verdictLabels } from "../resultInterpretation.js";
import { ACTIVE_RUN, RUN_STATUS_LABELS, apiRequest, formatMoney, formatPercent, formatShare, minimumMargin, restoreAndRecalculate } from "../optimization.js";
import { fieldLabels, fieldValueLabel } from "../labels.js";
import { EmptyState } from "./EmptyState.jsx";
import { CalculationOptionsDialog, ImproveDesign, Metric, MissingInputs, ModelWarnings, VerdictCallout, unconfirmedInputs } from "./ResultBlocks.jsx";
import { Icon3D, IconOptimizer, IconOptions, IconOverview, IconPlan, IconResult } from "../icons.jsx";
import TopologyOptimizerPanel from "./TopologyOptimizerPanel.jsx";

// «1 por unidad» rates (Matherra without prices): the costs measure material, not money.
const costLabel = (amount, comparison) => (comparison?.relative_costs
  ? (Number.isFinite(amount) ? `${formatNumber(amount, 0)} u. relativas` : "—") : formatMoney(amount, comparison?.currency));

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

// The part of the plan to draw: the whole site, or only the grid and its rods with a margin ("detail").
function planWindow(geometry, view) {
  const site = { x0: 0, y0: 0, x1: geometry.length_m, y1: geometry.width_m };
  if (view !== "detail") return site;
  const { lines, rods } = gridPlan(geometry);
  const xs = [...lines.flatMap(([a, b]) => [a[0], b[0]]), ...rods.map((rod) => rod[0])];
  const ys = [...lines.flatMap(([a, b]) => [a[1], b[1]]), ...rods.map((rod) => rod[1])];
  if (!xs.length) return site;
  const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const pad = Math.max(0.6, 0.12 * Math.max(maxX - minX, maxY - minY));
  return { x0: Math.max(site.x0, minX - pad), x1: Math.min(site.x1, maxX + pad), y0: Math.max(site.y0, minY - pad), y1: Math.min(site.y1, maxY + pad), mesh: { x: maxX - minX, y: maxY - minY } };
}

// Plan drawing. A site taller than wide is turned 90° so it always reads in landscape; «detail» zooms to the grid.
function ArtifactGrid({ geometry, view = "general" }) {
  const win = planWindow(geometry, view);
  const spanX = win.x1 - win.x0, spanY = win.y1 - win.y0;
  const rotated = spanY > spanX * 1.1;
  const across = rotated ? spanY : spanX, down = rotated ? spanX : spanY;
  const W = 490, H = 330, scale = Math.min(400 / across, 250 / down);
  const w = across * scale, h = down * scale, x0 = (W - w) / 2, y0 = (H - 10 - h) / 2 + 4;
  // Plan y grows upward from the origin corner. Turned, plan y runs left to right and plan x top to bottom.
  const px = (x, y) => rotated ? [x0 + (y - win.y0) * scale, y0 + (x - win.x0) * scale] : [x0 + (x - win.x0) * scale, y0 + h - (y - win.y0) * scale];
  const box = (xa, ya, xb, yb) => { const [ax, ay] = px(xa, ya), [bx, by] = px(xb, yb); return { x: Math.min(ax, bx), y: Math.min(ay, by), w: Math.abs(bx - ax), h: Math.abs(by - ay) }; };
  const { lines, rods } = gridPlan(geometry);
  const structures = geometry.structures || [];
  const areas = geometry.areas || [];
  const site = box(0, 0, geometry.length_m, geometry.width_m);
  const rodNote = geometry.rods?.length ? "posiciones del diseño" : "repartidas en el perímetro";
  const clipId = `plan-clip-${view}-${Math.round(spanX * 100)}-${Math.round(spanY * 100)}`;
  return <svg className="agent-grid-svg" viewBox={`0 0 ${W} 350`} role="img" aria-label={`${view === "detail" ? "Detalle de la malla" : "Plano general"}: terreno de ${geometry.length_m} por ${geometry.width_m} m, ${areas.length} zonas, ${gridDescription(geometry)}, ${rods.length} varillas y ${structures.length} elementos constructivos${rotated ? "; girado 90° para leerse en horizontal" : ""}`}>
    <defs>
      <pattern id="artifact-grid-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="6" stroke="#9aa0a3" strokeWidth="1.2"/></pattern>
      <clipPath id={clipId}><rect x={x0} y={y0} width={w} height={h}/></clipPath>
    </defs>
    <g clipPath={`url(#${clipId})`}>
      <rect x={site.x} y={site.y} width={site.w} height={site.h} fill="#fbfcfb" stroke="#b7c8c0" strokeDasharray="4 3"/>
      {areas.map((area, i) => { const b = box(area.x_min, area.y_min, area.x_max, area.y_max), open = area.type === "intervenible"; return <g key={`area-${i}`}><rect x={b.x} y={b.y} width={b.w} height={b.h} fill={open ? "rgba(63,154,98,.16)" : "#e3e5e6"} stroke={open ? "#3f9a62" : "#7d8487"} strokeWidth="1"/>{!open && <rect x={b.x} y={b.y} width={b.w} height={b.h} fill="url(#artifact-grid-hatch)"/>}<text x={b.x + b.w / 2} y={b.y + b.h / 2 + 3} textAnchor="middle" fill={open ? "#2f5f43" : "#5f6d66"} fontSize="8.5" transform={b.w < 50 && b.h > b.w ? `rotate(-90 ${b.x + b.w / 2} ${b.y + b.h / 2})` : undefined}>{area.label || (open ? "Área intervenible" : "No intervenible")}</text></g>; })}
      {structures.map((item, i) => { const b = box(item.x - item.width / 2, item.y - item.height / 2, item.x + item.width / 2, item.y + item.height / 2); return <g key={`structure-${i}`}><rect x={b.x} y={b.y} width={b.w} height={b.h} rx="2" fill="#e3e5e6" stroke="#7d8487" strokeWidth="1.2"/><rect x={b.x} y={b.y} width={b.w} height={b.h} rx="2" fill="url(#artifact-grid-hatch)"/><text x={b.x + b.w / 2} y={b.y + b.h / 2 - 2} textAnchor="middle" fill="#4f5a55" fontSize="9" fontWeight="600">{item.label || "Elemento constructivo"}</text><text x={b.x + b.w / 2} y={b.y + b.h / 2 + 9} textAnchor="middle" fill="#5f6d66" fontSize="8">No intervenible</text></g>; })}
      {lines.map(([a, b], i) => { const [ax, ay] = px(...a), [bx, by] = px(...b); return <line key={i} x1={ax} y1={ay} x2={bx} y2={by} stroke="#2563c9" strokeWidth={view === "detail" ? 2.2 : 1.6} strokeLinecap="round"/>; })}
      {rods.map(([x, y], i) => { const [cx, cy] = px(x, y); return <circle key={i} cx={cx} cy={cy} r={view === "detail" ? 5.5 : 4.5} fill="#c98a2b" stroke="#fff" strokeWidth="1.5"/>; })}
    </g>
    <text x={x0 + w / 2} y={y0 + h + 18} textAnchor="middle" fill="#5f6f68" fontSize="11">{win.mesh ? `Malla: ${formatValue(Number((rotated ? win.mesh.y : win.mesh.x).toFixed(2)))} m` : `${formatValue(Number(across.toFixed(2)))} m`} ({rotated ? "Y" : "X"})</text>
    <text x={x0 - 12} y={y0 + h / 2} textAnchor="middle" fill="#5f6f68" fontSize="11" transform={`rotate(-90 ${x0 - 12} ${y0 + h / 2})`}>{win.mesh ? `Malla: ${formatValue(Number((rotated ? win.mesh.x : win.mesh.y).toFixed(2)))} m` : `${formatValue(Number(down.toFixed(2)))} m`} ({rotated ? "X" : "Y"})</text>
    <text x="245" y="344" textAnchor="middle" fill="#93a09a" fontSize="9">{gridDescription(geometry)} · {rods.length} varillas ({rodNote}){rotated ? " · girado 90°" : ""}</text>
  </svg>;
}

// General plan and grid detail, side by side when there is room, or as two tabs.
function PlanViews({ geometry, initial = "general" }) {
  const [view, setView] = useState(initial);
  const general = planWindow(geometry, "general"), detail = planWindow(geometry, "detail");
  // The detail only adds something when the grid covers a small part of the site.
  const worthDetail = (detail.x1 - detail.x0) * (detail.y1 - detail.y0) < 0.7 * (general.x1 - general.x0) * (general.y1 - general.y0);
  return <div className="plan-views">
    {worthDetail && <div className="app-segmented plan-views-switch" role="group" aria-label="Vista del plano">
      <button type="button" className={view === "general" ? "active" : ""} aria-pressed={view === "general"} onClick={() => setView("general")}>Plano general</button>
      <button type="button" className={view === "detail" ? "active" : ""} aria-pressed={view === "detail"} onClick={() => setView("detail")}>Detalle de la malla</button>
    </div>}
    <ArtifactGrid geometry={geometry} view={worthDetail ? view : "general"}/>
  </div>;
}

function buildAgentIterationRows(events = []) {
  const rows = new Map();
  let current = null;
  for (const event of [...events].sort((a, b) => a.seq - b.seq)) {
    const iteration = event.payload?.iteration;
    if (Number.isInteger(iteration)) {
      current = iteration;
      const row = rows.get(iteration) || { iteration, status: "Ajustando la malla" };
      row.status = event.type === "subagent.started" ? "Proponiendo un ajuste" : event.title;
      row.maxIterations = event.payload?.max_iterations;
      rows.set(iteration, row);
      continue;
    }
    if (current == null) continue;
    const row = rows.get(current);
    if (event.type === "artifact.version_created") row.artifactVersion = event.payload?.version;
    if (event.type === "calculation.queued") {
      row.calculationId = event.payload?.calculation_id;
      row.status = "Cálculo de seguridad en curso";
    }
    if (event.type === "calculation.completed") {
      row.calculationId = event.payload?.calculation_id || row.calculationId;
      row.status = "Cálculo de seguridad terminado";
    }
    if (event.type === "calculation.failed") {
      row.calculationId = event.payload?.calculation_id || row.calculationId;
      row.status = "Falló el cálculo de seguridad";
    }
    if (event.type === "subagent.completed" && !String(event.title || "").includes("encolada")) row.status = event.title;
    rows.set(current, row);
  }
  return [...rows.values()].sort((a, b) => a.iteration - b.iteration);
}

const designLoopReasons = {
  goal_met: "Se alcanzó cumplimiento.",
  no_improvement: "La última iteración no mejoró el mejor margen.",
  iteration_limit: "Se agotó el límite de iteraciones sin cumplir.",
  no_valid_candidate: "El diseñador no produjo una geometría válida; no se guardó una versión.",
  save_failed: "La propuesta no pasó la validación al guardar; no se creó una versión.",
  calculation_failed: "La geometría se guardó, pero no se pudo iniciar su cálculo.",
  not_evaluable: "El cálculo no permitió evaluar el cumplimiento; revisa los datos de entrada.",
};

// One section for the agent's run: its live status, every iteration it versioned, and how it ended.
function AgentImprovements({ project, token, artifact, events, autonomousRun, progress, result, onRestored }) {
  const [details, setDetails] = useState({});
  const [restoring, setRestoring] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const artifactId = artifact?.artifact_id;
  const rows = buildAgentIterationRows(events);
  const signature = rows.map((row) => `${row.iteration}-${row.artifactVersion || ""}-${row.calculationId || ""}-${row.status}`).join("|");
  useEffect(() => {
    if (!artifactId || !rows.some((row) => row.artifactVersion)) { setDetails({}); return undefined; }
    let live = true;
    const root = `/api/v1/projects/${project.id}/artefactos-diseno-tierras/${artifactId}`;
    (async () => {
      try {
        const versions = await apiRequest(token, `${root}/versions`);
        const lookup = new Map((versions || []).map((version) => [version.version, version]));
        const loaded = await Promise.all(rows.filter((row) => row.artifactVersion).map(async (row) => {
          const calculation = row.calculationId ? await apiRequest(token, `${root}/calculos-potencial/${row.calculationId}`).catch(() => null) : null;
          return [row.iteration, { version: lookup.get(row.artifactVersion), calculation }];
        }));
        if (live) setDetails(Object.fromEntries(loaded));
      } catch (_) { /* El historial de versiones puede cargar en el siguiente ciclo de eventos. */ }
    })();
    return () => { live = false; };
  }, [artifactId, project.id, token, signature]);
  async function restore(key, version, calculationId) {
    if (!calculationId || restoring != null) return;
    setRestoring(key); setError(""); setNotice("");
    try {
      const restored = await restoreAndRecalculate({ token, projectId: project.id, artifactId, version, calculationId });
      setNotice(`Se recuperó la versión ${version} como versión ${restored.restored.version} y se inició un nuevo cálculo.`);
      onRestored?.(restored);
    } catch (failure) { setError(failure.message); }
    finally { setRestoring(null); }
  }
  if (!rows.length && !result && !autonomousRun && !progress) return null;
  const best = result?.best_candidate;
  // The best design can be recovered only if something versioned the plan after it and the run did not end compliant.
  const canRestoreBest = best?.artifact_version && best?.calculation_id && artifact && artifact.version > best.artifact_version && result.reason !== "goal_met";
  const bestIsIteration = rows.some((row) => row.artifactVersion === best?.artifact_version);
  const restoreButton = (key, version, calculationId, isBest) => <button className="button" type="button"
    data-testid={isBest && canRestoreBest ? "restore-best-design-candidate" : undefined}
    disabled={!calculationId || restoring != null || version === artifact?.version} onClick={() => restore(key, version, calculationId)}>
    {restoring === key ? "Recuperando y recalculando…" : version === artifact?.version ? "Versión actual" : calculationId ? "Recuperar y recalcular esta versión" : "Sin cálculo para recuperar"}
  </button>;
  return <section className="agent-iteration-timeline" aria-label="Mejoras del agente">
    <div className="optimization-review-heading"><strong>Mejoras del agente</strong><span>{result ? `${result.iterations_used}/${result.max_iterations} iteraciones` : "En curso"}</span></div>
    {!result && <p className="design-loop-progress" role="status" aria-live="polite">{progress?.title
      || (autonomousRun?.status === "waiting_calculation" ? "Esperando el cálculo de seguridad para decidir el siguiente ajuste." : "El agente está revisando el diseño.")}
      {Number.isInteger(progress?.payload?.iteration) && ` Iteración ${progress.payload.iteration}/${progress.payload.max_iterations}; cada cambio se guarda como versión y se vuelve a calcular.`}</p>}
    {result && <div className="design-loop-summary" data-testid="design-loop-result">
      <span>{designLoopReasons[result.reason] || `Terminó con resultado «${result.reason}».`} Iteraciones: {result.iterations_used}/{result.max_iterations}.</span>
      {best && <span>Mejor candidato: versión {best.artifact_version}{Number.isFinite(best.margin_percent) ? ` · margen mínimo ${formatPercent(best.margin_percent)}` : ""}.</span>}
      {canRestoreBest && !bestIsIteration && restoreButton("best", best.artifact_version, best.calculation_id, true)}
    </div>}
    {rows.map((row) => {
      const { version, calculation } = details[row.iteration] || {};
      const verdict = calculation?.status === "completed" ? evaluateResult(calculation.result).verdict : null;
      const margin = minimumMargin(calculation?.result);
      const isBest = best?.artifact_version != null && row.artifactVersion === best.artifact_version;
      return <article className={`agent-iteration-card${isBest ? " best" : ""}`} key={row.iteration}>
        <div className="agent-iteration-card-heading"><strong>Iteración {row.iteration}{row.maxIterations ? ` de ${row.maxIterations}` : ""}{row.artifactVersion ? ` · versión ${row.artifactVersion}` : ""}</strong><span>{isBest ? "Mejor resultado" : row.status}</span></div>
        {version?.snapshot?.geometry && <ArtifactGrid geometry={version.snapshot.geometry}/>}
        {verdict && <div className="agent-iteration-metrics"><strong className={`agent-iteration-verdict ${verdict}`}>{verdictLabels[verdict]}</strong>{margin != null && <span>Margen mínimo: {formatPercent(margin)}</span>}{Number.isFinite(calculation.result?.grid_resistance_ohm) && <span>R = {formatNumber(calculation.result.grid_resistance_ohm, 3)} Ω</span>}</div>}
        {verdict && <div className="agent-iteration-criteria">{(calculation.result?.safety || []).flatMap((standard) => (standard.criteria || []).map((criterion, index) => <span key={`${standard.standard}-${criterion.criterion}-${index}`}>{criterionLabel(criterion.criterion)}: {formatNumber(criterion.actual_v)} / {formatNumber(criterion.tolerable_v)} V tolerables{Number.isFinite(criterion.margin_rel) ? ` · margen ${formatPercent(criterion.margin_rel * 100)}` : ""}</span>))}</div>}
        {calculation?.status === "failed" && <small className="optimizer-context-error">{calculation.error || "El cálculo no se completó."}</small>}
        {row.artifactVersion && restoreButton(row.iteration, row.artifactVersion, calculation?.id, isBest)}
      </article>;
    })}
    {result && !rows.length && <p className="no-information">El agente terminó sin crear iteraciones de geometría.</p>}
    {error && <p className="artifact-update-warning" role="alert">{error}</p>}{notice && <p className="matherra-apply-notice" role="status">{notice}</p>}
  </section>;
}

function baseVerdict(electrical) {
  if (electrical?.status === "VIOLATED") return `no cumple en el nivel más fino${Number.isFinite(electrical.ratio) ? ` (utilización ${formatShare(electrical.ratio)})` : ""}`;
  if (electrical?.feasible === true) return `sin violaciones en el nivel más fino${Number.isFinite(electrical.ratio) ? ` (utilización ${formatShare(electrical.ratio)})` : ""}`;
  return "cumplimiento sin evaluar";
}

// The only place where Matherra's alternatives are compared, previewed and applied (the editor sets up and launches).
function MatherraRunReview({ project, token, artifact, refreshKey, onApplied }) {
  const [runs, setRuns] = useState([]);
  const [runId, setRunId] = useState("");
  const [detail, setDetail] = useState(null);
  const [comparison, setComparison] = useState(null);
  const [error, setError] = useState("");
  const [previewId, setPreviewId] = useState(null);
  const [applyingId, setApplyingId] = useState(null);
  const [notice, setNotice] = useState("");
  const [reload, setReload] = useState(0);
  const root = `/api/v1/projects/${encodeURIComponent(project.id)}/optimizer-runs`;
  useEffect(() => {
    let live = true;
    apiRequest(token, `${root}?limit=50`, { fallback: "No se pudo cargar el historial de Matherra." }).then((body) => {
      if (!live) return;
      const rows = (body.runs || []).filter((row) => row.request_snapshot?.algorithm === "topology_alns");
      setRuns(rows);
      setRunId((current) => rows.some((row) => row.id === current) ? current : rows[0]?.id || "");
    }).catch((failure) => { if (live) setError(failure.message); });
    return () => { live = false; };
  }, [root, token, refreshKey]);
  useEffect(() => {
    if (!runId) { setDetail(null); setComparison(null); return undefined; }
    let live = true;
    let timer;
    const load = async () => {
      try {
        const body = await apiRequest(token, `${root}/${encodeURIComponent(runId)}`, { fallback: "No se pudo consultar la búsqueda de Matherra." });
        if (!live) return;
        setDetail(body);
        setRuns((rows) => rows.map((row) => (row.id === body.run.id ? { ...row, status: body.run.status } : row)));
        const compared = body.run.status === "completed" ? await apiRequest(token, `${root}/${encodeURIComponent(runId)}/comparison`, { fallback: "No se pudo comparar las alternativas." }) : null;
        if (live) {
          setComparison(compared);
          const best = compared?.alternatives?.find((row) => row.recommended) || compared?.alternatives?.[0];
          if (best) setPreviewId(best.alternative_id);
        }
        if (ACTIVE_RUN.has(body.run.status)) timer = setTimeout(load, 1800);
      } catch (failure) { if (live) setError(failure.message); }
    };
    load();
    return () => { live = false; clearTimeout(timer); };
  }, [runId, root, token, reload]);
  async function apply(id) {
    if (!detail?.run?.id || applyingId) return;
    setApplyingId(id); setError(""); setNotice("");
    try {
      const body = await apiRequest(token, `${root}/${encodeURIComponent(detail.run.id)}/alternatives/${encodeURIComponent(id)}/apply`, { method: "POST", fallback: "No se pudo aplicar la alternativa." });
      const revalidation = body.revalidation?.status;
      setNotice(`Se creó la versión ${body.version} con la alternativa. ${revalidation === "pending" ? "Su cálculo completo con malla fina ya está en curso; el veredicto será el de ese cálculo, no el de la búsqueda."
        : revalidation === "blocked" ? `No se pudo calcular aún: ${body.revalidation.detail?.message || "faltan datos del diseño"}.` : "Calcula la versión para verificarla."}`);
      onApplied?.(body);
      setReload((key) => key + 1);
    } catch (failure) { setError(failure.message); }
    finally { setApplyingId(null); }
  }
  if (!runs.length && !error) return null;
  const run = detail?.run;
  const progress = run?.result_summary?.progress;
  const base = run?.request_snapshot?.initial_geometry || (run?.artifact_id === artifact?.artifact_id ? artifact?.snapshot?.geometry : null);
  const geometries = new Map((detail?.alternatives || []).map((alt) => [alt.id, alt.evaluation_snapshot?.geometry || alt.candidate_snapshot?.geometry]));
  const saving = comparison?.saving_vs_base;
  const nearMiss = run?.result_summary?.near_misses?.[0];
  const nearMissCriteria = nearMiss?.metrics?.criterion_ratios || [];
  const baseCriteria = comparison?.base?.electrical?.metrics?.criterion_ratios || [];
  return <section className="matherra-run-review" aria-label="Alternativas de Matherra">
    <div className="optimization-review-heading"><strong>Matherra</strong>{runs.length > 1
      ? <select aria-label="Historial de Matherra" value={runId} onChange={(event) => { setRunId(event.target.value); setDetail(null); setComparison(null); setPreviewId(null); setError(""); setNotice(""); }}>
          {runs.map((row) => <option key={row.id} value={row.id}>{new Date(row.created_at * 1000).toLocaleString("es-CO")} · v{row.artifact_version} · {RUN_STATUS_LABELS[row.status] || row.status}</option>)}
        </select>
      : run && <span>{new Date(run.created_at * 1000).toLocaleString("es-CO")}</span>}</div>
    {error && <p className="artifact-update-warning" role="alert">{error}</p>}
    {!run && !error && <p className="no-information">Cargando la búsqueda de Matherra…</p>}
    {run && <div className="matherra-run-status" role="status" aria-live="polite">
      <strong>{RUN_STATUS_LABELS[run.status] || run.status} · desde la versión {run.artifact_version}</strong>
      {ACTIVE_RUN.has(run.status) && <><span>{progress?.verdicts ?? 0} de {progress?.budget || run.request_snapshot?.request?.max_solver_calls || "—"} evaluaciones eléctricas.</span><progress max={progress?.budget || run.request_snapshot?.request?.max_solver_calls || 1} value={progress?.verdicts || 0}/></>}
      {run.error && <span className="optimizer-context-error">{run.error}</span>}
      {comparison && <span>{run.result_summary?.solver_calls_total ?? run.result_summary?.solver_calls ?? "—"} evaluaciones · {comparison.alternatives.length === 1 ? "1 alternativa verificada" : `${comparison.alternatives.length} alternativas verificadas`} en el nivel más fino.</span>}
    </div>}
    {comparison?.relative_costs && <p className="matherra-relative-note" role="note">Costos relativos: usaste precios de 1 por unidad, así que comparan cantidad de material, no dinero.</p>}
    {comparison?.base && <p className="matherra-base-summary">Diseño de partida: {costLabel(comparison.base.cost, comparison)}, {baseVerdict(comparison.base.electrical)}.
      {saving && (saving.kind === "saving" ? ` La recomendada ahorra ${costLabel(saving.amount, comparison)} (${formatShare(saving.fraction, 1)}).`
        : ` La recomendada cuesta ${costLabel(-saving.amount, comparison)} más${saving.base_status === "violates" ? ": es lo que cuesta cumplir" : ""}.`)}</p>}
    {notice && <p className="matherra-apply-notice" role="status">{notice}</p>}
    {comparison && <div className="matherra-candidate-list">
      {comparison.alternatives.length === 0 && base && <article className="matherra-best-design matherra-no-alternative">
        {nearMiss ? <>
          <strong>Diseño más cercano encontrado · todavía no cumple</strong>
          <p>La búsqueda evaluó este candidato en {nearMiss.level || "un nivel fino"}, pero todavía incumple. Se ordena por menor exceso eléctrico y luego por costo ({costLabel(nearMiss.cost, comparison)}). Compáralo con el diseño actual para ver si bajó la tensión de contacto o de paso; no es un diseño aprobado.</p>
          <div className="matherra-near-miss-criteria">{nearMissCriteria.map((criterion) => {
            const original = baseCriteria.find((item) => item.criterion === criterion.criterion && item.standard === criterion.standard);
            const label = criterion.criterion === "touch" ? "Contacto" : criterion.criterion === "step" ? "Paso" : criterion.criterion;
            return <div key={`${criterion.standard}-${criterion.criterion}`}><strong>{label}</strong><span>{original ? `${formatShare(original.ratio, 1)} → ` : ""}{formatShare(criterion.ratio, 1)} de utilización</span><small>{original ? `${formatNumber(original.actual_v, 0)} / ${formatNumber(original.limit_v, 0)} V → ` : ""}{formatNumber(criterion.actual_v, 0)} / {formatNumber(criterion.limit_v, 0)} V tolerables</small></div>;
          })}</div>
          <TopologyPreview base={base} alternative={nearMiss.geometry}/>
        </> : <>
          <strong>Diseño actual</strong><p>Con este presupuesto no se encontró una alternativa que pasara la verificación más fina. Aquí puedes revisar el diseño de partida; no hay un candidato cercano con evaluación fina para comparar.</p><TopologyPreview base={base} alternative={base}/>
        </>}
      </article>}
      {comparison.alternatives.length ? comparison.alternatives.map((candidate) => {
        const geometry = geometries.get(candidate.alternative_id);
        return <article className={`matherra-candidate${candidate.recommended ? " recommended" : ""}`} data-testid="matherra-candidate" key={candidate.alternative_id}>
          <div className="matherra-candidate-heading"><strong>{candidate.recommended ? "Recomendada · " : ""}Alternativa {candidate.rank}</strong>{candidate.pareto && <span>Equilibrio costo–seguridad</span>}</div>
          <div className="matherra-candidate-metrics">
            <span><small>Costo</small><strong>{costLabel(candidate.cost, comparison)}</strong></span>
            <span><small>Utilización</small><strong>{formatShare(candidate.utilization_ratio, 1)}</strong></span>
            <span><small>Margen mínimo</small><strong>{formatShare(candidate.margin, 1)}</strong></span>
            <span><small>Contacto / paso</small><strong>{Number.isFinite(candidate.Vt_v) && Number.isFinite(candidate.Vs_v) ? `${formatNumber(candidate.Vt_v, 0)} / ${formatNumber(candidate.Vs_v, 0)} V` : "—"}</strong></span>
            <span><small>Rg</small><strong>{Number.isFinite(candidate.Rg_ohm) ? `${formatNumber(candidate.Rg_ohm, 2)} Ω` : "—"}</strong></span>
            <span><small>Conductor · varillas · conexiones</small><strong>{Number.isFinite(candidate.complexity?.conductor_length_m) ? `${formatNumber(candidate.complexity.conductor_length_m, 0)} m · ${candidate.complexity.rods} · ${candidate.complexity.connections ?? "—"}` : "—"}</strong></span>
          </div>
          <small className="matherra-candidate-validation">Verificada en {candidate.validated_at_level || "nivel no informado"} · búsqueda muestreada, no certificada.{candidate.applied_version != null && (candidate.applied_is_latest ? ` Es la versión ${candidate.applied_version} del plano.` : ` Ya se aplicó como versión ${candidate.applied_version}.`)}</small>
          <div className="matherra-candidate-actions">
            <button className="button" type="button" aria-expanded={previewId === candidate.alternative_id} disabled={!geometry || !base} onClick={() => setPreviewId(previewId === candidate.alternative_id ? null : candidate.alternative_id)}>{previewId === candidate.alternative_id ? "Ocultar vista previa" : "Vista previa"}</button>
            <button className="button primary" type="button" disabled={!geometry || applyingId != null || candidate.applied_is_latest} onClick={() => apply(candidate.alternative_id)}>{applyingId === candidate.alternative_id ? "Aplicando…" : candidate.applied_is_latest ? "Versión actual" : "Aplicar como nueva versión"}</button>
          </div>
          {previewId === candidate.alternative_id && geometry && base && <div className="matherra-best-design"><strong>{candidate.recommended ? "Mejor alternativa encontrada · comparación gráfica con el diseño actual" : `Vista gráfica · alternativa ${candidate.rank}`}</strong><TopologyPreview base={base} alternative={geometry}/></div>}
        </article>;
      }) : !base && <p className="no-information">Matherra terminó, pero ninguna alternativa pasó la verificación más fina con este presupuesto. Prueba con un presupuesto mayor o revisa las áreas intervenibles.</p>}
      {comparison.alternatives.some((row) => row.pareto) && <small className="matherra-candidate-validation">«Equilibrio costo–seguridad»: ninguna otra alternativa es a la vez más barata y más segura.</small>}
      <details className="matherra-review-notes"><summary>Cómo interpretar este resultado</summary><ul>{comparison.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></details>
    </div>}
  </section>;
}

function AgentArtifactPanel({ project, conversation, token, refreshKey, onOpenGraph, onOpenPlan, onOpenResults }) {
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
      } catch (e) { if (live) setError("No se pudo cargar el diseño."); }
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
  const verdict = artifact?.calculation_verdict && artifact.calculation_verdict !== "no_evaluado" ? artifact.calculation_verdict : null;
  const verdictText = { cumple: "Las tensiones de contacto y paso y la sección del conductor están dentro de los límites.", no_cumple: "Al menos una tensión supera lo que una persona tolera durante una falla.", no_evaluable: "Faltan datos para evaluar el cumplimiento." };
  return <aside className="panel artifact-side-panel"><div className="panel-heading"><div><IconOverview size={17}/><h2>Diseño de puesta a tierra</h2></div><div className="artifact-results-heading-actions">{artifact && <span className="muted-label">Versión {artifact.version}</span>}{onOpenPlan && snapshot?.geometry && <button type="button" className="button primary" onClick={onOpenPlan}><IconPlan size={14}/> Editar plano</button>}</div></div>
    {snapshot ? <>
      {verdict && <div className={`summary-verdict ${verdict}`} data-testid="artifact-verdict"><span className="summary-verdict-dot"/><div><strong>{verdictLabels[verdict] || verdict}{artifact.calculation_status === "desactualizado" ? " · del cálculo anterior" : ""}</strong><span>{verdictText[verdict]}</span></div>{onOpenResults && <button type="button" className="button" onClick={onOpenResults}>Ver resultado <ChevronRight size={13}/></button>}</div>}
      {snapshot.geometry ? <div className="agent-grid-preview"><PlanViews geometry={snapshot.geometry}/>{planWarnings.map((warning, i) => <p key={i} className="artifact-update-warning">{warning.kind === "disconnected" ? `La malla tiene ${warning.parts} partes separadas: el cálculo las trata como un solo conductor, lo que solo es cierto si un conductor de unión las conecta.` : warning.message}</p>)}</div> : <EmptyState compact art="mesh" title="Este diseño aún no tiene malla" description="Dibújala en el editor de plano o pídesela al agente, por ejemplo «malla de 40 × 30 m con retícula de 5 m»." action={onOpenPlan && <button type="button" className="button primary" onClick={onOpenPlan}><IconPlan size={14}/> Dibujar plano</button>}/>}
      <div className="artifact-status"><strong>{artifact.name}</strong><span>{origin} · {new Date(artifact.created_at * 1000).toLocaleString("es-CO")}</span></div>
      {artifact.draft_watermark && <div className="artifact-status agent-fails"><strong>{artifact.draft_watermark}</strong><span>Confirma los supuestos antes de presentar el estudio como final.</span></div>}
      {artifact.calculation_status && <div className={`artifact-status${artifact.calculation_status === "desactualizado" ? " agent-fails" : ""}`}><strong>Vigencia</strong><span>{calculationFreshnessLabels[artifact.calculation_status] || artifact.calculation_status}{artifact.calculation_version && artifact.calculation_status === "desactualizado" ? ` · cálculo de versión ${artifact.calculation_version}` : ""}</span></div>}
      {snapshot.geometry && <div className="artifact-status"><strong>Malla <ProvenanceChip provenance={provenance} path="geometry" onOpen={openEvidence}/></strong><span>{formatValue(snapshot.geometry.length_m)} × {formatValue(snapshot.geometry.width_m)} m · {gridDescription(snapshot.geometry)} · profundidad {formatValue(snapshot.geometry.burial_depth_m)} m · {snapshot.geometry.rods_count} varillas de {formatValue(snapshot.geometry.rod_length_m)} m</span></div>}
      <div className="artifact-status"><strong>Suelo <ProvenanceChip provenance={provenance} path="soil_layers" onOpen={openEvidence}/></strong>{snapshot.soil_layers?.length ? <div className="artifact-soil-layers">{snapshot.soil_layers.map((layer, index) => <span key={index}>C{index + 1}: {formatValue(layer.resistivity_ohm_m)} Ω·m · {layer.depth_m ? `${formatValue(layer.depth_m)} m` : "semiespacio"}{layer.material ? ` · ${layer.material}` : ""}</span>)}{soilNote && <small>{soilNote}</small>}</div> : <span className="no-information">Pendiente: resistividad del suelo. Puedes pegar un sondeo Wenner o Schlumberger en el chat o subir un CSV/XLSX.</span>}</div>
      <div className="artifact-status"><strong>Falla <ProvenanceChip provenance={provenance} path="fault" onOpen={openEvidence}/></strong>{snapshot.fault?.current_a && snapshot.fault?.clearing_time_s ? <span>{formatValue(snapshot.fault.current_a)} A · {formatValue(snapshot.fault.clearing_time_s)} s · capa superficial {formatValue(snapshot.fault.surface_resistivity_ohm_m)} Ω·m, {formatValue(snapshot.fault.surface_thickness_m)} m</span> : <span className="no-information">Pendiente: {[!snapshot.fault?.current_a && "corriente de falla", !snapshot.fault?.clearing_time_s && "tiempo de despeje"].filter(Boolean).join(", ")}. Se necesitan para el cálculo de seguridad.</span>}</div>
      {snapshot.conductor && <div className="artifact-status"><strong>Conductor <ProvenanceChip provenance={provenance} path="conductor" onOpen={openEvidence}/></strong><span>{fieldValueLabel("conductor.material_id", snapshot.conductor.material_name || snapshot.conductor.material_id)} · {formatValue(snapshot.conductor.cross_section_mm2)} mm² · unión {fieldValueLabel("conductor.joint_type", snapshot.conductor.joint_type)}</span></div>}
      {evidenceSource && <ArtifactEvidencePanel project={project} token={token} source={evidenceSource} onClose={() => setEvidenceSource(null)} onOpenGraph={onOpenGraph}/>}
    </> : <EmptyState art="agent" title={error ? "No se pudo cargar el diseño" : "Aún no hay un diseño de puesta a tierra"} description={error || "Cuéntale al agente qué subestación quieres diseñar, sube planos y estudios en Fuentes o dibuja la malla tú mismo."} action={onOpenPlan && <button type="button" className="button primary" onClick={onOpenPlan}><IconPlan size={14}/> Dibujar plano</button>} testId="summary-empty"/>}
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
    <div className="artifact-update-head"><PencilRuler size={15}/><strong>{created ? "Se creó el diseño" : "Se editó el diseño"}</strong><span>{update.name} · versión {update.version}</span></div>
    <p>{update.summary}</p>
    <div className="artifact-update-changes">{update.changes.slice(0, 8).map((change) => <div key={change.path}><span>{fieldLabels[change.path] || change.path}</span><small>{change.confirmed ? <><b>{formatValue(fieldValueLabel(change.path, change.after))}</b> · confirmado</> : <>{created ? "" : `${formatValue(fieldValueLabel(change.path, change.before))} → `}<b>{formatValue(fieldValueLabel(change.path, change.after))}</b></>}</small></div>)}{update.changes.length > 8 && <div><span>+{update.changes.length - 8} cambios más</span></div>}</div>
    {!created && stale && <p className="artifact-update-warning">El resultado quedó desactualizado · recalcula para esta versión.</p>}
    {update.missing_for_calculation?.length > 0 && <p className="artifact-update-warning">Para el cálculo de seguridad faltan: {update.missing_for_calculation.map((path) => fieldLabels[path] || path).join(", ")}.</p>}
    <div className="artifact-update-actions">
      <button className="button" disabled={state === "busy" || state === "undone"} onClick={undo}><Undo2 size={14}/> {state === "undone" ? "Deshecho" : created ? "Deshacer (eliminar)" : `Deshacer (volver a v${update.previous_version})`}</button>
      <button className="button primary" onClick={onView}><Eye size={14}/> Ver diseño</button>
    </div>
    {state === "error" && <p className="artifact-update-warning">No se pudo deshacer el cambio.</p>}
  </article>;
}

// Matherra from Resultado: the same configurator as the plan editor, without leaving the result.
function MatherraDialog({ project, token, artifact, onClose, onShowResults, onOpenPlan }) {
  useEffect(() => {
    const onKey = (event) => { if (event.key === "Escape" && !document.querySelector(".help-card")) onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return <div className="app-dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="app-dialog matherra-dialog" role="dialog" aria-modal="true" aria-labelledby="matherra-dialog-title">
      <header className="app-dialog-header"><div><span className="app-dialog-icon matherra"><IconOptimizer size={18}/></span><div><h2 id="matherra-dialog-title">Optimizar con Matherra</h2><p>Busca trazados más baratos que cumplan, dentro de las áreas intervenibles del plano (versión {artifact.version}). Lo que ya está en el diseño se hereda.</p></div></div><button type="button" className="icon-button" aria-label="Cerrar Matherra" onClick={onClose}><X size={17}/></button></header>
      <div className="app-dialog-body"><TopologyOptimizerPanel projectId={project.id} token={token} artifact={artifact} canRun onShowResults={onShowResults}/></div>
      {onOpenPlan && <footer className="app-dialog-footer"><span className="matherra-dialog-note">Las áreas intervenibles se dibujan en el plano.</span><button type="button" className="button" onClick={onOpenPlan}><IconPlan size={14}/> Abrir en el editor de plano</button></footer>}
    </section>
  </div>;
}

// three.js loads only when the 3D view opens.
const Surface3D = lazy(() => import("./Surface3D.jsx"));


function AgentResultsPanel({ project, conversation, token, refreshKey, onSuggestion, onOpenMatherra, onCandidateApplied, onNavigate, onOpenPlan }) {
  const [artifact, setArtifact] = useState(null);
  const [calculation, setCalculation] = useState(null);
  const [geometry, setGeometry] = useState(null);
  const [freshness, setFreshness] = useState(null);
  const [show3d, setShow3d] = useState(false);
  const [showOptions, setShowOptions] = useState(false);
  const [showMatherra, setShowMatherra] = useState(false);
  const [readiness, setReadiness] = useState({ missing: [], coherence: [] });
  const [blocked, setBlocked] = useState(null);
  const [state, setState] = useState("loading");
  const [recalculating, setRecalculating] = useState(false);
  const [actionError, setActionError] = useState("");
  const [optimizing, setOptimizing] = useState(false);
  const [designLoopResult, setDesignLoopResult] = useState(null);
  const [designLoopProgress, setDesignLoopProgress] = useState(null);
  const [designLoopEvents, setDesignLoopEvents] = useState([]);
  const [autonomousRun, setAutonomousRun] = useState(null);
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
    if (!conversation) return undefined;
    setDesignLoopResult(null);
    setDesignLoopProgress(null);
    setDesignLoopEvents([]);
    setAutonomousRun(null);
    let live = true;
    let timer;
    const poll = async () => {
      try {
        const response = await fetch(`/api/v1/conversations/${conversation.id}/agent-events`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!response.ok) return;
        const data = await response.json();
        if (!live) return;
        if (data.active_run) {
          setAutonomousRun(data.active_run.mode === "autonomo" ? data.active_run : null);
          setDesignLoopResult(null);
          const runEvents = (data.events || []).filter((item) => item.run_id === data.active_run.id);
          const hasIteration = runEvents.some((item) => Number.isInteger(item.payload?.iteration));
          setDesignLoopEvents(hasIteration ? runEvents : []);
          const relevant = [...runEvents].reverse().find((item) =>
            item.run_id === data.active_run.id && (Number.isInteger(item.payload?.iteration)
              || item.title?.includes("Iteración automática")));
          if (relevant) setDesignLoopProgress(relevant);
        }
        const event = [...(data.events || [])].reverse().find((item) => item.payload?.design_loop_result);
        if (event?.payload?.design_loop_result && !data.active_run) {
          setDesignLoopResult(event.payload.design_loop_result);
          setDesignLoopEvents((data.events || []).filter((item) => item.run_id === event.run_id));
          setDesignLoopProgress(null);
          return;
        }
        if (!data.active_run) { setAutonomousRun(null); setDesignLoopProgress(null); setDesignLoopEvents([]); }
        if (data.active_run && live) timer = setTimeout(poll, data.poll_after_ms || 1500);
      } catch (_) { /* A later refresh can recover the terminal run event. */ }
    };
    poll();
    return () => { live = false; clearTimeout(timer); };
  }, [conversation?.id, token, refreshKey]);
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
  // What the backend would reject, known before pressing «Recalcular».
  useEffect(() => {
    if (!artifact) { setReadiness({ missing: [], coherence: [] }); return undefined; }
    let live = true;
    setBlocked(null);
    fetch(`/api/v1/projects/${project.id}/artefactos-diseno-tierras/${artifact.artifact_id}/versions/${artifact.version}/coherencia`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => (r.ok ? r.json() : null)).then((body) => { if (live && body) setReadiness({ missing: body.missing || [], coherence: body.errors || [] }); }).catch(() => {});
    return () => { live = false; };
  }, [project.id, token, artifact?.artifact_id, artifact?.version, refreshKey]);
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
  async function recalculate(config = solverConfig) {
    if (!artifact || recalculating) return;
    if (config.justification.trim().length < 10) { setActionError("Escribe una justificación de al menos 10 caracteres para registrar la configuración."); return; }
    setRecalculating(true); setActionError("");
    try {
      const response = await fetch(`/api/v1/projects/${project.id}/artefactos-diseno-tierras/${artifact.artifact_id}/versions/${artifact.version}/calculos-potencial`, { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ ...config, discretization_m: Number(config.discretization_m), surface_spacing_m: Number(config.surface_spacing_m), touch_reach_m: Number(config.touch_reach_m), safety_standards: ["IEEE 80-2013"] }) });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = body.detail;
        if (detail && typeof detail === "object" && (detail.missing || detail.unconfirmed_critical || detail.coherence)) {
          setBlocked({ missing: detail.missing || [], unconfirmed: detail.unconfirmed_critical || [], coherence: detail.coherence || [] });
          return;
        }
        throw new Error(detail?.message || detail || "No se pudo iniciar el cálculo.");
      }
      setBlocked(null);
      setCalculation(body); setFreshness("calculando"); setState("ready");
    } catch (error) { setActionError(error.message); }
    finally { setRecalculating(false); }
  }
  const result = calculation?.result;
  const { verdict, interpretation } = evaluateResult(result);
  const value = formatNumber;
  const running = recalculating || ["pending", "running"].includes(calculation?.status);
  const gaps = blocked || { missing: readiness.missing, unconfirmed: unconfirmedInputs(artifact), coherence: readiness.coherence };
  const cannotCalculate = gaps.missing.length + gaps.unconfirmed.length + gaps.coherence.length > 0;
  const missingPanel = <MissingInputs {...gaps} onNavigate={onNavigate} onOpenPlan={onOpenPlan}/>;
  const freshnessLabel = freshness === "desactualizado" ? "El resultado es de una versión anterior del diseño. Recalcula para ver el de la versión actual." : freshness === "calculando" ? "Calculando la versión vigente…" : null;
  const recalculateButton = <button className="button primary" disabled={!artifact || running || cannotCalculate} title={cannotCalculate ? "Completa los datos que faltan para calcular" : undefined} onClick={() => recalculate()}><RefreshCw size={14}/> {running ? "Calculando…" : "Recalcular"}</button>;
  const agentReady = verdict === "no_cumple" && conversation && calculation?.artifact_version === artifact?.version && freshness !== "desactualizado";
  // What the two improvement paths produced. It keeps one place in the tree whatever the calculation's state,
  // so a recalculation does not remount it and drop its notices.
  const improvements = <>
  <AgentImprovements project={project} token={token} artifact={artifact} events={designLoopEvents} autonomousRun={autonomousRun} progress={designLoopProgress} result={designLoopResult} onRestored={({ restored, calculation }) => { setArtifact(restored); setCalculation(calculation); setFreshness("calculando"); setState("ready"); onCandidateApplied?.(); }}/>
  {artifact && <MatherraRunReview project={project} token={token} artifact={artifact} refreshKey={refreshKey} onApplied={onCandidateApplied}/>}
  </>;
  const surface = result?.surface_potential;
  const reachNote = surface ? `La tensión de contacto se evalúa sobre la malla (${value(surface.grid_width_m)} × ${value(surface.grid_height_m)} m${Number(calculation.parameters?.touch_reach_m) > 0 ? `, hasta ${calculation.parameters.touch_reach_m} m fuera del perímetro` : ", dentro del perímetro"}); la de paso en todo el terreno, salvo dentro de construcciones.` : null;
  return <aside className="panel artifact-side-panel agent-results-panel"><div className="panel-heading"><div><IconResult size={17}/><h2>Resultado del cálculo</h2></div><div className="artifact-results-heading-actions">{calculation && <span className="muted-label">Versión {calculation.artifact_version}</span>}<button type="button" className="button" disabled={!artifact} onClick={() => setShowOptions(true)} title="Opciones del cálculo"><IconOptions size={14}/> Opciones</button>{recalculateButton}</div></div>
    {actionError && <p className="artifact-update-warning">{actionError}</p>}
    {showMatherra && artifact && <MatherraDialog project={project} token={token} artifact={artifact} onOpenPlan={onOpenMatherra && (() => { setShowMatherra(false); onOpenMatherra(); })} onClose={() => setShowMatherra(false)} onShowResults={() => { setShowMatherra(false); onCandidateApplied?.(); }}/>}
    {showOptions && <CalculationOptionsDialog config={solverConfig} layers={artifact?.snapshot?.soil_layers?.length} busy={running} onChange={setSolverConfig} onClose={() => setShowOptions(false)} onRecalculate={(config) => recalculate(config)}/>}
    {cannotCalculate && calculation && <div className="results-body results-body-top">{missingPanel}</div>}
    {!calculation ? (state === "loading" ? <p className="panel-empty-text">Cargando resultados…</p>
      : state === "error" ? <EmptyState art="calculate" title="No se pudieron cargar los resultados" description="Puede ser un problema de conexión. Vuelve a intentarlo en unos segundos." testId="results-empty"/>
      : !artifact ? <EmptyState art="mesh" title="Aún no hay un diseño para calcular" description="Pídele al agente una malla en el chat, por ejemplo «malla de 40 × 30 m con retícula de 5 m», o dibújala tú en el editor de plano." action={onOpenPlan && <button type="button" className="button primary" onClick={onOpenPlan}><IconPlan size={14}/> Dibujar plano</button>} testId="results-empty"/>
      : cannotCalculate ? <EmptyState art="missing" title="Faltan datos para calcular" description="Con estos datos el motor calcula las tensiones de contacto y paso y verifica la norma. Completa cada uno donde se indica." testId="results-empty">{missingPanel}</EmptyState>
      : <EmptyState art="calculate" title="Este diseño todavía no se ha calculado" description="Ya tiene todo lo necesario. El cálculo tarda unos segundos y te dirá si las tensiones de contacto y paso cumplen la norma." action={<button type="button" className="button primary" disabled={running} onClick={() => recalculate()}><RefreshCw size={14}/> {running ? "Calculando…" : "Calcular ahora"}</button>} secondary={<button type="button" className="button" onClick={() => setShowOptions(true)}><IconOptions size={14}/> Opciones del cálculo</button>} testId="results-empty"/>)
      : calculation.status !== "completed" ? <div className="artifact-status"><strong>Cálculo {calculation.status === "pending" || calculation.status === "running" ? "en curso…" : calculation.status}</strong>{calculation.error && <span className="no-information">{calculation.error}</span>}</div>
      : <div className="results-body">
        {freshnessLabel && <div className="artifact-update-warning">{freshnessLabel} {recalculateButton}</div>}
        <ModelWarnings warnings={result.model_warnings}/>
        <VerdictCallout result={result} footer={<ImproveDesign verdict={verdict} suggestions={verdict === "no_cumple" ? interpretation.actions : []} onSuggestion={onSuggestion} onOpenMatherra={() => setShowMatherra(true)}
          agent={{ available: Boolean(agentReady), disabled: optimizing || recalculating || Boolean(autonomousRun), onRun: optimizeUntilCompliant,
            label: optimizing ? "Iniciando…" : autonomousRun ? "El agente está trabajando…" : "Iterar con el agente",
            requirement: verdict === "no_cumple" ? "Disponible cuando el resultado corresponde a la versión actual del diseño." : "Disponible cuando el diseño no cumple." }}/>}/>
        <section className="result-section" aria-labelledby="grid-values-title">
          <div className="result-section-heading"><h3 id="grid-values-title">Malla de puesta a tierra</h3><p>Cómo se comporta la malla al inyectarle la corriente de falla.</p></div>
          <div className="result-metric-grid">
            <Metric label="Resistencia de malla" value={value(result.grid_resistance_ohm, 3)} unit="Ω" tip="Oposición de la malla a que la corriente pase al suelo. Depende del área, del conductor enterrado, de las varillas y de la resistividad del suelo. Cuanto menor, mejor."/>
            <Metric label="Elevación de potencial (GPR)" value={value(result.gpr_v)} unit="V" tip="Tensión que alcanza la malla respecto a tierra remota durante la falla: resistencia de malla × corriente inyectada. Si es menor que la tensión de contacto tolerable, el diseño cumple sin más análisis."/>
            <Metric label="Corriente inyectada" value={value(result.injected_current_a)} unit="A" tip="Parte de la corriente de falla que la malla descarga al suelo, después del factor de división."/>
          </div>
        </section>
        {surface && <SurfacePotentialMap field={surface} note={reachNote} action={geometry && <button type="button" className="button" onClick={() => setShow3d(true)}><Icon3D size={15}/> Ver en 3D</button>}/>}
        {show3d && <Suspense fallback={<div className="surface3d-backdrop"><div className="surface3d-loading">Cargando vista 3D…</div></div>}>
          <Surface3D calculation={calculation} onClose={() => setShow3d(false)} plan={{ ...gridPlan(geometry), length: geometry.length_m, width: geometry.width_m, burialDepth: geometry.burial_depth_m || 0.5, rodLength: geometry.rod_length_m || 2.4 }}/>
        </Suspense>}
      </div>}
    {improvements}
    {calculation?.status === "completed" && <p className="no-information agent-results-note">Verificación de prefactibilidad; requiere revisión de un ingeniero competente.</p>}
  </aside>;
}

export { AgentArtifactPanel, AgentResultsPanel, ArtifactGrid, ArtifactUpdateCard, PlanViews, gridPlan, planWindow };
