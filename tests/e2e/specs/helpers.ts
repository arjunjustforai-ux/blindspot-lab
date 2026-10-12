import { expect, type Page } from "@playwright/test";
import * as path from "node:path";

export const REPO_ROOT = path.resolve(__dirname, "..", "..", "..");
export const SHOTS = path.join(REPO_ROOT, "docs", "screenshots");

export async function shot(page: Page, name: string, fullPage = false) {
  await page.waitForTimeout(400); // let charts finish their entry animation
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage });
}

/** Start as a fresh synthetic demo learner and return the demo course id. */
export async function startDemo(page: Page): Promise<string> {
  await page.goto("/");
  await page.getByTestId("start-demo").click();
  await page.waitForURL("**/app");
  const link = page.locator('a[href*="/app/courses/"]').first();
  await expect(link).toBeVisible();
  const href = (await link.getAttribute("href"))!;
  return href.split("/")[3];
}

/** Answer whatever question form is on screen with a plausible (not necessarily correct) response. */
export async function answerVisibleQuestion(page: Page) {
  const scope = page.locator("form").filter({ has: page.getByRole("button", { name: /submit answer/i }) }).last();
  await expect(scope).toBeVisible();
  const radios = scope.locator('input[type="radio"]');
  if (await radios.count()) {
    await radios.first().check();
  } else if (await scope.getByLabel("Your numerical answer").count()) {
    await scope.getByLabel("Your numerical answer").fill("10");
  } else {
    await scope.getByLabel("Your answer").fill("Contribution per unit is price minus variable cost per unit.");
  }
  await scope.getByRole("button", { name: /submit answer/i }).click();
}
