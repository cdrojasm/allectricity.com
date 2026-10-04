import { test, expect } from "@playwright/test";

test("refines geometry, restores versions and stages attachments", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page.screenshot({
    path: "test-results/initial-desktop.png",
    fullPage: true,
  });
  await expect(
    page.getByRole("heading", { name: "Design refinement" }),
  ).toBeVisible();
  await page
    .getByRole("spinbutton", { name: "Grid length", exact: true })
    .fill("60");
  await expect(page.locator(".mesh-legend")).toContainText("60 × 30 m");
  await page.getByRole("button", { name: "Save version" }).click();
  await page
    .getByRole("spinbutton", { name: "Grid length", exact: true })
    .fill("50");
  await page.getByRole("button", { name: "History", exact: true }).click();
  await page.getByRole("button", { name: /Design revision 2/ }).click();
  await expect(
    page.getByRole("spinbutton", { name: "Grid length", exact: true }),
  ).toHaveValue("60");
  await page
    .getByRole("button", { name: "Select ground rod 1", exact: true })
    .click();
  await expect(page.locator(".selection-context")).toContainText("R-01");
  await page.locator("input[type=file]").setInputFiles({
    name: "survey.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("distance,resistivity\n1,100"),
  });
  await expect(page.locator(".attachment-chips")).toContainText("survey.csv");
  await page
    .getByRole("textbox", { name: "Message the design assistant" })
    .fill("Review the attached survey");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(page.locator(".asset-list")).toContainText("survey.csv");
  await expect(page.locator(".chat-messages")).toContainText(
    "does not yet run AI",
  );
  await page.getByText("Soil parameters", { exact: true }).click();
  await expect(
    page.getByRole("spinbutton", { name: "Soil resistivity" }),
  ).toBeHidden();
  await page.screenshot({ path: "test-results/desktop.png", fullPage: true });
  expect(errors).toEqual([]);
});

test("mobile layout fits the viewport and export downloads a design", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
  await expect(
    page.getByRole("heading", { name: "Project assets" }),
  ).toBeVisible();
  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export design" }).click();
  expect((await downloadEvent).suggestedFilename()).toBe(
    "north-substation.json",
  );
  await page.screenshot({ path: "test-results/mobile.png", fullPage: true });
});
