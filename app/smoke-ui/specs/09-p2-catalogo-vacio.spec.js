// P2-01 (catálogo global vacío): sin ninguna versión revisada en el catálogo de perfiles normativos, el
// optimizador no ofrece ni sugiere un perfil por defecto y bloquea la resolución del contexto.
// No vacía el catálogo: si existe algún perfil revisado, la prueba se omite (no toca datos compartidos).
// Solo local: crea un proyecto zz-smoke-* y lo barre al terminar.
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

test("P2-01: con el catálogo sin perfiles revisados, el optimizador no sugiere ninguno y bloquea el contexto", async ({ browser }, testInfo) => {
  test.skip(!LOCAL, "Crea objetos; solo se ejecuta contra localhost.");
  test.skip(!creds("designer"), "Falta el perfil designer; créalo con make smoke-ui-seed.");
  test.setTimeout(120_000);
  const page = await sessionPage(browser, "designer");
  try {
    const catalog = await api(page, "/api/v1/constraint-profiles");
    expect(catalog.status).toBe(200);
    const reviewed = catalog.body.profiles.filter((profile) => profile.status === "reviewed");
    test.skip(reviewed.length > 0, `El catálogo tiene ${reviewed.length} perfil(es) revisado(s); este caso necesita un catálogo vacío.`);

    const project = await post(page, "/api/v1/projects", { name: runId(), description: "P2-01 catálogo vacío; se borra solo." });
    expect(project.status, JSON.stringify(project.body)).toBe(201);
    const projectId = project.body.id;
    const artifact = await post(page, `/api/v1/projects/${projectId}/artefactos-diseno-tierras`, {
      name: "Malla catálogo vacío", geometry: { length_m: 40, width_m: 30, burial_depth_m: 0.5, conductor_spacing_x_m: 5, conductor_spacing_y_m: 6 },
      soil_layers: [{ resistivity_ohm_m: 100 }], fault: { current_a: 1000, clearing_time_s: 0.5 },
    });
    expect(artifact.status, JSON.stringify(artifact.body)).toBe(201);

    await page.goto(`/project/${projectId}`);
    await page.getByRole("tablist", { name: "Secciones del artefacto" }).getByRole("tab", { name: "Plano" }).click();
    await page.getByRole("button", { name: "Abrir editor de plano" }).click();
    await page.getByText("Restricciones de optimización").click();

    // Ningún perfil ofrecido ni marcado por defecto; guardar no tiene nada que fijar.
    await expect(page.getByText("No hay perfiles normativos revisados disponibles para seleccionar.")).toBeVisible();
    await expect(page.locator(".topology-optimizer, .optimizer-panel, body").getByRole("checkbox", { name: /perfil/i })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Guardar perfiles del proyecto" })).toBeDisabled();
    expect((await api(page, `/api/v1/projects/${projectId}/constraint-profiles`)).body.profiles).toEqual([]);

    await page.getByRole("button", { name: "Resolver contexto" }).click();
    await expect(page.locator(".optimizer-context-status")).toContainText("Optimización bloqueada");
    await expect(page.locator(".optimizer-context-result")).toContainText("normative_profile_not_selected");
    await expect(page.locator(".optimizer-context-result")).not.toContainText("vnone");
    // El bloqueo no fija nada a escondidas.
    expect((await api(page, `/api/v1/projects/${projectId}/constraint-profiles`)).body.profiles).toEqual([]);
    await page.screenshot({ path: testInfo.outputPath("catalogo-vacio.png") });
  } finally {
    await sweepResidue(page);
    await page.context().close();
  }
});
