import React, { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Bug, Check, ChevronDown, ChevronRight, CircleHelp, ExternalLink, FileText, ListChecks, Maximize2, Minus, Network, Pencil, Plus, RotateCcw, Search, X } from "lucide-react";

const statusLabels = { proposed: "Propuesta", needs_review: "Por revisar", accepted: "Aceptada", rejected: "Rechazada", superseded: "Reemplazada" };
const kindLabels = { entity: "Entidad", attribute: "Atributo", relation: "Relación" };
const runStatusLabels = { completed: "Completa", completed_with_errors: "Con errores", partial: "Parcial", already_processed: "Ya procesada" };
const questionStatusLabels = { pending: "Pendientes", resolved: "Resueltas", dismissed: "Descartadas", obsolete: "Obsoletas", all: "Todas" };
const typePalette = ["#2f8f7f", "#4f7cc4", "#c27c2c", "#8a5fc0", "#c25470", "#4c9a3f", "#2c8bb0", "#9b7a2f", "#6b7280", "#b4533a"];
const locatorLabels = { page: "pág.", sheet: "hoja", row: "fila", cell: "celda", column: "columna", paragraph: "párrafo", table: "tabla", region: "región", segment: "segmento" };

function typeColor(type = "") {
  let hash = 0;
  for (const char of type) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return typePalette[hash % typePalette.length];
}

function formatLocator(locator) {
  if (!locator) return "Sin localizador";
  const parts = Object.entries(locator).filter(([key, value]) => value !== null && value !== undefined && !["start", "end"].includes(key));
  if (!parts.length) return "Sin localizador";
  return parts.map(([key, value]) => `${locatorLabels[key] || key} ${typeof value === "object" ? JSON.stringify(value) : value}`).join(" · ");
}

function claimText(claim) {
  if (!claim) return "";
  if (claim.kind === "entity") return `${claim.entity_type} · ${claim.name}`;
  if (claim.kind === "attribute") {
    const value = claim.reviewed_value_literal ? `${claim.reviewed_value_literal} ${claim.reviewed_unit_literal || ""} (corregido; propuesto ${claim.value_literal} ${claim.unit_literal || ""})` : `${claim.value_literal ?? ""} ${claim.unit_literal || ""}`;
    return `${claim.subject_name || claim.name || "?"} · ${claim.attribute}${claim.qualifier ? ` [${claim.qualifier}]` : ""} = ${value.trim()}`;
  }
  return `${claim.source_name} —${claim.relation_type}→ ${claim.target_name}`;
}

function errorMessage(detail, fallback) {
  if (!detail) return fallback;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((item) => item.msg || JSON.stringify(item)).join("; ");
  return detail.message || JSON.stringify(detail);
}

const formatDate = (seconds) => seconds ? new Date(seconds * 1000).toLocaleString("es-CO", { dateStyle: "short", timeStyle: "short" }) : "—";
const StatusBadge = ({ status, labels = statusLabels }) => <span className={`kg-status ${status}`}>{labels[status] || status}</span>;
const RawJson = ({ value, label = "JSON crudo" }) => <details className="kg-raw"><summary>{label}</summary><pre>{JSON.stringify(value, null, 2)}</pre></details>;

function tokensOf(usage) {
  if (!usage) return 0;
  return Object.values(usage).reduce((total, part) => total + (part?.prompt_tokens || 0) + (part?.completion_tokens || 0), 0);
}

// Fruchterman–Reingold sin dependencias: suficiente para los ≤1000 nodos que expone la API.
function layoutGraph(nodes, edges, width, height) {
  if (!nodes.length) return {};
  const area = width * height;
  const k = Math.sqrt(area / nodes.length) * 0.45;
  const types = [...new Set(nodes.map((n) => n.entity_type))];
  const pos = nodes.map((node, i) => {
    const angle = (types.indexOf(node.entity_type) / types.length) * Math.PI * 2 + (i % 7) * 0.12;
    const radius = Math.min(width, height) * (0.2 + 0.25 * ((i * 0.618) % 1));
    return { x: width / 2 + Math.cos(angle) * radius, y: height / 2 + Math.sin(angle) * radius };
  });
  const index = new Map(nodes.map((node, i) => [node.entity_key, i]));
  const links = edges.map((e) => [index.get(e.source), index.get(e.target)]).filter(([a, b]) => a !== undefined && b !== undefined && a !== b);
  let temperature = width / 8;
  const iterations = nodes.length > 400 ? 120 : 220;
  for (let step = 0; step < iterations; step += 1) {
    const disp = pos.map(() => ({ x: 0, y: 0 }));
    for (let i = 0; i < pos.length; i += 1) {
      for (let j = i + 1; j < pos.length; j += 1) {
        const dx = pos[i].x - pos[j].x || 0.01;
        const dy = pos[i].y - pos[j].y || 0.01;
        const dist2 = dx * dx + dy * dy;
        const force = (k * k) / dist2;
        disp[i].x += dx * force; disp[i].y += dy * force;
        disp[j].x -= dx * force; disp[j].y -= dy * force;
      }
    }
    for (const [a, b] of links) {
      const dx = pos[a].x - pos[b].x;
      const dy = pos[a].y - pos[b].y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const force = dist / k;
      disp[a].x -= dx * force; disp[a].y -= dy * force;
      disp[b].x += dx * force; disp[b].y += dy * force;
    }
    for (let i = 0; i < pos.length; i += 1) {
      // Gravedad: sin ella las entidades aisladas se alejan y comprimen el resto al encuadrar.
      disp[i].x += (width / 2 - pos[i].x) * 0.15;
      disp[i].y += (height / 2 - pos[i].y) * 0.15;
      const length = Math.sqrt(disp[i].x ** 2 + disp[i].y ** 2) || 1;
      pos[i].x = Math.max(0, Math.min(width, pos[i].x + (disp[i].x / length) * Math.min(length, temperature)));
      pos[i].y = Math.max(0, Math.min(height, pos[i].y + (disp[i].y / length) * Math.min(length, temperature)));
    }
    temperature *= 0.97;
  }
  // Se encuadra el resultado en el lienzo con margen para las etiquetas.
  const pad = 60;
  const xs = pos.map((p) => p.x);
  const ys = pos.map((p) => p.y);
  const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const scale = Math.min((width - 2 * pad) / Math.max(maxX - minX, 1), (height - 2 * pad) / Math.max(maxY - minY, 1), 1.5);
  const offsetX = (width - (maxX - minX) * scale) / 2;
  const offsetY = (height - (maxY - minY) * scale) / 2;
  return Object.fromEntries(nodes.map((node, i) => [node.entity_key, { x: offsetX + (pos[i].x - minX) * scale, y: offsetY + (pos[i].y - minY) * scale }]));
}

function nodeState(node) {
  const claims = node.claims || [];
  if (claims.some((c) => c.status === "needs_review")) return "needs_review";
  if (claims.some((c) => c.status === "proposed")) return "proposed";
  if (claims.length && claims.every((c) => c.status === "accepted")) return "accepted";
  return "none";
}

function GraphMap({ map, onOpenClaim }) {
  const width = 1000;
  const height = 640;
  const svg = useRef(null);
  const drag = useRef(null);
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  const [selected, setSelected] = useState(null);
  const [hovered, setHovered] = useState(null);
  const [query, setQuery] = useState("");
  const [onlyOpen, setOnlyOpen] = useState(false);
  const [hiddenTypes, setHiddenTypes] = useState(() => new Set());
  const nodes = map?.nodes || [];
  const edges = map?.edges || [];
  const positions = useMemo(() => layoutGraph(nodes, edges, width, height), [map]);
  const types = useMemo(() => Object.entries(nodes.reduce((acc, n) => ({ ...acc, [n.entity_type]: (acc[n.entity_type] || 0) + 1 }), {})).sort(), [map]);
  const degree = useMemo(() => edges.reduce((acc, e) => { acc[e.source] = (acc[e.source] || 0) + 1; acc[e.target] = (acc[e.target] || 0) + 1; return acc; }, {}), [map]);
  const isolated = nodes.filter((n) => !degree[n.entity_key]).length;
  const visible = (node) => !hiddenTypes.has(node.entity_type) && (!onlyOpen || ["needs_review", "proposed"].includes(nodeState(node)) || edges.some((e) => e.status !== "accepted" && (e.source === node.entity_key || e.target === node.entity_key)));
  const shown = new Set(nodes.filter(visible).map((n) => n.entity_key));
  const needle = query.trim().toLowerCase();
  const matches = (node) => !needle || node.name?.toLowerCase().includes(needle) || node.entity_type.toLowerCase().includes(needle);
  const focus = selected || hovered;
  const neighbors = new Set(focus ? edges.filter((e) => e.source === focus || e.target === focus).flatMap((e) => [e.source, e.target]) : []);
  const selectedNode = nodes.find((n) => n.entity_key === selected);
  const byKey = Object.fromEntries(nodes.map((n) => [n.entity_key, n]));

  function wheel(event) {
    event.preventDefault();
    const rect = svg.current.getBoundingClientRect();
    const px = ((event.clientX - rect.left) / rect.width) * width;
    const py = ((event.clientY - rect.top) / rect.height) * height;
    setView((old) => {
      const k = Math.max(0.3, Math.min(4, old.k * (event.deltaY < 0 ? 1.15 : 1 / 1.15)));
      return { k, x: px - ((px - old.x) * k) / old.k, y: py - ((py - old.y) * k) / old.k };
    });
  }
  useEffect(() => {
    const node = svg.current;
    if (!node) return undefined;
    node.addEventListener("wheel", wheel, { passive: false });
    return () => node.removeEventListener("wheel", wheel);
  }, [nodes.length]);
  function zoom(factor) { setView((old) => { const k = Math.max(0.3, Math.min(4, old.k * factor)); return { k, x: width / 2 - ((width / 2 - old.x) * k) / old.k, y: height / 2 - ((height / 2 - old.y) * k) / old.k }; }); }
  function startPan(event) {
    if (event.target.closest(".kg-node, .kg-edge")) return;
    drag.current = { x: event.clientX, y: event.clientY, view, moved: false };
    event.currentTarget.setPointerCapture(event.pointerId);
  }
  function movePan(event) {
    if (!drag.current) return;
    const rect = svg.current.getBoundingClientRect();
    const dx = ((event.clientX - drag.current.x) / rect.width) * width;
    const dy = ((event.clientY - drag.current.y) / rect.height) * height;
    if (Math.abs(dx) + Math.abs(dy) > 3) drag.current.moved = true;
    setView({ ...drag.current.view, x: drag.current.view.x + dx, y: drag.current.view.y + dy });
  }
  function endPan() {
    if (drag.current && !drag.current.moved) setSelected(null);
    drag.current = null;
  }

  if (!nodes.length) return <div className="kg-empty"><Network size={26}/><strong>El grafo aún no tiene entidades</strong><span>Carga documentos al proyecto: cada archivo procesado propone entidades, atributos y relaciones con su evidencia.</span></div>;
  return <div className="kg-map-layout">
    <div className="kg-map-wrap">
      <div className="kg-map-toolbar">
        <label className="kg-search"><Search size={13}/><input placeholder="Buscar entidad o tipo" value={query} onChange={(e) => setQuery(e.target.value)}/></label>
        <label className="kg-check"><input type="checkbox" checked={onlyOpen} onChange={(e) => setOnlyOpen(e.target.checked)}/> Solo con revisión pendiente</label>
        <span className="kg-map-stats">{nodes.length} entidades · {edges.length} relaciones · <span className={isolated ? "warn" : ""}>{isolated} aisladas</span>{map.truncated && <span className="warn"> · truncado</span>}</span>
        <div className="kg-zoom"><button aria-label="Acercar" onClick={() => zoom(1.25)}><Plus size={13}/></button><button aria-label="Alejar" onClick={() => zoom(0.8)}><Minus size={13}/></button><button aria-label="Restablecer vista" onClick={() => setView({ x: 0, y: 0, k: 1 })}><Maximize2 size={13}/></button></div>
      </div>
      <svg ref={svg} className="kg-map" viewBox={`0 0 ${width} ${height}`} onPointerDown={startPan} onPointerMove={movePan} onPointerUp={endPan} onPointerCancel={() => { drag.current = null; }} role="img" aria-label="Mapa de entidades y relaciones del proyecto">
        <defs>
          {["accepted", "open"].map((kind) => <marker key={kind} id={`kg-arrow-${kind}`} viewBox="0 0 10 10" refX="17" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" className={`kg-arrow ${kind}`}/></marker>)}
        </defs>
        <g transform={`translate(${view.x},${view.y}) scale(${view.k})`}>
          {edges.filter((e) => shown.has(e.source) && shown.has(e.target)).map((edge) => {
            const a = positions[edge.source];
            const b = positions[edge.target];
            if (!a || !b) return null;
            const active = focus && (edge.source === focus || edge.target === focus);
            const kind = edge.status === "accepted" ? "accepted" : "open";
            return <g key={edge.claim_id} className={`kg-edge ${kind} ${focus && !active ? "dim" : ""} ${active ? "active" : ""}`} onClick={() => onOpenClaim(edge.claim_id)}>
              <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} markerEnd={`url(#kg-arrow-${kind})`}/>
              <line className="kg-edge-hit" x1={a.x} y1={a.y} x2={b.x} y2={b.y}><title>{`${byKey[edge.source]?.name} —${edge.type}→ ${byKey[edge.target]?.name} · ${statusLabels[edge.status] || edge.status}`}</title></line>
              {(active || view.k > 1.6) && <text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 4} textAnchor="middle">{edge.type}</text>}
            </g>;
          })}
          {nodes.filter((n) => shown.has(n.entity_key)).map((node) => {
            const p = positions[node.entity_key];
            const state = nodeState(node);
            const dim = (focus && focus !== node.entity_key && !neighbors.has(node.entity_key)) || !matches(node);
            const radius = 6 + Math.min(8, Math.sqrt((node.claims?.length || 0) + (degree[node.entity_key] || 0)) * 1.6);
            return <g key={node.entity_key} className={`kg-node ${state} ${dim ? "dim" : ""} ${selected === node.entity_key ? "selected" : ""}`} transform={`translate(${p.x},${p.y})`} onClick={(event) => { event.stopPropagation(); setSelected(node.entity_key === selected ? null : node.entity_key); }} onPointerEnter={() => setHovered(node.entity_key)} onPointerLeave={() => setHovered(null)}>
              <circle r={radius} fill={typeColor(node.entity_type)}/>
              {state !== "none" && state !== "accepted" && <circle className="kg-node-flag" r="3" cx={radius * 0.75} cy={-radius * 0.75}/>}
              {(view.k > 0.75 || focus === node.entity_key || (needle && matches(node))) && <text y={radius + 11} textAnchor="middle">{node.name}</text>}
              <title>{`${node.entity_type} · ${node.name}`}</title>
            </g>;
          })}
        </g>
      </svg>
      <div className="kg-legend">
        {types.map(([type, count]) => <button key={type} className={hiddenTypes.has(type) ? "off" : ""} onClick={() => setHiddenTypes((old) => { const next = new Set(old); next.has(type) ? next.delete(type) : next.add(type); return next; })}><i style={{ background: typeColor(type) }}/>{type} <small>{count}</small></button>)}
        <span className="kg-legend-sep"/>
        <span><i className="kg-legend-line accepted"/>Aceptada</span><span><i className="kg-legend-line open"/>Pendiente</span><span><i className="kg-legend-dot"/>Con afirmaciones por revisar</span>
      </div>
    </div>
    <aside className="kg-side panel">
      {selectedNode ? <>
        <div className="kg-side-head"><div><span className="kg-type-chip" style={{ "--chip": typeColor(selectedNode.entity_type) }}>{selectedNode.entity_type}</span><h3>{selectedNode.name}</h3><code title={selectedNode.entity_key}>{selectedNode.entity_key.slice(0, 16)}…</code></div><button className="icon-button" aria-label="Cerrar" onClick={() => setSelected(null)}><X size={15}/></button></div>
        <h4>Afirmaciones ({selectedNode.claims?.length || 0})</h4>
        <div className="kg-side-list">{selectedNode.claims?.length ? selectedNode.claims.map((c) => <button key={c.claim_id} onClick={() => onOpenClaim(c.claim_id)}><StatusBadge status={c.status}/><span>{c.kind === "entity" ? "Existencia de la entidad" : `${c.attribute}${c.qualifier ? ` [${c.qualifier}]` : ""} = ${c.value_literal ?? ""} ${c.unit_literal || ""}`}</span><ChevronRight size={13}/></button>) : <p className="kg-muted">Sin afirmaciones vigentes.</p>}</div>
        <h4>Relaciones ({edges.filter((e) => e.source === selected || e.target === selected).length})</h4>
        <div className="kg-side-list">{edges.filter((e) => e.source === selected || e.target === selected).map((e) => <button key={e.claim_id} onClick={() => onOpenClaim(e.claim_id)}><StatusBadge status={e.status}/><span>{e.source === selected ? `→ ${e.type} → ${byKey[e.target]?.name}` : `← ${e.type} ← ${byKey[e.source]?.name}`}</span><ChevronRight size={13}/></button>)}{!degree[selected] && <p className="kg-muted warn"><AlertTriangle size={12}/> Entidad aislada: ninguna relación vigente la conecta.</p>}</div>
      </> : <div className="kg-side-empty"><Network size={20}/><strong>Selecciona una entidad</strong><span>Verás sus afirmaciones y relaciones. Haz clic en una relación del mapa para abrir su evidencia.</span></div>}
    </aside>
  </div>;
}

function ClaimDrawer({ claimId, request, projectId, onClose, onOpenClaim, onChanged }) {
  const [claim, setClaim] = useState(null);
  const [error, setError] = useState("");
  const [decision, setDecision] = useState("accept");
  const [reason, setReason] = useState("");
  const [value, setValue] = useState("");
  const [unit, setUnit] = useState("");
  const [conflictIds, setConflictIds] = useState([]);
  const [supersede, setSupersede] = useState([]);
  const [busy, setBusy] = useState(false);
  const base = `/api/v1/projects/${projectId}/knowledge-graph`;
  async function load() {
    setError("");
    try { setClaim(await request(`${base}/claims/${claimId}`)); }
    catch (e) { setError(e.message); }
  }
  useEffect(() => { setClaim(null); setConflictIds([]); setSupersede([]); setReason(""); setDecision("accept"); load(); }, [claimId]);
  useEffect(() => { if (claim?.kind === "attribute") { setValue(claim.reviewed_value_literal || claim.value_literal || ""); setUnit(claim.reviewed_unit_literal || claim.unit_literal || ""); } }, [claim?.claim_id]);
  async function openSource(evidence) {
    const win = window.open("", "_blank");
    try {
      const source = await request(`${base}/documents/${evidence.upload_id || claim.upload_id}/source`);
      const page = evidence.locator?.page;
      const url = source.mime_type === "application/pdf" && page ? `${source.url}#page=${page}` : source.url;
      if (win) { win.opener = null; win.location = url; } else window.open(url, "_blank", "noopener");
    } catch (e) { win?.close(); setError(e.message); }
  }
  async function submit(event) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      const body = { decision, reason, supersede_claim_ids: supersede };
      if (decision === "correct") Object.assign(body, { corrected_value: value, corrected_unit: unit || null });
      setClaim(await request(`${base}/claims/${claimId}/decision`, { method: "POST", body: JSON.stringify(body) }));
      setReason(""); setConflictIds([]); setSupersede([]);
      onChanged();
    } catch (e) {
      if (e.status === 409 && e.detail?.claim_ids) { setConflictIds(e.detail.claim_ids); setError(errorMessage(e.detail)); }
      else setError(e.message);
    } finally { setBusy(false); }
  }
  const open = claim && ["proposed", "needs_review"].includes(claim.status);
  const reviewable = claim && claim.status !== "superseded";
  return <div className="kg-drawer-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <aside className="kg-drawer" role="dialog" aria-label="Detalle de la afirmación">
      <div className="kg-drawer-head"><div><div className="eyebrow">AFIRMACIÓN · {claim ? kindLabels[claim.kind] : "…"}</div><h2>{claim ? claimText(claim) : "Cargando…"}</h2>{claim && <div className="kg-drawer-meta"><StatusBadge status={claim.status}/>{claim.feeds_calculation && <span className="kg-pill calc">Entrada de cálculo</span>}{claim.methods?.map((m) => <span key={m} className="kg-pill">{m}</span>)}{claim.confidence_level && <span className="kg-pill" title={claim.confidence_reason || ""}>confianza {claim.confidence_level}</span>}</div>}</div><button className="icon-button" aria-label="Cerrar" onClick={onClose}><X size={17}/></button></div>
      {error && <div className="kg-alert" role="alert"><AlertTriangle size={14}/>{error}</div>}
      {claim && <div className="kg-drawer-body">
        {!!claim.review_reasons?.length && <section><h4>Motivos de revisión</h4><ul className="kg-reasons">{claim.review_reasons.map((r) => <li key={r}>{r}</li>)}</ul></section>}
        <section><h4>Evidencia ({claim.evidence?.length || 0})</h4>{claim.evidence?.length ? claim.evidence.map((ev, i) => <article className="kg-evidence" key={ev.evidence_id || i}><blockquote>«{ev.quote}»</blockquote><div><span><FileText size={12}/>{ev.filename || claim.filename} · {formatLocator(ev.locator)}{ev.ocr_needs_review && <em className="warn"> · OCR dudoso ({Math.round((ev.ocr_quality || 0) * 100) / 100})</em>}</span><button className="button" onClick={() => openSource(ev)}><ExternalLink size={12}/> Abrir documento</button></div></article>) : <p className="kg-muted warn">Sin evidencia enlazada: esto indica un problema de persistencia.</p>}</section>
        {!!claim.conflicts?.length && <section><h4>Contradicciones ({claim.conflicts.length})</h4><div className="kg-side-list">{claim.conflicts.map((c) => <button key={c.claim_id} onClick={() => onOpenClaim(c.claim_id)}><StatusBadge status={c.status}/><span>{claimText(c)} <small>· {c.filename}</small></span><ChevronRight size={13}/></button>)}</div></section>}
        {!!(claim.duplicates?.length || claim.superseded?.length) && <section><h4>Duplicados y reemplazos</h4><div className="kg-side-list">{[...(claim.duplicates || []).map((c) => ({ ...c, rel: "Duplicado" })), ...(claim.superseded || []).map((c) => ({ ...c, rel: "Reemplazo" }))].map((c) => <button key={`${c.rel}-${c.claim_id}`} onClick={() => onOpenClaim(c.claim_id)}><StatusBadge status={c.status}/><span>{c.rel} · <code>{c.claim_id.slice(0, 12)}</code></span><ChevronRight size={13}/></button>)}</div></section>}
        {!!claim.questions?.length && <section><h4>Preguntas</h4><ul className="kg-reasons">{claim.questions.map((q) => <li key={q.key}>{q.question} <small>({questionStatusLabels[q.status] || q.status})</small></li>)}</ul></section>}
        {reviewable && <section><h4>Decisión</h4><form className="kg-decision" onSubmit={submit}>
          <div className="kg-segmented">{[["accept", "Aceptar", Check], ["reject", "Rechazar", X], ...(claim.kind === "attribute" ? [["correct", "Corregir", Pencil]] : [])].map(([key, label, Icon]) => <button type="button" key={key} className={decision === key ? `active ${key}` : ""} onClick={() => setDecision(key)}><Icon size={13}/>{label}</button>)}</div>
          {!open && <p className="kg-muted">La afirmación ya está {statusLabels[claim.status].toLowerCase()}; una nueva decisión queda registrada en el historial.</p>}
          {decision === "correct" && <div className="kg-correct"><label>Valor<input required value={value} onChange={(e) => setValue(e.target.value)}/></label><label>Unidad<input value={unit} onChange={(e) => setUnit(e.target.value)}/></label></div>}
          {!!conflictIds.length && <div className="kg-supersede"><strong>Valores aceptados en conflicto</strong><span>Marca los que esta decisión reemplaza:</span>{conflictIds.map((id) => <label key={id}><input type="checkbox" checked={supersede.includes(id)} onChange={(e) => setSupersede((old) => e.target.checked ? [...old, id] : old.filter((x) => x !== id))}/><button type="button" className="kg-link" onClick={() => onOpenClaim(id)}>{id.slice(0, 16)}…</button></label>)}</div>}
          <label>Motivo<textarea required minLength="3" maxLength="2000" rows="2" placeholder="Ej. Coincide con la placa del equipo" value={reason} onChange={(e) => setReason(e.target.value)}/></label>
          <button className="button primary" disabled={busy || reason.trim().length < 3}>{busy ? "Guardando…" : "Registrar decisión"}</button>
        </form></section>}
        {!!claim.decisions?.length && <section><h4>Historial de decisiones</h4><ol className="kg-history">{claim.decisions.map((d) => <li key={d.decision_id}><strong>{d.decision}</strong> · {statusLabels[d.previous_status] || d.previous_status} → {statusLabels[d.new_status] || d.new_status}<span>{formatDate(d.decided_at)} · {d.actor_id?.slice(0, 8)} — {d.reason}</span>{d.reviewed_value_literal && <span>Valor revisado: {d.reviewed_value_literal} {d.reviewed_unit_literal || ""}</span>}</li>)}</ol></section>}
        <section><h4>Procedencia</h4><dl className="kg-dl"><dt>Documento</dt><dd>{claim.filename}</dd><dt>Ejecución</dt><dd><code>{claim.run_id?.slice(0, 16)}</code> · {claim.run?.method} · {formatDate(claim.run?.started_at)}</dd><dt>Modelo</dt><dd>{claim.run?.model || "—"}</dd><dt>Prompts</dt><dd>{claim.run?.extractor_prompt_name ? `${claim.run.extractor_prompt_name} v${claim.run.extractor_prompt_version} · ${claim.run.consolidator_prompt_name || "—"} v${claim.run.consolidator_prompt_version ?? "—"}` : "—"}</dd><dt>Parser / esquema</dt><dd>{claim.run?.parser_version} / {claim.run?.schema_version}</dd><dt>Hallazgos</dt><dd>{claim.finding_ids?.join(", ") || "—"}</dd><dt>ID</dt><dd><code>{claim.claim_id}</code></dd></dl></section>
        <RawJson value={claim}/>
      </div>}
    </aside>
  </div>;
}

function ClaimsTab({ request, base, summary, onOpenClaim, version }) {
  const [filters, setFilters] = useState({ status: "needs_review", kind: "", upload_id: "" });
  const [page, setPage] = useState({ items: [], total: 0, skip: 0, limit: 50 });
  const [error, setError] = useState("");
  async function load(skip = 0) {
    const params = new URLSearchParams({ limit: "50", skip: String(skip) });
    Object.entries(filters).forEach(([key, value]) => value && params.set(key, value));
    try { setPage(await request(`${base}/claims?${params}`)); setError(""); }
    catch (e) { setError(e.message); }
  }
  useEffect(() => { load(0); }, [filters, version]);
  const set = (key) => (event) => setFilters((old) => ({ ...old, [key]: event.target.value }));
  return <div className="kg-tab-body">
    <div className="kg-filters">
      <select aria-label="Estado" value={filters.status} onChange={set("status")}><option value="">Todos los estados</option>{Object.entries(statusLabels).map(([key, label]) => <option key={key} value={key}>{label} ({summary?.claims?.by_status?.[key] || 0})</option>)}</select>
      <select aria-label="Tipo" value={filters.kind} onChange={set("kind")}><option value="">Todos los tipos</option>{Object.entries(kindLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select>
      <select aria-label="Documento" value={filters.upload_id} onChange={set("upload_id")}><option value="">Todos los documentos</option>{summary?.documents?.map((d) => <option key={d.upload_id} value={d.upload_id}>{d.filename}</option>)}</select>
      <span className="kg-muted">{page.total} afirmaciones</span>
    </div>
    {error && <div className="kg-alert"><AlertTriangle size={14}/>{error}</div>}
    <div className="kg-table-wrap"><table className="kg-table"><thead><tr><th>Estado</th><th>Tipo</th><th>Afirmación</th><th>Evidencia</th><th>Documento</th><th>Método</th></tr></thead><tbody>
      {page.items.length ? page.items.map((c) => <tr key={c.claim_id} onClick={() => onOpenClaim(c.claim_id)}><td><StatusBadge status={c.status}/></td><td>{kindLabels[c.kind]}</td><td><strong>{claimText(c)}</strong>{c.conflict_count > 0 && <span className="kg-pill conflict"><AlertTriangle size={10}/> {c.conflict_count} conflicto{c.conflict_count > 1 ? "s" : ""}</span>}{c.feeds_calculation && <span className="kg-pill calc">cálculo</span>}</td><td className="kg-quote-cell">{c.evidence?.[0] ? <>«{c.evidence[0].quote}»<small>{formatLocator(c.evidence[0].locator)}</small></> : <span className="warn">sin evidencia</span>}</td><td>{c.filename}</td><td>{c.methods?.join(", ")}</td></tr>) : <tr><td colSpan="6" className="kg-table-empty">No hay afirmaciones con estos filtros.</td></tr>}
    </tbody></table></div>
    {page.total > page.limit && <div className="kg-pager"><button className="button" disabled={page.skip === 0} onClick={() => load(Math.max(0, page.skip - page.limit))}>Anterior</button><span>{page.skip + 1}–{Math.min(page.total, page.skip + page.limit)} de {page.total}</span><button className="button" disabled={page.skip + page.limit >= page.total} onClick={() => load(page.skip + page.limit)}>Siguiente</button></div>}
  </div>;
}

function QuestionsTab({ request, base, onOpenClaim, version, onChanged }) {
  const [status, setStatus] = useState("pending");
  const [data, setData] = useState({ items: [], total: 0 });
  const [drafts, setDrafts] = useState({});
  const [error, setError] = useState("");
  async function load() {
    try { setData(await request(`${base}/questions?status=${status}&limit=100`)); setError(""); }
    catch (e) { setError(e.message); }
  }
  useEffect(() => { load(); }, [status, version]);
  async function resolve(question, next) {
    try {
      await request(`${base}/questions/${encodeURIComponent(question.key)}/resolution`, { method: "POST", body: JSON.stringify({ status: next, resolution: drafts[question.key] || "" }) });
      setDrafts((old) => ({ ...old, [question.key]: "" }));
      onChanged();
    } catch (e) { setError(e.message); }
  }
  return <div className="kg-tab-body">
    <div className="kg-filters"><select aria-label="Estado de la pregunta" value={status} onChange={(e) => setStatus(e.target.value)}>{Object.entries(questionStatusLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><span className="kg-muted">{data.total} preguntas</span></div>
    {error && <div className="kg-alert"><AlertTriangle size={14}/>{error}</div>}
    <div className="kg-questions">{data.items.length ? data.items.map((q) => <article key={q.key} className="kg-question panel">
      <div className="kg-question-head"><span className="kg-pill">{q.kind}</span><StatusBadge status={q.status} labels={questionStatusLabels}/>{q.open_claims > 0 && <span className="kg-muted">{q.open_claims} afirmaciones abiertas</span>}<span className="kg-muted">{q.documents?.map((d) => d.filename).join(", ")}</span></div>
      <p>{q.question}</p>
      <div className="kg-chip-row">{q.claims?.map((c) => <button key={c.claim_id} className="kg-claim-chip" onClick={() => onOpenClaim(c.claim_id)}><StatusBadge status={c.status}/>{c.kind === "attribute" ? `${c.subject_name} · ${c.attribute} = ${c.value_literal ?? ""} ${c.unit_literal || ""}` : c.kind === "entity" ? `${c.entity_type} · ${c.name}` : `relación ${c.claim_id.slice(0, 8)}`}</button>)}</div>
      {q.resolution && <p className="kg-muted">Resolución: {q.resolution}</p>}
      {q.status === "pending" && <div className="kg-question-actions"><input placeholder="Cómo se resolvió (mín. 3 caracteres)" value={drafts[q.key] || ""} onChange={(e) => setDrafts((old) => ({ ...old, [q.key]: e.target.value }))}/><button className="button primary" disabled={(drafts[q.key] || "").trim().length < 3} onClick={() => resolve(q, "resolved")}><Check size={13}/> Resolver</button><button className="button" disabled={(drafts[q.key] || "").trim().length < 3} onClick={() => resolve(q, "dismissed")}>Descartar</button></div>}
    </article>) : <div className="kg-empty small"><CircleHelp size={20}/><strong>Sin preguntas en este estado</strong></div>}</div>
  </div>;
}

function RunsTab({ request, base, summary, version }) {
  const [uploadId, setUploadId] = useState("");
  const [runs, setRuns] = useState([]);
  const [expanded, setExpanded] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  async function reprocess() {
    try {
      await request(`${base}/documents/${uploadId}/reprocess`, { method: "POST" });
      setNotice("Reprocesamiento en cola. Si cambió el prompt, el modelo o el parser aparecerá una ejecución nueva; si no, se conserva la actual."); setError("");
    } catch (e) { setError(e.message); setNotice(""); }
  }
  useEffect(() => {
    setNotice("");
    (async () => {
      try { setRuns((await request(`${base}/runs?limit=100${uploadId ? `&upload_id=${uploadId}` : ""}`)).items); setError(""); }
      catch (e) { setError(e.message); }
    })();
  }, [uploadId, version]);
  return <div className="kg-tab-body">
    <div className="kg-filters"><select aria-label="Documento" value={uploadId} onChange={(e) => setUploadId(e.target.value)}><option value="">Todos los documentos</option>{summary?.documents?.map((d) => <option key={d.upload_id} value={d.upload_id}>{d.filename}</option>)}</select><span className="kg-muted">{runs.length} ejecuciones · las reemplazadas aparecen atenuadas</span>{uploadId && <button className="button" onClick={reprocess}><RotateCcw size={13}/> Reprocesar documento</button>}</div>
    {error && <div className="kg-alert"><AlertTriangle size={14}/>{error}</div>}
    {notice && <p className="kg-muted">{notice}</p>}
    <div className="kg-table-wrap"><table className="kg-table kg-runs"><thead><tr><th/><th>Documento</th><th>Inicio</th><th>Estado</th><th>Método / modelo</th><th>Afirmaciones</th><th>Rechazos</th><th>Errores</th><th>Preguntas</th><th>Tokens</th><th>Duración</th></tr></thead><tbody>
      {runs.length ? runs.map((run) => {
        const metrics = run.metrics || {};
        const isOpen = expanded === run.run_id;
        return <React.Fragment key={run.run_id}>
          <tr className={run.superseded_by ? "superseded" : ""} onClick={() => setExpanded(isOpen ? null : run.run_id)}>
            <td>{isOpen ? <ChevronDown size={13}/> : <ChevronRight size={13}/>}</td><td><strong>{run.filename}</strong>{run.superseded_by && <small>reemplazada</small>}</td><td>{formatDate(run.started_at)}</td><td><span className={`kg-run-status ${run.status}`}>{runStatusLabels[run.status] || run.status}</span></td><td>{run.method}<small>{run.model || "sin LLM"}</small></td>
            <td>{metrics.claims ?? "—"}<small>{Object.entries(metrics.by_status || {}).map(([s, n]) => `${statusLabels[s] || s}: ${n}`).join(" · ")}</small></td>
            <td className={metrics.rejected ? "warn" : ""}>{metrics.rejected ?? 0}</td><td className={run.errors?.length ? "warn" : ""}>{run.errors?.length || 0}</td><td>{metrics.questions ?? 0}</td><td>{tokensOf(metrics.usage).toLocaleString("es-CO")}{metrics.llm_cost_usd != null && <small>US$ {metrics.llm_cost_usd.toFixed(4)}</small>}</td><td>{metrics.duration_seconds != null ? `${metrics.duration_seconds.toFixed(1)} s` : "—"}</td>
          </tr>
          {isOpen && <tr className="kg-run-detail"><td colSpan="11"><RunDetail run={run}/></td></tr>}
        </React.Fragment>;
      }) : <tr><td colSpan="11" className="kg-table-empty">Aún no hay ejecuciones de extracción.</td></tr>}
    </tbody></table></div>
  </div>;
}

function RunDetail({ run }) {
  const coverage = run.coverage || {};
  const failedPages = coverage.failed_pages || [];
  return <div className="kg-run-grid">
    <section><h4>Errores ({run.errors?.length || 0})</h4>{run.errors?.length ? <ul className="kg-reasons error">{run.errors.map((e, i) => <li key={i}>{e}</li>)}</ul> : <p className="kg-muted">Sin errores.</p>}</section>
    <section><h4>Hallazgos rechazados ({run.rejected?.length || 0})</h4>{run.rejected?.length ? <table className="kg-mini"><thead><tr><th>Código</th><th>Hallazgo</th><th>Origen</th><th>Detalle</th></tr></thead><tbody>{run.rejected.map((r, i) => <tr key={i}><td><code>{r.code}</code></td><td>{r.finding_id}</td><td>{r.method}</td><td>{r.message}</td></tr>)}</tbody></table> : <p className="kg-muted">Ningún hallazgo rechazado.</p>}</section>
    <section><h4>Cobertura del documento</h4><dl className="kg-dl"><dt>Segmentos</dt><dd>{run.metrics?.segments ?? "—"}</dd>{coverage.pages != null && <><dt>Páginas</dt><dd>{coverage.pages} (texto: {coverage.text_pages?.length || 0}, OCR: {coverage.ocr_pages?.length || 0}, vacías: {coverage.empty_pages?.length || 0})</dd></>}{coverage.tables > 0 && <><dt>Tablas</dt><dd>{coverage.tables} en p. {coverage.table_pages.join(", ")}</dd></>}{coverage.low_quality_pages?.length > 0 && <><dt>OCR dudoso</dt><dd className="warn">p. {coverage.low_quality_pages.join(", ")}</dd></>}<dt>Páginas fallidas</dt><dd className={failedPages.length ? "warn" : ""}>{failedPages.length ? failedPages.map((p) => `p. ${p.page}: ${p.error}`).join("; ") : "ninguna"}</dd>{run.ocr && Object.keys(run.ocr).length > 0 && <><dt>OCR</dt><dd><code>{JSON.stringify(run.ocr)}</code></dd></>}</dl></section>
    <section><h4>Versiones y uso</h4><dl className="kg-dl"><dt>Run</dt><dd><code>{run.run_id}</code></dd><dt>Parser / reglas / esquema</dt><dd>{run.parser_version} / {run.rules_version} / {run.schema_version}</dd><dt>Extractor</dt><dd>{run.extractor_prompt_name ? `${run.extractor_prompt_name} v${run.extractor_prompt_version}` : "—"}</dd><dt>Consolidador</dt><dd>{run.consolidator_prompt_name ? `${run.consolidator_prompt_name} v${run.consolidator_prompt_version}` : "—"}</dd>{Object.entries(run.metrics?.usage || {}).map(([agent, usage]) => <React.Fragment key={agent}><dt>{agent}</dt><dd>{usage ? `${usage.prompt_tokens || 0} + ${usage.completion_tokens || 0} tokens · ${usage.rounds || 0} rondas${usage.submissions ? ` · ${usage.submissions} envíos` : ""}${usage.duration_seconds ? ` · ${usage.duration_seconds} s` : ""}` : "—"}</dd></React.Fragment>)}{run.superseded_by && <><dt>Reemplazada por</dt><dd><code>{run.superseded_by.slice(0, 16)}</code></dd></>}</dl></section>
    {(run.summary || run.notes?.length > 0) && <section className="wide"><h4>Resumen y notas del modelo</h4>{run.summary && <p>{run.summary}</p>}{run.notes?.length > 0 && <ul className="kg-reasons">{run.notes.map((n, i) => <li key={i}>{typeof n === "string" ? n : JSON.stringify(n)}</li>)}</ul>}</section>}
    <section className="wide"><RawJson value={run}/></section>
  </div>;
}

function KnowledgeGraphWorkspace({ project, token }) {
  const [tab, setTab] = useState("map");
  const [summary, setSummary] = useState(null);
  const [map, setMap] = useState(null);
  const [claimId, setClaimId] = useState(null);
  const [version, setVersion] = useState(0);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const base = `/api/v1/projects/${project.id}/knowledge-graph`;
  const request = async (url, options = {}) => {
    const response = await fetch(url, { ...options, headers: { Authorization: `Bearer ${token}`, ...(options.body ? { "Content-Type": "application/json" } : {}), ...options.headers } });
    const data = response.status === 204 ? null : await response.json().catch(() => null);
    if (!response.ok) {
      const failure = new Error(errorMessage(data?.detail, response.status === 503 ? "El grafo de conocimiento no está configurado en el servidor." : "No se pudo completar la operación."));
      failure.status = response.status;
      failure.detail = data?.detail;
      throw failure;
    }
    return data;
  };
  async function reload() {
    setLoading(true);
    try {
      const [nextSummary, nextMap] = await Promise.all([request(`${base}/summary`), request(`${base}/entities?limit=1000`)]);
      setSummary(nextSummary); setMap(nextMap); setError("");
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }
  useEffect(() => { reload(); }, [project.id, version]);
  const refresh = () => setVersion((v) => v + 1);
  const byStatus = summary?.claims?.by_status || {};
  const pendingQuestions = summary?.questions?.pending || 0;
  const runIssues = summary?.documents?.filter((d) => d.run_status && d.run_status !== "completed").length || 0;
  const tabs = [["map", "Mapa", Network], ["claims", "Afirmaciones", ListChecks, (byStatus.needs_review || 0) + (byStatus.proposed || 0)], ["questions", "Preguntas", CircleHelp, pendingQuestions], ["runs", "Ejecuciones", Bug, runIssues]];
  return <section className="kg-workspace">
    <div className="kg-summary">
      {[["Entidades", summary?.entities], ["Afirmaciones", summary?.claims?.total], ["Por revisar", (byStatus.needs_review || 0) + (byStatus.proposed || 0), "warn"], ["Aceptadas", byStatus.accepted, "ok"], ["Rechazadas", byStatus.rejected], ["Conflictos abiertos", summary?.open_conflicts, summary?.open_conflicts ? "bad" : ""], ["Preguntas pendientes", pendingQuestions, pendingQuestions ? "warn" : ""], ["Documentos", summary?.documents?.length]].map(([label, value, tone]) => <div key={label} className={`kg-stat ${tone || ""}`}><strong>{value ?? "—"}</strong><span>{label}</span></div>)}
      <button className="button" onClick={refresh} disabled={loading}><RotateCcw size={13}/>{loading ? "Actualizando…" : "Actualizar"}</button>
    </div>
    {error && <div className="kg-alert" role="alert"><AlertTriangle size={14}/>{error}</div>}
    <div className="artifact-view-tabs kg-tabs" role="tablist" aria-label="Vistas del grafo">{tabs.map(([key, label, Icon, badge]) => <button key={key} role="tab" aria-selected={tab === key} className={tab === key ? "active" : ""} onClick={() => setTab(key)}><Icon size={14}/>{label}{badge > 0 && <span className="kg-tab-badge">{badge}</span>}</button>)}</div>
    {tab === "map" ? <GraphMap map={map} onOpenClaim={setClaimId}/> : tab === "claims" ? <ClaimsTab request={request} base={base} summary={summary} onOpenClaim={setClaimId} version={version}/> : tab === "questions" ? <QuestionsTab request={request} base={base} onOpenClaim={setClaimId} version={version} onChanged={refresh}/> : <RunsTab request={request} base={base} summary={summary} version={version}/>}
    {claimId && <ClaimDrawer claimId={claimId} request={request} projectId={project.id} onClose={() => setClaimId(null)} onOpenClaim={setClaimId} onChanged={refresh}/>}
  </section>;
}

export { KnowledgeGraphWorkspace };
