// Prueba el botón «Optimizar hasta cumplir» desde un resultado real no conforme.
// El worker de agente usa el proveedor LLM configurado; solo ejecutar en local.
import { test, expect } from "@playwright/test";
import { creds, sessionPage, runId, sweepResidue } from "../helpers.js";

const LOCAL = /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:|\/|$)/.test(process.env.SMOKE_BASE_URL || "");

async function api(page, url, options = {}) {
  return page.evaluate(async ({ url, options }) => {
    const token = localStorage.getItem("spat_access_token");
    const response = await fetch(url, { ...options, headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" } });
    const text = await response.text();
    let body; try { body = JSON.parse(text); } catch { body = text; }
    return { status: response.status, body };
  }, { url, options });
}
const post = (page, url, body) => api(page, url, { method: "POST", body: JSON.stringify(body) });

const artifact = {
  name: "Malla para iteración autónoma smoke-ui",
  geometry: {
    length_m: 40, width_m: 30, burial_depth_m: 0.5,
    conductor_spacing_x_m: 5, conductor_spacing_y_m: 6, rods_count: 8, rod_length_m: 2.4,
  },
  soil_layers: [{ resistivity_ohm_m: 100 }],
  fault: { current_a: 8000, clearing_time_s: 0.5, body_weight_kg: 70, surface_resistivity_ohm_m: 3000, surface_thickness_m: 0.1 },
};

test("P1: optimiza desde el cálculo vigente, versiona y recalcula hasta cerrar", async ({ browser }) => {
  test.skip(!LOCAL, "Crea objetos y usa el proveedor LLM; solo se ejecuta contra localhost.");
  test.skip(!creds("designer"), "Falta el perfil designer; créalo localmente con make smoke-ui-seed.");
  test.setTimeout(360_000);

  const page = await sessionPage(browser, "designer");
  const projectName = runId();
  let projectId; let artifactId;
  try {
    const project = await post(page, "/api/v1/projects", { name: projectName, description: "Prueba P1 autónoma; se borra sola.", city: "Bogotá", country: "Colombia" });
    expect(project.status, JSON.stringify(project.body)).toBe(201);
    projectId = project.body.id;
    const created = await post(page, `/api/v1/projects/${projectId}/artefactos-diseno-tierras`, artifact);
    expect(created.status, JSON.stringify(created.body)).toBe(201);
    artifactId = created.body.artifact_id;

    await page.goto(`/project/${projectId}`); // abre/crea la conversación normal de producto
    await expect.poll(async () => {
      const rows = await api(page, `/api/v1/projects/${projectId}/conversations`);
      return rows.body.length;
    }).toBeGreaterThan(0);
    const conversations = await api(page, `/api/v1/projects/${projectId}/conversations`);
    const conversationId = conversations.body[0].id;
    const state = await api(page, `/api/v1/conversations/${conversationId}/agent-state`, {
      method: "PUT", body: JSON.stringify({ artifact_id: artifactId }),
    });
    expect(state.status).toBe(200);

    const calculation = await post(page, `/api/v1/projects/${projectId}/artefactos-diseno-tierras/${artifactId}/versions/1/calculos-potencial`, {});
    expect(calculation.status, JSON.stringify(calculation.body)).toBe(202);
    const calculationId = calculation.body.id;
    const calculationUrl = `/api/v1/projects/${projectId}/artefactos-diseno-tierras/${artifactId}/calculos-potencial/${calculationId}`;
    await expect.poll(async () => (await api(page, calculationUrl)).body.status, { timeout: 120_000, intervals: [1000, 2000, 4000] }).toBe("completed");
    const initial = await api(page, calculationUrl);
    const nonCompliant = initial.body.result?.safety?.some((standard) => standard.status === "no_cumple")
      || initial.body.result?.conductor_thermal?.status === "no_cumple";
    expect(nonCompliant, "El fixture debe arrancar en No cumple; si cambió el solver, ajusta el fixture.").toBe(true);

    await page.getByRole("tablist", { name: "Secciones del artefacto" }).getByRole("tab", { name: "Resultado" }).click();
    const optimize = page.getByTestId("optimize-until-compliant");
    await expect(optimize).toBeVisible();
    await optimize.click();

    await expect.poll(async () => {
      const versions = await api(page, `/api/v1/projects/${projectId}/artefactos-diseno-tierras/${artifactId}/versions`);
      return versions.status === 200 ? versions.body.length : 0;
    }, { timeout: 240_000, intervals: [1500, 3000, 5000] }).toBeGreaterThan(1);
    await expect.poll(async () => {
      const state = await api(page, `/api/v1/conversations/${conversationId}/agent-events`);
      return state.body.events.some((event) => event.payload?.design_loop_result) && !state.body.active_run ? "completed" : "working";
    }, { timeout: 240_000, intervals: [1500, 3000, 5000] }).toBe("completed");
    const versions = await api(page, `/api/v1/projects/${projectId}/artefactos-diseno-tierras/${artifactId}/versions`);
    const latest = versions.body[0]; // La API devuelve versiones newest-first.
    await expect.poll(async () => {
      const rows = await api(page, `/api/v1/projects/${projectId}/artefactos-diseno-tierras/${artifactId}/versions/${latest.version}/calculos-potencial`);
      return rows.body.some((row) => row.status === "completed");
    }, { timeout: 180_000, intervals: [1500, 3000, 5000] }).toBe(true);

    const events = await api(page, `/api/v1/conversations/${conversationId}/agent-events`);
    const loopResult = [...events.body.events].reverse().find((event) => event.payload?.design_loop_result)?.payload.design_loop_result;
    expect(loopResult?.reason).toMatch(/^(goal_met|iteration_limit|no_improvement|no_valid_candidate|save_failed|calculation_failed)$/);
    expect(loopResult?.best_candidate?.calculation_id).toBeTruthy();
    const iterations = [...new Set(events.body.events.map((event) => event.payload?.iteration).filter(Number.isInteger))];
    expect(iterations.length).toBeGreaterThan(0);
    expect(Math.max(...iterations)).toBeLessThanOrEqual(3);
    await page.getByRole("tablist", { name: "Secciones del artefacto" }).getByRole("tab", { name: "Resultado" }).click();
    await expect(page.getByTestId("design-loop-result")).toContainText("Mejor candidato");
    // Al cerrar, el mejor diseño es la versión vigente: si una iteración empeoró, el agente lo restauró y recalculó.
    expect(latest.version).toBe(loopResult.best_candidate.artifact_version);
    if (loopResult.best_candidate.restored_from != null) {
      expect(latest.origin?.restored_from).toBe(loopResult.best_candidate.restored_from);
    }
    // Restauración manual: solo aplica si alguien versionó el diseño durante la corrida (no ocurre en esta prueba).
    if (latest.version > loopResult.best_candidate.artifact_version) {
      const beforeRestore = versions.body.length;
      await page.getByTestId("restore-best-design-candidate").click();
      await expect.poll(async () => (await api(page, `/api/v1/projects/${projectId}/artefactos-diseno-tierras/${artifactId}/versions`)).body.length,
        { timeout: 30_000 }).toBe(beforeRestore + 1);
      const restoredVersions = await api(page, `/api/v1/projects/${projectId}/artefactos-diseno-tierras/${artifactId}/versions`);
      expect(restoredVersions.body[0].origin?.restored_from).toBe(loopResult.best_candidate.artifact_version);
      await expect.poll(async () => {
        const rows = await api(page, `/api/v1/projects/${projectId}/artefactos-diseno-tierras/${artifactId}/versions/${restoredVersions.body[0].version}/calculos-potencial`);
        return rows.body.some((row) => ["pending", "running", "completed"].includes(row.status));
      }, { timeout: 30_000 }).toBe(true);
    }
  } finally {
    await sweepResidue(page);
    await page.context().close();
  }
});
