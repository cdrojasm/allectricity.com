// Coherencia de producto: el estudio publicado debe concluir lo mismo que el panel Resultados del
// espacio de trabajo, con los mismos números, y ser legible (sin JSON crudo) también en móvil.
// Siembra por API un proyecto zz-smoke-* con un artefacto, un cálculo real y un estudio publicado
// (no usa el agente ni el LLM) y lo borra al terminar.
import { test, expect } from "@playwright/test";
import { creds, sessionPage, runId, sweepResidue } from "../helpers.js";

const SNAPSHOT = {
  name: "Malla patio 40x30",
  geometry: { length_m: 40, width_m: 30, burial_depth_m: 0.5, conductor_spacing_m: 5, rods_count: 8, rod_length_m: 2.4 },
  soil_layers: [{ resistivity_ohm_m: 120, depth_m: 2.0 }, { resistivity_ohm_m: 300 }],
  fault: { current_a: 8500, clearing_time_s: 0.5 },
};

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

test.describe.serial("estudio publicado", () => {
  test.skip(!creds("designer"), "Falta el perfil designer (SMOKE_DESIGNER_EMAIL/_PASSWORD).");
  let page; let ctx;
  const seed = {};

  test.beforeAll(async ({ browser }) => {
    test.setTimeout(180_000);
    page = await sessionPage(browser, "designer");
    ctx = page.context();
    seed.name = runId();
    const project = await post(page, "/api/v1/projects", { name: seed.name, description: "Subestación de prueba. Se borra sola.", city: "Medellín", country: "Colombia" });
    expect(project.status).toBe(201);
    seed.projectId = project.body.id;
    const root = `/api/v1/projects/${seed.projectId}/artefactos-diseno-tierras`;
    const artifact = await post(page, root, SNAPSHOT);
    expect(artifact.status).toBe(201);
    const { artifact_id: artifactId, version } = artifact.body;
    const calc = await post(page, `${root}/${artifactId}/versions/${version}/calculos-potencial`, { surface_spacing_m: 1.0, safety_standards: ["IEEE 80-2013"] });
    expect(calc.status).toBe(202);
    await expect.poll(async () => (await api(page, `${root}/${artifactId}/calculos-potencial/${calc.body.id}`)).body.status, { timeout: 150_000, intervals: [2000] }).toBe("completed");
    const study = await post(page, `/api/v1/projects/${seed.projectId}/studies`, { artifact_id: artifactId, artifact_version: version, title: "Estudio de prueba", access: "public" });
    expect(study.status).toBe(201);
    const publishUrl = `/api/v1/projects/${seed.projectId}/studies/${study.body.id}/publish`;
    const gate = await post(page, publishUrl, { status: "published" });
    if (gate.status === 409) { // un diseño que no cumple exige confirmación explícita
      expect(gate.body.detail.code).toBe("non_compliant");
      expect((await post(page, publishUrl, { status: "published", confirm_non_compliant: true })).status).toBe(200);
    } else expect(gate.status).toBe(200);
    seed.slug = study.body.slug;
  });

  test.afterAll(async () => {
    if (page) await sweepResidue(page); // borra por la UI el proyecto sembrado, aunque las pruebas fallen
    await ctx?.close();
  });

  test("concluye lo mismo que el panel Resultados del espacio de trabajo", async ({ browser }) => {
    await page.goto(`/project/${seed.projectId}`);
    await page.getByRole("tablist", { name: "Secciones del artefacto" }).getByRole("tab", { name: "Resultado" }).click();
    const panel = page.locator(".agent-results-panel");
    await expect(panel.locator(".agent-verdict")).toBeVisible();
    const workspace = {
      verdict: (await panel.locator(".agent-verdict").innerText()).trim(),
      interpretation: await panel.locator(".result-interpretation").innerText(),
      standard: await panel.locator(".artifact-status", { hasText: "IEEE 80-2013" }).innerText(),
    };

    // Sin sesión: así lo ve quien recibe el enlace.
    const visitor = await browser.newContext();
    const study = await visitor.newPage();
    await study.goto(`/e/${seed.slug}`);
    await expect(study.getByTestId("study-verdict")).toBeVisible();

    expect((await study.getByTestId("study-verdict").innerText()).trim()).toBe(workspace.verdict);
    const interpretation = await study.getByTestId("study-interpretation").innerText();
    for (const line of workspace.interpretation.split("\n").map((s) => s.trim()).filter((s) => /Tensión|V frente a/.test(s))) {
      expect(interpretation, `la interpretación del estudio debe contener «${line}»`).toContain(line);
    }
    // Los mismos números de contacto y paso que el panel (valor calculado y tolerable).
    const numbers = workspace.standard.match(/\d{1,3}(?:\.\d{3})*,\d V/g) || [];
    expect(numbers.length).toBeGreaterThanOrEqual(4);
    const results = await study.getByTestId("study-results").innerText();
    for (const n of numbers) expect(results, `el estudio debe mostrar ${n}`).toContain(n);
    await visitor.close();
  });

  test("el resultado es legible: tabla, mapa y aviso de revisión; sin JSON crudo", async ({ browser }) => {
    const visitor = await browser.newContext();
    const study = await visitor.newPage();
    await study.goto(`/e/${seed.slug}`);
    const results = study.getByTestId("study-results");
    await expect(results.getByRole("table")).toBeVisible();
    await expect(results.getByRole("row", { name: /Contacto/ })).toBeVisible();
    await expect(results.getByRole("row", { name: /Paso/ })).toBeVisible();
    await expect(study.getByTestId("study-thermal")).toContainText("mínima");
    await expect(study.getByTestId("study-map")).toBeVisible();
    await expect(study.getByTestId("study-disclaimer")).toContainText("requiere revisión de un ingeniero competente");
    await expect(study.locator("pre")).toHaveCount(0);
    await expect(study.locator("body")).not.toContainText(/calculation_id|artifact_version"|"status":/);
    // Entradas: suelo, falla y malla con unidades, no solo tres cifras sueltas.
    const inputs = study.getByTestId("study-inputs");
    await expect(inputs).toContainText("40 × 30 m");
    await expect(inputs).toContainText("8.500 A");
    await expect(inputs).toContainText("Capa 2");
    await expect(inputs).toContainText("semiinfinita");
    // El plano de la malla publicada acompaña a las entradas.
    await expect(study.getByTestId("study-plan").locator("svg")).toBeVisible();
    // Las referencias no repiten el origen en la nota ni muestran claves del esquema.
    const references = study.getByTestId("study-references");
    if (await references.count()) {
      await expect(references).not.toContainText(/Confirmado por el usuario · Confirmado por el usuario|schema version|geometry snap/);
    }
    await visitor.close();
  });

  test("en móvil el estudio no desborda horizontalmente", async ({ browser }) => {
    const visitor = await browser.newContext({ viewport: { width: 390, height: 800 } });
    const study = await visitor.newPage();
    await study.goto(`/e/${seed.slug}`);
    await expect(study.getByTestId("study-map")).toBeVisible();
    const overflow = await study.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, "no debe haber scroll horizontal de página").toBeLessThanOrEqual(1);
    await visitor.close();
  });
});
