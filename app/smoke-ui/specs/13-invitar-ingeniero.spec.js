// Alta de un ingeniero piloto por super_admin: invitar → correo (Mailpit local) → elegir contraseña → entrar como
// diseñador con bolsa de tokens y crear un proyecto. La cuenta se desactiva y el proyecto se borra al terminar.
import { test, expect } from "@playwright/test";
import { creds, sessionPage, runId } from "../helpers.js";

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

test("super_admin invita a un ingeniero que entra como diseñador con bolsa de tokens", async ({ browser, request }) => {
  test.skip(!LOCAL, "Usa Mailpit y crea una cuenta: solo local.");
  test.skip(!creds("super_admin"), "Falta el perfil super_admin; créalo con make smoke-ui-seed.");
  test.setTimeout(120_000);
  const admin = await sessionPage(browser, "super_admin");
  const email = `zz-smoke-piloto-${Date.now()}@example.com`;
  const password = `Piloto-${Math.random().toString(36).slice(2)}-Cc3`;
  let userId; let projectId; let engineerPage;
  try {
    await admin.getByRole("button", { name: "Usuarios" }).click();
    await expect(admin).toHaveURL(/\/users$/);
    await admin.getByRole("button", { name: "Invitar ingeniero" }).click();
    const modal = admin.getByRole("form", { name: "Invitar ingeniero" });
    await modal.getByLabel("Correo electrónico").fill(email);
    await modal.getByLabel("Nombre").fill("Ingeniera");
    await modal.getByLabel("Tokens para el agente").fill("500000");
    await modal.getByRole("button", { name: "Enviar invitación" }).click();
    await expect(admin.getByRole("status")).toContainText(`Invitación enviada a ${email}`);
    const row = admin.getByTestId("users-table").getByRole("row", { name: new RegExp(email) });
    await expect(row).toContainText("Diseñador");
    await expect(row).toContainText("0 de 500.000");
    userId = (await api(admin, "/api/v1/users?limit=100")).body.find((user) => user.email === email)?.id;

    let link = null;
    await expect.poll(async () => {
      const found = await request.get(`/mailpit/api/v1/search?query=${encodeURIComponent(`to:${email}`)}`);
      const messages = (await found.json()).messages || [];
      if (!messages.length) return false;
      const message = await (await request.get(`/mailpit/api/v1/message/${messages[0].ID}`)).json();
      link = `${message.Text || ""} ${message.HTML || ""}`.match(/https?:\/\/[^\s"'<>]+\/reset-password#token=[^\s"'<>]+/)?.[0] || null;
      return Boolean(link);
    }, { timeout: 60_000, intervals: [1000, 2000, 3000] }).toBe(true);

    const context = await browser.newContext();
    engineerPage = await context.newPage();
    const target = new URL(link.replace(/&amp;/g, "&"));
    await engineerPage.goto(`${target.pathname}${target.hash}`);
    await engineerPage.getByLabel("Contraseña nueva").fill(password);
    await engineerPage.getByLabel("Confirmar contraseña").fill(password);
    await engineerPage.getByRole("button", { name: "Cambiar contraseña" }).click();
    await expect(engineerPage.getByRole("status")).toContainText("Tu contraseña se cambió");
    await engineerPage.goto("/login");
    await engineerPage.getByLabel("Correo electrónico").fill(email);
    await engineerPage.getByLabel("Contraseña").fill(password);
    await engineerPage.getByRole("button", { name: "Iniciar sesión" }).click();
    await expect(engineerPage.getByRole("button", { name: "Proyectos", exact: true })).toBeVisible();
    await expect(engineerPage.getByRole("button", { name: "Usuarios" })).toHaveCount(0); // solo super_admin

    const me = await api(engineerPage, "/api/v1/auth/me");
    expect(me.body.roles).toContain("designer");
    const project = await api(engineerPage, "/api/v1/projects", { method: "POST", body: JSON.stringify({ name: runId() }) });
    expect(project.status, JSON.stringify(project.body)).toBe(201); // puede diseñar, no solo leer
    projectId = project.body.id;
    const budgets = await api(engineerPage, "/api/v1/budgets");
    expect(budgets.body.map((budget) => budget.total_tokens)).toEqual([500000]);
  } finally {
    if (projectId && engineerPage) await api(engineerPage, `/api/v1/projects/${projectId}`, { method: "DELETE" });
    if (engineerPage) await engineerPage.context().close();
    if (userId) await api(admin, `/api/v1/users/${userId}`, { method: "DELETE" });
    await admin.context().close();
  }
});
