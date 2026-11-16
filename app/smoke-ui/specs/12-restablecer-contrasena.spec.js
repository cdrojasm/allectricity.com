// Restablecer contraseña de punta a punta: «¿Olvidaste tu contraseña?» → correo (Mailpit local) → página
// /reset-password con el #token → login con la contraseña nueva. Usa una cuenta temporal creada por user_admin
// y la desactiva al terminar; nunca toca las contraseñas de los perfiles sembrados. Solo local.
import { test, expect } from "@playwright/test";
import { creds, sessionPage } from "../helpers.js";

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

test("restablecer contraseña desde el login con el enlace del correo", async ({ browser, request }) => {
  test.skip(!LOCAL, "Usa Mailpit y crea una cuenta temporal: solo local.");
  test.skip(!creds("user_admin"), "Falta el perfil user_admin; créalo con make smoke-ui-seed.");
  test.setTimeout(120_000);
  const admin = await sessionPage(browser, "user_admin");
  const email = `zz-smoke-reset-${Date.now()}@example.com`;
  const initial = `Inicial-${Math.random().toString(36).slice(2)}-Aa1`;
  const renewed = `Nueva-${Math.random().toString(36).slice(2)}-Bb2`;
  const created = await api(admin, "/api/v1/users", { method: "POST", body: JSON.stringify({ email, password: initial, first_name: "Smoke", last_name: "Reset" }) });
  expect(created.status, JSON.stringify(created.body)).toBe(201);
  const visitor = await browser.newContext();
  const page = await visitor.newPage();
  try {
    await page.goto("/login");
    await page.getByRole("button", { name: "¿Olvidaste tu contraseña?" }).click();
    const form = page.getByTestId("forgot-password-form");
    await form.getByLabel("Correo electrónico").fill(email);
    await form.getByRole("button", { name: "Enviar enlace" }).click();
    await expect(form.getByRole("status")).toContainText("recibirás un enlace");

    // El worker de correo entrega en Mailpit; el enlace trae el token en el fragmento (#token=…).
    let link = null;
    await expect.poll(async () => {
      const found = await request.get(`/mailpit/api/v1/search?query=${encodeURIComponent(`to:${email}`)}`);
      const messages = (await found.json()).messages || [];
      if (!messages.length) return false;
      const message = await (await request.get(`/mailpit/api/v1/message/${messages[0].ID}`)).json();
      link = `${message.Text || ""} ${message.HTML || ""}`.match(/https?:\/\/[^\s"'<>]+\/reset-password#token=[^\s"'<>]+/)?.[0] || null;
      return Boolean(link);
    }, { timeout: 60_000, intervals: [1000, 2000, 3000] }).toBe(true);
    const target = new URL(link.replace(/&amp;/g, "&"));
    await page.goto(`${target.pathname}${target.hash}`);

    const reset = page.getByTestId("reset-password-form");
    await reset.getByLabel("Contraseña nueva").fill(renewed);
    await reset.getByLabel("Confirmar contraseña").fill(`${renewed}x`);
    await reset.getByRole("button", { name: "Cambiar contraseña" }).click();
    await expect(reset.getByRole("alert")).toContainText("no coinciden");
    await reset.getByLabel("Confirmar contraseña").fill(renewed);
    await reset.getByRole("button", { name: "Cambiar contraseña" }).click();
    await expect(reset.getByRole("status")).toContainText("Tu contraseña se cambió");
    await expect(page).not.toHaveURL(/#token=/); // el token no queda en la barra de direcciones

    // El mismo enlace ya no sirve (pestaña nueva: cambiar solo el fragmento no recarga la página).
    const again = await visitor.newPage();
    await again.goto(`${target.pathname}${target.hash}`);
    const reused = again.getByTestId("reset-password-form");
    await reused.getByLabel("Contraseña nueva").fill(`${renewed}-otra`);
    await reused.getByLabel("Confirmar contraseña").fill(`${renewed}-otra`);
    await reused.getByRole("button", { name: "Cambiar contraseña" }).click();
    await expect(reused.getByRole("alert")).toContainText("no es válido o ya venció");

    // Entra con la contraseña nueva; la anterior ya no sirve.
    const login = await request.post("/api/v1/auth/login", { data: { email, password: initial } });
    expect(login.status()).toBe(401);
    await page.goto("/login");
    await page.getByLabel("Correo electrónico").fill(email);
    await page.getByLabel("Contraseña").fill(renewed);
    await page.getByRole("button", { name: "Iniciar sesión" }).click();
    await expect(page.getByRole("button", { name: "Proyectos", exact: true })).toBeVisible();
  } finally {
    await visitor.close();
    if (created.body?.id) await api(admin, `/api/v1/users/${created.body.id}`, { method: "DELETE" });
    await admin.context().close();
  }
});
