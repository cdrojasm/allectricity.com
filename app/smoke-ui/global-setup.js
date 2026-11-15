// Guardas de seguridad + UN login por perfil (la API limita 10 intentos por cuenta cada 5 min).
import { chromium } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

export const AUTH_DIR = path.resolve(import.meta.dirname, "../test-results/smoke-ui/.auth");
export const ALL_ROLES = ["designer", "viewer", "user_admin", "super_admin"];

export default async function globalSetup() {
  const base = process.env.SMOKE_BASE_URL;
  if (!base) throw new Error("Falta SMOKE_BASE_URL (ej. http://127.0.0.1:3001).");
  const local = /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:|\/|$)/.test(base);
  if (!local && process.env.SMOKE_CONFIRM_REMOTE !== "yes") {
    throw new Error(`${base} no es local. Para correr contra un entorno remoto exporta SMOKE_CONFIRM_REMOTE=yes ` +
      "(la suite crea y borra proyectos 'zz-smoke-*' con los usuarios configurados).");
  }
  const roles = ALL_ROLES.filter((r) => process.env[`SMOKE_${r.toUpperCase()}_EMAIL`]);
  if (!roles.length) throw new Error("No hay credenciales: define SMOKE_<ROL>_EMAIL y SMOKE_<ROL>_PASSWORD.");
  console.log(`\nsmoke-ui -> ${base} | perfiles: ${roles.join(", ")}\n`);

  fs.rmSync(AUTH_DIR, { recursive: true, force: true });
  fs.mkdirSync(AUTH_DIR, { recursive: true });
  const browser = await chromium.launch();
  try {
    for (const role of roles) {
      const key = role.toUpperCase();
      const page = await (await browser.newContext({ baseURL: base })).newPage();
      await page.goto("/login");
      await page.getByLabel("Correo electrónico").fill(process.env[`SMOKE_${key}_EMAIL`]);
      await page.getByLabel("Contraseña").fill(process.env[`SMOKE_${key}_PASSWORD`]);
      await page.getByRole("button", { name: "Iniciar sesión" }).click();
      try {
        await page.waitForURL((u) => !/login/.test(u.pathname), { timeout: 20_000 });
      } catch {
        const why = await page.getByRole("alert").first().textContent().catch(() => "sin mensaje");
        throw new Error(`Login falló para el perfil ${role}: ${why}`);
      }
      await page.context().storageState({ path: path.join(AUTH_DIR, `${role}.json`) });
      await page.context().close();
    }
  } finally {
    await browser.close();
  }
}
