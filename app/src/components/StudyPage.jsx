import React, { useEffect, useRef, useState } from "react";
import { fieldLabel, fieldValueLabel, pdfStatusLabels, rateLabels, referenceText, studyStatusLabels } from "../labels.js";
import { SurfacePotentialMap } from "./GroundingCalculations.jsx";
import { ArtifactGrid } from "./AgentArtifact.jsx";
import { criterionLabel, evaluateResult, formatNumber, verdictLabels } from "../resultInterpretation.js";
import { awaitJob } from "../asyncJobs.js";

async function jsonRequest(url, options = {}) {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body.detail;
    throw Object.assign(new Error(detail?.message || (typeof detail === "string" ? detail : "No se pudo completar la operación.")), { code: detail?.code });
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

const materialLabel = (material) => (material === "unspecified" || !material ? "sin especificar" : fieldValueLabel("conductor.material_id", material));

function StudyBillOfMaterials({ bom }) {
  if (!bom) return null;
  const rows = [
    ...bom.conductor.map((line) => [`Conductor (${materialLabel(line.material)}${line.cross_section_mm2 ? `, ${formatNumber(line.cross_section_mm2)} mm²` : ""})`, display(line.length_m, "m", 1)]),
    ...bom.rods.map((line) => [`Varillas de ${display(line.length_m, "m")} (${materialLabel(line.material)})`, `${line.count} und · ${display(line.length_m * line.count, "m", 1)}`]),
    ["Conexiones (uniones y varillas)", `${bom.connections} und`],
    ["Zanja", `${display(bom.trench.length_m, "m", 1)} · ${display(bom.trench.depth_m, "m")} de profundidad${bom.trench.width_m ? ` · ${display(bom.trench.width_m, "m")} de ancho` : ""}`],
    ["Excavación", bom.trench.excavation_m3 === null || bom.trench.excavation_m3 === undefined ? "Sin ancho de zanja declarado" : display(bom.trench.excavation_m3, "m³", 1)],
  ];
  return <section data-testid="study-bom">
    <h2>Lista de materiales</h2>
    <table className="study-bom-table"><tbody>{rows.map(([label, value]) => <tr key={label}><th scope="row">{label}</th><td>{value}</td></tr>)}</tbody></table>
    {bom.cost && <p data-testid="study-bom-cost"><strong>Costo estimado:</strong> {formatNumber(bom.cost.total, 0)} {bom.cost.currency || ""}{bom.cost.by_group ? ` (${Object.entries(bom.cost.by_group).map(([group, amount]) => `${rateLabels[group] || group}: ${formatNumber(Number(amount), 0)}`).join(" · ")})` : ""}. {bom.cost.note}</p>}
    {bom.notes?.length > 0 && <ul className="study-references">{bom.notes.map((note) => <li key={note}>{note}</li>)}</ul>}
  </section>;
}

function StudyInputs({ artifact, version, thermal }) {
  const geometry = artifact.geometry || {}; const fault = artifact.fault || {}; const conductor = artifact.conductor || {}; const layers = artifact.soil_layers || [];
  const spacing = geometry.conductor_spacing_x_m && geometry.conductor_spacing_y_m ? `${display(geometry.conductor_spacing_x_m, "", 2)} × ${display(geometry.conductor_spacing_y_m, "", 2)} m` : display(geometry.conductor_spacing_m, "m");
  const groups = [
    ["Malla", [["Dimensiones", `${display(geometry.length_m, "", 2)} × ${display(geometry.width_m, "", 2)} m`], ["Retícula", spacing], ["Profundidad", display(geometry.burial_depth_m, "m")], ["Varillas", rodsSummary(geometry)]]],
    ["Falla", [["Corriente", display(fault.current_a, "A", 0)], ["Tiempo de despeje", display(fault.clearing_time_s, "s")], ["Capa superficial", fault.surface_resistivity_ohm_m ? `${display(fault.surface_resistivity_ohm_m, "Ω·m", 0)} · ${display(fault.surface_thickness_m, "m")}` : "Sin capa superficial"]]],
    ["Conductor", [["Material", fieldValueLabel("conductor.material_id", conductor.material_name || thermal?.material_name || conductor.material_id || "—")], ["Sección", display(conductor.cross_section_mm2, "mm²")], ...(thermal?.profile ? [["Norma", thermal.profile]] : [])]],
  ];
  return <div className="study-inputs">
    {(geometry.length_m || geometry.conductors?.length) ? <figure className="study-plan" data-testid="study-plan"><ArtifactGrid geometry={geometry}/><figcaption>Plano de la malla de la versión publicada.</figcaption></figure> : null}
    {groups.map(([title, rows]) => <div className="study-input-group" key={title}><h3>{title}</h3><dl>{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl></div>)}
    <div className="study-input-group"><h3>Suelo</h3>{layers.length ? <dl>{layers.map((layer, index) => <div key={index}><dt>Capa {index + 1}{layer.material ? ` · ${layer.material}` : ""}</dt><dd>{display(layer.resistivity_ohm_m, "Ω·m", 1)}{layer.depth_m ? ` · ${display(layer.depth_m, "m")}` : " · semiinfinita"}</dd></div>)}</dl> : <p className="study-muted">Sin capas registradas.</p>}</div>
    <p className="study-muted">Versión del diseño: {version}</p>
  </div>;
}

function StudyResult({ calculation, summary }) {
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
    {result.surface_potential && <figure className="study-map" data-testid="study-map"><SurfacePotentialMap field={result.surface_potential}/><figcaption>Contacto evaluado sobre la malla ({formatNumber(result.surface_potential.grid_width_m)} × {formatNumber(result.surface_potential.grid_height_m)} m{reach ? `, ${calculation.parameters.touch_reach_m} m fuera del perímetro` : ", dentro del perímetro"}); paso en todo el terreno, salvo dentro de construcciones.</figcaption></figure>}
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

export function PublicStudyPage({ slug }) {
  const [data, setData] = useState(null); const [error, setError] = useState(""); const [password, setPassword] = useState("");
  const renderToken = new URLSearchParams(window.location.search).get("render_token");
  async function load(url, options = {}) { try { setData(await jsonRequest(url, { ...options, headers: { ...(options.headers || {}), ...(renderToken ? { "X-Study-Render-Token": renderToken } : {}) } })); } catch (e) { setError(e.message); } }
  useEffect(() => { load(`/api/v1/public/studies/${encodeURIComponent(slug)}`); }, [slug]);
  if (error) return <main className="study-public"><div className="study-card"><h1>Estudio no disponible</h1><p>{error}</p></div></main>;
  if (!data) return <main className="study-public"><div className="study-card">Cargando estudio…</div></main>;
  if (data.requires_password) return <main className="study-public"><div className="study-card"><h1>{data.study.title}</h1><p>Este estudio requiere una contraseña.</p><form onSubmit={(e) => { e.preventDefault(); load(`/api/v1/public/studies/${encodeURIComponent(slug)}/access`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password }) }); }}><input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Contraseña"/><button className="button primary">Abrir estudio</button></form></div></main>;
  const { study, project, artifact } = data; const enabled = (id) => study.config?.sections?.find((s) => s.id === id)?.enabled !== false;
  return <main className="study-public"><article className="study-document"><header className="study-header">{study.config?.logo_url && <img className="study-logo" src={study.config.logo_url} alt="Logo del estudio"/>}<div><div className="eyebrow">ESTUDIO DE PUESTA A TIERRA</div><h1>{study.title}</h1><p>{project.name}{project.city ? ` · ${project.city}` : ""}</p></div></header>{data.non_compliant && <div className="study-warning study-nonconforming" role="alert" data-testid="study-nonconforming"><strong>DISEÑO NO CONFORME</strong> · los resultados de este estudio no cumplen la norma evaluada.</div>}{data.draft && <div className="study-warning" role="status" data-testid="study-draft-warning"><strong>BORRADOR</strong> · {[data.unconfirmed_critical?.length ? `${data.unconfirmed_critical.length} supuesto(s) crítico(s) sin confirmar` : null, data.assumptions?.length ? `${data.assumptions.length} valor(es) supuesto(s) por el agente sin confirmar` : null].filter(Boolean).join(" · ") || "Este estudio contiene información pendiente de confirmar"}.{(data.unconfirmed_critical?.length > 0 || data.assumptions?.length > 0) && <ul>{[...(data.unconfirmed_critical || []), ...(data.assumptions || [])].map((path) => <li key={path}>{fieldLabel(path)}</li>)}</ul>}</div>}{data.has_newer_version && <div className="study-warning">Existe una versión más reciente. Este estudio conserva la versión {study.artifact_version} publicada.</div>}{enabled("summary") && <section><h2>Resumen</h2><p>{study.config?.sections?.find((s) => s.id === "summary")?.text || project.description || "Estudio calculado y trazable."}</p></section>}{enabled("inputs") && <section data-testid="study-inputs"><h2>Entradas</h2><StudyInputs artifact={artifact} version={study.artifact_version} thermal={data.calculation?.result?.conductor_thermal}/><p>{study.config?.sections?.find((s) => s.id === "inputs")?.text}</p></section>}{enabled("results") && <section data-testid="study-results"><h2>Resultado</h2><p>{study.config?.sections?.find((s) => s.id === "results")?.text}</p><StudyResult calculation={data.calculation} summary={artifact.result}/></section>}{enabled("results") && <StudyOptimization optimization={data.optimization}/>}{enabled("results") && <StudyBillOfMaterials bom={data.bill_of_materials}/>}{enabled("references") && <section><h2>Referencias y trazabilidad</h2><p>{study.config?.sections?.find((s) => s.id === "references")?.text || "Los valores publicados conservan su origen técnico."}</p>{data.references?.length > 0 && <><ul className="study-references" data-testid="study-references">{data.references.map((item) => <li key={item.path}><strong>{fieldLabel(item.path)}</strong> · {referenceText(item.reference)}</li>)}</ul><details className="study-audit"><summary>Detalle para auditoría</summary><ul className="study-references">{data.references.map((item) => <li key={item.path}><code>{item.path}</code> · {JSON.stringify(item.reference)}</li>)}</ul></details></>}</section>}<footer>{study.config?.show_allectricity_brand !== false && study.config?.show_terra_brand !== false && <span>Publicado con Allectricity</span>}<button className="button" onClick={() => window.print()}>Guardar como PDF</button></footer></article></main>;
}

function SectionEditor({ section, onChange, onGenerate, generating }) {
  return <div className="study-section-editor"><label><input type="checkbox" checked={section.enabled !== false} onChange={(e) => onChange({ ...section, enabled: e.target.checked })}/><strong>{section.label}</strong></label><textarea value={section.text || ""} disabled={section.enabled === false || generating} placeholder={`Texto para ${section.label.toLowerCase()}…`} onChange={(e) => onChange({ ...section, text: e.target.value })}/><button className="button" type="button" disabled={section.enabled === false || generating} onClick={() => onGenerate(section.id)}>{generating ? "Generando…" : "Generar con IA"}</button></div>;
}

export function StudyManager({ project, token, onNotice }) {
  const [studies, setStudies] = useState([]); const [artifacts, setArtifacts] = useState([]); const [title, setTitle] = useState(`Estudio — ${project.name}`); const [selected, setSelected] = useState(null); const [saving, setSaving] = useState(false); const [confirmNonCompliant, setConfirmNonCompliant] = useState(false); const [pdfInfo, setPdfInfo] = useState(null); const logoInput = useRef(null); const headers = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
  async function reload() { const [s, a] = await Promise.all([jsonRequest(`/api/v1/projects/${project.id}/studies`, { headers }), jsonRequest(`/api/v1/projects/${project.id}/artefactos-diseno-tierras`, { headers })]); setStudies(s); setArtifacts(a); setSelected((current) => current ? s.find((x) => x.id === current.id) || current : s[0] || null); }
  useEffect(() => { reload().catch((e) => onNotice(e.message)); }, [project.id]);
  async function create() { const artifact = artifacts[0]; if (!artifact) return onNotice("Primero crea un diseño para compartirlo."); try { await jsonRequest(`/api/v1/projects/${project.id}/studies`, { method: "POST", headers, body: JSON.stringify({ artifact_id: artifact.artifact_id, artifact_version: artifact.version, title, access: "link" }) }); await reload(); } catch (e) { onNotice(e.message); } }
  async function save(patch = {}) { if (!selected) return; setSaving(true); try { const body = { artifact_id: selected.artifact_id, artifact_version: selected.artifact_version, title: selected.title, access: selected.access, expires_at: selected.expires_at, config: selected.config, ...(selected.password ? { password: selected.password } : {}), ...patch }; const next = await jsonRequest(`/api/v1/projects/${project.id}/studies/${selected.id}`, { method: "PATCH", headers, body: JSON.stringify(body) }); setSelected(next); setStudies((items) => items.map((item) => item.id === next.id ? next : item)); } catch (e) { onNotice(e.message); } finally { setSaving(false); } }
  async function publish(status, confirmed = false) {
    try {
      if (status === "published" && selected.status === "draft") await save();
      await jsonRequest(`/api/v1/projects/${project.id}/studies/${selected.id}/publish`, { method: "POST", headers, body: JSON.stringify({ status, confirm_non_compliant: confirmed }) });
      setConfirmNonCompliant(false); await reload();
      if (status === "published") onNotice("Estudio publicado. Usa «Ver estudio» para abrirlo o «Copiar enlace» para compartirlo.");
    } catch (e) { if (e.code === "non_compliant") setConfirmNonCompliant(true); else onNotice(e.message); }
  }
  async function republish() { const artifact = artifacts.find((item) => item.artifact_id === selected.artifact_id) || artifacts[0]; if (!artifact) return onNotice("No hay una versión nueva para publicar."); try { await jsonRequest(`/api/v1/projects/${project.id}/studies/${selected.id}/republish`, { method: "POST", headers, body: JSON.stringify({ artifact_id: artifact.artifact_id, artifact_version: artifact.version, title: selected.title, access: selected.access, config: selected.config }) }); await reload(); onNotice("Nueva publicación creada; la anterior conserva su URL."); } catch (e) { onNotice(e.message); } }
  async function uploadLogo(file) { if (!file || !selected) return; try { const presign = await jsonRequest("/api/v1/files/presign", { method: "POST", headers, body: JSON.stringify({ filename: file.name, mime_type: file.type, category: "documents", project_id: project.id }) }); const put = await fetch(presign.upload_url, { method: "PUT", headers: { "Content-Type": file.type }, body: file }); if (!put.ok) throw new Error("No se pudo subir el logo."); await jsonRequest(`/api/v1/files/${presign.upload_id}/complete`, { method: "POST", headers }); await save({ config: { ...selected.config, logo_upload_id: presign.upload_id } }); onNotice("Logo cargado; aparecerá cuando termine el análisis del archivo."); } catch (e) { onNotice(e.message); } }
  async function pdf() { try { await jsonRequest(`/api/v1/projects/${project.id}/studies/${selected.id}/pdf`, { method: "POST", headers }); setPdfInfo({ pdf_status: "pending" }); } catch (e) { onNotice(e.message); } }
  useEffect(() => {
    setPdfInfo(null);
    if (!selected || selected.status !== "published") return undefined;
    let live = true;
    const poll = () => jsonRequest(`/api/v1/projects/${project.id}/studies/${selected.id}/pdf`, { headers }).then((info) => { if (live && info.pdf_status) setPdfInfo(info); return info; }).catch(() => null);
    poll();
    return () => { live = false; };
  }, [selected?.id, selected?.status]);
  useEffect(() => {
    if (!selected || !["pending", "running"].includes(pdfInfo?.pdf_status)) return undefined;
    const timer = setInterval(() => jsonRequest(`/api/v1/projects/${project.id}/studies/${selected.id}/pdf`, { headers }).then(setPdfInfo).catch(() => {}), 2500);
    return () => clearInterval(timer);
  }, [pdfInfo?.pdf_status, selected?.id]);
  const [generating, setGenerating] = useState([]);   // sections with an LLM call in flight: one call per section at a time
  async function generateSection(sectionId) { if (generating.includes(sectionId)) return; setGenerating((ids) => [...ids, sectionId]); try { const result = await awaitJob(token, await jsonRequest(`/api/v1/projects/${project.id}/studies/${selected.id}/sections/${sectionId}/generate`, { method: "POST", headers, body: JSON.stringify({}) })); setSelected((current) => ({ ...current, config: { ...current.config, sections: current.config.sections.map((section) => section.id === sectionId ? { ...section, text: result.text } : section) } })); } catch (e) { onNotice(e.message); } finally { setGenerating((ids) => ids.filter((id) => id !== sectionId)); } }
  const sections = selected?.config?.sections || [];
  return <section className="study-manager"><div className="panel-heading"><div><h2>Compartir estudio</h2><span className="count">{studies.length}</span></div></div><p className="study-manager-intro">Fija una versión del diseño, personaliza el estudio y compártelo como página o PDF.</p><div className="study-create"><input value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Título del estudio"/><button className="button primary" onClick={create}>Crear borrador</button></div>{studies.length > 0 && <div className="study-selector">{studies.map((study) => <button className={selected?.id === study.id ? "active" : ""} key={study.id} onClick={() => setSelected(study)}>{study.title}<small>v{study.artifact_version} · {studyStatusLabels[study.status] || study.status}</small></button>)}</div>}{selected && <div className="study-editor"><label>Título<input value={selected.title} onChange={(e) => setSelected({ ...selected, title: e.target.value })}/></label><div className="study-access-row"><label>Acceso<select value={selected.access} onChange={(e) => setSelected({ ...selected, access: e.target.value })}><option value="link">Solo con enlace</option><option value="public">Público</option><option value="password">Contraseña</option></select></label><label>Expira<input type="datetime-local" value={selected.expires_at ? new Date(selected.expires_at * 1000).toISOString().slice(0, 16) : ""} onChange={(e) => setSelected({ ...selected, expires_at: e.target.value ? Math.floor(new Date(e.target.value).getTime() / 1000) : null })}/></label></div>{selected.access === "password" && <label>Contraseña<input type="password" value={selected.password || ""} onChange={(e) => setSelected({ ...selected, password: e.target.value })} placeholder="Mínimo 8 caracteres"/></label>}<label className="study-logo-picker">Logo<input ref={logoInput} type="file" accept="image/png,image/jpeg" onChange={(e) => uploadLogo(e.target.files?.[0])}/></label><div className="study-section-editors">{sections.map((section) => <SectionEditor key={section.id} section={section} onChange={(next) => setSelected({ ...selected, config: { ...selected.config, sections: sections.map((item) => item.id === next.id ? next : item) } })} onGenerate={generateSection} generating={generating.includes(section.id)}/>)}</div>{confirmNonCompliant && <div className="study-warning study-confirm" role="alertdialog" aria-label="Confirmar publicación de un diseño no conforme"><p><strong>Este diseño no cumple la norma.</strong> Si lo publicas, el estudio llevará la banda «Diseño no conforme» visible para quien lo abra.</p><div className="study-actions"><button className="button danger" onClick={() => publish("published", true)}>Publicar de todos modos</button><button className="button" onClick={() => setConfirmNonCompliant(false)}>Cancelar</button></div></div>}<div className="study-actions">{selected.status === "draft" ? <><button className="button primary" onClick={() => publish("published")}>Publicar estudio</button><button className="button" disabled={saving} onClick={() => save()}>{saving ? "Guardando…" : "Guardar borrador"}</button></> : <>{selected.status === "published" && <a className="button primary" href={`/e/${selected.slug}`} target="_blank" rel="noopener noreferrer">Ver estudio</a>}<button className="button" onClick={() => navigator.clipboard?.writeText(`${window.location.origin}/e/${selected.slug}`).then(() => onNotice("Enlace copiado."))}>Copiar enlace</button><button className="button" onClick={pdf} disabled={["pending", "running"].includes(pdfInfo?.pdf_status)}>Generar PDF</button>{pdfInfo?.pdf_status && <span className="study-pdf-status" data-testid="study-pdf-status">PDF: {pdfStatusLabels[pdfInfo.pdf_status] || pdfInfo.pdf_status}{pdfInfo.url && <> · <a href={pdfInfo.url} target="_blank" rel="noopener noreferrer">Descargar</a></>}{pdfInfo.error && ` · ${pdfInfo.error}`}</span>}<button className="button" onClick={republish}>Republicar nueva versión</button><button className="button" onClick={() => publish("revoked")}>Revocar</button></>}</div>{selected.status === "published" && <p className="study-muted">Enlace: <code>{`${window.location.origin}/e/${selected.slug}`}</code></p>}</div>}{studies.length === 0 && <p>Aún no hay estudios publicados.</p>}</section>;
}
