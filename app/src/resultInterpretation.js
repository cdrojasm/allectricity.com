// Veredicto e interpretación de un resultado del solver. Lo usan el panel Resultados del espacio de
// trabajo y el estudio publicado, para que ambos muestren siempre la misma conclusión.

export const verdictLabels = { cumple: "Cumple", no_cumple: "No cumple", no_evaluable: "No evaluable" };

export const formatNumber = (field, digits = 1) => Number(field?.value ?? field).toLocaleString("es-CO", { maximumFractionDigits: digits });

export const criterionLabel = (criterion) => (criterion === "touch" ? "Contacto" : "Paso");

export function evaluateResult(result) {
  const safety = result?.safety || [];
  const thermalFailed = result?.conductor_thermal?.status === "no_cumple";
  const verdict = safety.some((s) => s.status === "no_cumple") || thermalFailed ? "no_cumple"
    : safety.length && safety.every((s) => s.status === "cumple") ? "cumple" : "no_evaluable";
  const failedCriteria = safety
    .flatMap((standard) => (standard.criteria || []).filter((criterion) => criterion.status === "no_cumple").map((criterion) => ({ ...criterion, standard: standard.standard })))
    .sort((a, b) => (a.margin_rel ?? 0) - (b.margin_rel ?? 0));
  const dominant = failedCriteria[0];
  const interpretation = verdict === "no_cumple" ? {
    title: "No cumple",
    constraint: thermalFailed && !dominant ? "Sección térmica del conductor" : dominant ? `${dominant.criterion === "touch" ? "Tensión de contacto" : "Tensión de paso"} · ${dominant.standard}` : "Criterio de seguridad",
    explanation: thermalFailed && !dominant
      ? `La sección seleccionada (${formatNumber(result.conductor_thermal.selected_section_mm2)} mm²) está por debajo de la mínima (${formatNumber(result.conductor_thermal.minimum_section_mm2)} mm²).`
      : dominant ? `${formatNumber(dominant.actual_v)} V frente a ${formatNumber(dominant.tolerable_v)} V tolerables; margen ${formatNumber(100 * dominant.margin_rel)}%.`
        : "Existe al menos una restricción de seguridad que no se satisface.",
    actions: thermalFailed && !dominant ? ["Aumenta la sección del conductor y recalcula"]
      : dominant?.criterion === "touch" ? ["Agrega varillas en el perímetro y recalcula", "Reduce la retícula perimetral y recalcula"]
        : dominant?.criterion === "step" ? ["Reduce la retícula perimetral y recalcula", "Agrega varillas en el perímetro y recalcula"]
          : ["Revisa los parámetros eléctricos y recalcula"],
  } : verdict === "cumple" ? {
    title: "Cumple", constraint: "Ninguna restricción dominante",
    explanation: "Contacto, paso y sección térmica están dentro de los límites evaluados.",
    actions: ["Revisa la evidencia y confirma el diseño"],
  } : {
    title: "No evaluable", constraint: "Faltan datos o criterios evaluables",
    explanation: "Completa y confirma los parámetros críticos antes de presentar el resultado como cumplimiento.",
    actions: ["Completa los parámetros eléctricos y recalcula"],
  };
  return { verdict, interpretation, safety };
}
