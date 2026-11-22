import React, { Suspense, lazy, useEffect, useState } from "react";
import { Activity, Box, ChevronRight, ExternalLink, Eye, FileText, PencilRuler, RefreshCw, Rotate3d, Settings2, Sparkles, Undo2, X } from "lucide-react";
import { SurfacePotentialMap } from "./GroundingCalculations.jsx";
import TopologyPreview from "./TopologyPreview.jsx";
import { criterionLabel, evaluateResult, formatNumber, verdictLabels } from "../resultInterpretation.js";
import { ACTIVE_RUN, RUN_STATUS_LABELS, apiRequest, formatMoney, formatPercent, formatShare, minimumMargin, restoreAndRecalculate } from "../optimization.js";
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
  const rodNote = geometry.rods?.length ? "posiciones del diseño" : "repartidas en el perímetro";
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
        if (live) setComparison(compared);
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
    {comparison?.base && <p className="matherra-base-summary">Diseño de partida: {formatMoney(comparison.base.cost, comparison.currency)}, {baseVerdict(comparison.base.electrical)}.
      {saving && (saving.kind === "saving" ? ` La recomendada ahorra ${formatMoney(saving.amount, comparison.currency)} (${formatShare(saving.fraction, 1)}).`
        : ` La recomendada cuesta ${formatMoney(-saving.amount, comparison.currency)} más${saving.base_status === "violates" ? ": es lo que cuesta cumplir" : ""}.`)}</p>}
    {notice && <p className="matherra-apply-notice" role="status">{notice}</p>}
    {comparison && <div className="matherra-candidate-list">
      {comparison.alternatives.length ? comparison.alternatives.map((candidate) => {
        const geometry = geometries.get(candidate.alternative_id);
        return <article className={`matherra-candidate${candidate.recommended ? " recommended" : ""}`} data-testid="matherra-candidate" key={candidate.alternative_id}>
          <div className="matherra-candidate-heading"><strong>{candidate.recommended ? "Recomendada · " : ""}Alternativa {candidate.rank}</strong>{candidate.pareto && <span>Equilibrio costo–seguridad</span>}</div>
          <div className="matherra-candidate-metrics">
            <span><small>Costo</small><strong>{formatMoney(candidate.cost, comparison.currency)}</strong></span>
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
          {previewId === candidate.alternative_id && geometry && base && <TopologyPreview base={base} alternative={geometry}/>}
        </article>;
      }) : <p className="no-information">Matherra terminó, pero ninguna alternativa pasó la verificación más fina con este presupuesto. Prueba con un presupuesto mayor o revisa las áreas intervenibles.</p>}
      {comparison.alternatives.some((row) => row.pareto) && <small className="matherra-candidate-validation">«Equilibrio costo–seguridad»: ninguna otra alternativa es a la vez más barata y más segura.</small>}
      <details className="matherra-review-notes"><summary>Cómo interpretar este resultado</summary><ul>{comparison.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></details>
    </div>}
  </section>;
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
  return <aside className="panel artifact-side-panel"><div className="panel-heading"><div><Box size={17}/><h2>Diseño de puesta a tierra</h2></div>{artifact && <span className="muted-label">Versión {artifact.version}</span>}</div>
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
    </> : <div className="artifact-preview-empty"><Box size={25}/><strong>Aún no hay un diseño de malla</strong><span>{error || "Pídele al agente en el chat que diseñe la malla, por ejemplo: «créame una malla de 40 × 30 m con retícula de 5 m»."}</span></div>}
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

// three.js loads only when the 3D view opens.
const Surface3D = lazy(() => import("./Surface3D.jsx"));


function AgentResultsPanel({ project, conversation, token, refreshKey, onSuggestion, onOpenMatherra, onCandidateApplied }) {
  const [artifact, setArtifact] = useState(null);
  const [calculation, setCalculation] = useState(null);
  const [geometry, setGeometry] = useState(null);
  const [freshness, setFreshness] = useState(null);
  const [show3d, setShow3d] = useState(false);
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
  // What the two improvement paths produced, right under the options that launch them. It keeps one place in the
  // tree whatever the calculation's state, so a recalculation does not remount it and drop its notices.
  const improvements = <>
  <AgentImprovements project={project} token={token} artifact={artifact} events={designLoopEvents} autonomousRun={autonomousRun} progress={designLoopProgress} result={designLoopResult} onRestored={({ restored, calculation }) => { setArtifact(restored); setCalculation(calculation); setFreshness("calculando"); setState("ready"); onCandidateApplied?.(); }}/>
  {artifact && <MatherraRunReview project={project} token={token} artifact={artifact} refreshKey={refreshKey} onApplied={onCandidateApplied}/>}
  </>;
  return <aside className="panel artifact-side-panel agent-results-panel"><div className="panel-heading"><div><Activity size={17}/><h2>Resultados</h2></div><div className="artifact-results-heading-actions">{calculation && <span className="muted-label">Versión {calculation.artifact_version}</span>}{recalculateButton}</div></div>
    {actionError && <p className="artifact-update-warning">{actionError}</p>}
    {!calculation ? <div className="artifact-results-empty"><p className="no-information">{state === "error" ? "No se pudieron cargar los resultados." : "Sin cálculo para esta versión del diseño."}</p>{artifact && <p className="no-information">Completa y confirma los parámetros eléctricos antes de recalcular.</p>}</div>
      : calculation.status !== "completed" ? <div className="artifact-status"><strong>Cálculo {calculation.status === "pending" || calculation.status === "running" ? "en curso…" : calculation.status}</strong>{calculation.error && <span className="no-information">{calculation.error}</span>}</div>
      : <>
        {freshnessLabel && <div className="artifact-update-warning">{freshnessLabel} {recalculateButton}</div>}
        <details className="solver-config-panel"><summary><Settings2 size={14}/> Configuración del solver</summary><div className="solver-config-grid"><label>Discretización (m)<select value={solverConfig.discretization_m} onChange={(event) => setSolverConfig((current) => ({ ...current, discretization_m: event.target.value }))}>{[0.25, 0.5, 1, 2, 5].map((value) => <option value={value} key={value}>{value}</option>)}</select></label><label>Segmentación<select value={solverConfig.segmentation} onChange={(event) => setSolverConfig((current) => ({ ...current, segmentation: event.target.value }))}><option value="graded">Graduada en nodos críticos</option><option value="uniform">Uniforme</option></select></label><label>Raster de superficie<select value={solverConfig.surface_spacing_m} onChange={(event) => setSolverConfig((current) => ({ ...current, surface_spacing_m: event.target.value }))}>{[0.25, 0.5, 1].map((value) => <option value={value} key={value}>{value} m</option>)}</select></label><label title="Margen alrededor de la malla donde se busca la tensión de contacto; 0 = dentro del perímetro (IEEE 80)">Alcance de contacto<select value={solverConfig.touch_reach_m} onChange={(event) => setSolverConfig((current) => ({ ...current, touch_reach_m: event.target.value }))}>{[0, 0.5, 1, 2].map((value) => <option value={value} key={value}>{value === 0 ? "Perímetro de la malla" : `${value} m fuera de la malla`}</option>)}</select></label><label className="solver-config-check"><input type="checkbox" checked={solverConfig.estimate_uncertainty} onChange={(event) => setSolverConfig((current) => ({ ...current, estimate_uncertainty: event.target.checked }))}/> Estimar incertidumbre numérica</label><label className="solver-config-justification">Justificación registrada<textarea value={solverConfig.justification} maxLength={500} onChange={(event) => setSolverConfig((current) => ({ ...current, justification: event.target.value }))}/></label><small>Capas del modelo: {artifact?.snapshot?.soil_layers?.length || "pendientes en Entradas"}. La cantidad de capas se define en el modelador de suelo y se valida antes de calcular.</small></div></details>
        <div className={`agent-verdict ${verdict}`}>{verdictLabels[verdict]}</div>
        <div className="result-interpretation"><div className="result-interpretation-title"><strong>Interpretación</strong></div><div><small>Restricción dominante</small><strong>{interpretation.constraint}</strong></div><div><small>Por qué</small><span>{interpretation.explanation}</span></div><div className="result-interpretation-actions"><small>Siguiente acción</small>{interpretation.actions.map((action) => <button className="button" key={action} onClick={() => onSuggestion?.(action)}>{action}</button>)}</div></div>
        <div className="artifact-status"><strong>Malla</strong><span>R = {Number(result.grid_resistance_ohm).toLocaleString("es-CO", { maximumFractionDigits: 3 })} Ω · GPR = {value(result.gpr_v)} V · I = {value(result.injected_current_a)} A</span></div>
        {safety.map((standard) => <div className="artifact-status" key={standard.standard}><strong>{standard.standard}</strong>{(standard.criteria || []).map((c) => <span key={c.criterion} className={c.status === "cumple" ? "" : "agent-fails"}>{c.criterion === "touch" ? "Contacto" : "Paso"}: {value(c.actual_v)} V / {value(c.tolerable_v)} V tolerable ({(100 * c.margin_rel).toLocaleString("es-CO", { maximumFractionDigits: 1 })} %)</span>)}{standard.reason && <span className="no-information">{standard.reason}</span>}</div>)}
        {result.conductor_thermal && <div className="artifact-status"><strong>Conductor (térmico)</strong><span className={result.conductor_thermal.status === "cumple" ? "" : "agent-fails"}>Sección {value(result.conductor_thermal.selected_section_mm2)} mm² · mínima {value(result.conductor_thermal.minimum_section_mm2)} mm²</span></div>}
        <section className="design-optimization-options" aria-labelledby="design-optimization-title">
          <div className="design-optimization-heading"><strong id="design-optimization-title">¿Cómo quieres mejorar este diseño?</strong></div>
          <div className="design-optimization-grid">
            <article className="design-optimization-card">
              <div className="design-optimization-card-title"><Sparkles size={16}/><h3>Mejorar con el agente</h3><span>Asistido</span></div>
              <p>Propone ajustes a la malla, guarda cada uno como versión y lo vuelve a calcular hasta cumplir o agotar las iteraciones.</p>
              {verdict === "no_cumple" && conversation && calculation.artifact_version === artifact?.version && freshness !== "desactualizado"
                ? <button className="button primary" data-testid="optimize-until-compliant" disabled={optimizing || recalculating || Boolean(autonomousRun)} onClick={optimizeUntilCompliant}><Sparkles size={14}/>{optimizing ? "Iniciando…" : autonomousRun ? "El agente está trabajando…" : "Mejorar con el agente"}</button>
                : <small className="design-optimization-requirement">Disponible cuando el cálculo de la versión actual no cumple.</small>}
            </article>
            <article className="design-optimization-card matherra">
              <div className="design-optimization-card-title"><Activity size={16}/><h3>Optimizar con Matherra</h3><span>Matemático</span></div>
              <p>Busca y compara trazados por costo y seguridad dentro de las áreas intervenibles, con las tarifas que definas.</p>
              <button className="button" data-testid="open-matherra-optimizer" onClick={onOpenMatherra}>Configurar Matherra <ChevronRight size={14}/></button>
            </article>
          </div>
        </section>
      </>}
    {improvements}
    {calculation?.status === "completed" && <>
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
