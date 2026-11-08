// Crea, edita y borra un proyecto "zz-smoke-*" por la UI y comprueba que el listado queda como estaba.
import { test, expect } from "@playwright/test";
import { creds, sessionPage, projectNames, createProject, deleteProject, row, runId, sweepResidue, openProjects } from "../helpers.js";

const ROLES = (process.env.SMOKE_LIFECYCLE_ROLES || "designer").split(",").map((s) => s.trim()).filter((r) => creds(r));

for (const role of ROLES) {
  test(`ciclo completo de proyecto como ${role}`, async ({ browser }) => {
    const page = await sessionPage(browser, role);
    const before = await projectNames(page);
    expect(before.filter((n) => n.startsWith("zz-smoke-")), "hay residuos de corridas anteriores: corre 'make smoke-ui-sweep'").toEqual([]);

    const name = runId();
    let created = false;
    try {
      await createProject(page, name);
      created = true;
      await expect(page.getByText("Proyecto creado.")).toBeVisible();

      // Editar
      await row(page, name).getByRole("button", { name: "Editar proyecto" }).click();
      await page.getByLabel("Descripción").fill("editado por la prueba");
      await page.getByRole("button", { name: "Guardar cambios" }).click();
      await expect(page.getByText("Proyecto actualizado.")).toBeVisible();
      await expect(row(page, name)).toContainText("editado por la prueba");

      // Persistencia real: recargar y seguir viéndolo
      await page.reload();
      await expect(row(page, name)).toBeVisible();

      // Abrir el espacio del proyecto
      await row(page, name).getByRole("button", { name: "Abrir espacio del proyecto" }).click();
      await expect(page).not.toHaveURL(/\/projects$/);
      await openProjects(page);

      // Borrar con confirmación (y que cancelar no borre)
      await row(page, name).getByRole("button", { name: "Borrar proyecto" }).click();
      await page.getByRole("alertdialog").getByRole("button", { name: "Cancelar" }).click();
      await expect(row(page, name)).toBeVisible();
      await deleteProject(page, name);
      await expect(page.getByText("Proyecto eliminado.")).toBeVisible();
      created = false;
    } finally {
      if (created) await sweepResidue(page); // limpieza aunque la prueba falle a medias
    }

    expect(await projectNames(page), "el listado final debe ser idéntico al inicial").toEqual(before);
  });
}
