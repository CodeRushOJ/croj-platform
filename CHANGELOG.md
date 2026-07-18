# Changelog

CodeRushOJ 的重要变化记录在此。该日志同时覆盖历史原型和当前平台化工作；
2025 年的条目根据各原仓库 README 与 Git 提交记录重建，并不表示当时存在统一的正式版本标签。

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
