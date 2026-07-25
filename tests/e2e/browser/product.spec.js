import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const namespace = "coderushoj";
const clusterName = process.env.CODERUSHOJ_E2E_CLUSTER_NAME;
const secretRoot = process.env.CODERUSHOJ_E2E_SECRET_ROOT;

const responsePathIs = (response, pathname, method) => {
  const request = response.request();
  return new URL(response.url()).pathname === pathname
    && request.method() === method;
};

const readSecret = (name) => fs.readFileSync(
  path.join(secretRoot, name),
  "utf8",
).trim();

const readCaptchaCode = (captchaKey) => {
  const redisValue = execFileSync(
    "kubectl",
    [
      "exec",
      "--namespace",
      namespace,
      "statefulset/coderushoj-infra-redis",
      "--",
      "/bin/sh",
      "-ec",
      'REDISCLI_AUTH="$REDIS_PASSWORD" exec redis-cli --raw GET "$1"',
      "sh",
      `captchaCode:${captchaKey}`,
    ],
    { encoding: "utf8" },
  );
  let captchaCode;
  try {
    captchaCode = JSON.parse(redisValue);
  } catch {
    throw new Error("Redis captcha value must be valid JSON");
  }
  if (typeof captchaCode !== "string" || captchaCode.length === 0) {
    throw new Error("Redis captcha value must be a non-empty JSON string");
  }
  return captchaCode;
};

test("administrator completes the real browser product journey", async ({
  context,
  page,
}) => {
  expect(clusterName).toMatch(/^croj-product-e2e-[0-9]+-[0-9]+$/);
  expect(secretRoot).toBeTruthy();

  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  await context.addInitScript(() => {
    window.localStorage.setItem("language", "zh-CN");
  });

  const captchaResponsePromise = page.waitForResponse(
    (response) => responsePathIs(response, "/api/captcha", "GET"),
  );
  await page.goto("/auth/login", { waitUntil: "domcontentloaded" });
  const captchaResponse = await captchaResponsePromise;
  expect(captchaResponse.ok()).toBeTruthy();
  const captchaKey = await captchaResponse.headerValue("captcha-key");
  expect(captchaKey).toBeTruthy();
  const captchaCode = readCaptchaCode(captchaKey);
  expect(captchaCode).toBeTruthy();

  await page.getByLabel("用户名或邮箱", { exact: true }).fill(
    readSecret("admin-username"),
  );
  await page.getByLabel("密码", { exact: true }).fill(
    readSecret("admin-password"),
  );
  await page.getByLabel("验证码", { exact: true }).fill(captchaCode);

  const loginResponsePromise = page.waitForResponse(
    (response) => responsePathIs(response, "/api/user/login", "POST"),
  );
  await page.getByRole("button", { name: "登录", exact: true }).click();
  const loginResponse = await loginResponsePromise;
  expect(loginResponse.ok()).toBeTruthy();
  expect(await loginResponse.json()).toMatchObject({ success: true });
  await expect(
    page.getByRole("button", { name: /e2e-admin/ }),
  ).toBeVisible();

  const primaryNavigation = page.getByRole("navigation", {
    name: "Primary navigation",
  });
  await primaryNavigation.getByRole("link", {
    name: "题库",
    exact: true,
  }).click();
  await expect(page.getByRole("heading", {
    name: "题库",
    exact: true,
  })).toBeVisible();

  const problemSearch = page.getByPlaceholder("搜索题号或标题");
  await problemSearch.fill("A+B Problem");
  const problemListResponsePromise = page.waitForResponse(
    (response) => responsePathIs(response, "/api/problem/list", "POST"),
  );
  await problemSearch.press("Enter");
  const problemListResponse = await problemListResponsePromise;
  expect(problemListResponse.ok()).toBeTruthy();
  await page.getByRole("link", {
    name: "A+B Problem",
    exact: true,
  }).click();
  await expect(page.getByRole("heading", {
    name: "A+B Problem",
    exact: true,
  })).toBeVisible();

  await page.getByRole("tab", { name: "讨论", exact: true }).click();
  await expect(page.getByRole("link", {
    name: "A+B product discussion",
    exact: true,
  })).toBeVisible();

  await page.getByRole("tab", { name: "题解", exact: true }).click();
  await expect(page.getByRole("link", {
    name: "A+B product solution",
    exact: true,
  })).toBeVisible();

  await page.getByRole("tab", { name: "提交代码", exact: true }).click();
  const editor = page.getByRole("textbox", { name: /Editor content/i });
  await expect(editor).toBeVisible();
  const sourceCode = `#include <iostream>
int main() {
  long long a, b;
  while (std::cin >> a >> b) {
    std::cout << a + b;
    if (a != 500 || b != 17) std::cout << "\\n";
  }
}`;
  await editor.fill(sourceCode);
  await expect(editor).toHaveValue(sourceCode);
  const submissionResponsePromise = page.waitForResponse(
    (response) => responsePathIs(response, "/api/submission", "POST"),
  );
  await page.getByRole("button", {
    name: "提交解答",
    exact: true,
  }).click();
  const submissionResponse = await submissionResponsePromise;
  expect(submissionResponse.ok()).toBeTruthy();
  expect(await submissionResponse.json()).toMatchObject({ success: true });
  await expect(page.getByText("ACCEPTED", { exact: true })).toBeVisible({
    timeout: 90_000,
  });

  await primaryNavigation.getByRole("link", {
    name: "公告",
    exact: true,
  }).click();
  await expect(page.getByRole("heading", {
    name: "公告",
    exact: true,
  })).toBeVisible();
  await page.getByRole("main").getByRole("link", {
    name: "Product E2E announcement",
    exact: true,
  }).last().click();
  await expect(page.getByRole("heading", {
    name: "Product E2E announcement",
    exact: true,
  })).toBeVisible();
  await expect(
    page.getByText("Real three-node Kind acceptance.", { exact: true }),
  ).toBeVisible();

  await primaryNavigation.getByRole("link", {
    name: "竞赛",
    exact: true,
  }).click();
  const contestCard = page.getByRole("article").filter({
    hasText: "Product E2E contest",
  });
  await expect(contestCard.getByRole("heading", {
    name: "Product E2E contest",
    exact: true,
  })).toBeVisible();
  await contestCard.getByRole("button", { name: "查看详情" }).click();
  await expect(page.getByRole("heading", {
    name: "Product E2E contest",
    exact: true,
  })).toBeVisible();
  await page.getByRole("button", { name: "题目", exact: true }).click();
  await expect(page.getByText("A+B Problem", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: /e2e-admin/ }).click();
  await page.getByRole("menuitem", {
    name: "管理工作台",
    exact: true,
  }).click();
  await page.getByRole("menuitem", {
    name: "题目导入",
    exact: true,
  }).click();
  await expect(page.getByRole("heading", {
    name: "题目导入",
    exact: true,
  })).toBeVisible();
  await expect(page.getByLabel("选择题目包", { exact: true })).toBeVisible();

  await page.getByRole("menuitem", {
    name: "测试包管理",
    exact: true,
  }).click();
  await expect(page.getByRole("heading", {
    name: "测试包管理",
    exact: true,
  })).toBeVisible();
  await expect(page.getByLabel("题目 ID", { exact: true })).toBeVisible();

  expect(pageErrors).toEqual([]);
});
