// Seguro en producción: no crea ni modifica nada.
import { test, expect } from "@playwright/test";
import { creds, login, sessionPage } from "../helpers.js";

const ROLES = ["designer", "viewer", "user_admin", "super_admin"].filter((r) => creds(r));

test("sin sesión, las rutas privadas redirigen al login", async ({ page }) => {
  await page.goto("/projects");
  await expect(page).toHaveURL(/login/);
  await expect(page.getByLabel("Email address")).toBeVisible();
});

test("credenciales inválidas no entran", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email address").fill("no-existe@example.com");
  await page.getByLabel("Password").fill("incorrecta-" + Date.now());
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/login/);
});

for (const role of ROLES) {
  test(`perfil ${role}: dashboard, proyectos y catálogo`, async ({ browser }) => {
    const page = await sessionPage(browser, role);
    await page.goto("/");
    await expect(page.getByRole("heading", { name: /^Hola,/ })).toBeVisible();
    const health = page.getByRole("region", { name: "Estado del sistema" });
    await expect(health).toBeVisible();
    await expect(health).toContainText("Todo operativo", { timeout: 40_000 });

    await page.goto("/projects");
    await expect(page.getByRole("heading", { name: "Proyectos" })).toBeVisible();

    await page.goto("/catalog");
    await expect(page.getByRole("heading", { name: "Catálogo de materiales" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Buscar proveedores" })).toBeVisible();
    await page.context().close();
  });
}

// Único login por formulario durante la corrida (además del setup): se prueba entrar y salir de verdad.
const LOGOUT_ROLE = ROLES[0];
test(`login y cierre de sesión reales (${LOGOUT_ROLE})`, async ({ page }) => {
  test.skip(!LOGOUT_ROLE, "sin perfiles");
  await login(page, LOGOUT_ROLE);
  await page.getByTitle(/Sign out/).click();
  await expect(page).toHaveURL(/login/);
  await page.goto("/projects");
  await expect(page).toHaveURL(/login/); // la sesión quedó cerrada de verdad
});
