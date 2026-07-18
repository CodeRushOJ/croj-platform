---
layout: home

hero:
  name: CodeRushOJ
  text: 从提交到判题，每一步都可验证
  tagline: Vue · Spring Boot · Go · RocketMQ · Kubernetes-native Sandbox
  actions:
    - theme: brand
      text: 本地部署
      link: /guide/quickstart
    - theme: alt
      text: 查看架构
      link: /architecture/platform

features:
  - icon: ⚡
    title: 异步判题链路
    details: MySQL 事务状态、RocketMQ 事件与幂等判题编排，目标支持 100 并发提交。
  - icon: 🛡️
    title: Kubernetes 原生沙箱
    details: Service/Endpoint 发现、临时 Job、工作节点隔离与 20 个并行判题任务。
  - icon: 🧭
    title: 完整 OJ 体验
    details: 题目、提交、竞赛、排名、论坛和题解统一设计；付费功能不在 v1 范围内。
  - icon: 📦
    title: 两条部署路径
    details: Docker Compose 面向单机开发，Helm + Kubernetes 是标准参考部署。
  - icon: 🧪
    title: 测试即产品
    details: 前端、后端、判题、沙箱、基础设施和文档均沉淀可重复执行的测试。
  - icon: 📖
    title: 可运营可回滚
    details: 安装、升级、回滚、诊断、备份、恢复与发版日志均由仓库管理。
---

## 当前状态

平台 `0.1.0` 已完成三节点 Kind、Gateway API、Envoy Gateway、MySQL、Redis、RocketMQ、SeaweedFS 和真实冒烟测试。业务服务继续在原有四个代码仓库内迭代，不会另建替代实现。

::: warning 阶段边界
Docker Compose 当前可直接启动平台依赖；完整前端、后端与判题镜像会在对应原仓库完成测试和镜像流水线后接入。Kubernetes 路由与基础设施已实际部署验证。
:::
