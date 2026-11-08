// @sweep  Borra por la UI los proyectos 'zz-smoke-*' que hayan quedado de corridas interrumpidas.
import { test } from "@playwright/test";
import { creds, sessionPage, sweepResidue } from "../helpers.js";

for (const role of ["designer", "viewer", "user_admin", "super_admin"].filter((r) => creds(r))) {
  test(`@sweep limpiar residuos de ${role}`, async ({ browser }) => {
    const page = await sessionPage(browser, role);
    console.log(`  ${role}: ${await sweepResidue(page)} residuo(s) borrados`);
  });
}
