# Changelog

CodeRushOJ 的重要变化记录在此。该日志同时覆盖历史原型和当前平台化工作；
2025 年的条目根据各原仓库 README 与 Git 提交记录重建，并不表示当时存在统一的正式版本标签。

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Features

- 增加 VitePress GitHub Pages 项目站点，默认使用 `/croj-platform/` 基路径，并支持通过 `CODERUSHOJ_DOCS_BASE` 切换到自定义域名根路径或子路径。
- 应用 Chart 增加默认关闭的 backend、frontend 与 judging-server Deployment；backend/frontend Service 固定匹配 Gateway 路由，judging 复用 namespace 级 EndpointSlice RBAC 且不暴露公网 Service。
- 三类应用增加 tag/digest、资源、安全上下文、PDB、拓扑分散/软反亲和、外部 Secret 与版本化 RocketMQ 合同；production 开启时强制不可变 digest。
- backend 上传目录支持开发 `emptyDir` 与 production `existingClaim` 两种显式模式，production 未提供现有 RWX PVC 时拒绝渲染。
- judging 预留 S3 hidden bundle 配置/Secret 映射和带容量上限的 `/tmp/croj-bundles` 可重建缓存，缓存不作为持久化真相源。
- judging hidden bundle 合同补齐缓存容量/TTL、压缩包与解压边界、zip bomb 比率和基础设施重试次数共 10 项 `JUDGE_BUNDLE_*` 环境变量，并通过 schema 拒绝非正数限制。
- 增加不读取/输出 Secret 值的安装前预检脚本，以及完整应用 Secret、render、安装、验证和回滚文档。
- sandbox 增加与 2 CPU limit 对齐的 `maxConcurrency=2` Helm 参数。
- 在应用 Helm Chart 中增加可水平扩展的 `croj-sandbox` Deployment 与 ClusterIP Service，固定 `grpc` 端口名和 `50051/TCP`，与 judging-server 的 EndpointSlice 发现契约一致。
- 增加标准 gRPC startup/readiness/liveness probes、Pod UID Downward API、专用节点选择、资源边界、无 ServiceAccount token 和默认拒绝网络出口的 NetworkPolicy 声明。
- 为 judging-server 增加 namespace 级 EndpointSlice 只读 ServiceAccount、Role 与 RoleBinding，避免使用 ClusterRole 或读取无关 Kubernetes 资源。
- 提供本地 Kind 高权限开发 profile 与默认禁用的 production fail-closed 参考 profile，并发布独立安装、验证和排障文档。

### Security

- Pages 工作流将只读构建与 OIDC 部署权限拆分到不同 Job；Pull Request 只构建检查，不接触 `pages: write` 或部署 environment。
- backend/judging 只从用户提供的 existing Secret key 注入 MySQL、Redis、RocketMQ、JWT、SMTP 与回调 token；values、模板和示例不包含凭据，且二者固定共享 `JUDGE_RESULT_SERVICE_TOKEN` key 契约。
- 应用 NetworkPolicy 改为显式 opt-in，避免在 kindnet 环境把“策略对象存在”误报为网络隔离生效。
- sandbox 在默认与 production values 中都保持关闭；production 渲染强制合法 sha256 digest、隔离 `kata-qemu` RuntimeClass、非 root、只读根文件系统、删除 capabilities 且禁止宿主 cgroup 挂载，但在执行器完成 cgroup/seccomp fail-closed 加固前不能作为可运行部署。
- `values-kind.yaml` 中的 `hostPID`、`nsenter`、privileged 与 Bidirectional host cgroup 挂载被明确限定为受控本地开发用途，不属于生产安全基线。
- 固定 Service 名并禁止覆盖 selector 保留 label，避免 judging-server EndpointSlice 发现静默失效。

### Operations

- 增加固定完整 commit SHA 的 Pages Actions、`github-pages` environment、并发控制、手动发布与文档回滚指南；`main` 合并和手动触发才部署。
- Helm 合约测试覆盖 Service/Pod selector、EndpointSlice 端口、三类 gRPC 探针、开发 cgroup 权限、生产 fail-closed 行为、禁用路径和 values schema。
- 部署脚本根据 Helm 3/4 自动选择 `--atomic` 或 `--rollback-on-failure`；CI 显式传播 Go 工具安装目录。

### Known Limitations

- backend/frontend production Dockerfile 已分别进入 backend PR #16 与 frontend PR #10 审核，但尚未合并发布不可变 digest；judging distroless 镜像仍无 Kubernetes 原生健康端点。对应工作由 backend#10、frontend#5 与 judging-server#7 跟踪，Helm 合同通过不代表镜像已发布可用。
- backend 的 RWX PVC 只是当前文件上传兼容路径；S3 兼容对象存储由 backend#11 跟踪，production 禁止使用会随 Pod 丢失且多副本不共享的 `emptyDir`。
- 当前 sandbox 在 child 启动前不可降级的身份/seccomp、可写 delegated cgroup 与对抗性测试方面仍未完成；production reference 默认禁用，不是 production-ready 部署。
- Kind 默认 kindnet 不执行 NetworkPolicy，因此本地策略对象只通过 schema 验证，不能宣称网络隔离已生效；policy-capable CNI 与正反向探针由 Issue #4 跟踪。
- judging-server 的真实 sandbox gRPC 调用、CAS 终态写回与幂等重试仍是目标态，当前不能承诺判题请求无损恢复。

### Upgrade

- 应用 Chart `0.3.0` 默认不启动 backend/frontend/judging；启用前必须创建并预检 existing Secret，production 还必须提供三类 digest 与 backend RWX PVC。
- 应用 Chart 升级到 `0.2.0` 后不会自动启动 sandbox。开发环境显式传入 `sandbox.enabled=true` 和 `values-kind.yaml`；production 保持禁用，待执行器安全门禁全部通过后才允许显式启用。

### Rollback

- 回滚到 Chart `0.2.0` 会删除已显式启用的 backend/frontend/judging Deployment、Service、PDB 与 RBAC；Secret 和现有 PVC 不由 Helm 删除，回滚前必须确认数据库/schema 与消息版本兼容。
- 回滚到 Chart `0.1.0` 会删除已经显式启用的 sandbox Deployment、Service 和 NetworkPolicy；正在执行的请求会中断，当前版本尚不能承诺由 judging-server 自动无损恢复。

## [0.1.0] - 2026-07-18

### Features

- 在保留原有 Vue、Spring Boot 与 Go 代码库的前提下，确立完整 OJ v1 架构与跨仓库交付计划。
- 建立语义化版本、Issue Epic、变更日志、固定依赖版本和可复现的本地工具链。
- 建立 1 个控制平面与 2 个判题工作节点的 Kind 集群，包含 Colima DNS 自愈和失败诊断。
- 引入 Gateway API v1.5.1 与 Envoy Gateway v1.8.2，并固定本地 NodePort 路由。
- 为 MySQL 8.4、Redis 8.6、RocketMQ 5.5 和 SeaweedFS 4.39 提供带持久化、探针、资源限制及 NetworkPolicy 的 Helm Chart。
- 增加与 Helm 版本一致的 Docker Compose 开发栈、本地密钥生成、幂等部署、冒烟测试与脱敏诊断基础。
- 发布中文优先的 VitePress 文档站，覆盖 Compose/Kind 部署、架构、故障排查、备份恢复、里程碑和发版流程。
- 建立 Issue Form、PR 门禁、三节点 Kind CI、依赖与 Secret 扫描、签名标签校验、Chart 打包和不可变文档镜像发布流程。

### Fixes

- 修复 Colima 虚拟机中 `/etc/resolv.conf` 为空导致 Kind 节点无法拉取镜像的问题，集群脚本会安全地自愈 DNS。
- 修复本地 Secret 文件尾部换行导致 MySQL 初始化客户端配置无效的问题，并规范化已生成的密钥文件。
- 修复 RocketMQ 默认 2 GiB 堆与 `AlwaysPreTouch` 在本地资源限制下触发 OOM 的问题，分别约束 NameServer、Broker 和管理任务内存。
- 修正不存在的 Kind v1.36.2 节点镜像与不匹配的 Gateway API 版本，改用经过实机验证且带 digest/checksum 的版本。

### Security

- Secret 只生成到 Git 忽略、权限为 `0600` 的本地目录，通过 Kubernetes Secret 或 Compose file secret 注入，不在终端输出值。
- 有状态工作负载默认启用非 root、安全上下文、seccomp、最小权限和 NetworkPolicy；部署诊断默认不导出 Secret。
- CI 的第三方 GitHub Actions 固定到完整 commit SHA，并对仓库执行 Secret、依赖漏洞和 Kubernetes 配置扫描。

### Migrations

- 本版本只建立平台底座，不修改原业务数据库 schema，也不执行生产数据迁移。
- 后续后端基线将把可保留的原 MySQL DDL 转换为有序 Flyway migration，并提供可重复的非生产测试数据。

### Operations

- 服务发现方向由历史原型中的 ZooKeeper 调整为 Kubernetes 原生 Service、EndpointSlice 与 Job 调度。
- MySQL 被确认为权威数据源，Redis 仅作可重建加速层；隐藏测试数据和附件使用 S3 兼容的 SeaweedFS。
- `make deploy && make smoke` 已在本机三节点 Kind 集群真实验证 MySQL `SELECT 1`、Redis `PONG`、RocketMQ topic、SeaweedFS S3 读写和 Gateway Programmed 状态。
- Docker Compose 5.3.1 配置已通过真实 CLI 解析；Compose 路径只暴露回环端口，且不会替代 Kubernetes 判题验收环境。

### Known Limitations

- 应用镜像、真实端到端判题、竞赛、论坛和题解仍在后续迭代中；本版本首先完成平台底座。
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
