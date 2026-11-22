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
  await page.getByRole("tablist", { name: "Secciones del artefacto" }).getByRole("tab", { name: "Resumen" }).click();
  await page.getByRole("button", { name: /^(Editar|Dibujar) plano$/ }).click();
  await page.getByText("Matherra · optimización matemática").click();
}
const profilesOf = async (page, projectId) => (await api(page, `/api/v1/projects/${projectId}/constraint-profiles`)).body.profiles.length;
async function fillRun(page) {
  await page.getByLabel("Clase de exposición").selectOption("public");
  await page.getByLabel("¿Existe capa superficial?").selectOption("true");
  await page.getByLabel("IEEE 80-2013").check();
  for (const [label, value] of Object.entries(RATES)) await page.getByLabel(label).fill(value);
  await page.getByLabel("Fuente de las tarifas").fill("cotización de prueba");
  await page.getByLabel("Ancho de zanja (m)").fill("0.4");
  await page.getByLabel("Fuente del ancho de zanja").fill("práctica de obra local");
  await page.getByLabel("Presupuesto de evaluaciones eléctricas").selectOption("60");
}
async function openResults(page) {
  await page.getByRole("tablist", { name: "Secciones del artefacto" }).getByRole("tab", { name: "Resultado" }).click();
  return page.getByRole("region", { name: "Alternativas de Matherra" });
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
    seed.draftProfileId = runId().toLowerCase();
    const draft = await post(admin, "/api/v1/constraint-profiles", {
      profile_id: seed.draftProfileId, definition: { ...PROFILE, title: "Perfil borrador smoke-ui" },
    });
    expect(draft.status, JSON.stringify(draft.body)).toBe(201);
    seed.incompatibleProfileId = runId().toLowerCase();
    const incompatible = await post(admin, "/api/v1/constraint-profiles", {
      profile_id: seed.incompatibleProfileId,
      definition: { ...PROFILE, title: "Perfil incompatible smoke-ui", installation_type: "industrial_ac" },
    });
    expect(incompatible.status, JSON.stringify(incompatible.body)).toBe(201);
    expect((await post(admin, `/api/v1/constraint-profiles/${seed.incompatibleProfileId}/versions/1/review`, {})).status).toBe(200);

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
    if (admin) {
      if (seed.draftProfileId) {
        await post(admin, `/api/v1/constraint-profiles/${seed.draftProfileId}/versions/1/review`, {}).catch(() => {});
        await post(admin, `/api/v1/constraint-profiles/${seed.draftProfileId}/versions/1/retire`, {}).catch(() => {});
      }
      if (seed.incompatibleProfileId) await post(admin, `/api/v1/constraint-profiles/${seed.incompatibleProfileId}/versions/1/retire`, {}).catch(() => {});
      await post(admin, `/api/v1/constraint-profiles/${seed.profileId}/versions/1/retire`, {}).catch(() => {});
      await admin.context().close();
    }
    await page?.context().close();
  });

  test("sin perfil fijado al proyecto no deja iniciar y dice por qué", async () => {
    await openOptimizer(page, seed.projectId);
    const profile = page.getByRole("checkbox", { name: /Perfil de prueba smoke-ui/ });
    await expect(profile).toBeChecked();
    await profile.uncheck();                                         // se guarda al marcar, sin paso aparte
    await expect.poll(() => profilesOf(page, seed.projectId)).toBe(0);
    await expect(page.getByRole("button", { name: "Iniciar búsqueda con Matherra" })).toBeDisabled();
    await expect(page.locator("#topology-start-blocker")).toContainText("perfil normativo revisado");
    await profile.check();
    await expect.poll(() => profilesOf(page, seed.projectId)).toBe(1);
  });

  test("oculta el perfil borrador y rechaza fijarlo al proyecto", async () => {
    await openOptimizer(page, seed.projectId);
    await expect(page.getByRole("checkbox", { name: /Perfil borrador smoke-ui/ })).toHaveCount(0);
    const response = await api(page, `/api/v1/projects/${seed.projectId}/constraint-profiles`, {
      method: "PUT", body: JSON.stringify({ profiles: [{ profile_id: seed.draftProfileId, version: 1 }] }),
    });
    expect([400, 404, 409, 422]).toContain(response.status);
    const selected = await api(page, `/api/v1/projects/${seed.projectId}/constraint-profiles`);
    expect(selected.body.profiles.map((item) => [item.profile_id, item.profile_version])).toEqual([[seed.profileId, 1]]);
  });

  test("rechaza buscar con perfiles fijados para tipos de instalación distintos", async () => {
    const selected = await api(page, `/api/v1/projects/${seed.projectId}/constraint-profiles`, {
      method: "PUT", body: JSON.stringify({ profiles: [
        { profile_id: seed.profileId, version: 1 },
        { profile_id: seed.incompatibleProfileId, version: 1 },
      ] }),
    });
    expect(selected.status).toBe(200);
    await openOptimizer(page, seed.projectId);
    await fillRun(page);
    await page.getByRole("button", { name: "Iniciar búsqueda con Matherra" }).click();
    await expect(page.locator(".topology-optimizer").getByRole("alert")).toContainText("different installation types");
    await api(page, `/api/v1/projects/${seed.projectId}/constraint-profiles`, {
      method: "PUT", body: JSON.stringify({ profiles: [{ profile_id: seed.profileId, version: 1 }] }),
    });
  });

  test("precarga el suelo y la falla del artefacto, busca, previsualiza y aplica", async () => {
    test.setTimeout(240_000);
    await openOptimizer(page, seed.projectId);
    // La falla viene del plano; el suelo se muestra (no se edita aquí: lo define el plano).
    await expect(page.getByText("Suelo del plano guardado: homogéneo, 100 Ω·m.")).toBeVisible();
    await expect(page.getByLabel("Corriente de falla inyectada (A)")).toHaveValue("1000");
    await expect(page.getByLabel("Tiempo de despeje (s)")).toHaveValue("0.5");
    await expect(page.getByLabel("Peso corporal (kg)")).toHaveValue("70");
    await fillRun(page);
    await page.getByRole("button", { name: "Iniciar búsqueda con Matherra" }).click();

    const result = page.locator(".topology-optimizer .optimizer-run-result");
    await expect(result).toContainText(/Completada|Falló|Rechazada/, { timeout: 200_000 });
    await expect(result).toContainText("Completada");
    // Las alternativas solo se revisan en Resultado, junto al veredicto.
    await page.getByTestId("matherra-show-results").click();
    const review = page.getByRole("region", { name: "Alternativas de Matherra" });
    await expect(review).toContainText("Diseño de partida");
    const card = review.getByTestId("matherra-candidate").first();
    await expect(card).toBeVisible(); // con el lote de prueba el solver siempre devuelve alternativas validadas
    await card.getByRole("button", { name: "Vista previa" }).click();
    await expect(card.locator("svg[aria-label='Alternativa sobre el diseño base']")).toBeVisible();
    await expect(card.locator("figcaption")).toContainText("Añadido");
    await card.getByRole("button", { name: "Aplicar como nueva versión" }).click();
    await expect(review.getByText(/Se creó la versión 2 con la alternativa/)).toBeVisible();
    await expect(card.getByRole("button", { name: "Versión actual" })).toBeDisabled();   // no se aplica dos veces
  });

  test("al recargar conserva las tarifas y la búsqueda sigue en Resultado", async () => {
    await openOptimizer(page, seed.projectId);
    await expect(page.getByLabel("Conductor (material)")).toHaveValue("18000");
    await expect(page.getByLabel("Clase de exposición")).toHaveValue("public");
    await expect(page.getByLabel("IEEE 80-2013")).toBeChecked();
    await page.getByRole("button", { name: "Cerrar editor de plano" }).click(); // the editor is a view: leave it to see the tabs
    const review = await openResults(page);
    await expect(review).toContainText("Completada");
    await expect(review.getByTestId("matherra-candidate").first()).toContainText("Es la versión 2 del plano");
  });

  test("ofrece las tarifas del catálogo aprobado y la corrida conserva su procedencia", async () => {
    test.setTimeout(240_000);
    const item = await post(page, `/api/v1/projects/${seed.projectId}/material-catalog`, {
      name: "Cable de cobre desnudo 2/0 (prueba)", category: "conductor", specification: "Cobre desnudo 2/0 AWG, cotización de prueba",
      quantity_unit: "m", price_per_unit: "21000", price_currency: "COP", supplier: "Proveedor de prueba", notes: "Cotización de prueba smoke-ui" });
    expect(item.status, JSON.stringify(item.body)).toBe(201);
    expect((await post(page, `/api/v1/projects/${seed.projectId}/material-catalog/${item.body.id}/approval`, { approved: true })).status).toBe(200);

    await openOptimizer(page, seed.projectId);
    await page.getByLabel("Clase de exposición").selectOption("public");
    await page.getByLabel("¿Existe capa superficial?").selectOption("true");
    await page.getByLabel("IEEE 80-2013").check();
    await page.getByLabel("Conductor (material): origen").selectOption(item.body.id);
    await expect(page.getByTestId("rate-catalog-material.conductor.unspecified")).toContainText("21.000 COP");
    await expect(page.getByLabel("Conductor (material)", { exact: true })).toHaveCount(0);   // ya no se escribe a mano
    await page.getByLabel("Presupuesto de evaluaciones eléctricas").selectOption("60");
    await page.getByRole("button", { name: "Iniciar búsqueda con Matherra" }).click();
    const result = page.locator(".topology-optimizer .optimizer-run-result");
    await expect(result).toContainText(/Completada|Falló|Rechazada/, { timeout: 200_000 });
    await expect(result).toContainText("Completada");

    const runs = await api(page, `/api/v1/projects/${seed.projectId}/optimizer-runs`);
    const latest = runs.body.runs.find((row) => row.request_snapshot?.request?.rates?.["material.conductor.unspecified"]?.catalog_item_id);
    expect(latest.request_snapshot.rate_provenance["material.conductor.unspecified"]).toMatchObject({ source_type: "catalog", catalog_item_id: item.body.id });
    expect(Number(latest.request_snapshot.rate_card.rates["material.conductor.unspecified"])).toBe(21000);
    expect(latest.request_snapshot.request.orthogonal_only).toBe(true);
    for (const alt of (await api(page, `/api/v1/projects/${seed.projectId}/optimizer-runs/${latest.id}`)).body.alternatives) {
      const diagonal = (alt.evaluation_snapshot.geometry.conductors || []).filter((c) => Math.abs(c.start.x - c.end.x) > 1e-6 && Math.abs(c.start.y - c.end.y) > 1e-6);
      expect(diagonal).toEqual([]);
    }
  });

  test("el estudio publicado muestra la alternativa aplicada, las tarifas y la advertencia de sin certificar", async () => {
    const list = await api(page, `/api/v1/projects/${seed.projectId}/artefactos-diseno-tierras`);
    const latest = list.body.reduce((a, b) => (b.version > a.version ? b : a));
    expect(latest.version).toBe(2);
    const study = await post(page, `/api/v1/projects/${seed.projectId}/studies`, { artifact_id: latest.artifact_id, artifact_version: 2, title: `${runId()} estudio`, access: "link" });
    expect(study.status, JSON.stringify(study.body)).toBe(201);
    let published = await post(page, `/api/v1/projects/${seed.projectId}/studies/${study.body.id}/publish`, { status: "published" });
    if (published.status === 409) published = await post(page, `/api/v1/projects/${seed.projectId}/studies/${study.body.id}/publish`, { status: "published", confirm_non_compliant: true });
    expect(published.status, JSON.stringify(published.body)).toBe(200);
    await page.goto(`/e/${study.body.slug}`);
    const section = page.getByTestId("study-optimization");
    await expect(section).toContainText("Borrador sin certificar");
    await expect(section.getByRole("table")).toContainText("Diseño base");
    await expect(page.getByTestId("study-optimization-rates")).toContainText("cotización de prueba");
    await expect(page.getByTestId("study-optimization-warnings")).toContainText("Ninguna alternativa está certificada");
    await page.screenshot({ path: "../test-results/smoke-ui/study-optimization.png", fullPage: true });
  });
});
