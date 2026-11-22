// Shared by the plan editor (Matherra setup) and Resultado (agent iterations and Matherra alternatives).

export const RUN_STATUS_LABELS = {
  queued: "En cola", running: "Buscando", completed: "Completada", failed: "Falló", cancelled: "Cancelada", rejected: "Rechazada",
};
export const ACTIVE_RUN = new Set(["queued", "running"]);

const es = (value, digits) => value.toLocaleString("es-CO", { maximumFractionDigits: digits });
export const formatMoney = (amount, currency) => (Number.isFinite(amount) ? `${currency || ""} ${es(amount, 0)}`.trim() : "—");
/** A fraction (0.84) as "84 %". */
export const formatShare = (fraction, digits = 0) => (Number.isFinite(fraction) ? `${es(fraction * 100, digits)} %` : "—");
/** A value already in percent (-122.4) as "-122,4 %". */
export const formatPercent = (value, digits = 1) => (Number.isFinite(value) ? `${es(value, digits)} %` : "—");

/** JSON request with the session token; a failed response throws its `detail` in the product's language. */
export async function apiRequest(token, url, { method = "GET", body, fallback = "No se pudo completar la solicitud." } = {}) {
  const response = await fetch(url, {
    method,
    headers: { Authorization: `Bearer ${token}`, ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : data.detail?.message;
    const error = new Error(detail || fallback);
    error.status = response.status;
    throw error;
  }
  return data;
}

/** Smallest relative margin of every safety criterion in a completed calculation, in percent. */
export function minimumMargin(result) {
  const margins = (result?.safety || []).flatMap((standard) => (standard.criteria || []).map((c) => c.margin_rel)).filter(Number.isFinite);
  return margins.length ? Math.min(...margins) * 100 : null;
}

// The calculation settings a restored version is recalculated with: those of the calculation it was chosen by.
const RECALCULATION_KEYS = ["justification", "conductor_radius_m", "discretization_m", "segmentation", "estimate_uncertainty",
  "surface_spacing_m", "touch_reach_m", "safety_standards", "fault_split", "x_over_r", "system_frequency_hz", "scenarios",
  "transfer_assessment_complete", "transfer_assessment_evidence", "transfer_exposures"];

/** Restore `version` as a new version and recalculate it with the settings of `calculationId`. */
export async function restoreAndRecalculate({ token, projectId, artifactId, version, calculationId }) {
  const root = `/api/v1/projects/${encodeURIComponent(projectId)}/artefactos-diseno-tierras/${encodeURIComponent(artifactId)}`;
  const original = await apiRequest(token, `${root}/calculos-potencial/${encodeURIComponent(calculationId)}`, { fallback: "No se encontró el cálculo de esa versión." });
  const restored = await apiRequest(token, `${root}/versions/${version}/restaurar`, { method: "POST", fallback: "No se pudo recuperar esa versión." });
  const parameters = Object.fromEntries(RECALCULATION_KEYS.filter((key) => original.parameters?.[key] !== undefined).map((key) => [key, original.parameters[key]]));
  const calculation = await apiRequest(token, `${root}/versions/${restored.version}/calculos-potencial`, { method: "POST", body: parameters, fallback: "Se recuperó la versión, pero no se pudo iniciar su cálculo." });
  return { restored, calculation };
}
