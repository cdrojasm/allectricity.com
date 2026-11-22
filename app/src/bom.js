import { fieldValueLabel } from "./labels.js";
import { formatNumber } from "./resultInterpretation.js";

// Bill of materials rows, shared by the workspace «Materiales» tab and the published study.
const materialName = (material, materialId) => {
  if (material && material !== "unspecified") return fieldValueLabel("conductor.material_id", material);
  return materialId ? fieldValueLabel("conductor.material_id", materialId) : "material sin especificar";
};
const quantity = (value, digits = 1) => (value === null || value === undefined ? "—" : formatNumber(value, digits));

export function bomRows(bom) {
  if (!bom) return [];
  const rows = [];
  for (const line of bom.conductor || []) {
    rows.push({ group: "Conductor", name: `Conductor de ${materialName(line.material, line.material_id).toLowerCase()}`,
      spec: line.cross_section_mm2 ? `Sección ${formatNumber(line.cross_section_mm2, 1)} mm²` : "Sección sin definir", quantity: quantity(line.length_m), raw: line.length_m, unit: "m" });
  }
  for (const line of bom.rods || []) {
    rows.push({ group: "Electrodos", name: `Varilla de ${formatNumber(line.length_m, 2)} m`, spec: line.material && line.material !== "unspecified" ? fieldValueLabel("conductor.material_id", line.material) : "Material sin especificar",
      quantity: quantity(line.count, 0), raw: line.count, unit: "und" });
  }
  const joints = bom.connections_by_type;
  if (joints) {
    rows.push({ group: "Conexiones", name: "Conexión conductor–conductor", spec: "Cruces y uniones en T de la malla", quantity: quantity(joints.conductor_conductor, 0), raw: joints.conductor_conductor, unit: "und" });
    rows.push({ group: "Conexiones", name: "Conexión conductor–electrodo", spec: "Unión de cada varilla a la malla", quantity: quantity(joints.conductor_rod, 0), raw: joints.conductor_rod, unit: "und" });
  } else {
    rows.push({ group: "Conexiones", name: "Conexiones", spec: "Uniones entre conductores y de conductor a varilla", quantity: quantity(bom.connections, 0), raw: bom.connections, unit: "und" });
  }
  if (bom.trench) {
    rows.push({ group: "Obra civil", name: "Zanja", spec: `${formatNumber(bom.trench.depth_m, 2)} m de profundidad${bom.trench.width_m ? ` · ${formatNumber(bom.trench.width_m, 2)} m de ancho` : ""}`, quantity: quantity(bom.trench.length_m), raw: bom.trench.length_m, unit: "m" });
    rows.push({ group: "Obra civil", name: "Excavación", spec: bom.trench.excavation_m3 === null || bom.trench.excavation_m3 === undefined ? "Requiere un ancho de zanja declarado" : "Volumen de la zanja", quantity: quantity(bom.trench.excavation_m3), raw: bom.trench.excavation_m3, unit: "m³" });
  }
  return rows;
}

export function bomCsv(rows) {
  const cell = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
  return [["Grupo", "Material", "Especificación", "Cantidad", "Unidad"], ...rows.map((row) => [row.group, row.name, row.spec, row.raw ?? "", row.unit])]
    .map((line) => line.map(cell).join(";")).join("\n");
}
