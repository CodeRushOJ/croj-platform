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

`config/source-lock.json` 只锁定 Frontend、Backend、Judging Server 和 Sandbox 四个外部仓库。source lock v3 的每项只接受 CodeRushOJ 官方 HTTPS 仓库、40 位小写 Git commit、对应的精确正式 SemVer tag、受约束的构建路径、Chart 使用的精确 `:dev` 镜像名，以及组件专属的 Release manifest 文件名和 64 位小写 SHA-256；branch、tag 和 `latest` 都不能替代 commit 作为跨仓库构建真相。当前固定资产为 Frontend `image-artifact.json` / `5af165529a4b8882dc492acf9886c424cf2aaebd43a7a77ea3c76018674d9a17`、Backend `backend-image.json` / `9474f05787b758d76e6115a6c8af329ab30203d141f11996558897b074d505ed`、Judging Server `judging-server-image.json` / `813d063d844fb0e19554fa15589d24c6052dbd85aa3cafc1dfdb4b5af2c71fbd`、Sandbox `sandbox-image.json` / `3b729035b7a7760ed25d86905c4db2da76bb21886df2798b0db0f4cdeb14e0ef`。Release workflow 必须先重新下载、按 source lock hash-before-parse 校验四组件公开 manifest，并校验最终制品 checksums，再创建完整的 verified draft Release；重跑会把恢复资产中的四组件对象与该可信 preflight 逐项比较，并用当前 CHANGELOG 和 Chart 重建核对 notes/render 后复用已有 draft，不删除或替换它。Docs SemVer tag 的 workflow 会先检查、仅在未观察到 tag 时创建，并在写后复核 digest；已观察到不同 digest 时立即失败。GHCR API 不提供原子 create-if-absent，外部 package 管理员的并发写入必须通过最小发布权限和运维互斥避免。部署真相始终是 immutable GitHub Release 中的 digest-only 资产。Docs 不自引用旧的平台提交：开发与产品 E2E 始终从当前平台 checkout 构建 Docs 镜像，并用当前 `GITHUB_SHA`（本地为 `HEAD`）写入 OCI provenance；正式文档镜像由 release workflow 从最新 `main` 上的 annotated SemVer tag 当前 tree 构建。

```bash
make source-verify
make source-checkout
make test-bundle-contract
make images-build
# 仅在目标 Kind 集群已经存在时执行
make images-load
```

四个外部源码按 `<组件>/<commit>` 放在 `.workspace/sources/`，不会覆盖开发者已有仓库。`test-bundle-contract` 会让锁定版本的 Backend 真实生成 TestBundle v1 ZIP，再把同一个文件交给锁定版本的 Judging 解析，避免两份手写 fixture 假装联调。`images-build` 会先做幂等 checkout，再用 Buildx 构建四个锁定组件镜像和一个当前 checkout 的 Docs 镜像，并写入各自的 OCI source/revision 标签；`images-load` 仅在外部镜像与源码锁、Docs 镜像与当前平台 revision 分别一致时才载入已有集群，不会创建或启动 Kind 集群。完整更新与故障处理见[快速开始](docs/guide/quickstart.md#不可变源码与开发镜像)。

## 容器镜像

GHCR 是组件 Release 的 canonical registry；Docker Hub 提供按 digest 逐字节验证的多架构镜像源，不是独立重建。四个组件独立版本化，不发布或支持 `latest`。生产部署只使用平台 immutable GitHub Release 记录的 digest，不根据 registry 页面时间或可变标签拼装版本。

| 组件 | 版本 | GHCR | Docker Hub 镜像源 | OCI index digest |
| --- | --- | --- | --- | --- |
| Frontend | `v1.0.1` | `ghcr.io/coderushoj/croj-frontend` | `docker.io/pursuitno1/croj-frontend` | `sha256:97c01e8febd44f3507e6d30e00db906f506ead2a4afab0ebebd2e7bfe7b2a43b` |
| Backend | `v1.0.3` | `ghcr.io/coderushoj/croj-backend` | `docker.io/pursuitno1/croj-backend` | `sha256:ec77492aa73089913a331db7c8dae39ca8b81ee579c13554a5bc1a763b2ac1b6` |
| Judging Server | `v1.0.2` | `ghcr.io/coderushoj/croj-judging-server` | `docker.io/pursuitno1/croj-judging-server` | `sha256:ffe302a1b2d3d07f063500c3da9508d1d4b9373753913de107591899eb10b4df` |
| Sandbox | `v1.0.2` | `ghcr.io/coderushoj/croj-sandbox` | `docker.io/pursuitno1/croj-sandbox` | `sha256:3cc6d8a9b0af30b560fdbbb82769d083c2dfc13966004428f5bdf30b0f317464` |

每个 index 都包含 `linux/amd64`、`linux/arm64` 和同批次证明 manifest。Docker Hub 部署覆盖只替换四组件 repository，不携带 tag 或 digest；Docs 仍使用 GHCR。使用方法见[应用服务部署](docs/guide/application-deployment.md#docker-hub-镜像源)。

## 项目状态

- 当前平台版本：`1.0.2`
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
