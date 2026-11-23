import React, { useMemo, useState } from "react";
import { ChevronDown, Plus, Trash2 } from "lucide-react";
import { apiRequest } from "../optimization.js";
import { HelpLabel, HelpTip } from "./HelpTip.jsx";

// Normative profile editor, inside «Perfil normativo del proyecto». Anyone can write a profile with their own
// criterion: fill it from a norm («Heredar de norma»: the shipped IEEE 80 / RETIE profiles, the catalog or your
// own profiles; the norm picked in «Estándares a evaluar» comes first) or from scratch («Personalizado»), save it
// as a draft and mark it reviewed. A designer's profile is personal (only they see and pin it); a super_admin
// may also publish to the shared catalog. The API checks everything again (constraint_profile_routes.py).
const CUSTOM = "custom";
const SCOPE_GROUPS = [["default", "Normas (incluidas en la app)"], ["catalog", "Catálogo compartido"], ["personal", "Mis perfiles"]];
const CRITERIA = [["touch", "Contacto"], ["step", "Paso"], ["transferred", "Transferidas"]];
const CATEGORIES = [["mandatory", "Obligatoria"], ["guidance", "Guía"], ["constructability", "Constructiva"], ["commercial", "Comercial"]];
const APPLICABILITY = [["applicable", "Aplica"], ["not_applicable", "No aplica"], ["unknown", "Desconocida"]];
const NORMATIVE = new Set(["mandatory", "guidance"]);

const blankRule = (index = 1) => ({
  id: `regla-${index}`, category: "mandatory", criterion: "touch", target: "", applicability: "unknown",
  conditions: "", verification_method: "", expression: "", min: "", max: "", unit: "",
  source: { document: "", edition: "", clause: "", url: "", official_publisher: "" },
});
const BLANK = { profile_id: "", title: "", jurisdiction: "", installation_type: "", description: "", required: ["touch", "step"], rules: [blankRule()] };

function fromDefinition(profileId, definition) {
  return {
    profile_id: profileId || "",
    title: definition.title || "", jurisdiction: definition.jurisdiction || "", installation_type: definition.installation_type || "",
    description: definition.description || "", required: [...(definition.required_mandatory_criteria || [])],
    rules: (definition.rules || []).map((rule, index) => ({
      ...blankRule(index + 1), ...rule,
      criterion: rule.criterion || "", target: rule.target || "", expression: rule.expression || "",
      conditions: (rule.applicability_conditions || []).join("\n"),
      min: rule.min ?? "", max: rule.max ?? "", unit: rule.unit || "",
      source: { ...blankRule().source, ...(rule.source || {}) },
    })),
  };
}

function toDefinition(form) {
  const text = (value) => String(value ?? "").trim();
  return {
    title: text(form.title), jurisdiction: text(form.jurisdiction), installation_type: text(form.installation_type),
    ...(text(form.description) ? { description: text(form.description) } : {}),
    required_mandatory_criteria: form.required,
    rules: form.rules.map((rule) => {
      const bounded = text(rule.min) !== "" || text(rule.max) !== "";
      const source = Object.fromEntries(Object.entries(rule.source).map(([key, value]) => [key, text(value)]).filter(([, value]) => value));
      return {
        id: text(rule.id), category: rule.category, applicability: rule.applicability,
        applicability_conditions: rule.conditions.split("\n").map(text).filter(Boolean),
        verification_method: text(rule.verification_method), source,
        ...(text(rule.criterion) ? { criterion: text(rule.criterion) } : {}),
        ...(text(rule.target) ? { target: text(rule.target) } : {}),
        ...(text(rule.expression) ? { expression: text(rule.expression) } : {}),
        ...(bounded ? { min: Number(rule.min), max: Number(rule.max), unit: text(rule.unit) } : {}),
      };
    }),
  };
}

// What keeps a rule from being saved, and what keeps the profile from being reviewed (same rules as the API).
function ruleProblems(rule) {
  const problems = [];
  if (!rule.id.trim()) problems.push("Falta el identificador de la regla.");
  if (!rule.conditions.trim()) problems.push("Escribe al menos una condición de aplicabilidad.");
  if (!rule.verification_method.trim()) problems.push("Falta el método de verificación.");
  if (NORMATIVE.has(rule.category) && ["document", "edition", "clause"].some((key) => !rule.source[key]?.trim()))
    problems.push("La fuente necesita documento, edición y cláusula.");
  if (!NORMATIVE.has(rule.category) && !rule.source.document?.trim()) problems.push("Indica el documento o referencia de la fuente.");
  const hasMin = String(rule.min).trim() !== "", hasMax = String(rule.max).trim() !== "";
  if (hasMin !== hasMax) problems.push("Los límites necesitan mínimo y máximo.");
  if (hasMin && hasMax && (!rule.target.trim() || !rule.unit.trim())) problems.push("Un límite necesita variable y unidad.");
  if (hasMin && hasMax && Number(rule.min) > Number(rule.max)) problems.push("El mínimo es mayor que el máximo.");
  return problems;
}
function missingForReview(form) {
  return form.required.filter((criterion) => !form.rules.some((rule) => rule.category === "mandatory"
    && rule.criterion === criterion && rule.applicability === "applicable"));
}
const criterionLabel = (value) => CRITERIA.find(([key]) => key === value)?.[1] || value;
// ["touch", "step"] → "contacto y paso"
const criteriaText = (items) => {
  const names = items.map(criterionLabel).map((name) => name.toLowerCase());
  return names.length > 1 ? `${names.slice(0, -1).join(", ")} y ${names[names.length - 1]}` : names.join("");
};

const slug = (text) => text.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase()
  .replace(/[^a-z0-9]+/g, "-").slice(0, 40).replace(/^-+|-+$/g, "");
const newPersonalId = (title) => `mio.${slug(title) || "perfil"}-${Date.now().toString(36)}`;
const rowKey = (row) => `catalog:${row.profile_id}:${row.version}`;

function readable(error) {
  const text = error?.message || "";
  if (text.includes("already exists")) return "Ya existe un perfil con ese identificador.";
  if (text.includes("missing applicable rules")) return "Faltan reglas obligatorias que apliquen para los criterios marcados.";
  return text || "No se pudo guardar el perfil.";
}

export function NormativeProfileEditor({ token, catalog, curator = false, suggestedId = null, onPublished }) {
  const [open, setOpen] = useState(false);
  const [origin, setOrigin] = useState(CUSTOM);
  const [scope, setScope] = useState(curator ? "catalog" : "personal");
  const [form, setForm] = useState(BLANK);
  const [expanded, setExpanded] = useState(0);
  const [saved, setSaved] = useState(null);      // { profile_id, version } of the draft just saved
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const latest = useMemo(() => {
    const byId = new Map();
    for (const row of catalog) if (!byId.has(row.profile_id) || row.version > byId.get(row.profile_id).version) byId.set(row.profile_id, row);
    return [...byId.values()];
  }, [catalog]);
  const owner = useMemo(() => Object.fromEntries(latest.map((row) => [row.profile_id, row])), [latest]);
  // Which existing profiles this person may add a version to: their own personal ones; a curator, also the catalog.
  const versionable = (id) => owner[id] && (owner[id].scope === "personal" || (curator && owner[id].scope === "catalog"));
  const id = form.profile_id.trim();
  const blocking = form.rules.flatMap((rule, index) => ruleProblems(rule).map((text) => `Regla ${index + 1}: ${text}`));
  const headerMissing = [...(curator ? ["profile_id"] : []), "title", "jurisdiction", "installation_type"].filter((key) => !String(form[key]).trim());
  const idValid = !curator || /^[a-z0-9][a-z0-9._-]+$/.test(id);
  const idTaken = Boolean(id && owner[id] && !versionable(id));
  const reviewGaps = missingForReview(form);
  const savesAsVersion = Boolean(id && versionable(id));
  const personal = savesAsVersion ? owner[id].scope === "personal" : scope === "personal";

  const edit = (patch) => { setForm((old) => ({ ...old, ...patch })); setSaved(null); setNotice(""); };
  const editRule = (index, patch) => edit({ rules: form.rules.map((rule, i) => (i === index ? { ...rule, ...patch } : rule)) });
  const editSource = (index, key, value) => editRule(index, { source: { ...form.rules[index].source, [key]: value } });

  function openEditor() {
    // Start from the norm the user already picked (the suggested profile), or from a blank form.
    const suggested = suggestedId && owner[suggestedId];
    setOrigin(suggested ? rowKey(suggested) : CUSTOM);
    // The curator flag arrives after mount (the drafts listing answers later), so the default scope is set here.
    setScope(curator ? "catalog" : "personal");
    setOpen(true);
  }

  function inherit() {
    setError(""); setSaved(null); setConfirmed(false);
    if (origin === CUSTOM) { setForm({ ...BLANK, rules: [blankRule()] }); setExpanded(0); setNotice("Formulario en blanco: escribe tu criterio desde cero."); return; }
    const row = catalog.find((item) => rowKey(item) === origin);
    if (!row) return;
    // Your own profile (or, for a curator, a catalog one) keeps its id: saving adds a version. Anything else is a copy.
    const keep = versionable(row.profile_id);
    const next = fromDefinition(keep ? row.profile_id : "", row.definition || {});
    if (!keep) next.title = `${next.title} · ${curator ? "copia" : "criterio propio"}`;
    setForm(next); setExpanded(-1);
    setNotice(keep
      ? `Heredado de ${row.definition?.title || row.profile_id} v${row.version}. Al guardar se crea la versión ${Math.max(...catalog.filter((item) => item.profile_id === row.profile_id).map((item) => item.version)) + 1}; la anterior no cambia.`
      : `Heredado de ${row.definition?.title || row.profile_id}. Cambia lo que tu criterio necesite y guárdalo como perfil propio; la norma original no cambia.`);
  }

  async function save() {
    setBusy(true); setError(""); setNotice("");
    try {
      const profileId = id || newPersonalId(form.title);
      const definition = toDefinition(form);
      const row = savesAsVersion
        ? await apiRequest(token, `/api/v1/constraint-profiles/${encodeURIComponent(profileId)}/versions`, { method: "POST", body: { definition }, fallback: "No se pudo guardar la versión." })
        : await apiRequest(token, "/api/v1/constraint-profiles", { method: "POST", body: { profile_id: profileId, definition, ...(curator ? { scope } : {}) }, fallback: "No se pudo crear el perfil." });
      setForm((old) => ({ ...old, profile_id: row.profile_id || profileId }));
      setSaved({ profile_id: row.profile_id || profileId, version: row.version || 1 });
      setConfirmed(false);
      setNotice(`Borrador guardado (versión ${row.version || 1}). ${personal ? "Márcalo como revisado para poder fijarlo a tus proyectos." : "Todavía no aparece para los diseñadores."}`);
      onPublished?.();
    } catch (failure) { setError(readable(failure)); }
    finally { setBusy(false); }
  }

  async function review() {
    if (!saved) return;
    setBusy(true); setError("");
    try {
      await apiRequest(token, `/api/v1/constraint-profiles/${encodeURIComponent(saved.profile_id)}/versions/${saved.version}/review`, { method: "POST", fallback: "No se pudo marcar como revisado." });
      setNotice(`«${form.title}» v${saved.version} quedó revisado: ya puedes fijarlo al proyecto arriba.`);
      setSaved(null); setOpen(false); onPublished?.();
    } catch (failure) { setError(readable(failure)); }
    finally { setBusy(false); }
  }

  // Enter inside the editor must not submit the optimizer form that contains it, and Escape must not close the
  // Matherra dialog around it (that would throw away the profile being written).
  const stopEnter = (event) => {
    if (event.key === "Enter" && event.target.tagName === "INPUT") event.preventDefault();
    // With a help card open, let Escape through: HelpTip closes the card and stops it there.
    if (event.key === "Escape" && !document.querySelector(".help-card")) event.nativeEvent.stopPropagation();
  };

  if (!open) return <div className="profile-editor-toggle">
    <button type="button" className="button" onClick={openEditor}><Plus size={14}/> Crear perfil con mi criterio</button>
    <HelpTip topic="profile_editor" label="Crear un perfil normativo"/>
    {notice && <small className="profile-editor-ok" role="status">{notice}</small>}
  </div>;

  return <section className="profile-editor" aria-label="Crear perfil normativo" onKeyDown={stopEnter}>
    <header className="profile-editor-head">
      <HelpLabel text="Crear perfil normativo" topic="profile_editor"/>
      <button type="button" className="button" onClick={() => setOpen(false)}>Cerrar</button>
    </header>

    <div className="profile-editor-inherit">
      <label><HelpLabel text="Heredar de norma" topic="profile_inherit"/>
        <select value={origin} onChange={(event) => setOrigin(event.target.value)}>
          <option value={CUSTOM}>Personalizado — lo escribo todo yo</option>
          {SCOPE_GROUPS.map(([group, label]) => {
            const rows = catalog.filter((row) => (row.scope || "catalog") === group && row.status !== "retired")
              .sort((a, b) => (b.profile_id === suggestedId) - (a.profile_id === suggestedId) || a.profile_id.localeCompare(b.profile_id) || b.version - a.version);
            return rows.length > 0 && <optgroup key={group} label={label}>
              {rows.map((row) => <option key={rowKey(row)} value={rowKey(row)}>
                {row.profile_id === suggestedId ? "★ " : ""}{row.definition?.title || row.profile_id} · v{row.version}{row.status === "reviewed" ? "" : row.status === "retired" ? " · retirado" : " · borrador"}{row.profile_id === suggestedId ? " · sugerido por tu norma" : ""}
              </option>)}
            </optgroup>;
          })}
        </select>
      </label>
      <button type="button" className="button primary" onClick={inherit}>{origin === CUSTOM ? "Empezar en blanco" : "Heredar"}</button>
    </div>
    {notice && <small className="profile-editor-ok" role="status">{notice}</small>}

    <div className="profile-editor-grid">
      {curator && <label><HelpLabel text="Publicar en" topic="profile_scope"/>
        <select value={savesAsVersion ? owner[id].scope : scope} disabled={savesAsVersion} onChange={(event) => setScope(event.target.value)}>
          <option value="catalog">Catálogo compartido (lo ven todos)</option><option value="personal">Solo para mí</option>
        </select>
      </label>}
      {curator && <label><HelpLabel text="Identificador" topic="profile_id"/>
        <input value={form.profile_id} placeholder="co.retie.substation_ac" onChange={(event) => edit({ profile_id: event.target.value.toLowerCase() })}/>
        {form.profile_id && !idValid && <small className="profile-editor-warn">Solo minúsculas, números, puntos y guiones.</small>}
        {idValid && id && <small className={idTaken ? "profile-editor-warn" : undefined}>{idTaken ? "Ese identificador es de un perfil que no se puede modificar; usa otro." : savesAsVersion ? "Ya existe: se guardará como versión nueva de ese perfil." : "Perfil nuevo."}</small>}
      </label>}
      <label><HelpLabel text="Título" topic="profile_title"/><input value={form.title} onChange={(event) => edit({ title: event.target.value })}/></label>
      <label><HelpLabel text="Jurisdicción" topic="profile_jurisdiction"/><input value={form.jurisdiction} placeholder="Colombia" onChange={(event) => edit({ jurisdiction: event.target.value })}/></label>
      <label><HelpLabel text="Tipo de instalación" topic="profile_installation"/><input value={form.installation_type} placeholder="AC substation" onChange={(event) => edit({ installation_type: event.target.value })}/></label>
      <label className="wide"><HelpLabel text="Descripción y alcance" topic="profile_description"/><textarea rows={3} value={form.description} onChange={(event) => edit({ description: event.target.value })}/></label>
      <div className="wide profile-editor-criteria">
        <HelpLabel text="Criterios obligatorios" topic="required_criteria"/>
        {CRITERIA.map(([key, label]) => <label key={key} className="checkbox-row">
          <input type="checkbox" checked={form.required.includes(key)} onChange={(event) => edit({ required: event.target.checked ? [...form.required, key] : form.required.filter((item) => item !== key) })}/>{label}
        </label>)}
      </div>
    </div>

    <div className="profile-editor-rules">
      <div className="profile-editor-rules-head">
        <HelpLabel text={`Reglas (${form.rules.length})`} topic="profile_rule"/>
        <button type="button" className="button" onClick={() => { edit({ rules: [...form.rules, blankRule(form.rules.length + 1)] }); setExpanded(form.rules.length); }}><Plus size={13}/> Agregar regla</button>
      </div>
      {form.rules.map((rule, index) => {
        const problems = ruleProblems(rule);
        const isOpen = expanded === index;
        const pending = problems.length > 0 || (rule.category === "mandatory" && rule.applicability === "unknown");
        return <article key={index} className={`profile-rule ${isOpen ? "is-open" : ""}`}>
          <button type="button" className="profile-rule-summary" aria-expanded={isOpen} onClick={() => setExpanded(isOpen ? -1 : index)}>
            <ChevronDown size={14} className="profile-rule-chevron"/>
            <span><strong>{rule.criterion ? criterionLabel(rule.criterion) : rule.target || rule.id || `Regla ${index + 1}`}</strong>
              {" · "}{CATEGORIES.find(([key]) => key === rule.category)?.[1]}{" · "}{APPLICABILITY.find(([key]) => key === rule.applicability)?.[1].toLowerCase()}
              {rule.source.clause ? ` · ${rule.source.clause}` : ""}</span>
            {pending && <span className="profile-rule-flag" title={problems.join(" ") || "Aplicabilidad sin confirmar"}>⚠</span>}
          </button>
          {isOpen && <div className="profile-rule-body">
            <label><span className="help-label">Identificador de la regla</span><input value={rule.id} onChange={(event) => editRule(index, { id: event.target.value })}/></label>
            <label><HelpLabel text="Tipo" topic="rule_category"/>
              <select value={rule.category} onChange={(event) => editRule(index, { category: event.target.value })}>{CATEGORIES.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select>
            </label>
            <label><HelpLabel text="Criterio de seguridad" topic="rule_criterion"/>
              <select value={rule.criterion} onChange={(event) => editRule(index, { criterion: event.target.value })}>
                <option value="">Ninguno (limita una variable)</option>{CRITERIA.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
              </select>
            </label>
            <label><span className="help-label">Variable que limita<HelpTip topic="rule_criterion"/></span><input value={rule.target} placeholder="rod_length_m, ground_resistance_ohm…" onChange={(event) => editRule(index, { target: event.target.value })}/></label>
            <fieldset className="wide profile-rule-applicability"><legend><HelpLabel text="Aplicabilidad" topic="rule_applicability"/></legend>
              {APPLICABILITY.map(([key, label]) => <label key={key} className="checkbox-row"><input type="radio" name={`applicability-${index}`} checked={rule.applicability === key} onChange={() => editRule(index, { applicability: key })}/>{label}</label>)}
            </fieldset>
            <label className="wide"><HelpLabel text="Condiciones de aplicabilidad (una por línea)" topic="rule_conditions"/><textarea rows={3} value={rule.conditions} onChange={(event) => editRule(index, { conditions: event.target.value })}/></label>
            <label className="wide"><HelpLabel text="Requisito" topic="rule_expression"/><textarea rows={2} value={rule.expression} onChange={(event) => editRule(index, { expression: event.target.value })}/></label>
            <label className="wide"><HelpLabel text="Método de verificación" topic="rule_verification"/><textarea rows={2} value={rule.verification_method} onChange={(event) => editRule(index, { verification_method: event.target.value })}/></label>
            <fieldset className="wide profile-rule-source"><legend><HelpLabel text="Fuente" topic="rule_source"/></legend>
              <label>Documento<input value={rule.source.document} onChange={(event) => editSource(index, "document", event.target.value)}/></label>
              <label>Edición<input value={rule.source.edition} placeholder="2026-06-23" onChange={(event) => editSource(index, "edition", event.target.value)}/></label>
              <label>Cláusula<input value={rule.source.clause} onChange={(event) => editSource(index, "clause", event.target.value)}/></label>
              <label>Enlace al texto oficial<input type="url" value={rule.source.url} onChange={(event) => editSource(index, "url", event.target.value)}/></label>
            </fieldset>
            <fieldset className="wide profile-rule-bounds"><legend><HelpLabel text="Límites (opcional)" topic="rule_bounds"/></legend>
              <label>Mínimo<input type="number" step="any" value={rule.min} onChange={(event) => editRule(index, { min: event.target.value })}/></label>
              <label>Máximo<input type="number" step="any" value={rule.max} onChange={(event) => editRule(index, { max: event.target.value })}/></label>
              <label>Unidad<input value={rule.unit} placeholder="m, Ω…" onChange={(event) => editRule(index, { unit: event.target.value })}/></label>
            </fieldset>
            {problems.length > 0 && <ul className="profile-editor-warn wide">{problems.map((text) => <li key={text}>{text}</li>)}</ul>}
            <button type="button" className="button danger-outline wide" onClick={() => { edit({ rules: form.rules.filter((_, i) => i !== index) }); setExpanded(-1); }}><Trash2 size={13}/> Quitar regla</button>
          </div>}
        </article>;
      })}
    </div>

    <footer className="profile-editor-foot">
      {(headerMissing.length > 0 || blocking.length > 0) && <small className="profile-editor-warn">Para guardar: {[...headerMissing.length ? [`completa ${curator ? "identificador, " : ""}título, jurisdicción y tipo de instalación`] : [], ...blocking].join(" · ")}</small>}
      {reviewGaps.length > 0 && <small>Para poder revisarlo más adelante, {criteriaText(reviewGaps)} {reviewGaps.length === 1 ? "necesita" : "necesitan"} una regla obligatoria marcada como «Aplica».</small>}
      <button type="button" className="button primary" disabled={busy || !idValid || idTaken || headerMissing.length > 0 || blocking.length > 0 || !form.rules.length} onClick={save}>
        {busy && !saved ? "Guardando…" : savesAsVersion ? "Guardar como versión nueva (borrador)" : personal ? "Guardar como perfil propio (borrador)" : "Guardar en el catálogo (borrador)"}
      </button>
      {saved && <div className="profile-editor-review">
        <HelpLabel text={`Marcar «${form.title}» v${saved.version} como revisado`} topic="profile_review"/>
        <label className="checkbox-row"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)}/>
          {personal ? "Revisé cada regla y respondo por este criterio en mis proyectos." : "Un profesional competente revisó cada regla contra el texto oficial y aprueba esta versión para todos."}</label>
        <button type="button" className="button primary" disabled={busy || !confirmed || reviewGaps.length > 0} onClick={review}>Marcar como revisado</button>
        {reviewGaps.length > 0 && <small className="profile-editor-warn">No se puede revisar todavía: {criteriaText(reviewGaps)} sin regla obligatoria que aplique.</small>}
      </div>}
      {error && <small className="profile-editor-warn" role="alert">{error}</small>}
    </footer>
  </section>;
}
