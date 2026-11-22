// P4-02 y P4-03 forzados desde la UI con el LLM de prueba (escenario p4): el modelo SÍ emite la negación o la
// afirmación falsa, así que la prueba demuestra que el backend la corrige antes de que llegue al chat.
// Requiere el worker de agente apuntando al LLM de prueba (app/smoke-ui/loop-scenarios/README.md) y
// SMOKE_LOOP_SCENARIO=p4. Solo local: crea un proyecto zz-smoke-* y lo barre al terminar.
import { test, expect } from "@playwright/test";
import { creds, sessionPage, runId, sweepResidue } from "../helpers.js";

const LOCAL = /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:|\/|$)/.test(process.env.SMOKE_BASE_URL || "");
const CLAIMS_A_SAVE = /\b(?:guard[eé]|cre[eé]|apliqu[eé]|actualic[eé])\b.{0,50}\b(?:versi[oó]n|diseñ|artefacto)\b/i;

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

let page; let ctx;
test.describe.configure({ mode: "serial" });

test.beforeAll(async ({ browser }) => {
  test.skip(!LOCAL || !creds("designer"), "Solo local y con el perfil designer (make smoke-ui-seed).");
  test.skip(process.env.SMOKE_LOOP_SCENARIO !== "p4", "El worker de agente no apunta al LLM de prueba en el escenario p4.");
  page = await sessionPage(browser, "designer");
  const project = await post(page, "/api/v1/projects", { name: runId(), description: "P4 forzado; se borra solo." });
  expect(project.status, JSON.stringify(project.body)).toBe(201);
  const artifact = await post(page, `/api/v1/projects/${project.body.id}/artefactos-diseno-tierras`, {
    name: "Malla P4 forzada", geometry: { length_m: 40, width_m: 30, burial_depth_m: 0.5, conductor_spacing_x_m: 5, conductor_spacing_y_m: 6 },
    soil_layers: [{ resistivity_ohm_m: 100 }], fault: { current_a: 1000, clearing_time_s: 0.5 },
  });
  expect(artifact.status, JSON.stringify(artifact.body)).toBe(201);
  ctx = { projectId: project.body.id, artifactId: artifact.body.artifact_id, evidence: [] };
  await page.goto(`/project/${ctx.projectId}`);
  await expect.poll(async () => (await api(page, `/api/v1/projects/${ctx.projectId}/conversations`)).body.length).toBeGreaterThan(0);
  ctx.conversationId = (await api(page, `/api/v1/projects/${ctx.projectId}/conversations`)).body[0].id;
  expect((await api(page, `/api/v1/conversations/${ctx.conversationId}/agent-state`, { method: "PUT", body: JSON.stringify({ artifact_id: ctx.artifactId }) })).status).toBe(200);
});

test.afterAll(async ({}, testInfo) => {
  if (!page) return;
  await testInfo.attach("evidencia-p4-forzado.json", { body: JSON.stringify(ctx?.evidence || [], null, 2), contentType: "application/json" });
  await page.screenshot({ path: testInfo.outputPath("p4-forzado.png") });
  await sweepResidue(page);
  await page.context().close();
});

const versions = async () => (await api(page, `/api/v1/projects/${ctx.projectId}/artefactos-diseno-tierras/${ctx.artifactId}/versions`)).body;

async function ask(text) {
  const before = (await api(page, `/api/v1/conversations/${ctx.conversationId}/messages/first`)).body.length;
  const composer = page.getByPlaceholder("Describe lo que necesitas…");
  await composer.fill(text);
  await composer.press("Enter");
  await expect.poll(async () => {
    const state = await api(page, `/api/v1/conversations/${ctx.conversationId}/agent-events`);
    const messages = (await api(page, `/api/v1/conversations/${ctx.conversationId}/messages/first`)).body;
    return messages.slice(before).some((m) => m.source === "agent") && !state.body.active_run ? "done" : "working";
  }, { timeout: 120_000, intervals: [1000, 2000, 3000] }).toBe("done");
  const messages = (await api(page, `/api/v1/conversations/${ctx.conversationId}/messages/first`)).body;
  return [...messages].reverse().find((m) => m.source === "agent").text;
}

for (const [index, negation] of ["No se realizaron cambios.", "No hicimos cambios.", "No hubo cambios.", "No changes were made."].entries()) {
  const width = 31 + index;
  test(`P4-02 forzado: el modelo niega con «${negation}» tras guardar el ancho ${width} m`, async () => {
    const before = (await versions())[0].version;
    const answer = await ask(`ESCENARIO=negar ANCHO=${width} FRASE=«${negation}»`);
    const [latest] = await versions();
    ctx.evidence.push({ case: "P4-02", modelSaid: negation, versionSaved: latest.version, answer });
    expect(latest.version).toBe(before + 1);
    expect(latest.snapshot.geometry.width_m).toBe(width);
    expect(answer).not.toContain(negation);
    expect(answer).toContain(`Se guardó la versión ${latest.version}`);
    await expect(page.getByText(`Se guardó la versión ${latest.version}`).last()).toBeVisible();
    await expect(page.getByText(negation, { exact: true })).toHaveCount(0);
  });
}

test("P4-02 forzado: el modelo afirma una versión que no guardó", async () => {
  const before = (await versions())[0].version;
  const answer = await ask("ESCENARIO=afirmar");
  const [latest] = await versions();
  ctx.evidence.push({ case: "P4-02 sin cambios", modelSaid: "Guardé la versión 99 del diseño.", versionSaved: null, answer });
  expect(latest.version).toBe(before);
  expect(answer).toBe("No se guardó una versión nueva del diseño en este paso.");
  await expect(page.getByText("Guardé la versión 99 del diseño.")).toHaveCount(0);
});

test("P4-03 forzado: tras un cambio válido, el inválido no se anuncia ni se guarda", async () => {
  const before = (await versions())[0].version;
  const answer = await ask("ESCENARIO=invalido ANCHO=38");
  const after = await versions();
  const created = after.filter((row) => row.version > before);
  ctx.evidence.push({ case: "P4-03", modelSaid: "Guardé la profundidad de -2 m en una versión nueva.",
    created: created.map((row) => ({ version: row.version, width: row.snapshot.geometry.width_m, depth: row.snapshot.geometry.burial_depth_m })), answer });
  expect(created.map((row) => row.snapshot.geometry.width_m)).toEqual([38]);
  expect(after.every((row) => row.snapshot.geometry.burial_depth_m > 0)).toBe(true);
  expect(answer).toContain(`Se guardó la versión ${created[0].version}`);
  const saved = (answer.split("Campos guardados:")[1] || "").split(/Cambios no aplicados|no se aplic|rechaz/i)[0];
  expect(saved).toContain("ancho: 38 m");
  expect(saved, "La profundidad rechazada no puede figurar como guardada").not.toContain("burial_depth_m");
  // P4-03: el rechazo se conserva y se explica en la misma respuesta.
  expect(answer, "La respuesta debe explicar el cambio rechazado").toMatch(/(no aplicad|rechaz|no se guard|no pas)[^]*burial_depth_m|burial_depth_m[^]*(no aplicad|rechaz|no se guard|no pas)/i);
  await expect(page.getByText("Guardé la profundidad de -2 m en una versión nueva.")).toHaveCount(0);

  // El registro aplicado no se reutiliza: un paso posterior sin cambios no hereda la versión anterior.
  const next = await ask("ESCENARIO=afirmar");
  ctx.evidence.push({ case: "P4-03 paso siguiente", answer: next });
  expect(next).toBe("No se guardó una versión nueva del diseño en este paso.");
  expect(CLAIMS_A_SAVE.test(next)).toBe(false);
});
