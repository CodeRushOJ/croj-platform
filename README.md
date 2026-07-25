# CodeRushOJ Platform

CodeRushOJ Platform 是现有 CodeRushOJ 多仓库项目的部署、集成测试和发版中心。它不替代业务代码：

- `croj-frontend`：Vue 3 用户端、管理端、竞赛与社区界面
- `croj-backend`：Spring Boot 业务 API 与持久化
- `croj-judging-server`：Go 异步 REST/RocketMQ 判题编排、持久化任务与回调
- `croj-sandbox`：Go 多语言隔离执行器
- `croj-platform`：本仓库，负责 Docker Compose、Helm、Kind、文档和跨仓库验收

## 快速开始

完整安装、升级、回滚和故障处理请阅读[快速开始](docs/guide/quickstart.md)。
应用 Secret、镜像 digest 和 Helm 安装流程见[应用服务部署](docs/guide/application-deployment.md)，沙箱的节点权限、服务发现与容量边界见[Sandbox 部署](docs/guide/sandbox-deployment.md)。
公开文档通过 [GitHub Pages](https://coderushoj.github.io/croj-platform/) 发布；首次启用、自定义域名和回滚步骤见 [Pages 发布指南](docs/guide/github-pages.md)。Pages 只承载静态文档，真实 OJ 仍由 Kubernetes Gateway 提供。

```bash
make bootstrap
make cluster-up
make deploy
make smoke
```

当前平台底座的 MySQL、Redis、RocketMQ、SeaweedFS、Gateway API 和 Envoy Gateway 已在三节点 Kind 集群通过真实冒烟测试。本地 profile 还提供不出网的 Mailpit 邮件捕获器。应用 Chart 已覆盖前端、后端、文档、异步 REST 判题服务、两副本沙箱和默认关闭的一次性超级管理员 bootstrap Job；CI 另有自己命名、always 清理的三节点产品 E2E，覆盖真实登录、FPS/TestBundle、RocketMQ 内部回调、外部异步 REST、manifest v2 OI 部分分、沙箱内 special judge、社区、比赛、邮件、Service DNS/EndpointSlice 与 Calico NetworkPolicy，并在同一集群上用固定版本 Playwright/Chromium 驱动真实浏览器关键路径。真实公网 Webhook 只有在三项 receiver Secret 完整配置并通过签名复算后才计入发布证据；未配置不会被伪报为通过。发布环境必须传入 CI 产出的镜像 digest。

## 不可变跨仓库构建

`config/source-lock.json` 只锁定 Frontend、Backend、Judging Server 和 Sandbox 四个外部仓库。source lock v2 的每项只接受 CodeRushOJ 官方 HTTPS 仓库、40 位小写 Git commit、对应的精确正式 SemVer tag、受约束的构建路径和 Chart 使用的精确 `:dev` 镜像名；branch、tag 和 `latest` 都不能替代 commit 作为跨仓库构建真相，`releaseTag` 仅用于核对并下载该 commit 的正式发布清单。Docs 不自引用旧的平台提交：开发与产品 E2E 始终从当前平台 checkout 构建 Docs 镜像，并用当前 `GITHUB_SHA`（本地为 `HEAD`）写入 OCI provenance；正式文档镜像由 release workflow 从最新 `main` 上的 annotated SemVer tag 当前 tree 构建。

```bash
make source-verify
make source-checkout
make test-bundle-contract
make images-build
# 仅在目标 Kind 集群已经存在时执行
make images-load
```

四个外部源码按 `<组件>/<commit>` 放在 `.workspace/sources/`，不会覆盖开发者已有仓库。`test-bundle-contract` 会让锁定版本的 Backend 真实生成 TestBundle v1 ZIP，再把同一个文件交给锁定版本的 Judging 解析，避免两份手写 fixture 假装联调。`images-build` 会先做幂等 checkout，再用 Buildx 构建四个锁定组件镜像和一个当前 checkout 的 Docs 镜像，并写入各自的 OCI source/revision 标签；`images-load` 仅在外部镜像与源码锁、Docs 镜像与当前平台 revision 分别一致时才载入已有集群，不会创建或启动 Kind 集群。完整更新与故障处理见[快速开始](docs/guide/quickstart.md#不可变源码与开发镜像)。

## 项目状态

- 当前平台版本：`1.0.0`
- 历史原型：2025-03-31 至 2025-04-26，详见 [CHANGELOG.md](CHANGELOG.md)
- 目标：完整 v1.0 OJ，包含竞赛、论坛和题解，不包含付费功能
- 参考容量：1,000 在线用户、100 并发提交、20 个并行沙箱执行

## 验证

```bash
make validate
make source-verify
make test-bundle-contract
make smoke
```

完整产品门禁及可选公网 HTTPS Webhook receiver contract 见
[三节点产品 E2E](docs/operations/product-e2e.md)。本地静态验证不会声称 Kind、
OI/SPJ 或 Webhook 已实际执行；以对应 GitHub Actions run 为准。

本地密钥位于 `.workspace/secrets/`，不会写入 Git。失败诊断位于 `.workspace/diagnostics/latest/`，以受限权限保存资源状态和事件，默认不抓取应用日志或导出 Kubernetes Secret；共享前仍须按敏感运维数据审阅。
