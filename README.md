# CodeRushOJ Platform

CodeRushOJ Platform 是现有 CodeRushOJ 多仓库项目的部署、集成测试和发版中心。它不替代业务代码：

- `croj-frontend`：Vue 3 用户端、管理端、竞赛与社区界面
- `croj-backend`：Spring Boot 业务 API 与持久化
- `croj-judging-server`：Go 异步 REST/RocketMQ 判题编排、持久化任务与回调
- `croj-sandbox`：Go 多语言隔离执行器
- `croj-platform`：本仓库，负责 Docker Compose、Helm、Kind、文档和跨仓库验收

## 快速开始

完整安装、升级、回滚和故障处理请阅读[快速开始](docs/guide/quickstart.md)。

```bash
make bootstrap
make cluster-up
make deploy
make smoke
```

当前平台底座的 MySQL、Redis、RocketMQ、SeaweedFS、Gateway API 和 Envoy Gateway 已在三节点 Kind 集群通过真实冒烟测试。本地 profile 还提供不出网的 Mailpit 邮件捕获器。应用 Chart 已覆盖前端、后端、文档、异步 REST 判题服务和两副本沙箱；发布环境必须传入 CI 产出的镜像 digest。

全新数据库没有硬编码管理员密码。应用镜像部署后运行 `scripts/bootstrap-admin.sh`，会通过独立、可删除的 Kubernetes Secret 执行一次性 Job；本地用户名为 `admin`，随机密码只保存在 `.workspace/secrets/bootstrap-admin-password`，不会输出到日志或注入长期 Backend Deployment。

## 项目状态

- 当前平台版本：`0.1.0`
- 历史原型：2025-03-31 至 2025-04-26，详见 [CHANGELOG.md](CHANGELOG.md)
- 目标：完整 v1.0 OJ，包含竞赛、论坛和题解，不包含付费功能
- 参考容量：1,000 在线用户、100 并发提交、20 个并行沙箱执行

## 验证

```bash
make validate
make smoke
```

本地密钥位于 `.workspace/secrets/`，不会写入 Git。失败诊断位于 `.workspace/diagnostics/latest/`，默认不导出 Kubernetes Secret。
