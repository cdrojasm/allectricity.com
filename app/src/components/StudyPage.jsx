import React, { Suspense, lazy, useEffect, useRef, useState } from "react";
import { ArrowDown, ArrowUp, Check, ExternalLink, GripVertical, Link2, Plus, Trash2, Upload } from "lucide-react";
import { Icon3D, IconAgent, IconInputs, IconMaterials, IconOptimizer, IconPlan, IconPotential, IconReferences, IconReport, IconResult, IconText } from "../icons.jsx";
import { BillOfMaterialsTable } from "./ResultBlocks.jsx";
import { EmptyState } from "./EmptyState.jsx";
import { fieldLabel, fieldValueLabel, pdfStatusLabels, rateLabels, referenceText, studyStatusLabels } from "../labels.js";
import { SurfacePotentialMap } from "./GroundingCalculations.jsx";
import { ArtifactGrid, gridPlan } from "./AgentArtifact.jsx";

const Surface3D = lazy(() => import("./Surface3D.jsx"));
import { criterionLabel, evaluateResult, formatNumber, verdictLabels } from "../resultInterpretation.js";
import { awaitJob } from "../asyncJobs.js";

async function jsonRequest(url, options = {}) {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body.detail;
    throw Object.assign(new Error(detail?.message || (typeof detail === "string" ? detail : "No se pudo completar la operación.")), { code: detail?.code, detail });
  }
  return body;
}

const display = (value, unit = "", digits = 2) => (value === undefined || value === null || value === "" ? "—" : `${formatNumber(value, digits)}${unit ? ` ${unit}` : ""}`);

// Explicit rods carry their own length (SV-28); perimeter rods share rod_length_m.
function rodsSummary(geometry) {
  const rods = Array.isArray(geometry.rods) ? geometry.rods : [];
  if (rods.length) {
    const lengths = new Map();
    rods.forEach((rod) => { const length = Number(rod.length_m ?? geometry.rod_length_m ?? 2.4); lengths.set(length, (lengths.get(length) || 0) + 1); });
    const parts = [...lengths.entries()].sort((a, b) => a[0] - b[0]).map(([length, count]) => `${count} × ${display(length, "m")}`);
    return `${rods.length} (${parts.join(", ")})`;
  }
  return geometry.rods_count ? `${geometry.rods_count} × ${display(geometry.rod_length_m, "m")}` : "Sin varillas";
}

function StudyBillOfMaterials({ bom, title = "Lista de materiales" }) {
  if (!bom) return null;
  return <section data-testid="study-bom">
    <h2>{title}</h2>
    <BillOfMaterialsTable bom={bom} adjustments={bom.adjustments || {}}/>
    {bom.cost && <p data-testid="study-bom-cost"><strong>Costo estimado:</strong> {formatNumber(bom.cost.total, 0)} {bom.cost.currency || ""}{bom.cost.by_group ? ` (${Object.entries(bom.cost.by_group).map(([group, amount]) => `${rateLabels[group] || group}: ${formatNumber(Number(amount), 0)}`).join(" · ")})` : ""}. {bom.cost.note}</p>}
    {bom.notes?.length > 0 && <ul className="study-references">{bom.notes.map((note) => <li key={note}>{note}</li>)}</ul>}
  </section>;
}

function StudyInputs({ artifact, version, thermal, showPlan = true }) {
  const geometry = artifact.geometry || {}; const fault = artifact.fault || {}; const conductor = artifact.conductor || {}; const layers = artifact.soil_layers || [];
  const spacing = geometry.conductor_spacing_x_m && geometry.conductor_spacing_y_m ? `${display(geometry.conductor_spacing_x_m, "", 2)} × ${display(geometry.conductor_spacing_y_m, "", 2)} m` : display(geometry.conductor_spacing_m, "m");
  const groups = [
    ["Malla", [["Dimensiones", `${display(geometry.length_m, "", 2)} × ${display(geometry.width_m, "", 2)} m`], ["Retícula", spacing], ["Profundidad", display(geometry.burial_depth_m, "m")], ["Varillas", rodsSummary(geometry)]]],
    ["Falla", [["Corriente", display(fault.current_a, "A", 0)], ["Tiempo de despeje", display(fault.clearing_time_s, "s")], ["Capa superficial", fault.surface_resistivity_ohm_m ? `${display(fault.surface_resistivity_ohm_m, "Ω·m", 0)} · ${display(fault.surface_thickness_m, "m")}` : "Sin capa superficial"]]],
    ["Conductor", [["Material", fieldValueLabel("conductor.material_id", conductor.material_name || thermal?.material_name || conductor.material_id || "—")], ["Sección", display(conductor.cross_section_mm2, "mm²")], ...(thermal?.profile ? [["Norma", thermal.profile]] : [])]],
  ];
  return <div className="study-inputs">
    {showPlan && (geometry.length_m || geometry.conductors?.length) ? <figure className="study-plan" data-testid="study-plan"><ArtifactGrid geometry={geometry}/><figcaption>Plano de la malla de la versión publicada.</figcaption></figure> : null}
    {groups.map(([title, rows]) => <div className="study-input-group" key={title}><h3>{title}</h3><dl>{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl></div>)}
    <div className="study-input-group"><h3>Suelo</h3>{layers.length ? <dl>{layers.map((layer, index) => <div key={index}><dt>Capa {index + 1}{layer.material ? ` · ${layer.material}` : ""}</dt><dd>{display(layer.resistivity_ohm_m, "Ω·m", 1)}{layer.depth_m ? ` · ${display(layer.depth_m, "m")}` : " · semiinfinita"}</dd></div>)}</dl> : <p className="study-muted">Sin capas registradas.</p>}</div>
    <p className="study-muted">Versión del diseño: {version}</p>
  </div>;
}

function StudyResult({ calculation, summary, showMap = true }) {
  const result = calculation?.result;
  if (!result?.safety) {
    if (!summary?.verdict || summary.verdict === "no_evaluado") return <p className="study-muted" data-testid="study-verdict">Pendiente de cálculo.</p>;
    return <><div className={`agent-verdict ${summary.verdict} study-verdict`} data-testid="study-verdict">{verdictLabels[summary.verdict] || summary.verdict}</div><p className="study-disclaimer" data-testid="study-disclaimer">Verificación de prefactibilidad; requiere revisión de un ingeniero competente.</p></>;
  }
  const { verdict, interpretation, safety } = evaluateResult(result);
  const thermal = result.conductor_thermal;
  const reach = Number(calculation.parameters?.touch_reach_m) > 0;
  return <div className="study-result-view">
    <div className={`agent-verdict ${verdict} study-verdict`} data-testid="study-verdict">{verdictLabels[verdict]}</div>
    <div className="study-interpretation" data-testid="study-interpretation"><div><small>Restricción dominante</small><strong>{interpretation.constraint}</strong></div><div><small>Por qué</small><span>{interpretation.explanation}</span></div></div>
    <div className="study-grid study-metrics"><div><small>Resistencia de malla</small><strong>{formatNumber(result.grid_resistance_ohm, 3)} Ω</strong></div><div><small>GPR</small><strong>{formatNumber(result.gpr_v)} V</strong></div><div><small>Corriente inyectada</small><strong>{formatNumber(result.injected_current_a)} A</strong></div></div>
    {safety.map((standard) => <table className="study-table" key={standard.standard}><caption>{standard.standard}</caption><thead><tr><th>Criterio</th><th>Calculado</th><th>Tolerable</th><th>Margen</th><th>Estado</th></tr></thead><tbody>{(standard.criteria || []).map((criterion) => <tr key={criterion.criterion} className={criterion.status === "cumple" ? "" : "agent-fails"}><td>{criterionLabel(criterion.criterion)}</td><td>{formatNumber(criterion.actual_v)} V</td><td>{formatNumber(criterion.tolerable_v)} V</td><td>{formatNumber(100 * criterion.margin_rel)} %</td><td>{criterion.status === "cumple" ? "Cumple" : "No cumple"}</td></tr>)}</tbody></table>)}
    {thermal && <p className={thermal.status === "cumple" ? "" : "agent-fails"} data-testid="study-thermal"><strong>Conductor (térmico):</strong> sección {formatNumber(thermal.selected_section_mm2)} mm² · mínima {formatNumber(thermal.minimum_section_mm2)} mm² · {thermal.status === "cumple" ? "cumple" : "no cumple"}</p>}
    {showMap && result.surface_potential && <figure className="study-map" data-testid="study-map"><SurfacePotentialMap field={result.surface_potential}/><figcaption>Contacto evaluado sobre la malla ({formatNumber(result.surface_potential.grid_width_m)} × {formatNumber(result.surface_potential.grid_height_m)} m{reach ? `, ${calculation.parameters.touch_reach_m} m fuera del perímetro` : ", dentro del perímetro"}); paso en todo el terreno, salvo dentro de construcciones.</figcaption></figure>}
    {result.model_warnings?.length > 0 && <div className="study-model-warnings"><strong>Advertencias del modelo</strong><ul>{result.model_warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div>}
    <p className="study-disclaimer" data-testid="study-disclaimer">Verificación de prefactibilidad; requiere revisión de un ingeniero competente.</p>
  </div>;
}

const rateSourceText = (rate) => (rate.source_type === "catalog" ? `Catálogo aprobado${rate.catalog_version ? ` (versión ${rate.catalog_version})` : ""}` : rate.source || "—");
const savingText = (saving, currency) => (saving ? `${saving.kind === "saving" ? "Ahorro" : "Diferencia de costo"}: ${display(saving.amount, currency, 0)} (${formatNumber(100 * saving.fraction, 1)} %)` : null);

// The optimizer's applied alternative against the base design it started from; a draft, never certified.
function StudyOptimization({ optimization }) {
  if (!optimization) return null;
  if (!optimization.available) return <section data-testid="study-optimization"><h2>Optimización del diseño</h2><p className="study-muted">Esta versión proviene del optimizador, pero la corrida ya no está disponible. No está certificada.</p></section>;
  const { alternative, base, currency } = optimization;
  const baseStatus = base.status === "VIOLATED" ? "No cumple" : base.feasible === true ? "Sin violaciones" : "No evaluado";
  const rows = [
    ["Costo", display(base.cost, currency, 0), display(alternative?.cost, currency, 0)],
    ["Resistencia de malla", "—", display(alternative?.Rg_ohm, "Ω", 3)],
    ["Tensión de paso", "—", display(alternative?.Vs_v, "V", 0)],
    ["Tensión de contacto", "—", display(alternative?.Vt_v, "V", 0)],
    ["Utilización", display(base.ratio !== undefined && base.ratio !== null ? 100 * base.ratio : null, "%", 0), display(alternative?.utilization_ratio !== undefined && alternative?.utilization_ratio !== null ? 100 * alternative.utilization_ratio : null, "%", 0)],
    ["Cumplimiento", baseStatus, alternative ? "Sin violaciones en el nivel más fino" : "—"],
  ];
  return <section data-testid="study-optimization">
    <h2>Optimización del diseño</h2>
    <p>Esta versión aplica una alternativa del optimizador de topología sobre la versión {optimization.based_on_version}. <strong>Borrador sin certificar</strong>: requiere aprobación de un profesional competente.</p>
    <table className="study-table"><caption>Alternativa aplicada frente al diseño base</caption><thead><tr><th></th><th>Diseño base</th><th>Alternativa aplicada</th></tr></thead><tbody>{rows.map(([label, a, b]) => <tr key={label}><td>{label}</td><td>{a}</td><td>{b}</td></tr>)}</tbody></table>
    {savingText(optimization.saving, currency) && <p data-testid="study-optimization-saving"><strong>{savingText(optimization.saving, currency)}</strong></p>}
    {optimization.rates?.length > 0 && <><h3>Procedencia de las tarifas</h3><ul className="study-references" data-testid="study-optimization-rates">{optimization.rates.map((rate) => <li key={rate.item}><strong>{rateLabels[rate.item] || rate.item}</strong> · {rateSourceText(rate)}</li>)}</ul></>}
    {optimization.warnings?.length > 0 && <div className="study-model-warnings" data-testid="study-optimization-warnings"><strong>Advertencias</strong><ul>{optimization.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div>}
  </section>;
}

const formatDateTime = (seconds) => new Date(seconds * 1000).toLocaleString("es-CO", { dateStyle: "long", timeStyle: "short" });
// <input type="datetime-local"> works in local time; converting through toISOString shifted every save by the UTC offset.
const toLocalInput = (seconds) => { if (!seconds) return ""; const date = new Date(seconds * 1000); return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16); };
const fromLocalInput = (value) => (value ? Math.floor(new Date(value).getTime() / 1000) : null);

// The state a viewer of the link meets, with its date: what the workspace must show next to each study.
function linkState(study) {
  if (!study) return { key: "draft", label: "Borrador" };
  if (study.status === "revoked") return { key: "revoked", label: "Revocado", detail: study.updated_at ? `Revocado el ${formatDateTime(study.updated_at)}` : "Revocado" };
  if (study.status === "draft") return { key: "draft", label: "Borrador", detail: study.expires_at ? `Vencerá el ${formatDateTime(study.expires_at)}` : "Sin fecha de vencimiento" };
  if (study.expires_at && study.expires_at * 1000 <= Date.now()) return { key: "expired", label: "Vencido", detail: `Venció el ${formatDateTime(study.expires_at)}` };
  return { key: "published", label: "Publicado", detail: study.expires_at ? `Vigente hasta el ${formatDateTime(study.expires_at)}` : "Vigente, sin fecha de vencimiento" };
}

const paragraphs = (text) => String(text || "").split(/\n{2,}/).map((part) => part.trim()).filter(Boolean);

function StudyReferences({ references, text, title = "Referencias y trazabilidad" }) {
  return <section><h2>{title}</h2><p>{text || "Los valores publicados conservan su origen técnico."}</p>{references?.length > 0 && <><ul className="study-references" data-testid="study-references">{references.map((item) => <li key={item.path}><strong>{fieldLabel(item.path)}</strong> · {referenceText(item.reference)}</li>)}</ul><details className="study-audit"><summary>Detalle para auditoría</summary><ul className="study-references">{references.map((item) => <li key={item.path}><code>{item.path}</code> · {JSON.stringify(item.reference)}</li>)}</ul></details></>}</section>;
}

const viewsOf = (block) => (block.view === "both" ? ["general", "detail"] : [block.view === "detail" ? "detail" : "general"]);

// One element of a report composed in «Compartir estudio».
function StudyBlock({ block, data }) {
  const { study, artifact } = data;
  const heading = (fallback) => (block.title ?? fallback) ? <h2>{block.title ?? fallback}</h2> : null;
  switch (block.type) {
    case "text": case "ai_text": return paragraphs(block.text).length ? <section>{heading("")}{paragraphs(block.text).map((part, index) => <p key={index}>{part}</p>)}</section> : null;
    case "inputs": return <section data-testid="study-inputs">{heading("Datos del diseño")}<StudyInputs artifact={artifact} version={study.artifact_version} thermal={data.calculation?.result?.conductor_thermal} showPlan={false}/></section>;
    case "plan": return artifact.geometry?.length_m || artifact.geometry?.conductors?.length ? <section>{heading("Plano de la malla")}{viewsOf(block).map((view) => <figure className="study-plan" data-testid="study-plan" key={view}><ArtifactGrid geometry={artifact.geometry} view={view}/><figcaption>{view === "detail" ? "Detalle de la malla" : "Plano general del terreno"} · versión {study.artifact_version}.</figcaption></figure>)}</section> : null;
    case "result": return <section data-testid="study-results">{heading("Resultado")}<StudyResult calculation={data.calculation} summary={artifact.result} showMap={false}/></section>;
    case "potential_map": { const field = data.calculation?.result?.surface_potential; return field ? <section>{heading("Potencial en la superficie")}{viewsOf(block).map((view) => <figure className="study-map" data-testid="study-map" key={view}><SurfacePotentialMap field={field} view={view}/></figure>)}</section> : null; }
    case "potential_3d": { const result = data.calculation?.result; const geometry = artifact.geometry; if (!result?.surface_potential || !geometry?.length_m) return null;
      return <section data-testid="study-3d">{heading("Vista 3D del potencial")}<Suspense fallback={<p className="study-muted">Cargando la vista 3D…</p>}><Surface3D embedded initialMode={block.mode === "potential" ? "potential" : "touch"} calculation={{ ...data.calculation, artifact_version: study.artifact_version }} plan={{ ...gridPlan(geometry), length: geometry.length_m, width: geometry.width_m, burialDepth: geometry.burial_depth_m || 0.5, rodLength: geometry.rod_length_m || 2.4 }}/></Suspense></section>; }
    case "bom": return <StudyBillOfMaterials bom={data.bill_of_materials} title={block.title ?? "Lista de materiales"}/>;
    case "optimization": return <StudyOptimization optimization={data.optimization}/>;
    case "references": return <StudyReferences references={data.references} text={block.text} title={block.title ?? "Referencias y trazabilidad"}/>;
    default: return null;
  }
}

export function PublicStudyPage({ slug }) {
  const [data, setData] = useState(null); const [error, setError] = useState(""); const [password, setPassword] = useState("");
  const renderToken = new URLSearchParams(window.location.search).get("render_token");
  async function load(url, options = {}) { try { setData(await jsonRequest(url, { ...options, headers: { ...(options.headers || {}), ...(renderToken ? { "X-Study-Render-Token": renderToken } : {}) } })); } catch (e) { setError(e); } }
  useEffect(() => { load(`/api/v1/public/studies/${encodeURIComponent(slug)}`); }, [slug]);
  if (error) {
    const reason = {
      expired: ["El enlace existe, pero venció", `Este estudio estuvo disponible hasta el ${error.detail?.expired_at ? formatDateTime(error.detail.expired_at) : "fin de su vigencia"}. Pídele a quien te lo compartió que amplíe la fecha o te envíe un enlace vigente.`],
      revoked: ["El enlace existe, pero fue revocado", `Quien publicó este estudio lo revocó${error.detail?.revoked_at ? ` el ${formatDateTime(error.detail.revoked_at)}` : ""}, así que ya no se puede consultar. Si lo necesitas, pídele una versión vigente.`],
      not_found: ["No encontramos este estudio", "Revisa que el enlace esté completo. Si te lo compartieron hace poco, puede que todavía no esté publicado."],
    }[error.code] || ["Estudio no disponible", error.message];
    return <main className="study-public"><div className={`study-card study-error ${error.code || ""}`} data-testid="study-error">{["expired", "revoked"].includes(error.code) && <span className={`study-error-badge ${error.code}`}>{error.code === "expired" ? "Vencido" : "Revocado"}</span>}<EmptyState art="report" title={reason[0]} description={reason[1]}/></div></main>;
  }
  if (!data) return <main className="study-public"><div className="study-card">Cargando estudio…</div></main>;
  if (data.requires_password) return <main className="study-public"><div className="study-card"><h1>{data.study.title}</h1><p>Este estudio requiere una contraseña.</p><form onSubmit={(e) => { e.preventDefault(); load(`/api/v1/public/studies/${encodeURIComponent(slug)}/access`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password }) }); }}><input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Contraseña"/><button className="button primary">Abrir estudio</button></form></div></main>;
  const { study, project, artifact } = data; const enabled = (id) => study.config?.sections?.find((s) => s.id === id)?.enabled !== false;
  const blocks = Array.isArray(study.config?.blocks) ? study.config.blocks : null;
  return <main className="study-public"><article className="study-document"><header className="study-header">{study.config?.logo_url && <img className="study-logo" src={study.config.logo_url} alt="Logo del estudio"/>}<div><div className="eyebrow">ESTUDIO DE PUESTA A TIERRA</div><h1>{study.title}</h1><p>{project.name}{project.city ? ` · ${project.city}` : ""}</p></div></header>{data.non_compliant && <div className="study-warning study-nonconforming" role="alert" data-testid="study-nonconforming"><strong>DISEÑO NO CONFORME</strong> · los resultados de este estudio no cumplen la norma evaluada.</div>}{data.draft && <div className="study-warning" role="status" data-testid="study-draft-warning"><strong>BORRADOR</strong> · {[data.unconfirmed_critical?.length ? `${data.unconfirmed_critical.length} supuesto(s) crítico(s) sin confirmar` : null, data.assumptions?.length ? `${data.assumptions.length} valor(es) supuesto(s) por el agente sin confirmar` : null].filter(Boolean).join(" · ") || "Este estudio contiene información pendiente de confirmar"}.{(data.unconfirmed_critical?.length > 0 || data.assumptions?.length > 0) && <ul>{[...(data.unconfirmed_critical || []), ...(data.assumptions || [])].map((path) => <li key={path}>{fieldLabel(path)}</li>)}</ul>}</div>}{data.has_newer_version && <div className="study-warning">Existe una versión más reciente. Este estudio conserva la versión {study.artifact_version} publicada.</div>}{blocks ? blocks.map((block) => <StudyBlock key={block.id} block={block} data={data}/>) : <>{enabled("summary") && <section><h2>Resumen</h2><p>{study.config?.sections?.find((s) => s.id === "summary")?.text || project.description || "Estudio calculado y trazable."}</p></section>}{enabled("inputs") && <section data-testid="study-inputs"><h2>Entradas</h2><StudyInputs artifact={artifact} version={study.artifact_version} thermal={data.calculation?.result?.conductor_thermal}/><p>{study.config?.sections?.find((s) => s.id === "inputs")?.text}</p></section>}{enabled("results") && <section data-testid="study-results"><h2>Resultado</h2><p>{study.config?.sections?.find((s) => s.id === "results")?.text}</p><StudyResult calculation={data.calculation} summary={artifact.result}/></section>}{enabled("results") && <StudyOptimization optimization={data.optimization}/>}{enabled("results") && <StudyBillOfMaterials bom={data.bill_of_materials}/>}{enabled("references") && <section><h2>Referencias y trazabilidad</h2><p>{study.config?.sections?.find((s) => s.id === "references")?.text || "Los valores publicados conservan su origen técnico."}</p>{data.references?.length > 0 && <><ul className="study-references" data-testid="study-references">{data.references.map((item) => <li key={item.path}><strong>{fieldLabel(item.path)}</strong> · {referenceText(item.reference)}</li>)}</ul><details className="study-audit"><summary>Detalle para auditoría</summary><ul className="study-references">{data.references.map((item) => <li key={item.path}><code>{item.path}</code> · {JSON.stringify(item.reference)}</li>)}</ul></details></>}</section>}</>}<footer>{study.config?.show_allectricity_brand !== false && study.config?.show_terra_brand !== false && <span>Publicado con Allectricity</span>}<button className="button" onClick={() => window.print()}>Guardar como PDF</button></footer></article></main>;
}


// Elements the user can add to the report, from the pool on the right of «Compartir estudio».
const BLOCK_TYPES = {
  text: { icon: IconText, label: "Texto", hint: "Un párrafo escrito por ti: alcance, contexto, conclusiones.", group: "Texto", repeatable: true },
  ai_text: { icon: IconAgent, label: "Texto generado con IA", hint: "Describe qué quieres y la IA lo redacta con los datos fijados del estudio.", group: "Texto", repeatable: true },
  result: { icon: IconResult, label: "Resultado del cálculo", hint: "Veredicto, restricción dominante y tabla de contacto, paso y sección térmica.", group: "Resultados calculados" },
  potential_map: { icon: IconPotential, label: "Mapa de potencial", hint: "La gráfica de potencial en la superficie con el perímetro de la malla.", group: "Resultados calculados" },
  potential_3d: { icon: Icon3D, label: "Vista 3D del potencial", hint: "Superficie 3D que el lector puede girar: la zona de la malla (contacto) o el terreno completo.", group: "Resultados calculados" },
  plan: { icon: IconPlan, label: "Plano de la malla", hint: "Conductores, varillas, zonas y elementos constructivos.", group: "Resultados calculados" },
  inputs: { icon: IconInputs, label: "Resumen de los datos", hint: "Malla, falla, conductor y capas del suelo usados en el cálculo.", group: "Resultados calculados" },
  bom: { icon: IconMaterials, label: "Lista de materiales", hint: "Conductor, varillas, conexiones y zanja de esta versión.", group: "Resultados calculados" },
  optimization: { icon: IconOptimizer, label: "Optimización", hint: "La alternativa de Matherra aplicada frente al diseño base, si existe.", group: "Resultados calculados" },
  references: { icon: IconReferences, label: "Referencias y trazabilidad", hint: "El origen de cada valor publicado: documentos, confirmaciones y supuestos.", group: "Anexos" },
};
const BLOCK_TITLES = { text: "", ai_text: "", result: "Resultado", potential_map: "Potencial en la superficie", potential_3d: "Vista 3D del potencial", plan: "Plano de la malla", inputs: "Datos del diseño", bom: "Lista de materiales", optimization: "Optimización del diseño", references: "Referencias y trazabilidad" };
const newBlockId = () => `bloque-${crypto.randomUUID().replace(/-/g, "").slice(0, 12)}`;
const makeBlock = (type, extra = {}) => ({ id: newBlockId(), type, title: BLOCK_TITLES[type], ...(type === "text" || type === "ai_text" ? { text: "" } : {}), ...(type === "ai_text" ? { instruction: "" } : {}), ...extra });

// Studies saved before the composer only have the four fixed sections: the same content, as blocks.
function blocksFromSections(config) {
  if (Array.isArray(config?.blocks)) return config.blocks;
  const sections = config?.sections || [];
  const section = (id) => sections.find((item) => item.id === id) || { enabled: true, text: "" };
  const blocks = [];
  if (section("summary").enabled !== false) blocks.push(makeBlock("text", { title: "Resumen", text: section("summary").text || "" }));
  if (section("inputs").enabled !== false) { if (section("inputs").text) blocks.push(makeBlock("text", { title: "", text: section("inputs").text })); blocks.push(makeBlock("inputs", { title: "Entradas" }), makeBlock("plan")); }
  if (section("results").enabled !== false) { if (section("results").text) blocks.push(makeBlock("text", { title: "", text: section("results").text })); blocks.push(makeBlock("result"), makeBlock("potential_map"), makeBlock("optimization"), makeBlock("bom")); }
  if (section("references").enabled !== false) blocks.push(makeBlock("references", { text: section("references").text || "" }));
  return blocks;
}

function ReportBlock({ block, index, total, generating, version, onChange, onMove, onRemove, onGenerate, drag }) {
  const type = BLOCK_TYPES[block.type] || { icon: IconText, label: block.type };
  const Icon = type.icon;
  const prose = block.type === "text" || block.type === "ai_text";
  return <article className={`report-block ${prose ? "prose" : "data"}${drag.dragging ? " dragging" : ""}`} data-testid="report-block" data-block-id={block.id}
    draggable={drag.armed} onDragStart={drag.onDragStart} onDragEnd={drag.onDragEnd}>
    <header>
      <span className="report-block-grip" title="Arrastra para reordenar" aria-hidden="true" onPointerDown={drag.arm} onPointerUp={drag.disarm}><GripVertical size={16}/></span>
      <span className="report-block-icon"><Icon size={16}/></span>
      <input className="report-block-title" aria-label={`Título de ${type.label}`} value={block.title ?? ""} placeholder={prose ? "Sin título" : BLOCK_TITLES[block.type]} onChange={(event) => onChange({ ...block, title: event.target.value })}/>
      <span className="report-block-type">{type.label}</span>
      <div className="report-block-tools">
        <button type="button" className="icon-button" aria-label="Subir" title="Subir" disabled={index === 0} onClick={() => onMove(-1)}><ArrowUp size={14}/></button>
        <button type="button" className="icon-button" aria-label="Bajar" title="Bajar" disabled={index === total - 1} onClick={() => onMove(1)}><ArrowDown size={14}/></button>
        <button type="button" className="icon-button danger" aria-label={`Quitar ${type.label}`} title="Quitar del informe" onClick={onRemove}><Trash2 size={14}/></button>
      </div>
    </header>
    {block.type === "ai_text" && <div className="report-block-ai">
      <input className="app-input" aria-label="Qué debe redactar la IA" value={block.instruction || ""} placeholder="Ej.: resume el resultado para el cliente en un párrafo, sin jerga" onChange={(event) => onChange({ ...block, instruction: event.target.value })}/>
      <button type="button" className="button" disabled={generating} onClick={onGenerate}><IconAgent size={14}/>{generating ? "Redactando…" : block.text ? "Volver a generar" : "Generar"}</button>
    </div>}
    {prose ? <textarea className="app-input" aria-label={`Texto de ${type.label}`} value={block.text || ""} disabled={generating} placeholder={block.type === "ai_text" ? "El texto generado aparecerá aquí y podrás editarlo." : "Escribe el texto de este bloque…"} onChange={(event) => onChange({ ...block, text: event.target.value })}/>
      : <p className="report-block-data">{type.hint} Se toma de la versión {version} fijada en el estudio.</p>}
    {["plan", "potential_map"].includes(block.type) && <div className="report-block-options"><span>Vista</span><div className="app-segmented" role="group" aria-label="Vista del bloque">
      {[["general", block.type === "plan" ? "Plano general" : "Terreno completo"], ["detail", "Detalle de la malla"], ["both", "Ambas"]].map(([value, text]) => <button type="button" key={value} className={(block.view || "general") === value ? "active" : ""} aria-pressed={(block.view || "general") === value} onClick={() => onChange({ ...block, view: value })}>{text}</button>)}
    </div></div>}
    {block.type === "potential_3d" && <div className="report-block-options"><span>Muestra</span><div className="app-segmented" role="group" aria-label="Magnitud de la vista 3D">
      {[["touch", "Tensión de contacto · zona de la malla"], ["potential", "Potencial · terreno completo"]].map(([value, text]) => <button type="button" key={value} className={(block.mode || "touch") === value ? "active" : ""} aria-pressed={(block.mode || "touch") === value} onClick={() => onChange({ ...block, mode: value })}>{text}</button>)}
    </div></div>}
    {block.type === "references" && <textarea className="app-input" aria-label="Texto introductorio de referencias" value={block.text || ""} placeholder="Texto introductorio (opcional)" onChange={(event) => onChange({ ...block, text: event.target.value })}/>}
  </article>;
}

export function StudyManager({ project, token, onNotice }) {
  const [studies, setStudies] = useState([]); const [artifacts, setArtifacts] = useState([]); const [title, setTitle] = useState(`Estudio — ${project.name}`); const [selected, setSelected] = useState(null); const [saving, setSaving] = useState(false); const [confirmNonCompliant, setConfirmNonCompliant] = useState(false); const [pdfInfo, setPdfInfo] = useState(null); const logoInput = useRef(null); const headers = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
  const withBlocks = (study) => (study ? { ...study, config: { ...(study.config || {}), blocks: blocksFromSections(study.config) } } : study);
  async function reload() { const [s, a] = await Promise.all([jsonRequest(`/api/v1/projects/${project.id}/studies`, { headers }), jsonRequest(`/api/v1/projects/${project.id}/artefactos-diseno-tierras`, { headers })]); setStudies(s); setArtifacts(a); setSelected((current) => withBlocks(current ? s.find((x) => x.id === current.id) || current : s[0] || null)); }
  useEffect(() => { reload().catch((e) => onNotice(e.message)); }, [project.id]);
  async function create() { const artifact = artifacts[0]; if (!artifact) return onNotice("Primero crea un diseño para compartirlo."); try { await jsonRequest(`/api/v1/projects/${project.id}/studies`, { method: "POST", headers, body: JSON.stringify({ artifact_id: artifact.artifact_id, artifact_version: artifact.version, title, access: "link" }) }); await reload(); } catch (e) { onNotice(e.message); } }
  async function save(patch = {}) { if (!selected) return; if (selected.expires_at && selected.expires_at * 1000 <= Date.now() && !("expires_at" in patch)) { onNotice("La fecha de vencimiento ya pasó: elige una fecha futura o déjala vacía."); return; } setSaving(true); try { const body = { artifact_id: selected.artifact_id, artifact_version: selected.artifact_version, title: selected.title, access: selected.access, expires_at: selected.expires_at, config: selected.config, ...(selected.password ? { password: selected.password } : {}), ...patch }; const next = await jsonRequest(`/api/v1/projects/${project.id}/studies/${selected.id}`, { method: "PATCH", headers, body: JSON.stringify(body) }); setSelected(withBlocks(next)); setStudies((items) => items.map((item) => item.id === next.id ? next : item)); } catch (e) { onNotice(e.message); } finally { setSaving(false); } }
  async function publish(status, confirmed = false) {
    try {
      if (status === "published" && selected.expires_at && selected.expires_at * 1000 <= Date.now()) { onNotice("No se puede publicar con una fecha de vencimiento pasada: elige una futura o déjala vacía."); return; }
      if (status === "published" && selected.status === "draft") await save();
      await jsonRequest(`/api/v1/projects/${project.id}/studies/${selected.id}/publish`, { method: "POST", headers, body: JSON.stringify({ status, confirm_non_compliant: confirmed }) });
      setConfirmNonCompliant(false); await reload();
      if (status === "published") onNotice("Estudio publicado. Usa «Ver estudio» para abrirlo o «Copiar enlace» para compartirlo.");
    } catch (e) { if (e.code === "non_compliant") setConfirmNonCompliant(true); else onNotice(e.message); }
  }
  async function republish() { const artifact = artifacts.find((item) => item.artifact_id === selected.artifact_id) || artifacts[0]; if (!artifact) return onNotice("No hay una versión nueva para publicar."); try { await jsonRequest(`/api/v1/projects/${project.id}/studies/${selected.id}/republish`, { method: "POST", headers, body: JSON.stringify({ artifact_id: artifact.artifact_id, artifact_version: artifact.version, title: selected.title, access: selected.access, config: selected.config }) }); await reload(); onNotice("Nueva publicación creada; la anterior conserva su URL."); } catch (e) { onNotice(e.message); } }
  async function uploadLogo(file) { if (!file || !selected) return; try { const presign = await jsonRequest("/api/v1/files/presign", { method: "POST", headers, body: JSON.stringify({ filename: file.name, mime_type: file.type, category: "documents", project_id: project.id }) }); const put = await fetch(presign.upload_url, { method: "PUT", headers: { "Content-Type": file.type }, body: file }); if (!put.ok) throw new Error("No se pudo subir el logo."); await jsonRequest(`/api/v1/files/${presign.upload_id}/complete`, { method: "POST", headers }); await save({ config: { ...selected.config, logo_upload_id: presign.upload_id, logo_filename: file.name } }); onNotice("Logo cargado; aparecerá cuando termine el análisis del archivo."); } catch (e) { onNotice(e.message); } }
  async function saveAccess(patch = {}) {
    if (!selected) return;
    const body = { access: selected.access, expires_at: selected.expires_at ?? null, ...(selected.password ? { password: selected.password } : {}), ...patch };
    if (body.expires_at && body.expires_at * 1000 <= Date.now()) return onNotice("La fecha de vencimiento ya pasó: elige una fecha futura o déjala vacía.");
    setSaving(true);
    try { const next = await jsonRequest(`/api/v1/projects/${project.id}/studies/${selected.id}/access`, { method: "PATCH", headers, body: JSON.stringify(body) }); setSelected(withBlocks({ ...selected, ...next, config: selected.config })); setStudies((items) => items.map((item) => item.id === next.id ? { ...item, ...next } : item)); onNotice(body.expires_at ? "Acceso actualizado." : "Listo: el enlace ya no vence."); }
    catch (e) { onNotice(e.message); } finally { setSaving(false); }
  }
  async function pdf() { try { await jsonRequest(`/api/v1/projects/${project.id}/studies/${selected.id}/pdf`, { method: "POST", headers }); setPdfInfo({ pdf_status: "pending" }); } catch (e) { onNotice(e.message); } }
  useEffect(() => {
    setPdfInfo(null);
    if (!selected || selected.status !== "published") return undefined;
    let live = true;
    jsonRequest(`/api/v1/projects/${project.id}/studies/${selected.id}/pdf`, { headers }).then((info) => { if (live && info.pdf_status) setPdfInfo(info); }).catch(() => null);
    return () => { live = false; };
  }, [selected?.id, selected?.status]);
  useEffect(() => {
    if (!selected || !["pending", "running"].includes(pdfInfo?.pdf_status)) return undefined;
    const timer = setInterval(() => jsonRequest(`/api/v1/projects/${project.id}/studies/${selected.id}/pdf`, { headers }).then(setPdfInfo).catch(() => {}), 2500);
    return () => clearInterval(timer);
  }, [pdfInfo?.pdf_status, selected?.id]);
  const [generating, setGenerating] = useState([]);   // blocks with an LLM call in flight: one call per block at a time
  const blocks = selected?.config?.blocks || [];
  const setBlocks = (update) => setSelected((current) => ({ ...current, config: { ...current.config, blocks: typeof update === "function" ? update(current.config.blocks || []) : update } }));
  async function generateBlock(block) {
    if (generating.includes(block.id)) return;
    setGenerating((ids) => [...ids, block.id]);
    try {
      const result = await awaitJob(token, await jsonRequest(`/api/v1/projects/${project.id}/studies/${selected.id}/sections/${block.id}/generate`, { method: "POST", headers, body: JSON.stringify({ instruction: block.instruction?.trim() || `Redacta la sección «${block.title || "texto del informe"}» para un revisor técnico.` }) }));
      setBlocks((items) => items.map((item) => item.id === block.id ? { ...item, text: result.text } : item));
    } catch (e) { onNotice(e.message); } finally { setGenerating((ids) => ids.filter((id) => id !== block.id)); }
  }
  const addBlock = (type, at = null) => setBlocks((items) => { const next = [...items]; next.splice(at ?? next.length, 0, makeBlock(type)); return next; });
  // Drag and drop: a block's grip reorders it; a pool item dropped in the list is inserted where it falls.
  const [armedId, setArmedId] = useState(null);
  const [dragging, setDragging] = useState(null);       // {kind: "block", id} | {kind: "pool", type}
  const [dropAt, setDropAt] = useState(null);
  const listRef = useRef(null);
  function dropIndex(event) {
    const items = [...(listRef.current?.querySelectorAll('[data-testid="report-block"]') || [])];
    const index = items.findIndex((item) => { const box = item.getBoundingClientRect(); return event.clientY < box.top + box.height / 2; });
    return index === -1 ? items.length : index;
  }
  function onListDragOver(event) {
    if (!dragging) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = dragging.kind === "pool" ? "copy" : "move";
    setDropAt(dropIndex(event));
  }
  function onListDrop(event) {
    if (!dragging) return;
    event.preventDefault();
    const at = dropIndex(event);
    if (dragging.kind === "pool") addBlock(dragging.type, at);
    else setBlocks((items) => { const from = items.findIndex((item) => item.id === dragging.id); if (from < 0) return items; const next = [...items]; const [moved] = next.splice(from, 1); next.splice(at > from ? at - 1 : at, 0, moved); return next; });
    endDrag();
  }
  function endDrag() { setDragging(null); setDropAt(null); setArmedId(null); }
  const moveBlock = (index, delta) => setBlocks((items) => { const next = [...items]; const [item] = next.splice(index, 1); next.splice(index + delta, 0, item); return next; });
  const used = new Set(blocks.map((block) => block.type));
  const pool = Object.entries(BLOCK_TYPES).reduce((groups, [type, item]) => ({ ...groups, [item.group]: [...(groups[item.group] || []), [type, item]] }), {});
  const link = selected ? `${window.location.origin}/e/${selected.slug}` : "";
  const editable = selected?.status === "draft";
  const expired = Boolean(selected?.expires_at && selected.expires_at * 1000 <= Date.now());
  return <section className="study-manager">
    <div className="panel study-manager-head">
      <div className="panel-heading"><div><IconReport size={17}/><h2>Compartir estudio</h2><span className="count">{studies.length}</span></div></div>
      <p className="panel-lead">Fija una versión del diseño, arma el informe con los elementos de la derecha y compártelo como página o PDF.</p>
      <div className="study-create"><input className="app-input" value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Título del estudio"/><button className="button primary" onClick={create}><Plus size={14}/>Crear borrador</button></div>
      {studies.length > 0 && <div className="study-selector app-segmented" role="tablist" aria-label="Estudios del proyecto">{studies.map((study) => <button role="tab" aria-selected={selected?.id === study.id} className={selected?.id === study.id ? "active" : ""} key={study.id} onClick={() => setSelected(withBlocks(study))}><span>{study.title}</span><small>v{study.artifact_version} · <b className={`study-state-text ${linkState(study).key}`}>{linkState(study).label}</b>{study.expires_at && study.status !== "revoked" ? ` · ${linkState(study).key === "expired" ? "venció" : "vence"} ${new Date(study.expires_at * 1000).toLocaleDateString("es-CO", { day: "numeric", month: "short" })}` : ""}</small></button>)}</div>}
      {studies.length === 0 && <EmptyState compact art="report" title="Aún no hay estudios" description="Un estudio fija una versión del diseño y la presenta como página o PDF para tu cliente. Escribe el título arriba y crea el primer borrador."/>}
    </div>
    {selected && <div className="study-workbench">
      <div className="study-main">
        <section className="panel study-publish" aria-labelledby="study-publish-title">
          <div className="panel-heading"><div><Link2 size={16}/><h2 id="study-publish-title">Publicación y enlace</h2></div><span className={`study-status ${linkState(selected).key}`} data-testid="study-link-state">{linkState(selected).label}</span></div>
          <div className="study-publish-body">
            {!["expired", "revoked"].includes(linkState(selected).key) && <p className={`study-validity ${linkState(selected).key}`}>{linkState(selected).detail}</p>}
            {expired && selected.status === "published" && <div className="study-expired" role="alert" data-testid="study-expired"><div><strong>El enlace venció el {formatDateTime(selected.expires_at)}</strong><span>Quien lo abra verá que el estudio ya no está disponible.</span></div><button type="button" className="button primary" disabled={saving} onClick={() => saveAccess({ expires_at: null })}>Quitar el vencimiento</button></div>}
            {editable ? <p className="study-publish-lead">Este estudio es un borrador: nadie más puede verlo. Al publicarlo obtendrás un enlace para compartir y podrás generar el PDF.</p>
              : selected.status === "published" ? <div className="study-link-row">
                  <a className="study-link" href={link} target="_blank" rel="noopener noreferrer" data-testid="study-public-link">{link}<ExternalLink size={13}/></a>
                  <button type="button" className="button" onClick={() => navigator.clipboard?.writeText(link).then(() => onNotice("Enlace copiado."))}><Link2 size={14}/>Copiar enlace</button>
                </div>
              : <div className="study-expired revoked" role="status"><div><strong>Revocado{selected.updated_at ? ` el ${formatDateTime(selected.updated_at)}` : ""}</strong><span>El enlace sigue existiendo, pero quien lo abra verá que el estudio fue revocado. Para volver a compartirlo usa «Republicar nueva versión»: genera un enlace nuevo.</span></div></div>}
            <div className="study-actions">
              {editable ? <><button className="button primary" onClick={() => publish("published")}>Publicar estudio</button><button className="button" disabled={saving} onClick={() => save()}>{saving ? "Guardando…" : "Guardar borrador"}</button></>
                : <>{selected.status === "published" && <a className="button primary" href={`/e/${selected.slug}`} target="_blank" rel="noopener noreferrer"><ExternalLink size={14}/>Ver estudio</a>}
                  {selected.status === "published" && <button className="button" onClick={pdf} disabled={["pending", "running"].includes(pdfInfo?.pdf_status)}>{["pending", "running"].includes(pdfInfo?.pdf_status) ? "Generando PDF…" : pdfInfo?.url ? "Regenerar PDF" : "Generar PDF"}</button>}
                  <button className="button" onClick={republish}>Republicar nueva versión</button>
                  {selected.status === "published" && <button className="button danger-outline" onClick={() => publish("revoked")}>Revocar</button>}</>}
              {pdfInfo?.pdf_status && <span className={`study-pdf-chip ${pdfInfo.pdf_status}`} data-testid="study-pdf-status">PDF: {pdfStatusLabels[pdfInfo.pdf_status] || pdfInfo.pdf_status}{pdfInfo.url && <> · <a href={pdfInfo.url} target="_blank" rel="noopener noreferrer">Descargar</a></>}{pdfInfo.error && ` · ${pdfInfo.error}`}</span>}
            </div>
          </div>
        </section>
        {confirmNonCompliant && <div className="verdict-callout no_cumple" role="alertdialog" aria-label="Confirmar publicación de un diseño no conforme"><div className="verdict-callout-head"><div><strong>Este diseño no cumple la norma</strong><p>Si lo publicas, el estudio llevará la banda «Diseño no conforme» visible para quien lo abra.</p></div></div><div className="study-actions"><button className="button danger" onClick={() => publish("published", true)}>Publicar de todos modos</button><button className="button" onClick={() => setConfirmNonCompliant(false)}>Cancelar</button></div></div>}
        <section className="panel">
          <div className="panel-heading"><div><h2>Configuración</h2></div></div>
          <div className="study-settings">
            <label className="app-field study-field-wide">Título<input className="app-input" value={selected.title} onChange={(e) => setSelected({ ...selected, title: e.target.value })}/></label>
            <label className="app-field">Acceso<select className="app-select" value={selected.access} onChange={(e) => setSelected({ ...selected, access: e.target.value })}><option value="link">Solo con enlace</option><option value="public">Público</option><option value="password">Con contraseña</option></select></label>
            <label className="app-field">Expira<input className="app-input" type="datetime-local" min={toLocalInput(Math.floor(Date.now() / 1000))} value={toLocalInput(selected.expires_at)} onChange={(e) => setSelected({ ...selected, expires_at: fromLocalInput(e.target.value) })}/><small className={expired ? "study-field-error" : undefined}>{expired ? `Venció el ${formatDateTime(selected.expires_at)}: el enlace ya no abre.` : "Déjalo vacío para que no venza."}</small></label>
            {selected.access === "password" && <label className="app-field">Contraseña<input className="app-input" type="password" value={selected.password || ""} onChange={(e) => setSelected({ ...selected, password: e.target.value })} placeholder="Mínimo 8 caracteres"/></label>}
            {!editable && <div className="study-field-wide study-access-save"><button type="button" className="button" disabled={saving} onClick={saveAccess}>{saving ? "Guardando…" : "Guardar acceso y vencimiento"}</button><small>En un estudio publicado, el acceso y el vencimiento cambian de inmediato, sin republicar.</small></div>}
            <div className="app-field">Logo<div className="study-logo-picker"><button type="button" className="button" onClick={() => logoInput.current?.click()}><Upload size={14}/>{selected.config?.logo_upload_id ? "Cambiar logo" : "Cargar logo"}</button><small>{selected.config?.logo_upload_id ? <><Check size={12}/> {selected.config.logo_filename || "Logo cargado"}</> : "PNG o JPG; aparece en el encabezado."}</small><input ref={logoInput} hidden type="file" accept="image/png,image/jpeg" onChange={(e) => { uploadLogo(e.target.files?.[0]); e.target.value = ""; }}/></div></div>
          </div>
        </section>
        <section className="panel study-report">
          <div className="panel-heading"><div><h2>Contenido del informe</h2><span className="count">{blocks.length}</span></div><span className="muted-label">Versión {selected.artifact_version} del diseño</span></div>
          {!editable && <p className="panel-lead">El estudio está {studyStatusLabels[selected.status]}; los cambios en el contenido se publican con «Republicar nueva versión».</p>}
          <div className={`report-blocks${dragging ? " drag-active" : ""}`} ref={listRef} onDragOver={onListDragOver} onDrop={onListDrop} onDragLeave={(event) => { if (!listRef.current?.contains(event.relatedTarget)) setDropAt(null); }}>{blocks.length ? blocks.map((block, index) => <React.Fragment key={block.id}>{dropAt === index && <div className="report-drop-line" aria-hidden="true"/>}<ReportBlock block={block} index={index} total={blocks.length} version={selected.artifact_version} generating={generating.includes(block.id)}
            drag={{ armed: armedId === block.id, dragging: dragging?.id === block.id, arm: () => setArmedId(block.id), disarm: () => { if (!dragging) setArmedId(null); },
              onDragStart: (event) => { event.dataTransfer.effectAllowed = "move"; event.dataTransfer.setData("text/plain", block.id); setDragging({ kind: "block", id: block.id }); }, onDragEnd: endDrag }}
            onChange={(next) => setBlocks((items) => items.map((item) => item.id === next.id ? next : item))} onMove={(delta) => moveBlock(index, delta)} onRemove={() => setBlocks((items) => items.filter((item) => item.id !== block.id))} onGenerate={() => generateBlock(block)}/></React.Fragment>)
            : <EmptyState compact art="report" title={dragging ? "Suelta aquí el elemento" : "El informe está vacío"} description="Agrega texto y resultados desde «Elementos para el informe», a la derecha. Aparecerán aquí en el orden en que los agregues, o arrástralos hasta aquí."/>}{dropAt === blocks.length && blocks.length > 0 && <div className="report-drop-line" aria-hidden="true"/>}</div>
        </section>
      </div>
      <aside className="panel study-pool" aria-label="Elementos para el informe">
        <div className="panel-heading"><div><Plus size={16}/><h2>Elementos para el informe</h2></div></div>
        <p className="panel-lead">Haz clic para agregarlo al final del informe, o arrástralo hasta el lugar donde lo quieres. Para reordenar, arrastra un bloque por su asa ⋮⋮ o usa las flechas.</p>
        {Object.entries(pool).map(([group, items]) => <div className="study-pool-group" key={group}><h3>{group}</h3>{items.map(([type, item]) => { const Icon = item.icon; const taken = !item.repeatable && used.has(type); return <button type="button" key={type} className="study-pool-item" disabled={taken} onClick={() => addBlock(type)} draggable={!taken}
                onDragStart={(event) => { event.dataTransfer.effectAllowed = "copy"; event.dataTransfer.setData("text/plain", type); setDragging({ kind: "pool", type }); }} onDragEnd={endDrag}><span className="report-block-icon"><Icon size={16}/></span><span><strong>{item.label}</strong><small>{taken ? "Ya está en el informe" : item.hint}</small></span>{taken ? <Check size={15}/> : <Plus size={15}/>}</button>; })}</div>)}
      </aside>
    </div>}
  </section>;
}
