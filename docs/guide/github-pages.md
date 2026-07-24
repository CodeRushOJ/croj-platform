# GitHub Pages 文档发布

平台文档通过 GitHub Actions 构建并发布到
[https://coderushoj.github.io/croj-platform/](https://coderushoj.github.io/croj-platform/)。Pull Request
只执行 VitePress 构建与链接检查，不上传或部署站点；合并到 `main` 或手动触发工作流后才会更新线上文档。

GitHub Pages 只承载公开的架构、部署和运维文档。它不能运行 Spring Boot、MySQL、Redis、RocketMQ、判题服务或沙箱；真实 OJ 的前端与 `/api` 仍必须通过 Kubernetes Gateway 对外提供。

## 首次启用

仓库管理员在 `Settings → Pages` 中将构建来源设为 `GitHub Actions`。随后运行
`Documentation Pages` 工作流，默认站点路径为 `/croj-platform/`。构建任务只有只读仓库权限，部署任务才单独获得 `pages: write` 和 OIDC `id-token: write` 权限。

## 自定义域名

在仓库 Pages 设置中配置并验证域名、HTTPS 和 DNS，然后创建 Repository variable：

```text
CODERUSHOJ_DOCS_BASE=/
```

默认值 `/croj-platform/` 适用于 GitHub 项目站点。自定义域根路径使用 `/`；如果文档发布在域名子路径，变量必须同时以 `/` 开头和结尾，例如 `/docs/`。错误格式会让构建立即失败，避免生成不可用的静态链接。

## 本地验证

项目站点路径：

```bash
cd docs
corepack enable
pnpm install --frozen-lockfile
CODERUSHOJ_DOCS_BASE=/croj-platform/ pnpm build
```

自定义域根路径：

```bash
CODERUSHOJ_DOCS_BASE=/ pnpm build
```

VitePress 会在构建阶段检查内部链接。产物位于 `docs/.vitepress/dist`，该目录是生成物，不提交到 Git。

## 发布与回滚

Pages 部署使用 `github-pages` environment，建议为生产仓库配置审批与分支保护。所有部署共享仓库级并发组，旧部署不会被新部署中途取消。回滚时，在目标历史提交上手动运行工作流，或恢复文档提交后合并到 `main`；不要手工编辑构建产物。
