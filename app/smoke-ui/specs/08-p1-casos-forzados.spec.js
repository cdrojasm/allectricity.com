// P1-02 a P1-04 desde la UI: límite de una iteración, propuesta sin cambio válido y recuperación del mejor
// candidato cuando una iteración posterior empeora. Cada caso exige que el worker de agente esté levantado con
// la configuración del escenario (ver app/smoke-ui/loop-scenarios/README.md) y SMOKE_LOOP_SCENARIO igual:
//   limit1  → proveedor LLM real, DESIGN_MAX_ITERATIONS=1
//   invalid → LLM de prueba que propone una profundidad inválida
//   worse   → LLM de prueba que abre la retícula a 10 × 10 m
// Solo local: crea proyectos zz-smoke-* y los barre al terminar.
import { test, expect } from "@playwright/test";
import { creds, sessionPage, runId, sweepResidue } from "../helpers.js";

const LOCAL = /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:|\/|$)/.test(process.env.SMOKE_BASE_URL || "");
const SCENARIO = process.env.SMOKE_LOOP_SCENARIO || "";

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

const ARTIFACT = {
  name: "Malla para casos forzados smoke-ui",
  geometry: {
    length_m: 40, width_m: 30, burial_depth_m: 0.5,
    conductor_spacing_x_m: 5, conductor_spacing_y_m: 6, rods_count: 8, rod_length_m: 2.4,
  },
  soil_layers: [{ resistivity_ohm_m: 100 }],
  fault: { current_a: 8000, clearing_time_s: 0.5, body_weight_kg: 70, surface_resistivity_ohm_m: 3000, surface_thickness_m: 0.1 },
};

const minMargin = (calculation) => Math.min(...(calculation.result?.safety || [])
  .flatMap((standard) => (standard.criteria || []).map((criterion) => criterion.margin_rel)));

/** Crea el proyecto, calcula v1 («No cumple»), pulsa «Optimizar hasta cumplir» y espera el cierre del bucle. */
async function runLoop(page, record) {
  const project = await post(page, "/api/v1/projects", { name: runId(), description: "Caso P1 forzado; se borra solo.", city: "Bogotá", country: "Colombia" });
  expect(project.status, JSON.stringify(project.body)).toBe(201);
  const projectId = project.body.id;
  const created = await post(page, `/api/v1/projects/${projectId}/artefactos-diseno-tierras`, ARTIFACT);
  expect(created.status, JSON.stringify(created.body)).toBe(201);
  const artifactId = created.body.artifact_id;
  const root = `/api/v1/projects/${projectId}/artefactos-diseno-tierras/${artifactId}`;

  await page.goto(`/project/${projectId}`);
  await expect.poll(async () => (await api(page, `/api/v1/projects/${projectId}/conversations`)).body.length).toBeGreaterThan(0);
  const conversationId = (await api(page, `/api/v1/projects/${projectId}/conversations`)).body[0].id;
  expect((await api(page, `/api/v1/conversations/${conversationId}/agent-state`, { method: "PUT", body: JSON.stringify({ artifact_id: artifactId }) })).status).toBe(200);

  const first = await post(page, `${root}/versions/1/calculos-potencial`, {});
  expect(first.status, JSON.stringify(first.body)).toBe(202);
  await expect.poll(async () => (await api(page, `${root}/calculos-potencial/${first.body.id}`)).body.status,
    { timeout: 120_000, intervals: [1000, 2000, 4000] }).toBe("completed");
  const initial = (await api(page, `${root}/calculos-potencial/${first.body.id}`)).body;
  expect(minMargin(initial), "El fixture debe arrancar en «No cumple»").toBeLessThan(0);

  await page.reload();
  await page.getByRole("tablist", { name: "Secciones del artefacto" }).getByRole("tab", { name: "Resultado" }).click();
  const optimize = page.getByTestId("optimize-until-compliant");
  await expect(optimize).toBeVisible();
  await optimize.click();
  await expect.poll(async () => {
    const state = await api(page, `/api/v1/conversations/${conversationId}/agent-events`);
    return state.body.events.some((event) => event.payload?.design_loop_result) && !state.body.active_run ? "closed" : "working";
  }, { timeout: 300_000, intervals: [2000, 4000, 5000] }).toBe("closed");

  const events = (await api(page, `/api/v1/conversations/${conversationId}/agent-events`)).body.events;
  const loop = [...events].reverse().find((event) => event.payload?.design_loop_result).payload.design_loop_result;
  const versions = (await api(page, `${root}/versions`)).body; // newest-first
  const calculations = {};
  for (const version of versions) calculations[version.version] = (await api(page, `${root}/versions/${version.version}/calculos-potencial`)).body;
  const chat = (await api(page, `/api/v1/conversations/${conversationId}/messages/first`)).body;
  const finalText = [...chat].reverse().find((message) => message.source === "agent")?.text || "";
  const iterations = [...new Set(events.map((event) => event.payload?.iteration).filter(Number.isInteger))];
  record({ projectId, conversationId, artifactId, initialCalculation: first.body.id, loop,
    versions: versions.map((v) => ({ version: v.version, summary: v.origin?.summary, restored_from: v.origin?.restored_from,
      calculations: calculations[v.version].map((c) => ({ id: c.id, status: c.status, min_margin: c.result ? minMargin(c) : null })) })),
    iterations, finalText });

  await page.reload();
  await page.getByRole("tablist", { name: "Secciones del artefacto" }).getByRole("tab", { name: "Resultado" }).click();
  const panel = page.getByTestId("design-loop-result");
  await expect(panel).toBeVisible({ timeout: 30_000 });
  return { loop, versions, calculations, finalText, iterations, panel, initial };
}

function scenario(name, title, body) {
  test(title, async ({ browser }, testInfo) => {
    test.skip(!LOCAL, "Crea objetos; solo se ejecuta contra localhost.");
    test.skip(SCENARIO !== name, `El worker no está en el escenario «${name}» (SMOKE_LOOP_SCENARIO=${SCENARIO || "vacío"}).`);
    test.skip(!creds("designer"), "Falta el perfil designer; créalo con make smoke-ui-seed.");
    test.setTimeout(420_000);
    const page = await sessionPage(browser, "designer");
    try {
      await body(page, (evidence) => testInfo.attach(`evidencia-${name}.json`, { body: JSON.stringify(evidence, null, 2), contentType: "application/json" }));
      await page.screenshot({ path: testInfo.outputPath(`${name}.png`), fullPage: false });
    } finally {
      await sweepResidue(page);
      await page.context().close();
    }
  });
}

scenario("limit1", "P1-02: con límite 1 crea como máximo una versión de iteración y cierra sin afirmar cumplimiento", async (page, record) => {
  const { loop, versions, finalText, iterations, panel } = await runLoop(page, record);
  expect(loop.max_iterations).toBe(1);
  expect(loop.iterations_used).toBeLessThanOrEqual(1);
  expect(Math.max(0, ...iterations)).toBeLessThanOrEqual(1);
  const iterationVersions = versions.filter((v) => /^Iteración automática/.test(v.origin?.summary || ""));
  expect(iterationVersions.length).toBeLessThanOrEqual(1);
  expect(loop.best_candidate?.calculation_id).toBeTruthy();
  expect(loop.best_candidate?.dominant_criterion?.criterion).toBeTruthy();
  if (loop.verdict !== "cumple") {
    expect(loop.reason).not.toBe("goal_met");
    expect(finalText).not.toMatch(/el diseño cumple/i);
  }
  await expect(panel).toContainText("Iteraciones:");
  await expect(panel).toContainText("/1");
  await expect(panel).toContainText(`Mejor candidato: versión ${versions[0].version}`);
});

scenario("invalid", "P1-03: una propuesta inválida no guarda versión ni encola cálculo y cierra con explicación", async (page, record) => {
  const { loop, versions, calculations, finalText, panel } = await runLoop(page, record);
  expect(loop.reason).toBe("no_valid_candidate");
  expect(versions.map((v) => v.version)).toEqual([1]);
  expect(calculations[1].length).toBe(1); // solo el cálculo inicial
  expect(versions[0].snapshot.geometry.burial_depth_m).toBe(0.5);
  expect(finalText).toContain("No se pudo guardar una mejora válida");
  expect(finalText).toContain("Iteraciones usadas: 1/");
  await expect(panel).toContainText("Mejor candidato: versión 1");
  await expect(page.getByTestId("restore-best-design-candidate")).toHaveCount(0);
});

scenario("worse", "P1-04: si la iteración empeora, el mejor diseño vuelve a ser la versión vigente y se recalcula", async (page, record) => {
  const { loop, versions, calculations, finalText, panel, initial } = await runLoop(page, record);
  const byVersion = Object.fromEntries(versions.map((v) => [v.version, v]));
  expect(versions.map((v) => v.version)).toEqual([3, 2, 1]);
  expect(byVersion[2].snapshot.geometry.conductor_spacing_x_m).toBe(10);
  const marginV2 = minMargin(calculations[2].find((c) => c.status === "completed"));
  expect(marginV2, "La iteración forzada debe empeorar el margen").toBeLessThan(minMargin(initial));
  // v3 = v1 restaurada por el agente, con su propio cálculo terminado y el mismo resultado.
  expect(byVersion[3].origin.restored_from).toBe(1);
  expect(byVersion[3].snapshot).toEqual(byVersion[1].snapshot);
  const restored = calculations[3].find((c) => c.status === "completed");
  expect(restored, "La versión restaurada debe tener su propio cálculo terminado").toBeTruthy();
  expect(minMargin(restored)).toBeCloseTo(minMargin(initial), 6);
  expect(loop.reason).toBe("no_improvement");
  expect(loop.best_candidate.artifact_version).toBe(3);
  expect(loop.best_candidate.restored_from).toBe(1);
  expect(loop.best_candidate.calculation_id).toBe(restored.id);
  expect(finalText).toContain("versión 3 (restaurada desde la versión 1)");
  await expect(panel).toContainText("Mejor candidato: versión 3");
  await expect(page.getByTestId("restore-best-design-candidate")).toHaveCount(0); // ya no hace falta rescatarlo a mano
  await expect(page.locator(".artifact-update-warning")).toHaveCount(0); // el resultado de v3 está al día
});
