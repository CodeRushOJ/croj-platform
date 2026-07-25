# Changelog

CodeRushOJ 的重要变化记录在此。该日志同时覆盖历史原型和当前平台化工作；
2025 年的条目根据各原仓库 README 与 Git 提交记录重建，并不表示当时存在统一的正式版本标签。

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Features

- 平台源码锁更新到已评审的 Frontend、Backend、Judging Server 与 Sandbox v1 发布候选提交。
- 三节点产品门禁增加外部 manifest v2 OI `30/100` 部分分与沙箱内 special judge 闭环，并保留原 Backend → RocketMQ → Judging → Sandbox → callback → MySQL 主链。
- 增加可选真实公网 HTTPS Webhook 验收：运维 CLI 注册 callback，异步 job 触发 outbox 投递，assertion API 返回原始 body/header 后由门禁重新计算 HMAC-SHA256。

### Fixes

- 补齐外部 Judge 启动所需的独立 `coderushoj_judge` DSN、版本化 source/callback key ring Secret 引用，以及主容器前带 advisory lock 的 schema migration init container。
- 产品 E2E 现在比较 `sandbox-workers` DNS A 记录与 Ready EndpointSlice address，并核对 Judging 始终使用 `dns:///...` 且关闭 legacy discovery。

### Security

- Webhook E2E 不放宽公网 HTTPS、SSRF、DNS rebinding 或 redirect 防护；三项 receiver 配置不完整时失败关闭，未配置时不声称该门禁通过。
- 一次性 callback secret、外部 API key、Judge DSN 与 AES key ring 只保存在 Git 忽略的 `0600` 文件或 Kubernetes Secret 引用中。

### Operations

- 部署与排障文档增加 Judge 专用 schema、migration init container、key rotation、Service DNS/EndpointSlice 对账及 Webhook receiver contract。

## [0.1.0] - 2026-07-24

### Features

- 三节点产品门禁在真实 API 数据准备之后增加固定版本 Playwright/Chromium 浏览器验收，覆盖登录、题目列表与详情、代码提交到终态、公告、讨论/题解、比赛详情，以及管理端题目导入与 TestBundle 入口。
- 增加跨仓库 `source-lock.json`，用五个官方仓库的 40 位 Git commit、构建路径和精确开发镜像名建立可审计的镜像输入。
- 增加 commit-addressed checkout、五镜像 Buildx 构建和显式 Kind image load 命令；构建镜像写入 OCI source/revision 标签，载入命令不会隐式创建集群。
- 应用 Helm Chart 现已渲染前端、后端、VitePress 文档、异步 REST 判题服务及双副本 gRPC 沙箱，并提供 Service、探针、资源边界和核心多副本组件 PDB。
- 本地基础设施 profile 增加固定版本 Mailpit，捕获注册/验证码邮件而不向公网发送；生产 profile 强制由运维提供真实 SMTP 地址、账号和 Secret。
- 增加 `sandbox-workers` headless Service；判题服务通过 Kubernetes Service DNS 和 gRPC `round_robin` 使用 Ready EndpointSlice，不再需要默认 Kubernetes API 权限。
- 为第三方 OJ 增加独立 Judge hostname 与 `/api/v1` 路由；默认只提供集群内 Service，Kind profile 才显式开放本地 HTTP。
- 增加 TestBundle v1 真实跨仓门禁：Backend 从锁定源码生成 ZIP，Judging 原样消费同一个产物；CI 不再依赖两仓各自维护的同名 fixture 推断兼容性。
- 在保留原有 Vue、Spring Boot 与 Go 代码库的前提下，确立完整 OJ v1 架构与跨仓库交付计划。
- 建立语义化版本、Issue Epic、变更日志、固定依赖版本和可复现的本地工具链。
- 建立 1 个控制平面与 2 个判题工作节点的 Kind 集群，包含 Colima DNS 自愈和失败诊断。
- 引入 Gateway API v1.5.1 与 Envoy Gateway v1.8.2，并固定本地 NodePort 路由。
- 为 MySQL 8.4、Redis 8.6、RocketMQ 5.5 和 SeaweedFS 4.39 提供带持久化、探针、资源限制及 NetworkPolicy 的 Helm Chart。
- 增加与 Helm 版本一致的 Docker Compose 开发栈、本地密钥生成、幂等部署、冒烟测试与受限诊断基础。
- 发布中文优先的 VitePress 文档站，覆盖 Compose/Kind 部署、架构、故障排查、备份恢复、里程碑和发版流程。
- 建立 Issue Form、PR 门禁、三节点 Kind CI、依赖与 Secret 扫描、签名标签校验、Chart 打包和不可变文档镜像发布流程。

### Fixes

- 修复三节点 Kind 验收中的 S3 probe 被默认拒绝策略阻断：新增只允许 probe 访问集群 DNS 与 SeaweedFS `8333/TCP` 的最小权限双向 NetworkPolicy。
- 修复应用与基础设施 NetworkPolicy 的 release selector 和真实数据流：分别限定 MySQL、Redis、S3、RocketMQ NameServer/Broker、Mailpit、生产 SMTP、内部 HTTP 与 gRPC 端口。
- 外部判题入口只在 listener 启用且显式暴露时开放 `8081/TCP`，Judge 的 Redis 双向授权随 external API 开关同步渲染。
- 修复 Colima 虚拟机中 `/etc/resolv.conf` 为空导致 Kind 节点无法拉取镜像的问题，集群脚本会安全地自愈 DNS。
- 修复本地 Secret 文件尾部换行导致 MySQL 初始化客户端配置无效的问题，并规范化已生成的密钥文件。
- 修复 RocketMQ 默认 2 GiB 堆与 `AlwaysPreTouch` 在本地资源限制下触发 OOM 的问题，分别约束 NameServer、Broker 和管理任务内存。
- 修正不存在的 Kind v1.36.2 节点镜像与不匹配的 Gateway API 版本，改用经过实机验证且带 digest/checksum 的版本。

### Security

- 浏览器验收不注入认证状态、不拦截网络请求；真实 CAPTCHA 继续使用 disposable 集群 Redis 白盒夹具，runner 对 owned cluster 名称和当前 kubectl context 都失败关闭。
- 源码锁的 Shell 传递改为 NUL 分隔记录并拒绝全部 ASCII 控制字符；Kind 载入前强制核对镜像 OCI source/revision，checkout 缓存通过崩溃自动释放的内核文件锁并发发布并二次验证，旧 owner 目录只在宽限期和双重快照确认后隔离回收。
- 源码锁校验会拒绝可变 ref、非 CodeRushOJ 远端、未知字段、不安全相对路径、重复镜像和不完整组件集合；已有 checkout 不干净时保持现场并 fail closed。
- 生产 values 强制所有应用镜像使用 digest，任何缺失都会使 Helm 渲染失败。
- 默认 profile 不拉取未发布的应用镜像；Kind 应用 profile 固定 `:dev` 且使用 `imagePullPolicy: Never`，要求先显式载入本地构建产物。
- 本地 Secret 生成器新增 JWT、内部结果 token 和四项 32-byte Base64 外部 API 密钥材料，保持幂等、静默和 `0600` 权限。
- 所有应用与基础设施 Pod 默认关闭 ServiceAccount token；NetworkPolicy 只允许实际组件、release instance 与端口，DNS 仅访问 kube-system CoreDNS，公开 Webhook 出口单独限制。
- Secret 只生成到 Git 忽略、权限为 `0600` 的本地目录，通过 Kubernetes Secret 或 Compose file secret 注入，不在终端输出值。
- 有状态工作负载默认启用非 root、安全上下文、seccomp、最小权限和 NetworkPolicy；部署诊断默认不导出 Secret。
- CI 的第三方 GitHub Actions 固定到完整 commit SHA，并对仓库执行 Secret、依赖漏洞和 Kubernetes 配置扫描。

### Migrations

- 本版本只建立平台底座，不修改原业务数据库 schema，也不执行生产数据迁移。
- 后续后端基线将把可保留的原 MySQL DDL 转换为有序 Flyway migration，并提供可重复的非生产测试数据。

### Operations

- 浏览器失败保留 Playwright trace、screenshot、video 与 HTML report，集群失败继续保留受限诊断；owned cluster 在 artifact 上传前通过 `always()` 清理，证据保留 14 天。
- Kind 的两个工作节点新增 `coderushoj.io/sandbox=true` 专用调度标签。
- 文档更新为长期运行沙箱、异步 REST、稳定 Webhook outbox 和 headless Service 架构，并记录本地/生产暴露差异。
- 失败诊断按敏感运维数据以受限权限保存，默认不抓取应用日志；文档明确 Envoy Gateway controller/CRD 与应用 Helm release 的独立生命周期和回滚边界。
- 失败诊断由 Python wrapper 持有 `.publish.flock` 内核锁并直接运行当前 Bash worker，避免共享 fd/env 绕过、PID/TZ 与 stale-lock 竞态；旧 `.publish.lock/` 活 owner 会失败关闭，legacy journal 可在 SIGKILL 后恢复。
- 服务发现方向由历史原型中的 ZooKeeper 调整为 Kubernetes 原生 Service、EndpointSlice 与 Job 调度。
- MySQL 被确认为权威数据源，Redis 仅作可重建加速层；隐藏测试数据和附件使用 S3 兼容的 SeaweedFS。
- `make deploy && make smoke` 已在本机三节点 Kind 集群真实验证 MySQL `SELECT 1`、Redis `PONG`、RocketMQ topic、SeaweedFS S3 读写和 Gateway Programmed 状态。
- Docker Compose 5.3.1 配置已通过真实 CLI 解析；Compose 路径只暴露回环端口，且不会替代 Kubernetes 判题验收环境。

### Known Limitations

- 跨仓库 E2E 的第一阶段只完成不可变源码、镜像构建和载入契约；锁中的组件 commit 将在各自最终集成分支合并后通过独立评审更新，Kind 内真实产品闭环仍由 issue #11 后续阶段验收。
- 这些应用清单已通过 Helm/契约测试，但在跨仓库集成镜像和 Judge v5 migration 完成前尚未执行完整 Kind 端到端判题验收。
- 现有头像接口仍使用单副本后端的 RWO PVC；切换为 S3 对象存储适配器前，后端不具备无状态多副本能力。
- 协调发布的应用镜像、真实端到端判题、竞赛、论坛和题解仍在后续迭代中；本版本首先交付可审计的平台底座与应用清单。
- 当前生产形态的有状态组件仍为单节点参考配置，正式生产应使用外部托管或高可用集群。

### Upgrade

- `0.1.0` 是第一个协调的平台版本，没有来自更早平台 Chart 的升级步骤；已有原型数据暂不自动导入。
- 后续版本升级前必须备份 MySQL 与对象存储，并使用 `helm upgrade --install` 配合固定版本 values；完整命令见文档站发版流程。

### Rollback

- 无业务 schema 变更时，可使用 `helm rollback coderushoj-infra <revision> -n coderushoj` 和对应应用 release 回退。
- 如果基础设施初始化失败，`--atomic` 会回退本次 Helm 变更；持久卷不会由普通 `compose down` 或 Helm 回滚自动删除。

## [0.0.1] - 2025-04-26

> 历史原型里程碑：根据 2025-03-31 至 2025-04-26 的原仓库提交重建，充分记录项目已有成果；它不是协调发布的 Git 标签。

### Frontend

- 初始化 Vue 3/Vite 应用，完成登录、注册、CAPTCHA、邮箱验证和会话过期处理。
- 完成路由守卫、退出流程、错误消息国际化与账户状态识别。
- 建立管理端界面、个人资料、头像上传、设置与运行环境切换页面。
- 集成 Monaco Editor，并形成提交代码与提交记录的首版用户流程。
- 增加前端日志能力并持续修复浮层、布局和显示问题。

### Backend

- 建立用户模块、Spring Security、JWT 鉴权、角色生效逻辑和 CORS 配置。
- 完成 CAPTCHA，并使用 `SecureRandom` 加固验证码生成。
- 实现邮箱验证双流程、账户状态检查、头像上传及相关修复。
- 建立题目接口、提交模块和 MySQL 持久化基础。
- 接入 RocketMQ，为异步判题消息链路奠定基础。

### Judge orchestration

- 建立 Go 判题服务的首版工程框架和配置结构。
- 形成判题任务处理、沙箱客户端与结果回写的初始边界，并修复次数更新异常。

### Sandbox

- 建立 Go 本地代码执行沙箱，覆盖 Go、C++、Python、Java 与 JavaScript 的首版语言适配。
- 实现编译/执行超时、内存监控、输出限制、退出码与判题状态收集。
- 引入日志和调试模块，并原型化 seccomp、cgroups 与 Linux 隔离机制。
- 提供 gRPC API、简单客户端、Dockerfile，以及 ZooKeeper 服务注册的早期实现。
- 记录 Accepted、Wrong Answer、Compile Error、Runtime Error、TLE、OLE 与 Sandbox Error 等结果模型。

### Project architecture

- 建立 CodeRushOJ 组织级架构说明，明确 Vue、Spring Boot、Go、MySQL、Redis、RocketMQ、gRPC、Docker 与 Kubernetes 的技术方向。
- 描述了异步提交、前端轮询、判题协调、沙箱执行和结果回写的完整目标流程。

### Historical limitations

- 各组件尚未形成可重复的一键部署，配置中仍存在固定地址和敏感信息风险。
- 判题服务仍包含模拟结果路径，沙箱隔离实现与 README 描述之间存在差距。
- 缺少系统化的前后端测试、真实隐藏测试数据、CI、升级回滚与运维文档。

[Unreleased]: https://github.com/CodeRushOJ/croj-platform/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/CodeRushOJ/croj-platform/releases/tag/v0.1.0
[0.0.1]: https://github.com/orgs/CodeRushOJ/repositories
