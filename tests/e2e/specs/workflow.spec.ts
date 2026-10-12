import { expect, test, type Page } from "@playwright/test";
import { answerVisibleQuestion, shot, startDemo } from "./helpers";

// One continuous learner journey through the demo course, mirroring the demo video.
test.describe.serial("Blindspot Lab learner workflow", () => {
  let page: Page;
  let courseId: string;

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
  });
  test.afterAll(async () => page.close());

  test("1. landing page and demo access", async () => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("You don't know what you don't know");
    await shot(page, "01-landing");
    courseId = await startDemo(page);
    await expect(page.getByText("synthetic demo learner", { exact: true })).toBeVisible();
    await expect(page.getByText("Take the diagnostic check-in")).toBeVisible();
    await shot(page, "02-dashboard");
  });

  test("2. course studio shows processed multimodal sources", async () => {
    await page.goto(`/app/courses/${courseId}/studio`);
    const rows = page.getByTestId("source-row");
    await expect(rows).toHaveCount(3);
    for (const name of ["Marketing_Analytics_Primer.pdf", "Unit_Economics_for_Marketers.pptx", "Lecture_03_Price_Cuts.mp4"]) {
      await expect(rows.filter({ hasText: name }).getByLabel("Status: ready")).toBeVisible();
    }
    await shot(page, "03-course-studio");
  });

  test("3. knowledge explorer graph and concept detail", async () => {
    await page.goto(`/app/courses/${courseId}/knowledge`);
    await expect(page.getByTestId("concept-graph")).toBeVisible();
    await page.locator(".react-flow__node").filter({ hasText: "Contribution margin" }).first().click();
    const drawer = page.getByTestId("concept-drawer");
    await expect(drawer).toBeVisible();
    await expect(drawer.getByTestId("citation-chip").first()).toBeVisible();
    await shot(page, "04-knowledge-explorer");
  });

  test("4. grounded tutor answers with citations and opens the cited source", async () => {
    await page.goto(`/app/courses/${courseId}/tutor`);
    await page.getByTestId("new-conversation").first().click();
    await page.getByTestId("tutor-input").fill("Why can a price cut need more extra volume than people expect?");
    await page.getByTestId("tutor-send").click();
    const answer = page.getByTestId("assistant-message").first();
    await expect(answer.getByTestId("citation-chip").first()).toBeVisible({ timeout: 60_000 });
    await expect(answer.getByTestId("refusal-badge")).toHaveCount(0);
    await shot(page, "05-tutor-grounded");

    await page.getByTestId("tutor-input").fill("How do I set up conversion tracking in Google Analytics 4?");
    await page.getByTestId("tutor-send").click();
    await expect(page.getByTestId("assistant-message")).toHaveCount(2, { timeout: 60_000 });
    await expect(page.getByTestId("assistant-message").last().getByTestId("refusal-badge")).toBeVisible();
    await shot(page, "06-tutor-refusal");

    // Open the first citation of the grounded answer in the source viewer.
    await answer.getByTestId("citation-chip").first().click();
    await page.waitForURL(/\/sources\//);
    await expect(page.getByTestId("cited-unit")).toBeVisible();
    await expect(page.locator('[data-testid="pdf-viewer"], [data-testid="slide-viewer"], [data-testid="video-player"]').first()).toBeVisible();
    await shot(page, "07-source-viewer");
  });

  test("5. Blindspot Lab: diagnose, probe, repair, transfer", async () => {
    await page.goto(`/app/courses/${courseId}/lab`);
    await page.getByTestId("start-scenario").click();
    await page.getByTestId("fill-scripted").click();
    await page.getByRole("button", { name: /submit answer/i }).click();

    // The scripted 25% answer opens competing hypotheses and a discriminating probe.
    await expect(page.getByTestId("hypothesis-status").first()).toBeVisible();
    await expect(page.getByTestId("fill-scripted-probe")).toBeVisible();
    await shot(page, "08-lab-hypotheses");
    for (let i = 0; i < 3 && (await page.getByTestId("fill-scripted-probe").isVisible()); i++) {
      await page.getByTestId("fill-scripted-probe").click();
      await page.getByTestId("submit-probe").click();
      await expect(page.getByTestId("submit-probe")).toBeHidden({ timeout: 30_000 }).catch(() => undefined);
    }
    await expect(page.getByTestId("conclusion")).toBeVisible();
    await expect(page.getByTestId("repair-card")).toBeVisible();
    await expect(page.getByTestId("repair-card").getByTestId("citation-chip").first()).toBeVisible();
    await page.getByTestId("repair-card").scrollIntoViewIfNeeded();
    await shot(page, "09-lab-repair");

    await page.getByTestId("continue-repair").click();
    // Practice, then transfer (the scripted learner answers both correctly after the repair).
    for (let i = 0; i < 4 && !(await page.getByTestId("session-complete").isVisible()); i++) {
      await page.getByTestId("fill-scripted").click();
      await page.getByRole("button", { name: /submit answer/i }).click();
      await page.waitForTimeout(1500);
    }
    await expect(page.getByTestId("session-complete")).toBeVisible();
    await expect(page.getByTestId("hypothesis-status").first()).toContainText(/Repaired|Resolved/);
    await shot(page, "10-lab-complete");
  });

  test("6. adaptive diagnostic assessment with feedback and report", async () => {
    await page.goto(`/app/courses/${courseId}/assess`);
    await page.getByTestId("kind-diagnostic").click();
    await page.getByTestId("start-assessment").click();
    for (let i = 0; i < 8; i++) {
      await answerVisibleQuestion(page);
      await expect(page.getByTestId("feedback").last()).toBeVisible();
      if (i === 0) await shot(page, "11-assessment-feedback");
      if (await page.getByTestId("next-question").isVisible()) await page.getByTestId("next-question").click();
      else break;
    }
    await page.getByTestId("finish-assessment-bottom").click();
    await expect(page.getByTestId("assessment-report")).toBeVisible();
    await shot(page, "12-assessment-report");
  });

  test("7. mastery analytics reflect the evidence", async () => {
    await page.goto(`/app/courses/${courseId}/progress`);
    await expect(page.getByTestId("trajectory-chart")).toBeVisible();
    await expect(page.getByTestId("hypothesis-row").first()).toBeVisible();
    await shot(page, "13-mastery-analytics");
    await page.goto("/app");
    await expect(page.getByText("No scored evidence yet")).toHaveCount(0);
    await shot(page, "14-dashboard-after");
  });

  test("8. evaluation lab shows recorded runs", async () => {
    await page.goto("/app/evaluation");
    await expect(page.getByTestId("metric-card").first()).toBeVisible();
    await shot(page, "15-evaluation-rag");
    await page.getByRole("tab", { name: "Personalization" }).click();
    await shot(page, "16-evaluation-personalization");
  });
});
