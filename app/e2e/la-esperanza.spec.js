// E2E del agente con los archivos de docs/datos_prueba_agente (ver PLAN_E2E.md).
// Crea un usuario designer local por corrida; la contraseña vive solo en este proceso.
import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(import.meta.dirname, "../..");
const DATA = path.join(ROOT, "docs/datos_prueba_agente");
const OUT = path.join(import.meta.dirname, "../test-results/e2e");
const COMPOSE = ["compose", "--env-file", path.join(ROOT, ".env"), "-f", path.join(ROOT, "deploy/local/docker/docker-compose.yml")];
const log = { started_at: new Date().toISOString(), steps: [] };

function createUser() {
  const email = `e2e-${Date.now()}@example.com`;
  const password = randomBytes(18).toString("base64url");
  const script = `
import os
from src.application.use_cases.identity import assign, new_user
from src.infrastructure.security.container import build_services
from src.infrastructure.security.settings import Settings
s = build_services(Settings.from_env())
with s.store.transaction(write=True) as db:
    u = new_user(db, email=os.environ["E2E_EMAIL"], first_name="E2E", last_name="La Esperanza",
                 password_hash=s.identity.passwords.hash(os.environ["E2E_PASSWORD"]))
    assign(db, u["id"], "designer")
`;
  execFileSync("docker", [...COMPOSE, "exec", "-T", "-e", "E2E_EMAIL", "-e", "E2E_PASSWORD", "api", "python", "-c", script],
    { env: { ...process.env, E2E_EMAIL: email, E2E_PASSWORD: password }, stdio: ["ignore", "ignore", "inherit"] });
  return { email, password };
}

async function api(page, url, options = {}) {
  return page.evaluate(async ({ url, options }) => {
    const token = localStorage.getItem("spat_access_token");
    const response = await fetch(url, { ...options, headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", ...(options.headers || {}) } });
    const text = await response.text();
    try { return { status: response.status, body: JSON.parse(text) }; } catch { return { status: response.status, body: text }; }
  }, { url, options });
}

async function shot(page, name) {
  await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: false });
}

function record(step, data) {
  log.steps.push({ step, at: new Date().toISOString(), ...data });
  fs.writeFileSync(path.join(OUT, "log.json"), JSON.stringify(log, null, 2));
}


const UPLOADS = ["01_plano_implantacion_SE_La_Esperanza.pdf", "05_estudio_cortocircuito_SE_La_Esperanza.pdf",
  "06_informe_resistividad_SEV-2.docx", "07_sondeo_wenner_SEV-2.csv", "08_sondeo_schlumberger_SEV-3_ampliacion.xlsx",
  "03_malla_puesta_tierra_SE_La_Esperanza.dxf", "04_plano_general_multicapa_SE_La_Esperanza.dxf"];

const ACTIVE = new Set(["queued", "running", "waiting_calculation", "cancelling"]);

async function conversationId(page, projectId) {
  const { body } = await api(page, `/api/v1/projects/${projectId}/conversations`);
  const items = Array.isArray(body) ? body : body.items || body.conversations || [];
  return items[0]?.id;
}

async function messages(page, cid) {
  const { body } = await api(page, `/api/v1/conversations/${cid}/messages/first?limit=100`);
  return Array.isArray(body) ? body : [];
}

// Envía un mensaje por el composer y espera a que el run del agente termine o pida algo.
async function say(page, ctx, name, text, { maxMinutes = 15 } = {}) {
  ctx.cid ||= await conversationId(page, ctx.projectId);
  const before = ctx.cid ? (await messages(page, ctx.cid)).map((m) => m.id) : [];
  const box = page.getByRole("textbox", { name: "Mensaje para el chat del proyecto" });
  await box.fill(text);
  await box.press("Enter");
  const started = Date.now();
  let run = null, newMessages = [], events = [];
  await page.waitForTimeout(4000);
  while (Date.now() - started < maxMinutes * 60_000) {
    ctx.cid ||= await conversationId(page, ctx.projectId);
    const ev = (await api(page, `/api/v1/conversations/${ctx.cid}/agent-events?limit=200`)).body;
    run = ev.active_run;
    events = ev.events || [];
    newMessages = (await messages(page, ctx.cid)).filter((m) => !before.includes(m.id));
    const replied = newMessages.some((m) => m.source !== "user" && m.source !== "notification");
    if (replied && (!run || !ACTIVE.has(run.status))) break;
    await page.waitForTimeout(3000);
  }
  const lastSeq = before.length ? ctx.lastSeq || 0 : 0;
  const fresh = events.filter((e) => e.seq > lastSeq);
  ctx.lastSeq = events.at(-1)?.seq ?? ctx.lastSeq;
  await page.waitForTimeout(1500);
  await shot(page, name);
  record(name, {
    user: text,
    seconds: Math.round((Date.now() - started) / 1000),
    run_status: run?.status || "idle",
    pending_question: run?.pending_question || null,
    events: fresh.map((e) => `${e.type} · ${e.title}`),
    replies: newMessages.filter((m) => m.source !== "user").map((m) => ({ source: m.source, text: m.text, payload_kind: m.payload?.kind })),
  });
  return newMessages;
}

async function openSection(page, label) {
  await page.getByRole("tablist", { name: "Secciones del artefacto" }).getByRole("tab", { name: label }).click();
  await page.waitForTimeout(2000);
}

test("SE La Esperanza: carga, chat, malla, cálculo, estudio y PDF", async ({ page }) => {
  fs.rmSync(OUT, { recursive: true, force: true });
  fs.mkdirSync(OUT, { recursive: true });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const ctx = {};

  // 1. Login con un designer nuevo
  const user = createUser();
  await page.goto("/login");
  await page.getByLabel("Email address").fill(user.email);
  await page.getByLabel("Password").fill(user.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).not.toHaveURL(/login/);
  record("01-login", { email: user.email });

  // 2. Proyecto
  await page.goto("/projects");
  await page.getByRole("button", { name: "Nuevo proyecto" }).click();
  await page.getByLabel("Nombre del proyecto").fill("SE La Esperanza e2e");
  await page.getByLabel("Descripción").fill("Subestación 34,5/13,8 kV. Prueba e2e del agente con datos_prueba_agente.");
  await page.getByRole("button", { name: "Crear proyecto" }).last().click();
  await page.getByRole("button", { name: /SE La Esperanza e2e/ }).first().click();
  await expect(page).toHaveURL(/\/project\//);
  ctx.projectId = page.url().match(/project\/([^/?#]+)/)[1];
  await page.waitForTimeout(2000);
  await shot(page, "02-workspace");
  record("02-proyecto", { project_id: ctx.projectId });

  // 3. Carga de archivos por el chat
  await page.locator('input[type=file][accept*=".dxf"]').setInputFiles(UPLOADS.map((f) => path.join(DATA, f)));
  let files = [];
  for (let i = 0; i < 120; i += 1) {
    files = (await api(page, `/api/v1/projects/${ctx.projectId}/files`)).body;
    if (files.length >= UPLOADS.length && files.every((f) => !["pending", "uploading", "scanning", "quarantined", "processing"].includes(f.status))) break;
    await page.waitForTimeout(3000);
  }
  await openSection(page, "Fuentes");
  await shot(page, "03-fuentes");
  record("03-carga", { files: files.map((f) => ({ filename: f.filename, status: f.status, error: f.last_error })) });

  // 4–8. Conversación con el agente
  await say(page, ctx, "04-malla", "Diseña la malla del patio de la subestación según el plano de implantación: 40 × 30 m, retícula de 5 m en X y 6 m en Y, enterrada a 0,5 m, con varillas de 2,4 m en las cuatro esquinas y cada 10 m en el perímetro.");
  await say(page, ctx, "05-suelo", "Usa el sondeo SEV-2 del archivo 07_sondeo_wenner_SEV-2.csv para el modelo de suelo. La columna D es la resistencia medida R en ohmios.");
  await say(page, ctx, "06-calculo-sin-datos", "Calcula la seguridad de la malla.");
  await say(page, ctx, "07-datos-falla", "Según el estudio de cortocircuito EC-02: la falla monofásica a tierra en 34,5 kV es 8,5 kA, el tiempo de despeje es 0,5 s, X/R = 14 y S_f = 0,62. La capa superficial es gravilla de 3000 Ω·m y 0,15 m de espesor.");
  let replies = await say(page, ctx, "08-calculo", "Calcula la seguridad de la malla con esos datos.", { maxMinutes: 20 });
  const asked = (text) => /confirm|¿/i.test(text || "");
  if (replies.some((m) => m.source !== "user" && asked(m.text)) && !replies.some((m) => /GPR|tensión de contacto|cumple/i.test(m.text || ""))) {
    replies = await say(page, ctx, "08b-confirmacion", "Confirmo: gravilla de 3000 Ω·m y 0,15 m, 8,5 kA y 0,5 s. Lanza el cálculo.", { maxMinutes: 20 });
  }
  const verdict = replies.map((m) => m.text || "").join("\n");
  if (/no cumple/i.test(verdict)) {
    await say(page, ctx, "09-ajuste", "Aplica la recomendación del análisis para cumplir y recalcula.", { maxMinutes: 25 });
  }

  // 10. DXF y visualización del artefacto
  await openSection(page, "Plano");
  await shot(page, "10a-plano");
  await page.getByRole("button", { name: "Abrir drawer de dibujo" }).click();
  await page.waitForTimeout(2000);
  const dxfSelect = page.locator("label", { hasText: /^DXF/ }).locator("select");
  const option = await dxfSelect.locator("option", { hasText: "03_malla" }).getAttribute("value");
  await dxfSelect.selectOption(option);
  await page.getByRole("button", { name: "Importar propuesta DXF" }).click();
  const dxfMessage = page.locator(".ground-plan-message", { hasText: /DXF leído|No se pudo leer el DXF|Selecciona un DXF/ });
  await expect(dxfMessage).toBeVisible();
  await shot(page, "10b-importar-dxf");
  record("10-dxf", { message: await dxfMessage.innerText() });
  await page.getByRole("button", { name: "Cerrar drawer" }).click();
  for (const [label, file] of [["Resumen", "10c-resumen"], ["Suelo", "10d-suelo"], ["Parámetros", "10e-parametros"], ["Resultado", "10f-resultado"]]) {
    await openSection(page, label);
    await page.screenshot({ path: path.join(OUT, `${file}.png`), fullPage: true });
  }
  const artifacts = (await api(page, `/api/v1/projects/${ctx.projectId}/artefactos-diseno-tierras`)).body;
  const artifactList = Array.isArray(artifacts) ? artifacts : artifacts.items || [];
  record("10-artefacto", { artifacts: artifactList.map((a) => ({ id: a.artifact_id, version: a.version, name: a.name })) });

  // 11–12. Estudio publicado y PDF
  await page.getByRole("tab", { name: "Compartir estudio" }).click();
  await page.getByLabel("Título del estudio").fill("Estudio de puesta a tierra — SE La Esperanza");
  await page.getByRole("button", { name: "Crear borrador" }).click();
  await page.waitForTimeout(2500);
  await page.getByRole("button", { name: "Publicar estudio" }).click();
  await page.waitForTimeout(2500);
  await shot(page, "11-estudio");
  const studies = (await api(page, `/api/v1/projects/${ctx.projectId}/studies`)).body;
  const study = (Array.isArray(studies) ? studies : studies.items || [])[0];
  record("11-estudio", { study: study && { id: study.id, slug: study.slug, status: study.status, version: study.artifact_version } });

  await page.getByRole("button", { name: "Generar PDF" }).click();
  let pdf = null;
  for (let i = 0; i < 60; i += 1) {
    pdf = (await api(page, `/api/v1/projects/${ctx.projectId}/studies/${study.id}/pdf`)).body;
    if (["ready", "failed"].includes(pdf.pdf_status)) break;
    await page.waitForTimeout(3000);
  }
  record("12-pdf", { status: pdf?.pdf_status, error: pdf?.error });
  expect(pdf?.pdf_status).toBe("ready");
  if (pdf?.url) {
    const response = await page.request.get(pdf.url);
    fs.writeFileSync(path.join(OUT, "estudio_SE_La_Esperanza.pdf"), await response.body());
  }
  const publicPage = await page.context().newPage();
  await publicPage.goto(`/e/${study.slug}`);
  await publicPage.waitForTimeout(3000);
  await expect(publicPage.getByText("Pendiente de cálculo")).toHaveCount(0);
  await publicPage.screenshot({ path: path.join(OUT, "12-estudio-publico.png"), fullPage: true });
  await publicPage.emulateMedia({ media: "print" });
  await publicPage.pdf({ path: path.join(OUT, "estudio_publico_print.pdf"), format: "A4", printBackground: true }).catch(() => {});
  record("13-errores-frontend", { errors });
});
