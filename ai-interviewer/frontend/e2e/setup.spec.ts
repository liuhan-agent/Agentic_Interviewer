import { expect, test } from "@playwright/test";

import { mockSetupApis } from "./fixtures/interview";

test("candidate can walk through setup and start an interview", async ({ page }) => {
  await mockSetupApis(page);

  await page.goto("/interview/setup");
  await expect(page.getByText("先选目标岗位")).toBeVisible();

  await page.getByRole("button", { name: /下一步/ }).click();
  await page.getByPlaceholder("请输入你的姓名或昵称").fill("Ada");

  await page.getByRole("button", { name: /下一步/ }).click();
  await expect(page.getByRole("button", { name: /开始我的面试/ })).toBeVisible();

  await page.getByRole("button", { name: /开始我的面试/ }).click();
  await expect(page).toHaveURL(/\/interview\/sess-e2e$/);
});
