// Comprobaciones visuales de dos correcciones P0: materialización de la geometría paramétrica
// y coherencia de la respuesta del agente con la versión guardada. Solo usa proyectos locales zz-smoke-*.
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
const geometry = {
  length_m: 40, width_m: 30, burial_depth_m: 0.5,
  conductor_spacing_x_m: 5, conductor_spacing_y_m: 6, rods_count: 8, rod_length_m: 2.4,
  conductors: [],
};
const artifact = {
  name: "Malla paramétrica smoke-ui",
  geometry,
  soil_layers: [{ resistivity_ohm_m: 100 }],
  fault: { current_a: 8000, clearing_time_s: 0.5, body_weight_kg: 70, surface_resistivity_ohm_m: 3000, surface_thickness_m: 0.1 },
};
const explicitConductors = [
  ...Array.from({ length: 6 }, (_, index) => ({ start: { x: 0, y: index * 6 }, end: { x: 40, y: index * 6 } })),
  ...Array.from({ length: 9 }, (_, index) => ({ start: { x: index * 5, y: 0 }, end: { x: index * 5, y: 30 } })),
];
const explicitRods = [[0, 0], [17.5, 0], [35, 0], [40, 12.5], [40, 30], [22.5, 30], [5, 30], [0, 17.5]]
  .map(([x, y]) => ({ x, y, length_m: 2.4 }));

test.describe.serial("flujos P0: plano y agente", () => {
  test.skip(!LOCAL, "Crea y borra datos de prueba; solo se ejecuta contra localhost.");
  test.skip(!creds("designer"), "Falta el perfil designer; créalo localmente con make smoke-ui-seed.");

  let page;
  const seed = { projectName: runId() };

  test.beforeAll(async ({ browser }) => {
    test.setTimeout(60_000);
    page = await sessionPage(browser, "designer");
    const project = await post(page, "/api/v1/projects", {
      name: seed.projectName, description: "Pruebas P0 de plano y agente; se borra automáticamente.", city: "Bogotá", country: "Colombia",
    });
    expect(project.status, JSON.stringify(project.body)).toBe(201);
    seed.projectId = project.body.id;
    const created = await post(page, `/api/v1/projects/${seed.projectId}/artefactos-diseno-tierras`, artifact);
    expect(created.status, JSON.stringify(created.body)).toBe(201);
    seed.artifactId = created.body.artifact_id;
    const emptyLists = await post(page, `/api/v1/projects/${seed.projectId}/artefactos-diseno-tierras`, {
      ...artifact, name: "Malla con listas vacías smoke-ui",
    });
    expect(emptyLists.status, JSON.stringify(emptyLists.body)).toBe(201);
    seed.emptyArtifactId = emptyLists.body.artifact_id;
    const explicit = await post(page, `/api/v1/projects/${seed.projectId}/artefactos-diseno-tierras`, {
      ...artifact, name: "Malla explícita smoke-ui",
      geometry: { ...geometry, conductors: explicitConductors, rods: explicitRods },
    });
    expect(explicit.status, JSON.stringify(explicit.body)).toBe(201);
    seed.explicitArtifactId = explicit.body.artifact_id;
    const implicit = await post(page, `/api/v1/projects/${seed.projectId}/artefactos-diseno-tierras`, {
      ...artifact, name: "Malla sin listas smoke-ui",
      geometry: { ...geometry, conductors: undefined },
    });
    expect(implicit.status, JSON.stringify(implicit.body)).toBe(201);
    seed.implicitArtifactId = implicit.body.artifact_id;
    const conversation = await post(page, `/api/v1/projects/${seed.projectId}/conversations`, { title: "Plano y agente smoke-ui" });
    expect(conversation.status, JSON.stringify(conversation.body)).toBe(201);
    seed.conversationId = conversation.body.id;
  });

  test.afterAll(async () => {
    if (page) await sweepResidue(page);
    await page?.context().close();
  });

  test("P3: abre la retícula paramétrica y las varillas en Resumen y en el editor de plano", async () => {
    const state = await api(page, `/api/v1/conversations/${seed.conversationId}/agent-state`, {
      method: "PUT", body: JSON.stringify({ artifact_id: seed.artifactId }),
    });
    expect(state.status).toBe(200);
    await page.goto(`/project/${seed.projectId}`);
    const tabs = page.getByRole("tablist", { name: "Secciones del artefacto" });
    await tabs.getByRole("tab", { name: "Resumen" }).click();
    await expect(page.locator('.agent-grid-svg line[stroke="#2563c9"]')).toHaveCount(15);
    await expect(page.locator(".agent-grid-svg circle")).toHaveCount(8);

    // The plan editor is its own project view, opened from Resumen.
    await page.getByRole("button", { name: "Editar plano" }).click();
    const dialog = page.getByRole("region", { name: /Editor del plano de puesta a tierra/ });
    await expect(dialog.getByText("Elementos (23)")).toBeVisible();
    await expect(dialog.locator(".ground-plan-preview-conductor")).toHaveCount(15);
    await expect(dialog.locator(".ground-plan-preview-electrode")).toHaveCount(8);
    await dialog.locator("g[data-item-id]").nth(7).click({ force: true });
    const coordinates = dialog.locator(".ground-plan-properties input[type=number]");
    await coordinates.nth(0).fill("4");
    await coordinates.nth(2).fill("4");
    await expect.poll(async () => {
      const versions = await api(page, `/api/v1/projects/${seed.projectId}/artefactos-diseno-tierras/${seed.artifactId}/versions`);
      return versions.status === 200 ? versions.body.length : 0;
    }).toBe(2);
    const versions = await api(page, `/api/v1/projects/${seed.projectId}/artefactos-diseno-tierras/${seed.artifactId}/versions`);
    expect(versions.status).toBe(200);
    expect(versions.body.map((version) => version.version)).toEqual([2, 1]);
    expect(versions.body[0].snapshot.geometry.conductors).toContainEqual(expect.objectContaining({
      start: { x: 4, y: 0 }, end: { x: 4, y: 30 },
    }));
    expect(versions.body[1].snapshot.geometry.conductors).toEqual([]); // la versión original no se muta
    await dialog.getByRole("button", { name: "Cerrar editor de plano" }).click();
    await page.getByRole("button", { name: "Editar plano" }).click();
    const reopened = page.getByRole("region", { name: /Editor del plano de puesta a tierra/ });
    await expect(reopened.locator(".ground-plan-preview-conductor")).toHaveCount(15);
    await expect(reopened.locator(".ground-plan-preview-electrode")).toHaveCount(8);
    expect((await api(page, `/api/v1/projects/${seed.projectId}/artefactos-diseno-tierras/${seed.artifactId}/versions`)).body.length).toBe(2);
    await reopened.getByRole("button", { name: "Cerrar editor de plano" }).click();
  });

  test("P3: la geometría explícita, las listas vacías y la ausencia de listas se hidratan una sola vez", async () => {
    for (const artifactId of [seed.explicitArtifactId, seed.emptyArtifactId, seed.implicitArtifactId]) {
      const state = await api(page, `/api/v1/conversations/${(await api(page, `/api/v1/projects/${seed.projectId}/conversations`)).body[0].id}/agent-state`, {
        method: "PUT", body: JSON.stringify({ artifact_id: artifactId }),
      });
      expect(state.status).toBe(200);
      await page.goto(`/project/${seed.projectId}`);
      await page.getByRole("tablist", { name: "Secciones del artefacto" }).getByRole("tab", { name: "Resumen" }).click();
      await page.getByRole("button", { name: "Editar plano" }).click();
      const dialog = page.getByRole("region", { name: /Editor del plano de puesta a tierra/ });
      await expect(dialog.locator(".ground-plan-preview-conductor")).toHaveCount(15);
      await expect(dialog.locator(".ground-plan-preview-electrode")).toHaveCount(8);
      await dialog.getByRole("button", { name: "Cerrar editor de plano" }).click();
      const versions = await api(page, `/api/v1/projects/${seed.projectId}/artefactos-diseno-tierras/${artifactId}/versions`);
      expect(versions.body).toHaveLength(1);
    }
    const explicit = await api(page, `/api/v1/projects/${seed.projectId}/artefactos-diseno-tierras/${seed.explicitArtifactId}/versions`);
    expect(explicit.body[0].snapshot.geometry.conductors).toEqual(explicitConductors);
    expect(explicit.body[0].snapshot.geometry.rods).toEqual(explicitRods);
  });

  test("P4: una edición visible en una versión no termina con una negación de cambios", async () => {
    test.setTimeout(180_000);
    await page.goto(`/project/${seed.projectId}`);
    const conversationResponse = await api(page, `/api/v1/projects/${seed.projectId}/conversations`);
    expect(conversationResponse.status).toBe(200);
    const conversation = conversationResponse.body[0];
    const selectedArtifact = await api(page, `/api/v1/conversations/${conversation.id}/agent-state`, {
      method: "PUT", body: JSON.stringify({ artifact_id: seed.artifactId }),
    });
    expect(selectedArtifact.status).toBe(200);
    const initialVersions = await api(page, `/api/v1/projects/${seed.projectId}/artefactos-diseno-tierras/${seed.artifactId}/versions`);
    const previousVersion = initialVersions.body[0].version;
    const expectedVersion = previousVersion + 1;
    await page.getByLabel("Mensaje para el chat del proyecto").fill(
      "En el artefacto, establece exactamente geometry.width_m = 31.0 (ahora es 30.0). No redondees el valor ni cambies geometry.length_m; conserva todos los otros datos y guarda la nueva versión. Luego dime qué cambió.",
    );
    await page.getByLabel("Mensaje para el chat del proyecto").press("Enter");

    await expect.poll(async () => {
      const versions = await api(page, `/api/v1/projects/${seed.projectId}/artefactos-diseno-tierras/${seed.artifactId}/versions`);
      return versions.status === 200 ? versions.body[0]?.version : 0;
    }, { timeout: 150_000, intervals: [1000, 2000, 4000] }).toBe(expectedVersion);
    await expect(page.locator(".artifact-update-card").last()).toContainText(new RegExp(`versión ${expectedVersion}|version ${expectedVersion}`, "i"), { timeout: 90_000 });
    const conversationId = conversation.id;
    await expect.poll(async () => {
      const state = await api(page, `/api/v1/conversations/${conversationId}/agent-events`);
      const status = state.body.active_run?.status;
      return !status || status === "waiting_user" ? "idle" : status;
    }, { timeout: 150_000, intervals: [1000, 2000, 4000] }).toBe("idle");
    const assistantMessages = page.locator(".project-chat-messages .message.assistant");
    await expect(assistantMessages.last()).not.toContainText(/no se realizaron cambios|no hicieron cambios|no hubo cambios|no changes were made/i);
    const versions = await api(page, `/api/v1/projects/${seed.projectId}/artefactos-diseno-tierras/${seed.artifactId}/versions`);
    // La API devuelve versiones newest-first.
    expect(versions.body[0].snapshot.geometry.width_m,
      JSON.stringify({ width_m: versions.body[0].snapshot.geometry.width_m, message: await assistantMessages.last().textContent() })).toBe(31);
    await expect(assistantMessages.last()).toContainText(new RegExp(`versión ${expectedVersion}|version ${expectedVersion}|geometry.width_m=31`, "i"));
  });
});
