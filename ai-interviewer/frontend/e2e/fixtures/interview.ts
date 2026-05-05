import type { Page } from "@playwright/test";

export async function mockSetupApis(page: Page) {
  await page.route("**/api/v1/interview/directions", async (route) => {
    await route.fulfill({
      json: {
        directions: [
          {
            direction: "java_backend",
            industry: "internet",
            label: "Java 后端开发",
            default_title: "Java 后端开发工程师",
            default_level: "senior",
            skills: ["java", "spring", "mysql"],
            dimension_catalog: [
              { id: "technical_depth", label: "技术深度" },
              { id: "problem_solving", label: "问题解决" },
              { id: "communication", label: "沟通表达" },
            ],
          },
        ],
      },
    });
  });

  await page.route("**/api/v1/interview/dimensions", async (route) => {
    await route.fulfill({
      json: {
        dimensions: [
          { id: "technical_depth", label: "技术深度" },
          { id: "problem_solving", label: "问题解决" },
          { id: "communication", label: "沟通表达" },
        ],
      },
    });
  });

  await page.route("**/api/v1/interview/job-template**", async (route) => {
    await route.fulfill({
      json: {
        direction: "java_backend",
        level: "senior",
        title: "Java 后端开发工程师",
        template: "岗位职责：负责核心服务开发。",
        skills: ["java", "spring", "mysql"],
        rubric_dimensions: ["technical_depth", "problem_solving", "communication"],
      },
    });
  });

  await page.route("**/api/v1/interview/sessions", async (route) => {
    await route.fulfill({
      json: {
        session_id: "sess-e2e",
        session_token: "token-e2e",
        trace_id: "trace-e2e",
        status: "running",
      },
    });
  });
}
