# Changelog

CodeRushOJ 的重要变化记录在此。该日志同时覆盖历史原型和当前平台化工作；
2025 年的条目根据各原仓库 README 与 Git 提交记录重建，并不表示当时存在统一的正式版本标签。

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Features

- 后续兼容功能将记录在本节，并在下一次语义化发版时归档。

### Fixes

- 后续缺陷修复将记录在本节，并附带对应测试证据。

### Security

- 后续安全更新将记录在本节，并注明升级或密钥轮换影响。

### Operations

- 后续部署、监控与回滚变化将记录在本节。

## [1.0.2] - 2026-07-25

### Features

- 保持 `1.0.1` 已验收的完整 OJ 运行时、Kubernetes 架构与不可变组件锁，不引入业务行为或数据模型变化。

### Fixes

- Release job 在执行 `make validate` 前显式运行 `corepack enable` 并按 lockfile 安装文档依赖，确保文档链接契约调用固定版本 `pnpm` 和 VitePress 时工具链已存在；修复 `v1.0.1` 在全部版本、标签、main 与真实产品 E2E 预检通过后，因 `FileNotFoundError: pnpm` 停在静态门禁的问题。
- 新增发布工作流顺序契约，强制先完成 tag/main 与主干 E2E 信任预检，再执行 package-manager provisioning 和限定于 `docs` 的锁定依赖安装，最后才运行完整静态发布门禁；不可信标签不能先执行仓库控制的 package lifecycle。
- 四个组件的镜像清单改从其不可变公开 GitHub Release 资产下载，不再错误地使用仅限平台仓库的 `GITHUB_TOKEN` 读取跨仓 Actions artifact；清单字段、源码锁 revision/tag 和四个 GHCR 双架构索引均在首次推送前验证。
- Docs 镜像先仅发布 commit-addressed `sha-<revision>` staging tag；全部生产 values、registry、Helm/Kubeconform 与 checksums 验证完成后才创建 SemVer 镜像 tag，避免前置失败留下看似正式但没有 Release 的部分版本。

### Security

- pnpm 继续由仓库 `packageManager` 与 lockfile 固定版本，Release 不依赖 runner 上未声明的全局包管理器；跨仓输入通过公开 Release 资产读取，无需扩大平台 token 到其他仓库的 Actions 权限。

### Migrations

- 无数据库、对象存储、消息队列或 Judge schema 迁移。

### Operations

- 保留失败的 annotated `v1.0.0` 与 `v1.0.1` 标签，不移动或删除公开历史；两者均未创建 GitHub Release 或可部署制品。正式制品发布从 `v1.0.2` 开始。

### Known Limitations

- Chart 内有状态依赖仍面向本机、测试和参考部署；高可用生产应使用托管 MySQL、Redis、RocketMQ 与 S3 兼容对象存储。

### Upgrade

- 候选环境无需数据迁移；使用 `v1.0.2` Release 的 digest-only `production-images.yaml` 与 Chart 包执行 `helm upgrade --install --atomic`。

### Rollback

- `v1.0.0` 与 `v1.0.1` 未产生可部署制品，不能作为制品回滚目标；运行时回滚应使用先前成功 Helm revision，`v1.0.2` 可按固定 digest 重建。

## [1.0.1] - 2026-07-25

### Features

- 保持 `1.0.0` 的完整 OJ 功能、Kubernetes 原生 Sandbox 发现、异步 REST Judge 接入和跨仓不可变组件锁，不引入运行时行为变更。

### Fixes

- 发布工作流改用已在主干 CI 验证的 `actions/setup-python` 不可变 revision，修复首次 `v1.0.0` 发布尝试在 GitHub Actions job setup 阶段无法解析 Action、因而没有生成 Release 或制品的问题。
- 新增跨 `.yml`/`.yaml` 工作流的治理契约：所有外部 GitHub Action 必须固定到完整 40 位 SHA，同一 Action 的大小写与引号写法规范化后只能使用一个已验证 revision。

### Security

- 继续对第三方 GitHub Action 使用 commit pin，并阻止 CI 与 Release 工作流悄然漂移到不同供应链输入。

### Migrations

- 无数据库、对象存储或 Judge schema 迁移；`1.0.0` 的 Flyway V1–V13 与 Judge schema 保持不变。

### Operations

- 保留失败的 annotated `v1.0.0` 标签作为审计记录，不移动或删除公开标签；该标签没有对应 GitHub Release 或部署制品。正式发布从通过完整主干门禁的 `v1.0.1` 开始。

### Known Limitations

- Chart 内有状态依赖仍面向本机、测试和参考部署；高可用生产应使用托管 MySQL、Redis、RocketMQ 与 S3 兼容对象存储。

### Upgrade

- 已部署候选环境无需数据迁移；使用 `v1.0.1` Release 附带的 digest-only `production-images.yaml` 和 Chart 包执行 `helm upgrade --install --atomic`。

### Rollback

- `v1.0.0` 未产生可部署 Release 制品，不应作为回滚目标；使用 `v1.0.1` 的固定 digest 保持可重复部署，应用回滚使用先前成功的 Helm revision。

## [1.0.0] - 2026-07-25

### Features

- 平台源码锁更新到已评审的 Frontend、Backend、Judging Server 与 Sandbox v1 发布候选提交。
- 完成 `config/source-lock.json` 锁定的前端、后端、Judge、Sandbox 与当前 Docs 构建的协调 v1 发布，保留真实 Mailpit 邮件、RocketMQ 主链与外部异步 REST 闭环。
- 三节点产品门禁增加外部 manifest v2 OI `30/100` 部分分与沙箱内 special judge 闭环，并保留原 Backend → RocketMQ → Judging → Sandbox → callback → MySQL 主链。
- Backend 与 Judging 的真实 `TestBundle v2` producer-to-consumer 门禁覆盖 OI 权重和 special checker，不依赖同名 mock fixture。
- Backend OI 内部回调后同时断言公开与管理员排行榜的用户名、总分、分题得分、submission ID 和 achievedAt，形成真实 MySQL 排行榜兼容门禁。
- 增加可选真实公网 HTTPS Webhook 验收：运维 CLI 注册 callback，异步 job 触发 outbox 投递，assertion API 返回原始 body/header 后由门禁重新计算 HMAC-SHA256。

### Fixes

- 修复 API 与浏览器产品 E2E 将 Redis 中 Jackson 序列化的 CAPTCHA 原始 JSON（含引号）直接提交、导致真实管理员登录被拒绝的问题；夹具现在严格解码非空 JSON 字符串并对畸形值失败关闭。
- 产品 E2E 的业务失败诊断只输出类型受限的 `success`、`code` 与 `messagePresent` 元数据，不会打印任意消息内容、响应 `data` 或原始正文。
- TestBundle E2E 改用确定性 ZIP 构建器保留 manifest 声明的目录路径、普通文件类型和固定时间戳，避免通用 ZIP CLI 扁平化 `cases/`、`checker/` 路径后被后端正确拒绝。
- Backend 的共享 S3 client 对第三方对象存储仅启用协议必需的 checksum，避免 AWS SDK 默认 `CRC32`/`aws-chunked` 使 SeaweedFS TestBundle 上传返回 HTTP 500。
- 产品 E2E 按公告管理 API 的 `AdminPage.items` 读取版本，不再套用 MyBatis 分页的 `records` 字段而在真实公告发布前误报空数据。
- 产品 OI 题目的不可变内存限制与复用的 TestBundle v2 fixture 保持一致，并由契约测试锁定时间、内存和总分三项，避免后端正确拒绝不兼容题包。
- 外部异步 REST 门禁的 ACM job 幂等键满足 Judge 的 `16–128` 可见 ASCII 合同，并由回归测试统一扫描所有 E2E 幂等键。
- 平台发布不再假设所有组件与平台共用同一 tag；source lock v2 同时锁定组件 commit 与正式 release tag，下载和校验 Frontend `v1.0.1`、Backend `v1.0.3`、Judge/Sandbox `v1.0.2` 的真实镜像清单。
- Backend 与一次性管理员 bootstrap 的 JDBC 连接同时设置 UTC 解释时区并强制 MySQL 会话使用 UTC，避免 `CURRENT_TIMESTAMP` 与 Java `Instant` 相差八小时后把比赛提交排除在排行榜统计窗口之外。
- Sandbox headless Service DNS 探针改为显式创建 Pod、等待成功终态、读取日志后删除，避免短任务在 `kubectl --attach --rm` 建立连接前已经退出而丢失真实 DNS 结果。
- Sandbox worker 节点标签验收使用 Kubernetes JSONPath 规定的单反斜杠转义，避免正确分布到两个专用节点的 Ready endpoint 被空标签结果误报为失败。
- Kind 本地 Chart 的 Backend CORS allowlist 与浏览器实际入口 `http://coderushoj.local:8080` 保持一致，真实 Chromium 登录不再被 Spring Security 以 `Invalid CORS request` 拒绝；生产域名仍由 production values 独立指定。
- Playwright 通过跨平台 `ControlOrMeta+A` 选中 Monaco 的完整模型，再用真实逐键事件替换为无缩进歧义的单行 C++ 源码并在提交前精确断言编辑器值；这既让编辑器正确执行自动闭合字符的 overtype，也避免 `textarea.fill` 只清除当前输入区而残留模板尾部。
- 平台与四个组件的 release job 补齐 GitHub `attestations: write` 最小权限，避免镜像已推送但 OIDC provenance 因 API `403` 无法持久化。
- 修复 Calico 默认拒绝出站时 Mailpit 无法向 Backend 返回 SMTP greeting、邮件接口最终被 Envoy 504 的问题；仅限本地的 Mailpit 现在只可向可配置的精确 Kind node/Pod CIDR 回包，真实 E2E 在业务请求前验证完整 SMTP `220` 协议握手。
- Backend SMTP 连接、读取与写入增加 3s/5s/5s 默认超时和 Helm 覆盖项，裸机与容器部署同样在启动时校验 `100–60000ms` 整数范围；传输失败会在应用层有界返回，不再依赖网关超时终止请求。
- 固定 digest 的 E2E 网络探针改用 `IfNotPresent`，避免 Kind 导入 manifest-list 后 kubelet 因缺少原始 digest 引用报 `ErrImageNeverPull`；网络受限环境可显式覆盖为同 digest 镜像代理。
- 补齐外部 Judge 启动所需的独立 `coderushoj_judge` DSN、版本化 source/callback key ring Secret 引用，以及主容器前带 advisory lock 的 schema migration init container。
- Judge schema bootstrap 强制通过容器内 `127.0.0.1` TCP 连接 MySQL，避免依赖镜像特定的 Unix socket 路径。
- RocketMQ topic bootstrap 和产品部署都等待 `submission-topic` 返回真实 broker route；Judging legacy consumer 同时具备 fresh-consumer 重试，暂态 route race 不再拖垮外部 REST 健康入口。
- 一次性产品 E2E 在失败时保留未回滚 Pod，通过敏感行过滤后收集 current/previous 容器日志，并让 Judging 终止消息回退到错误日志，缩短远程 CI 排障闭环。
- 产品 E2E 现在比较 `sandbox-workers` DNS A 记录与 Ready EndpointSlice address，并核对 Judging 始终使用 `dns:///...` 且关闭 legacy discovery。

### Security

- Webhook E2E 不放宽公网 HTTPS、SSRF、DNS rebinding 或 redirect 防护；三项 receiver 配置不完整时失败关闭，未配置时不声称该门禁通过。
- 一次性 callback secret、外部 API key、Judge DSN 与 AES key ring 只保存在 Git 忽略的 `0600` 文件或 Kubernetes Secret 引用中。
- 应用默认使用最小权限 `NetworkPolicy`；发布只接受五个组件的精确仓库、tag、revision、digest 与 `linux/amd64`/`linux/arm64` 清单，并用 GitHub OIDC 写入 registry provenance。

### Operations

- 产品 E2E 任一步失败都会额外收集脱敏后的应用 current/previous 日志、NetworkPolicy 与 EndpointSlice，邮件链路故障不再只表现为缺少上下文的网关超时。
- 部署与排障文档增加 Judge 专用 schema、migration init container、key rotation、Service DNS/EndpointSlice 对账及 Webhook receiver contract。
- 发布工作流收集五个组件的 digest JSON，验证真实 registry index，生成 `production-images.yaml`/JSON、生产 Helm render、Kubeconform 结果与 SHA-256 checksums；生产部署不依赖可变镜像 tag。
- Sandbox 由 `sandbox-workers` headless Service 和原生 EndpointSlice 承载，Judge 使用 DNS `round_robin`，RocketMQ NameServer 同样支持 Kubernetes Service DNS。

### Migrations

- Backend 在部署前执行已发布 Flyway V1–V13 migration；Judge 使用独立 schema migration init container 与 checksum 校验，业务 Pod 不隐式修改 schema。
- 从 `0.1.0` 升级前必须先备份 MySQL 与对象存储，并在维护窗口内让 migration Job 成功完成后再滚动应用。

### Known Limitations

- Chart 内有状态依赖仍是适合本机、测试与单节点参考环境的配置；高可用生产应使用托管 MySQL、Redis、RocketMQ 与 S3 兼容对象存储。
- 头像上传仍依赖 Backend 的 RWO PVC，切换到对象存储前 Backend 维持单副本；这不影响题目 TestBundle 与隐藏测试数据的 S3 路径。

### Upgrade

- 先合并四个组件 PR，记录 GitHub merge 后真实的最新 `main` SHA，并在这些提交创建各组件自己的 annotated SemVer tag；等待双架构镜像与 provenance 成功后，把平台 source lock v2 的 `commit` 与 `releaseTag` 更新为四个实际发布输入并重跑最终 E2E，最后才合并和标记平台。
- 使用 GitHub Release 中的 `production-images.yaml` 覆盖生产 values，先升级基础设施与 schema migration，再以 `helm upgrade --install --atomic` 升级应用。

### Rollback

- 使用 Release 附带的 `production-images.yaml` 与 Chart 包可恢复完全相同的五个镜像 digest；应用失败时执行 `helm rollback coderushoj <revision> -n coderushoj`。
- Flyway 与 Judge migration 只允许向前兼容；涉及不可逆数据变化时先恢复升级前备份，再回滚应用和基础设施 release。

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

[Unreleased]: https://github.com/CodeRushOJ/croj-platform/compare/v1.0.2...HEAD
[1.0.2]: https://github.com/CodeRushOJ/croj-platform/releases/tag/v1.0.2
[1.0.1]: https://github.com/CodeRushOJ/croj-platform/tree/v1.0.1
[1.0.0]: https://github.com/CodeRushOJ/croj-platform/tree/v1.0.0
[0.1.0]: https://github.com/CodeRushOJ/croj-platform/releases/tag/v0.1.0
[0.0.1]: https://github.com/orgs/CodeRushOJ/repositories
