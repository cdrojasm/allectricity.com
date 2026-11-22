import React, { useEffect, useId, useState } from "react";
import { ChevronDown, ChevronRight, Download, X } from "lucide-react";
import { evaluateResult, formatNumber } from "../resultInterpretation.js";
import { bomCsv, bomRows } from "../bom.js";
import { download } from "../shared.jsx";
import { EmptyState } from "./EmptyState.jsx";
import { IconAgent, IconCatalog, IconCheckCircle, IconFailCircle, IconImprove, IconInfo, IconMaterials, IconOptimizer, IconOptions, IconSuggestion, IconWarning } from "../icons.jsx";

// Small «i» that explains a term on hover or keyboard focus.
export function InfoTip({ text, label = "Más información" }) {
  const id = useId();
  return <span className="info-tip" tabIndex={0} aria-label={label} aria-describedby={id}>
    <IconInfo size={13}/><span className="info-tip-bubble" role="tooltip" id={id}>{text}</span>
  </span>;
}

export const CRITERIA = {
  touch: { label: "Tensión de contacto", tip: "Diferencia de potencial entre la mano que toca una estructura conectada a la malla y los pies sobre el suelo, durante una falla." },
  step: { label: "Tensión de paso", tip: "Diferencia de potencial entre los dos pies, separados 1 m, sobre el suelo durante una falla." },
};
const TOLERABLE_TIP = "Máximo que el cuerpo humano soporta sin riesgo de fibrilación según la norma, para el tiempo de despeje, el peso corporal y la capa superficial definidos en Parámetros.";

function LimitBar({ label, tip, actual, limit, unit, unitLabel, inverse = false, ok }) {
  // Normal criteria must stay under the limit; the conductor section must stay over its minimum.
  const ratio = inverse ? limit / actual : actual / limit;
  const fill = Number.isFinite(ratio) ? Math.min(1, ratio) : 0;
  const times = Number.isFinite(ratio) && ratio > 1 ? `${formatNumber(ratio, 1)} veces ${inverse ? "por debajo de la mínima" : "el límite"}` : null;
  return <div className={`limit-row ${ok ? "ok" : "fails"}`}>
    <div className="limit-row-head">
      <span className="limit-row-title">{label}{tip && <InfoTip text={tip}/>}</span>
      <span className={`limit-chip ${ok ? "ok" : "fails"}`}>{ok ? "Dentro del límite" : inverse ? "Sección insuficiente" : "Supera el límite"}</span>
    </div>
    <div className="limit-bar" aria-hidden="true"><i style={{ width: `${fill * 100}%` }}/>{!ok && !inverse && <b/>}</div>
    <div className="limit-row-values">
      <span><small>{inverse ? "Elegida" : "Calculada"}</small><strong>{formatNumber(actual, 1)} {unit}</strong></span>
      <span><small>{inverse ? "Mínima" : <>Tolerable <InfoTip text={TOLERABLE_TIP} label="Qué es la tensión tolerable"/></>}</small><strong>{formatNumber(limit, 1)} {unit}</strong></span>
      {times && <span className="limit-times">{times}</span>}
      {unitLabel && <span className="limit-times muted">{unitLabel}</span>}
    </div>
  </div>;
}

// One connected block: the verdict, what fails and why, every limit with its value, and what to do next.
export function VerdictCallout({ result, footer, compact = false }) {
  const { verdict, interpretation, safety } = evaluateResult(result);
  const standards = [...new Set(safety.map((s) => s.standard))].join(", ") || "la norma evaluada";
  const thermal = result?.conductor_thermal;
  const title = verdict === "cumple" ? `Cumple ${standards}` : verdict === "no_cumple" ? `No cumple ${standards}` : "Cumplimiento sin evaluar";
  const lead = verdict === "cumple" ? "Las tensiones que puede sentir una persona durante una falla y la sección del conductor están dentro de los límites."
    : verdict === "no_cumple" ? "Durante una falla, una persona en la subestación quedaría expuesta a una tensión mayor de la que tolera. Ajusta el diseño antes de presentarlo."
      : interpretation.explanation;
  const Icon = verdict === "cumple" ? IconCheckCircle : verdict === "no_cumple" ? IconFailCircle : IconWarning;
  const criteria = safety.flatMap((standard) => (standard.criteria || []).map((criterion) => ({ ...criterion, standard: standard.standard })));
  return <section className={`verdict-callout ${verdict}${compact ? " compact" : ""}`} aria-label="Veredicto del cálculo" data-testid="verdict-callout">
    <div className="verdict-callout-head"><span className="verdict-callout-icon"><Icon size={22}/></span><div><strong>{title}</strong><p>{lead}</p></div></div>
    {verdict === "no_cumple" && <dl className="verdict-callout-why"><div><dt>Qué no cumple</dt><dd>{interpretation.constraint}</dd></div><div><dt>Por qué</dt><dd>{interpretation.explanation}</dd></div></dl>}
    {!compact && (criteria.length > 0 || thermal) && <div className="verdict-callout-limits">
      {criteria.map((criterion, index) => <LimitBar key={`${criterion.standard}-${criterion.criterion}-${index}`} label={CRITERIA[criterion.criterion]?.label || criterion.criterion} tip={CRITERIA[criterion.criterion]?.tip}
        actual={criterion.actual_v} limit={criterion.tolerable_v} unit="V" ok={criterion.status === "cumple"}/>)}
      {thermal && Number.isFinite(Number(thermal.selected_section_mm2)) && <LimitBar label="Sección del conductor" inverse unit="mm²"
        tip="El conductor debe soportar la corriente de falla durante el tiempo de despeje sin fundirse ni dañar sus uniones. La sección elegida debe ser al menos la mínima térmica."
        actual={thermal.selected_section_mm2} limit={thermal.minimum_section_mm2} ok={thermal.status === "cumple"}/>}
    </div>}
    {footer}
  </section>;
}

// Every way to improve the design, behind one button inside the verdict.
export function ImproveDesign({ verdict, suggestions = [], onSuggestion, agent, onOpenMatherra, children }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  return <div className="improve-design">
    <button type="button" className={`button ${verdict === "no_cumple" ? "primary" : ""} improve-toggle`} aria-expanded={open} aria-controls={panelId} onClick={() => setOpen((value) => !value)}>
      <IconImprove size={15}/>{verdict === "no_cumple" ? "Cómo hacer que cumpla" : "Cómo mejorar el diseño"}{open ? <ChevronDown size={14}/> : <ChevronRight size={14}/>}
    </button>
    {open && <div className="improve-panel" id={panelId}>
      {suggestions.length > 0 && <article className="improve-option">
        <span className="improve-option-icon"><IconSuggestion size={17}/></span>
        <div><h4>Ajustes sugeridos</h4><p>Cambios concretos para la restricción que domina. El agente los aplica en una versión nueva y recalcula.</p>
          <div className="improve-suggestions">{suggestions.map((action) => <button type="button" className="button" key={action} onClick={() => onSuggestion?.(action)}>{action}</button>)}</div></div>
      </article>}
      <article className="improve-option">
        <span className="improve-option-icon"><IconAgent size={17}/></span>
        <div><h4>Iterar con el agente <span className="improve-tag">Asistido</span></h4><p>El agente propone ajustes a la malla, guarda cada uno como versión y la recalcula hasta cumplir o agotar las iteraciones.</p>
          {agent.available
            ? <button type="button" className="button" data-testid="optimize-until-compliant" disabled={agent.disabled} onClick={agent.onRun}><IconAgent size={14}/>{agent.label}</button>
            : <small className="improve-requirement">{agent.requirement}</small>}</div>
      </article>
      <article className="improve-option">
        <span className="improve-option-icon matherra"><IconOptimizer size={17}/></span>
        <div><h4>Optimizar con Matherra <span className="improve-tag matherra">Matemático</span></h4><p>Busca y compara trazados por costo y seguridad dentro de las áreas intervenibles, con las tarifas que definas en el plano.</p>
          <button type="button" className="button" data-testid="open-matherra-optimizer" onClick={onOpenMatherra}>Configurar Matherra <ChevronRight size={14}/></button></div>
      </article>
    </div>}
    {children}
  </div>;
}

// Model assumptions shown first, so the reader weighs the verdict knowing them.
export function ModelWarnings({ warnings }) {
  if (!warnings?.length) return null;
  return <details className="model-warnings">
    <summary><IconWarning size={15}/><span><strong>Supuestos y límites del modelo</strong><small>{warnings.length === 1 ? "1 aspecto" : `${warnings.length} aspectos`} que el cálculo no representa. Tenlos en cuenta al leer el resultado.</small></span><ChevronDown size={14}/></summary>
    <ul>{warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
  </details>;
}

export function Metric({ label, value, unit, tip, hint }) {
  return <div className="result-metric"><small>{label}{tip && <InfoTip text={tip}/>}</small><strong>{value}{unit && <span> {unit}</span>}</strong>{hint && <em>{hint}</em>}</div>;
}

export const SOLVER_FIELDS = {
  discretization_m: { title: "Longitud de los tramos del conductor", help: "El conductor se divide en tramos para calcular cómo reparte la corriente hacia el suelo. Tramos más cortos dan un resultado más preciso, pero el cálculo tarda más.", options: [0.25, 0.5, 1, 2, 5].map((value) => [value, `${formatNumber(value, 2)} m`]) },
  segmentation: { title: "Reparto de los tramos", help: "«Graduada» usa tramos más cortos cerca de cruces, extremos y varillas, donde la corriente se concentra; es la opción recomendada. «Uniforme» usa tramos iguales en toda la malla.", options: [["graded", "Graduada en cruces y extremos"], ["uniform", "Uniforme"]] },
  surface_spacing_m: { title: "Detalle del mapa de superficie", help: "Separación entre los puntos del suelo donde se calcula el potencial. Define el detalle del mapa y la búsqueda del peor contacto y del peor paso.", options: [0.25, 0.5, 1].map((value) => [value, `Un punto cada ${formatNumber(value, 2)} m`]) },
  touch_reach_m: { title: "Dónde se busca la tensión de contacto", help: "IEEE 80 la evalúa dentro del perímetro de la malla, donde están los equipos. Amplíala si hay cercas o estructuras metálicas conectadas fuera de ella.", options: [[0, "Dentro del perímetro de la malla"], ...[0.5, 1, 2].map((value) => [value, `Hasta ${formatNumber(value, 1)} m fuera de la malla`])] },
};

// The solver settings live next to «Recalcular», each with what it changes.
export function CalculationOptionsDialog({ config, layers, busy, onChange, onClose, onRecalculate }) {
  const [draft, setDraft] = useState(config);
  useEffect(() => {
    const onKey = (event) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const set = (key, value) => setDraft((current) => ({ ...current, [key]: value }));
  const justificationShort = draft.justification.trim().length < 10;
  return <div className="app-dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="app-dialog" role="dialog" aria-modal="true" aria-labelledby="calc-options-title">
      <header className="app-dialog-header"><div><span className="app-dialog-icon"><IconOptions size={18}/></span><div><h2 id="calc-options-title">Opciones del cálculo</h2><p>Cómo el motor resuelve la malla. Los valores predeterminados sirven para la mayoría de los diseños.</p></div></div><button type="button" className="icon-button" aria-label="Cerrar opciones del cálculo" onClick={onClose}><X size={17}/></button></header>
      <div className="app-dialog-body calc-options">
        {Object.entries(SOLVER_FIELDS).map(([key, field]) => <label className="calc-option" key={key}>
          <span className="calc-option-title">{field.title}</span>
          <span className="calc-option-help">{field.help}</span>
          <select className="app-select" value={draft[key]} onChange={(event) => set(key, event.target.value)}>{field.options.map(([value, text]) => <option value={value} key={value}>{text}</option>)}</select>
        </label>)}
        <label className="calc-option calc-option-check">
          <span className="app-switch"><input type="checkbox" checked={draft.estimate_uncertainty} onChange={(event) => set("estimate_uncertainty", event.target.checked)}/><i/></span>
          <span><span className="calc-option-title">Estimar la incertidumbre numérica</span><span className="calc-option-help">Repite el cálculo con tramos más finos para medir cuánto cambia el resultado. Tarda cerca del doble.</span></span>
        </label>
        <label className="calc-option">
          <span className="calc-option-title">Justificación</span>
          <span className="calc-option-help">Por qué usas esta configuración. Queda registrada con el cálculo para la trazabilidad del estudio.</span>
          <textarea className="app-input" value={draft.justification} maxLength={500} onChange={(event) => set("justification", event.target.value)}/>
          {justificationShort && <small className="calc-option-error">Escribe al menos 10 caracteres.</small>}
        </label>
        <p className="calc-option-note"><IconInfo size={13}/> El modelo de suelo tiene {layers ? `${layers} ${layers === 1 ? "capa" : "capas"}` : "capas pendientes"}; se define en la pestaña Suelo.</p>
      </div>
      <footer className="app-dialog-footer">
        <button type="button" className="button" onClick={onClose}>Cancelar</button>
        <button type="button" className="button" disabled={justificationShort} onClick={() => { onChange(draft); onClose(); }}>Guardar</button>
        <button type="button" className="button primary" disabled={justificationShort || busy} onClick={() => { onChange(draft); onRecalculate(draft); onClose(); }}>Guardar y recalcular</button>
      </footer>
    </section>
  </div>;
}

export function BillOfMaterialsTable({ bom }) {
  const rows = bomRows(bom);
  return <table className="bom-table"><thead><tr><th>Material</th><th>Especificación</th><th className="num">Cantidad</th><th>Unidad</th></tr></thead>
    <tbody>{rows.map((row) => <tr key={`${row.group}-${row.name}-${row.spec}`}><td><strong>{row.name}</strong><small>{row.group}</small></td><td>{row.spec}</td><td className="num">{row.quantity}</td><td>{row.unit}</td></tr>)}</tbody></table>;
}

// Workspace «Materiales» tab: the take-off of the current version.
export function BillOfMaterialsPanel({ project, conversation, token, refreshKey, onOpenCatalog }) {
  const [state, setState] = useState({ status: "loading" });
  useEffect(() => {
    let live = true;
    const headers = { Authorization: `Bearer ${token}` };
    (async () => {
      try {
        const root = `/api/v1/projects/${project.id}/artefactos-diseno-tierras`;
        const [agentState, artifacts] = await Promise.all([
          conversation ? fetch(`/api/v1/conversations/${conversation.id}/agent-state`, { headers }).then((r) => (r.ok ? r.json() : null)) : null,
          fetch(root, { headers }).then((r) => (r.ok ? r.json() : [])),
        ]);
        const artifact = artifacts.find((row) => row.artifact_id === agentState?.artifact_id) || artifacts[0];
        if (!artifact) { if (live) setState({ status: "empty" }); return; }
        const response = await fetch(`${root}/${artifact.artifact_id}/versions/${artifact.version}/materiales`, { headers });
        if (!response.ok) throw new Error();
        const body = await response.json();
        if (live) setState({ status: body.bill_of_materials ? "ready" : "empty", bom: body.bill_of_materials, version: artifact.version, name: artifact.name });
      } catch { if (live) setState({ status: "error" }); }
    })();
    return () => { live = false; };
  }, [project.id, conversation?.id, token, refreshKey]);
  const { bom } = state;
  const rows = bomRows(bom);
  return <section className="panel artifact-side-panel bom-panel">
    <div className="panel-heading"><div><IconMaterials size={17}/><h2>Lista de materiales</h2></div><div className="artifact-results-heading-actions">{state.version && <span className="muted-label">Versión {state.version}</span>}{onOpenCatalog && <button type="button" className="button" onClick={onOpenCatalog} title="Precios aprobados para cotizar estos materiales"><IconCatalog size={14}/> Catálogo de materiales</button>}{bom && <button type="button" className="button" onClick={() => download(`materiales-${project.name}-v${state.version}.csv`, `﻿${bomCsv(rows)}`, "text/csv")}><Download size={14}/> Exportar CSV</button>}</div></div>
    {state.status === "loading" && <p className="panel-empty-text">Calculando cantidades…</p>}
    {state.status === "error" && <p className="panel-empty-text">No se pudo cargar la lista de materiales.</p>}
    {state.status === "empty" && <EmptyState art="materials" title="Aún no hay materiales que listar" description="La lista sale de la geometría de la malla: conductor, varillas, conexiones y zanja. Cuando el diseño tenga una malla aparecerá aquí, lista para cotizar."/>}
    {bom && <>
      <p className="panel-lead">Cantidades tomadas de la geometría de la versión {state.version}. Úsalas como base para cotizar; no incluyen desperdicio, traslapos ni holguras de instalación.</p>
      <div className="result-metric-grid">
        <Metric label="Conductor" value={formatNumber((bom.conductor || []).reduce((sum, line) => sum + Number(line.length_m || 0), 0), 1)} unit="m"/>
        <Metric label="Varillas" value={formatNumber(bom.rods_total?.count ?? 0, 0)} unit="und" hint={bom.rods_total?.length_m ? `${formatNumber(bom.rods_total.length_m, 1)} m en total` : null}/>
        <Metric label="Conexiones" value={formatNumber(bom.connections ?? 0, 0)} unit="und" hint={bom.connections_by_type ? `${formatNumber(bom.connections_by_type.conductor_conductor, 0)} conductor–conductor · ${formatNumber(bom.connections_by_type.conductor_rod, 0)} conductor–electrodo` : null} tip="Conductor–conductor: cada cruce o unión en T de la malla. Conductor–electrodo: la unión de cada varilla a la malla. Suelen ser de tipos distintos (molde de soldadura exotérmica o conector), por eso se cotizan aparte."/>
        <Metric label="Zanja" value={formatNumber(bom.trench?.length_m ?? 0, 1)} unit="m" hint={bom.trench?.depth_m ? `a ${formatNumber(bom.trench.depth_m, 2)} m de profundidad` : null}/>
      </div>
      <div className="bom-table-wrap"><BillOfMaterialsTable bom={bom}/></div>
      {bom.cost && <p className="panel-lead"><strong>Costo estimado:</strong> {formatNumber(bom.cost.total, 0)} {bom.cost.currency || ""}. {bom.cost.note}</p>}
      {bom.notes?.length > 0 && <ul className="panel-notes">{bom.notes.map((note) => <li key={note}>{note}</li>)}</ul>}
    </>}
  </section>;
}

// What the calculation needs, in engineering words, and where each item is filled in.
const INPUT_PLACES = {
  plan: "Plano", soil: "Suelo", safety: "Parámetros",
};
const MISSING_TEXT = {
  geometry: ["La malla", "Dibújala en el editor de plano o pídele al agente una retícula.", "plan"],
  "networks/electrodes": ["La malla o los electrodos", "Dibújalos en el editor de plano.", "plan"],
  soil_layers: ["El modelo de suelo", "Ajusta las capas con tus mediciones o ingrésalas por materiales.", "soil"],
  "soil_layers.resistivity_ohm_m": ["La resistividad de alguna capa del suelo", "Completa la resistividad de cada capa.", "soil"],
  "fault.current_a": ["La corriente de falla", "Es la corriente que la malla debe disipar (A).", "safety"],
  "fault.clearing_time_s": ["El tiempo de despeje de la falla", "Cuánto tarda la protección en despejarla (s).", "safety"],
  "fault.surface_resistivity_ohm_m": ["La resistividad de la capa superficial", "La grava o el material sobre el terreno (Ω·m).", "safety"],
  "fault.surface_thickness_m": ["El espesor de la capa superficial", "Espesor de la grava o el material superficial (m).", "safety"],
};
export const CRITICAL_INPUTS = ["soil_layers", "fault.current_a", "fault.clearing_time_s", "fault.surface_resistivity_ohm_m", "fault.surface_thickness_m"];
const pathValue = (snapshot, path) => path.split(".").reduce((value, key) => value?.[key], snapshot);

// Same rule as the backend's unconfirmed_critical: a critical value the agent assumed blocks the calculation.
export function unconfirmedInputs(artifact) {
  const provenance = artifact?.origin?.provenance;
  if (!provenance || !Object.keys(provenance).length) return [];
  return CRITICAL_INPUTS.filter((path) => {
    const value = pathValue(artifact.snapshot, path);
    const kind = provenance[path]?.kind;
    return value == null || (Array.isArray(value) && !value.length) || !kind || ["schema_default", "assumption"].includes(kind);
  });
}

export function MissingInputs({ missing = [], unconfirmed = [], coherence = [], onNavigate, onOpenPlan }) {
  if (!missing.length && !unconfirmed.length && !coherence.length) return null;
  const go = (section) => (section === "plan" ? onOpenPlan?.() : onNavigate?.(section));
  const describe = (path) => MISSING_TEXT[path] || (path.startsWith("geometry") ? [`Dato de la malla (${path.replace("geometry.", "")})`, "Revísalo en el plano.", "plan"] : path.startsWith("soil") ? ["Dato del suelo", "Revísalo en Suelo.", "soil"] : [path, "Revísalo en Parámetros.", "safety"]);
  const row = (path, kind) => { const [label, hint, section] = describe(path); return <li key={`${kind}-${path}`}><span className={`missing-dot ${kind}`}/><div><strong>{label}</strong><small>{kind === "unconfirmed" ? "El agente lo supuso y nadie lo ha confirmado. Revísalo y guárdalo tú para confirmarlo." : hint}</small></div>{(onNavigate || onOpenPlan) && <button type="button" className="button" onClick={() => go(section)}>Ir a {INPUT_PLACES[section]} <ChevronRight size={13}/></button>}</li>; };
  return <section className="missing-inputs" aria-label="Lo que falta para calcular" data-testid="missing-inputs">
    <div className="missing-inputs-head"><IconWarning size={18}/><div><strong>Para calcular falta completar {missing.length + unconfirmed.length + coherence.length === 1 ? "un dato" : `${missing.length + unconfirmed.length + coherence.length} datos`}</strong><p>Cuando estén completos, «Recalcular» se habilita.</p></div></div>
    <ul>
      {missing.map((path) => row(path, "missing"))}
      {unconfirmed.map((path) => row(path, "unconfirmed"))}
      {coherence.map((item, index) => <li key={`coherence-${index}`}><span className="missing-dot incoherent"/><div><strong>Datos incoherentes</strong><small>{item.message}</small></div></li>)}
    </ul>
  </section>;
}
