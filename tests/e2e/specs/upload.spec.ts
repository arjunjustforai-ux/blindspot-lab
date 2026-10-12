import { expect, test } from "@playwright/test";
import * as path from "node:path";
import { REPO_ROOT, shot } from "./helpers";

// An instructor registers, creates a course, uploads a PDF and watches it move through ingestion.
test("instructor uploads a PDF and it becomes ready", async ({ page }) => {
  const email = `e2e-${Date.now()}@example.com`;
  await page.goto("/login?mode=register");
  await page.getByLabel("Name").fill("E2E Instructor");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("correct-horse-battery");
  await page.getByRole("button", { name: "Create account" }).click();
  await page.waitForURL("**/app");

  await page.getByRole("button", { name: "New course" }).first().click();
  await page.getByLabel("Title").fill("E2E Upload Course");
  await page.getByRole("button", { name: "Create course" }).click();
  await page.waitForURL(/\/studio$/);

  await page.getByTestId("file-input").setInputFiles(path.join(REPO_ROOT, "demo", "course-materials", "Marketing_Analytics_Primer.pdf"));
  const row = page.getByTestId("source-row").filter({ hasText: "Marketing_Analytics_Primer.pdf" });
  await expect(row).toBeVisible();
  await shot(page, "17-upload-processing");
  await expect(row.getByLabel("Status: ready")).toBeVisible({ timeout: 200_000 });
  await expect(row.getByText(/pdf text/)).toBeVisible();

  // Invalid files are rejected with a clear message.
  await page.getByTestId("file-input").setInputFiles({ name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("hello") });
  await expect(page.getByText("notes.txt: unsupported type", { exact: false })).toBeVisible();
});
