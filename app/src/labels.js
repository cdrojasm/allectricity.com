// User-facing glossary: one place where internal names become engineering language.
export const fieldLabels = {
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
const fieldValueLabels = {
  "conductor.material_id": {
    copper_annealed: "Cobre recocido",
    copper_hard_drawn: "Cobre comercial duro",
    copper_clad_40: "Acero revestido de cobre, 40 %",
    copper_clad_30: "Acero revestido de cobre, 30 %",
    copper_clad_rod_17: "Varilla de acero revestida de cobre, 17 %",
    copper_clad_rod_20: "Varilla de acero revestida de cobre, 20 %",
    aluminum_clad_steel: "Acero revestido de aluminio",
    steel_1020: "Acero 1020",
    stainless_clad_rod: "Varilla revestida de acero inoxidable",
    zinc_coated_steel_rod: "Varilla de acero galvanizado",
    stainless_304: "Acero inoxidable 304",
    copper: "Cobre",
    aluminium: "Aluminio",
    aluminum: "Aluminio",
    steel: "Acero",
  },
  "conductor.joint_type": {
    bolted: "Apernada",
    brazed: "Brasada o a presión",
    welded: "Soldada o exotérmica",
    other: "Otra",
    mechanical: "Mecánica",
    exothermic: "Exotérmica",
  },
};
export const fieldValueLabel = (path, value) => fieldValueLabels[path]?.[value] || value;
export const provenanceLabels = { claim: "Extraído de documentos", document: "Documento", user: "Confirmado por el usuario", tool: "Calculado", assumption: "Supuesto", schema_default: "Valor predeterminado" };
export const studyStatusLabels = { draft: "borrador", published: "publicado", revoked: "revocado" };
export const pdfStatusLabels = { none: "Sin generar", pending: "En cola", running: "Generando…", ready: "Listo", failed: "Falló" };

// Plain label for a field path; unknown paths lose their dots and underscores instead of leaking raw keys.
export const fieldLabel = (path) => (fieldLabels[path] || String(path).replace(/[._]/g, " ")).replace(/\s*\([^)]*\)\s*$/, "");

// What a provenance entry says in engineering language.
export function referenceText(reference) {
  const kind = provenanceLabels[reference?.kind];
  const note = reference?.note;
  const ref = reference?.ref;
  const looksInternal = typeof ref === "string" && /^[0-9a-f]{8}-|^[0-9a-f]{16,}$/i.test(ref);
  return [kind || "Origen registrado", note, ref && !looksInternal ? ref : null].filter(Boolean).join(" · ");
}

export const designStatusLabels = { sin_diseno: "Sin diseño", borrador: "Borrador", no_cumple: "No cumple", cumple: "Cumple" };

// Cost lines of the topology optimizer's rate card, in the order the run form asks for them.
export const rateLabels = {
  "material.conductor.unspecified": "Conductor (material)",
  "material.rod.unspecified": "Varilla (material)",
  "excavation.trench": "Excavación de zanja",
  "installation.conductor": "Tendido de conductor",
  "installation.rod": "Hincado de varilla",
  "installation.connection": "Conexiones",
  "assumption.trench_width_m": "Ancho de zanja",
};
