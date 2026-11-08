import { expect } from "@playwright/test";
import path from "node:path";
import { AUTH_DIR } from "./global-setup.js";

export const PREFIX = "zz-smoke-";
export const runId = () => `${PREFIX}${new Date().toISOString().slice(0, 10).replace(/-/g, "")}-${Math.random().toString(36).slice(2, 8)}`;

/** Perfiles configurados por entorno: SMOKE_<ROL>_EMAIL / SMOKE_<ROL>_PASSWORD. */
export function creds(role) {
  const key = role.toUpperCase();
  const email = process.env[`SMOKE_${key}_EMAIL`];
  const password = process.env[`SMOKE_${key}_PASSWORD`];
  return email && password ? { email, password } : null;
}

/** Página ya autenticada reutilizando la sesión del setup (no consume intentos de login). */
export async function sessionPage(browser, role) {
  const context = await browser.newContext({ storageState: path.join(AUTH_DIR, `${role}.json`) });
  const page = await context.newPage();
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Proyectos", exact: true })).toBeVisible();
  return page;
}

/** Login real por el formulario: úsalo solo donde el login es lo que se prueba. */
export async function login(page, role) {
  const c = creds(role);
  if (!c) throw new Error(`Faltan credenciales del perfil ${role}`);
  await page.goto("/login");
  await page.getByLabel("Email address").fill(c.email);
  await page.getByLabel("Password").fill(c.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).not.toHaveURL(/login/);
  await expect(page.getByRole("button", { name: "Proyectos", exact: true })).toBeVisible();
}

export async function openProjects(page) {
  // Esperar la respuesta del listado: el botón aparece antes que los datos y se leería una tabla vacía.
  const loaded = page.waitForResponse((r) => /\/api\/v1\/projects(\?|$)/.test(r.url()) && r.request().method() === "GET" && r.ok());
  await page.goto("/projects");
  await loaded;
  // dos fotogramas para que React pinte la respuesta (networkidle se cuelga si la página hace polling)
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
  await expect(page.getByRole("heading", { name: "Proyectos" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Nuevo proyecto" })).toBeVisible();
}

export const row = (page, name) => page.locator("tr").filter({ has: page.locator("strong", { hasText: name }) });

/** Nombres de proyecto visibles para el usuario actual (UI). */
export async function projectNames(page) {
  await openProjects(page);
  return (await page.locator("tr td:first-child strong").allTextContents()).map((s) => s.trim()).sort();
}

export async function createProject(page, name, description = "Prueba automática, se borra sola.") {
  await page.getByRole("button", { name: "Nuevo proyecto" }).click();
  await page.getByLabel("Nombre del proyecto").fill(name);
  await page.getByLabel("Descripción").fill(description);
  await page.getByRole("button", { name: "Crear proyecto" }).last().click();
  await expect(row(page, name)).toBeVisible();
}

export async function deleteProject(page, name) {
  await row(page, name).getByRole("button", { name: "Borrar proyecto" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Borrar proyecto" }).click();
  await expect(row(page, name)).toHaveCount(0);
}

/** Borra por la UI todo proyecto con prefijo zz-smoke- que el usuario actual pueda ver. Devuelve cuántos. */
export async function sweepResidue(page) {
  await openProjects(page);
  let n = 0;
  for (;;) {
    const names = (await page.locator("tr td:first-child strong").allTextContents()).map((s) => s.trim());
    const left = names.find((s) => s.startsWith(PREFIX));
    if (!left) return n;
    await deleteProject(page, left);
    n++;
  }
}
