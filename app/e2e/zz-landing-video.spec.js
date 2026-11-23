// TEMPORAL: graba el flujo real (agente y motor de cálculo locales) para la demo de la landing. Se borra al terminar.
// Crea un usuario designer local y un proyecto zz-smoke que se renombra para la toma y se borra después.
import { test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(import.meta.dirname, "../..");
const DATA = path.join(ROOT, "docs/datos_prueba_agente");
const OUT = path.join(import.meta.dirname, "../test-results/landing-video");
const COMPOSE = ["compose", "--env-file", path.join(ROOT, ".env"), "-f", path.join(ROOT, "deploy/local/docker/docker-compose.yml")];
const SIZE = { width: 1440, height: 900 };
const UPLOADS = ["01_plano_implantacion_SE_La_Esperanza.pdf", "05_estudio_cortocircuito_SE_La_Esperanza.pdf",
  "06_informe_resistividad_SEV-2.docx", "07_sondeo_wenner_SEV-2.csv", "08_sondeo_schlumberger_SEV-3_ampliacion.xlsx",
  "03_malla_puesta_tierra_SE_La_Esperanza.dxf", "04_plano_general_multicapa_SE_La_Esperanza.dxf"];
const ACTIVE = new Set(["queued", "running", "waiting_calculation", "cancelling"]);

test.use({ viewport: SIZE, video: { mode: "on", size: SIZE }, actionTimeout: 30_000 });

const t0 = Date.now();
const log = { segments: [], steps: [] };
const now = () => (Date.now() - t0) / 1000;
const save = () => fs.writeFileSync(path.join(OUT, "timeline.json"), JSON.stringify(log, null, 2));

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
    u = new_user(db, email=os.environ["E2E_EMAIL"], first_name="Laura", last_name="Gómez",
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
    const response = await fetch(url, { ...options, headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" } });
    const text = await response.text();
    try { return { status: response.status, body: JSON.parse(text) }; } catch { return { status: response.status, body: text }; }
  }, { url, options });
}

async function conversationId(page, projectId) {
  const { body } = await api(page, `/api/v1/projects/${projectId}/conversations`);
  const items = Array.isArray(body) ? body : body.items || body.conversations || [];
  return items[0]?.id;
}

async function messages(page, cid) {
  const { body } = await api(page, `/api/v1/conversations/${cid}/messages/first?limit=100`);
  return Array.isArray(body) ? body : [];
}

async function tab(page, label, hold = 3500) {
  await page.getByRole("tablist", { name: "Secciones del artefacto" }).getByRole("tab", { name: label }).click();
  await page.waitForTimeout(hold);
}

async function chatBottom(page) {
  await page.evaluate(() => { const box = document.querySelector(".project-chat-messages"); if (box) box.scrollTo({ top: box.scrollHeight, behavior: "smooth" }); });
  await page.waitForTimeout(800);
}

// Escribe en el composer como una persona y espera a que Aleia termine; la espera se marca para acelerarla en el montaje.
async function say(page, ctx, name, text, { maxMinutes = 20 } = {}) {
  ctx.cid ||= await conversationId(page, ctx.projectId);
  const before = ctx.cid ? (await messages(page, ctx.cid)).map((m) => m.id) : [];
  const box = page.getByRole("textbox", { name: "Mensaje para el chat del proyecto" });
  await box.click();
  await box.pressSequentially(text, { delay: 14 });
  await page.waitForTimeout(500);
  await box.press("Enter");
  const start = now();
  let run = null, fresh = [];
  await page.waitForTimeout(3000);
  while ((now() - start) < maxMinutes * 60) {
    ctx.cid ||= await conversationId(page, ctx.projectId);
    run = (await api(page, `/api/v1/conversations/${ctx.cid}/agent-events?limit=50`)).body.active_run;
    fresh = (await messages(page, ctx.cid)).filter((m) => !before.includes(m.id));
    if (fresh.some((m) => m.source === "agent") && (!run || !ACTIVE.has(run.status))) break;
    await page.waitForTimeout(2500);
  }
  await page.waitForTimeout(1500);
  log.segments.push({ kind: "wait", name, start: start + 1, end: now() });
  await chatBottom(page);
  await page.waitForTimeout(4500);  // tiempo para leer la respuesta
  const replies = fresh.filter((m) => m.source !== "user").map((m) => ({ source: m.source, text: m.text }));
  log.steps.push({ name, user: text, at: start, run_status: run?.status || "idle", replies });
  save();
  return replies.map((m) => m.text || "").join("\n");
}

test("video real para la landing", async ({ page }) => {
  test.setTimeout(80 * 60 * 1000);
  fs.mkdirSync(OUT, { recursive: true });
  const ctx = {};
  const user = createUser();
  await page.goto("/login");
  await page.getByLabel("Correo electrónico").fill(user.email);
  await page.getByLabel("Contraseña").fill(user.password);
  await page.getByRole("button", { name: "Iniciar sesión" }).click();
  await page.waitForURL((u) => !/login/.test(u.pathname));
  log.segments.push({ kind: "cut", name: "login", start: 0, end: now() });

  // Proyecto con el prefijo de pruebas, renombrado para la toma.
  const created = await api(page, "/api/v1/projects", { method: "POST", body: JSON.stringify({ name: "zz-smoke-20261120-video", description: "Subestación 34,5/13,8 kV · patio de 40 × 30 m." }) });
  ctx.projectId = created.body.id;
  log.project_id = ctx.projectId;
  save();
  const { id, owner_id, created_at, updated_at, ...rest } = created.body;
  await api(page, `/api/v1/projects/${id}`, { method: "PATCH", body: JSON.stringify({ ...rest, name: "SE La Esperanza" }) });
  await page.goto(`/project/${ctx.projectId}`);
  await page.waitForTimeout(3000);
  log.segments.push({ kind: "cut", name: "proyecto", start: log.segments.at(-1).end, end: now() - 2.5 });

  // 1. Nos das tus documentos
  log.steps.push({ name: "documentos", at: now() });
  await page.locator('input[type=file][accept*=".dxf"]').setInputFiles(UPLOADS.map((f) => path.join(DATA, f)));
  const uploadStart = now();
  await page.waitForTimeout(3000);
  for (let i = 0; i < 160; i += 1) {
    const files = (await api(page, `/api/v1/projects/${ctx.projectId}/files`)).body;
    if (files.length >= UPLOADS.length && files.every((f) => !["pending", "uploading", "scanning", "quarantined", "processing"].includes(f.status))) break;
    await page.waitForTimeout(3000);
  }
  log.segments.push({ kind: "wait", name: "lectura-documentos", start: uploadStart + 3, end: now() });
  await chatBottom(page);
  await page.waitForTimeout(3000);
  await tab(page, "Fuentes", 4000);

  // 2. Los entendemos: lo extraído
  const extracted = page.getByRole("button", { name: "Ver lo extraído" });
  if (await extracted.isVisible().catch(() => false)) {
    log.steps.push({ name: "grafo", at: now() });
    await extracted.click();
    await page.waitForTimeout(7000);
    await page.goto(`/project/${ctx.projectId}`);
    await page.waitForTimeout(3000);
  }

  // 3. Te sugerimos una malla
  await say(page, ctx, "malla", "Diseña la malla del patio según el plano de implantación: 40 × 30 m, retícula de 5 m en X y 6 m en Y, enterrada a 0,5 m, con varillas de 2,4 m en las cuatro esquinas y cada 10 m en el perímetro.");
  await tab(page, "Plano", 5000);

  // 4. Entendemos el terreno
  await say(page, ctx, "suelo", "Usa el sondeo Wenner SEV-2 (07_sondeo_wenner_SEV-2.csv) para el modelo de suelo. La columna D es la resistencia medida R en ohmios.");
  await tab(page, "Suelo", 5000);

  // 5. Revisamos que sea segura
  let reply = await say(page, ctx, "calcular", "Calcula la seguridad de la malla.");
  if (!/GPR|tensión de contacto/i.test(reply)) {
    reply = await say(page, ctx, "datos-falla", "Sí: usa la falla monofásica de 8,5 kA y el despeje de 0,5 s del estudio de cortocircuito, con X/R = 14 y S_f = 0,62. La capa superficial es gravilla de 3000 Ω·m y 0,15 m. Calcula la seguridad.", { maxMinutes: 25 });
  }
  if (!/GPR|tensión de contacto/i.test(reply) && /confirm|¿/i.test(reply)) {
    reply = await say(page, ctx, "confirmar", "Confirmo esos valores. Lanza el cálculo.", { maxMinutes: 25 });
  }
  if (/GPR|tensión de contacto/i.test(reply)) await tab(page, "Resultado", 6000);
  for (let round = 1; round <= 2 && /no cumple/i.test(reply); round += 1) {
    reply = await say(page, ctx, `ajuste-${round}`, round === 1
      ? "Aplica la recomendación del análisis para que cumpla y recalcula."
      : "Sigue: aplica la siguiente recomendación y recalcula.", { maxMinutes: 30 });
    await tab(page, "Plano", 4000);
    await tab(page, "Resultado", 6000);
  }
  const potential = page.getByText("Potencial superficial", { exact: true }).first();
  if (await potential.isVisible().catch(() => false)) {
    await potential.scrollIntoViewIfNeeded().catch(() => {});
    await page.waitForTimeout(5000);
  }
  log.verdict = /no cumple/i.test(reply) ? "no_cumple" : /cumple/i.test(reply) ? "cumple" : "sin_resultado";
  save();

  // 6. Te entregamos el estudio
  log.steps.push({ name: "estudio", at: now() });
  save();
  try {
  await page.evaluate(() => window.scrollTo({ top: 0 }));
  await page.getByRole("tab", { name: "Compartir estudio" }).click();
  await page.waitForTimeout(1500);
  const title = page.getByLabel("Título del estudio");
  await title.click();
  await title.fill("");
  await title.pressSequentially("Estudio de puesta a tierra — SE La Esperanza", { delay: 20 });
  await page.getByRole("button", { name: "Crear borrador" }).click();
  await page.waitForTimeout(3500);
  await page.getByRole("button", { name: "Publicar estudio" }).click();
  await page.waitForTimeout(1500);
  const anyway = page.getByRole("button", { name: "Publicar de todos modos" });
  if (await anyway.isVisible().catch(() => false)) { await page.waitForTimeout(2000); await anyway.click(); }
  await page.waitForTimeout(3500);
  const studies = (await api(page, `/api/v1/projects/${ctx.projectId}/studies`)).body;
  const study = (Array.isArray(studies) ? studies : studies.items || [])[0];
  log.study_slug = study?.slug;
  save();
  if (study?.slug) {
    await page.goto(`/e/${study.slug}`);
    await page.waitForTimeout(4000);
    for (let i = 0; i < 6; i += 1) {
      await page.mouse.wheel(0, 650);
      await page.waitForTimeout(1600);
    }
    await page.waitForTimeout(2000);
  }
  } catch (error) {
    log.study_error = String(error).slice(0, 500);
    await page.screenshot({ path: path.join(OUT, "study-error.png") }).catch(() => {});
  }
  log.end = now();
  save();
  await page.goto("/projects");
  log.deleted = (await api(page, `/api/v1/projects/${ctx.projectId}`, { method: "DELETE" })).status;
  save();
});
