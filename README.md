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

## 不可变跨仓库构建

`config/source-lock.json` 是五个开发镜像唯一的源码输入。每项只接受 CodeRushOJ 官方 HTTPS 仓库、40 位小写 Git commit、受约束的构建路径和 Chart 使用的精确 `:dev` 镜像名；branch、tag 和 `latest` 都不能作为跨仓库验收真相。其中 `docs` 锁定到已独立评审的平台基线，只用于构建本地 `:dev` 文档镜像，不作为协调发版文档镜像的输入；正式文档镜像始终由 release workflow 从已签名 tag 的当前 tree 构建。

```bash
make source-verify
make source-checkout
make test-bundle-contract
make images-build
# 仅在目标 Kind 集群已经存在时执行
make images-load
```

源码按 `<组件>/<commit>` 放在 `.workspace/sources/`，不会覆盖开发者已有仓库。`test-bundle-contract` 会让锁定版本的 Backend 真实生成 TestBundle v1 ZIP，再把同一个文件交给锁定版本的 Judging 解析，避免两份手写 fixture 假装联调。`images-build` 会先做幂等 checkout，再用 Buildx 构建五个镜像并写入 OCI source/revision 标签；`images-load` 仅在这两项标签与源码锁完全一致时才载入已有集群，不会创建或启动 Kind 集群。完整更新与故障处理见[快速开始](docs/guide/quickstart.md#不可变源码与开发镜像)。

## 项目状态

- 当前平台版本：`0.1.0`
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

本地密钥位于 `.workspace/secrets/`，不会写入 Git。失败诊断位于 `.workspace/diagnostics/latest/`，以受限权限保存资源状态和事件，默认不抓取应用日志或导出 Kubernetes Secret；共享前仍须按敏感运维数据审阅。
