// Un usuario no ve los proyectos de otro. Crea un proyecto con el perfil A y comprueba que B no lo ve.
import { test, expect } from "@playwright/test";
import { creds, sessionPage, projectNames, createProject, deleteProject, runId, sweepResidue } from "../helpers.js";

const A = "designer", B = process.env.SMOKE_ISOLATION_OTHER || "viewer";

test(`proyectos de ${A} no son visibles para ${B}`, async ({ browser }) => {
  test.skip(!creds(A) || !creds(B), "faltan credenciales de dos perfiles");
  const name = runId();
  let created = false;
  const pa = await sessionPage(browser, A), pb = await sessionPage(browser, B);
  try {
    await projectNames(pa);
    await createProject(pa, name);
    created = true;
    expect(await projectNames(pb)).not.toContain(name);
    await deleteProject(pa, name);
    created = false;
  } finally {
    if (created) await sweepResidue(pa);
    await pa.context().close();
    await pb.context().close();
  }
});
