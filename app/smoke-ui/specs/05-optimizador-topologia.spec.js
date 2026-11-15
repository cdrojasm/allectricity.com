// Flujo del optimizador topológico por la interfaz: precarga desde el artefacto, tarifas, corrida real con el
// solver, vista previa sobre el diseño base, aplicar como versión nueva, y recuperar el historial al recargar.
// Siembra por API un perfil normativo de PRUEBA (revisado, con id zz-smoke-*), un proyecto y un artefacto.
// Crea un perfil global: solo corre contra un entorno local y lo retira al terminar.
import { test, expect } from "@playwright/test";
import { creds, sessionPage, runId, sweepResidue } from "../helpers.js";

const LOCAL = /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:|\/|$)/.test(process.env.SMOKE_BASE_URL || "");
const SOURCE = { document: "Perfil de prueba smoke-ui", edition: "2026", clause: "1" };
const rule = (id, criterion) => ({ id, category: "mandatory", criterion, applicability: "applicable", applicability_conditions: ["toda la malla"], verification_method: "IEEE 80", source: SOURCE });
const PROFILE = {
  title: "Perfil de prueba smoke-ui", jurisdiction: "global", installation_type: "substation_ac",
  required_mandatory_criteria: ["touch", "step"],
  rules: [rule("touch", "touch"), rule("step", "step"),
    { id: "rod", category: "constructability", target: "rod_length_m", applicability: "applicable", applicability_conditions: ["varillas comerciales"], verification_method: "catálogo", min: 1.5, max: 3.0, unit: "m", source: { reference: "catálogo de prueba" } }],
};
const GEOMETRY = {
  length_m: 36, width_m: 28, burial_depth_m: 0.6,
  areas: [{ type: "intervenible", label: "lote", polygon: [{ x: 2, y: 2 }, { x: 34, y: 2 }, { x: 34, y: 14 }, { x: 22, y: 14 }, { x: 22, y: 26 }, { x: 2, y: 26 }] }],
  structures: [{ x: 10, y: 18, width: 5, height: 4, label: "edificio" }],
  conductors: [{ start: { x: 4, y: 4 }, end: { x: 32, y: 4 } }, { start: { x: 32, y: 4 }, end: { x: 32, y: 12 } }, { start: { x: 32, y: 12 }, end: { x: 4, y: 12 } }, { start: { x: 4, y: 12 }, end: { x: 4, y: 4 } }, { start: { x: 18, y: 4 }, end: { x: 18, y: 12 } }],
  rods: [{ x: 4, y: 4, length_m: 2.4 }, { x: 32, y: 12, length_m: 2.4 }],
};
const ARTIFACT = {
  name: "Malla smoke optimizador", geometry: GEOMETRY, soil_layers: [{ resistivity_ohm_m: 100 }],
  fault: { current_a: 1000, clearing_time_s: 0.5, body_weight_kg: 70, surface_resistivity_ohm_m: 3000, surface_thickness_m: 0.1 },
};
const RATES = { "Conductor (material)": "18000", "Varilla (material)": "25000", "Excavación de zanja": "60000", "Tendido de conductor": "7000", "Hincado de varilla": "40000", "Conexiones": "15000" };

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

async function openOptimizer(page, projectId) {
  await page.goto(`/project/${projectId}`);
  await page.getByRole("tablist", { name: "Secciones del artefacto" }).getByRole("tab", { name: "Plano" }).click();
  await page.getByRole("button", { name: "Abrir editor de plano" }).click();
  await page.getByText("Restricciones de optimización").click();
}

test.describe.serial("optimizador de topologías", () => {
  test.skip(!creds("designer") || !creds("super_admin"), "Faltan los perfiles designer y super_admin (make smoke-ui-seed los crea).");
  test.skip(!LOCAL, "Crea un perfil normativo global de prueba: solo se corre contra un entorno local.");
  let page; let admin; const seed = { profileId: runId().toLowerCase() };

  test.beforeAll(async ({ browser }) => {
    test.setTimeout(120_000);
    admin = await sessionPage(browser, "super_admin");
    const created = await post(admin, "/api/v1/constraint-profiles", { profile_id: seed.profileId, definition: PROFILE });
    expect(created.status, JSON.stringify(created.body)).toBe(201);
    expect((await post(admin, `/api/v1/constraint-profiles/${seed.profileId}/versions/1/review`, {})).status).toBe(200);

    page = await sessionPage(browser, "designer");
    const project = await post(page, "/api/v1/projects", { name: runId(), description: "Prueba del optimizador. Se borra sola.", city: "Medellín", country: "Colombia" });
    expect(project.status).toBe(201);
    seed.projectId = project.body.id;
    const selected = await api(page, `/api/v1/projects/${seed.projectId}/constraint-profiles`, { method: "PUT", body: JSON.stringify({ profiles: [{ profile_id: seed.profileId, version: 1 }] }) });
    expect(selected.status, JSON.stringify(selected.body)).toBe(200);
    expect((await post(page, `/api/v1/projects/${seed.projectId}/artefactos-diseno-tierras`, ARTIFACT)).status).toBe(201);
  });

  test.afterAll(async () => {
    if (page) await sweepResidue(page);
    if (admin) { await post(admin, `/api/v1/constraint-profiles/${seed.profileId}/versions/1/retire`, {}).catch(() => {}); await admin.context().close(); }
    await page?.context().close();
  });

  test("precarga el suelo y la falla del artefacto, busca, previsualiza y aplica", async () => {
    test.setTimeout(240_000);
    await openOptimizer(page, seed.projectId);
    // Sin pulsar «Resolver contexto»: los datos del artefacto ya están en el formulario.
    await expect(page.getByLabel("Resistividad de suelo (Ω·m)")).toHaveValue("100");
    await expect(page.getByLabel("Corriente de falla inyectada (A)")).toHaveValue("1000");
    await expect(page.getByLabel("Tiempo de despeje (s)")).toHaveValue("0.5");
    await expect(page.getByLabel("Peso corporal (kg)")).toHaveValue("70");

    await page.getByLabel("Clase de exposición").selectOption("public");
    await page.getByLabel("¿Existe capa superficial?").selectOption("true");
    await page.getByLabel("IEEE 80-2013").check();
    for (const [label, value] of Object.entries(RATES)) await page.getByLabel(label).fill(value);
    await page.getByLabel("Fuente de las tarifas").fill("cotización de prueba");
    await page.getByLabel("Ancho de zanja (m)", { exact: true }).fill("0.4");
    await page.getByLabel("Fuente del ancho de zanja").fill("práctica de obra local");
    await page.getByLabel("Presupuesto de llamadas al solver").selectOption("60");
    await page.getByRole("button", { name: "Buscar topologías" }).click();

    const result = page.locator(".topology-optimizer .optimizer-run-result");
    await expect(result).toContainText(/Completada|Falló|Rechazada/, { timeout: 200_000 });
    await expect(result).toContainText("Completada");
    const card = page.locator(".topology-card:not(.base)").first();
    await expect(page.locator(".topology-card.base")).toBeVisible();

    await expect(card).toBeVisible(); // con el lote de prueba el solver siempre devuelve alternativas validadas
    {

      await card.getByRole("button", { name: /Vista previa/ }).click();
      await expect(card.locator("svg[aria-label='Alternativa sobre el diseño base']")).toBeVisible();
      await expect(card.locator("figcaption")).toContainText("Añadido");
      await card.getByRole("button", { name: "Aplicar como versión nueva" }).click();
      await expect(page.getByText(/Se creó la versión 2 del plano/)).toBeVisible();
    }
  });

  test("al recargar conserva el historial y las tarifas", async () => {
    await openOptimizer(page, seed.projectId);
    await expect(page.locator(".topology-history summary")).toContainText("Corridas anteriores (1)");
    await expect(page.getByLabel("Conductor (material)")).toHaveValue("18000");
    await page.locator(".topology-history summary").click();
    await page.locator(".topology-history button").first().click();
    await expect(page.locator(".topology-optimizer .optimizer-run-result")).toContainText("Completada");
    await expect(page.locator(".topology-card.base")).toBeVisible();
  });
});
