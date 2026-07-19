# CodeRushOJ Platform

CodeRushOJ Platform 是现有 CodeRushOJ 多仓库项目的部署、集成测试和发版中心。它不替代业务代码：

- `croj-frontend`：Vue 3 用户端、管理端、竞赛与社区界面
- `croj-backend`：Spring Boot 业务 API 与持久化
- `croj-judging-server`：Go 判题编排与 Kubernetes EndpointSlice 发现
- `croj-sandbox`：Go 多语言隔离执行器
- `croj-platform`：本仓库，负责 Docker Compose、Helm、Kind、文档和跨仓库验收

## 快速开始

完整安装、升级、回滚和故障处理请阅读[快速开始](docs/guide/quickstart.md)。
应用服务的 Secret、镜像 digest、存储与 Helm 安装流程见[应用服务部署](docs/guide/application-deployment.md)。

```bash
make bootstrap
make cluster-up
make deploy
make smoke
```

当前平台底座的 MySQL、Redis、RocketMQ、SeaweedFS、Gateway API 和 Envoy Gateway 已在三节点 Kind 集群通过真实冒烟测试。应用服务会继续直接在原仓库中迭代并接入版本化镜像。

应用 Chart 已提供默认关闭的 `croj-backend`、`croj-frontend` 和 `croj-judging-server` Deployment 合同，包括固定 Gateway Service、外部 Secret、资源/探针、安全上下文、PDB、拓扑分散以及 judging EndpointSlice RBAC。backend 与 frontend 的 production Dockerfile、non-root/read-only 合同正在 [backend PR #16](https://github.com/CodeRushOJ/croj-backend/pull/16) 和 [frontend PR #10](https://github.com/CodeRushOJ/croj-frontend/pull/10) 审核；judging 原生健康端点仍在开发。在对应 PR 合并并发布不可变 digest 前，本轮只保证 Helm 离线渲染与 schema/kubeconform 验证，不声称三类镜像已全部可直接上线。

题库导入计划采用 [Free Problem Set](https://github.com/zhblue/freeproblemset/tree/master) 的 LGPL-3.0 XML 交换格式，由 [backend Issue #12](https://github.com/CodeRushOJ/croj-backend/issues/12) 跟踪。当前不要手工直灌数据库；后续实现会提供 dry-run、许可来源 provenance、安全 XML 解析与受校验 bundle 流程。

应用 Chart 已集成 `croj-sandbox` 的 Kubernetes-native Deployment、`croj-sandbox:50051` Service、EndpointSlice 就绪发现、gRPC 探针、专用节点、资源和 NetworkPolicy 声明。开发与 production values 均默认关闭；Kind 的 `hostPID/nsenter/privileged` 风险、kindnet 不执行策略、production cgroup/seccomp 阻塞项见 [Sandbox 部署](docs/guide/sandbox-deployment.md)。

## 项目状态

- 当前平台版本：`0.1.0`
- 历史原型：2025-03-31 至 2025-04-26，详见 [CHANGELOG.md](CHANGELOG.md)
- 目标：完整 v1.0 OJ，包含竞赛、论坛和题解，不包含付费功能
- 参考容量：1,000 在线用户、100 并发提交、20 个并行判题 Job

## 验证

```bash
make validate
make smoke
```

只渲染并验证 sandbox，不启动业务服务：

```bash
helm template coderushoj ./charts/coderushoj \
  --namespace coderushoj --values ./charts/coderushoj/values-kind.yaml \
  --set sandbox.enabled=true \
  | kubeconform -strict -summary -ignore-missing-schemas
```

本地密钥位于 `.workspace/secrets/`，不会写入 Git。失败诊断位于 `.workspace/diagnostics/latest/`，默认不导出 Kubernetes Secret。
