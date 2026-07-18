# 项目历史

CodeRushOJ 不是从平台仓库建立之日才开始。历史原型在 2025 年 3 月 31 日至 4 月 26 日集中完成，已有成果分布在四个原代码仓库和组织主页中。

## 2025 历史原型

- 前端完成认证、CAPTCHA、邮箱验证、路由守卫、国际化错误、管理界面、资料/头像、设置、Monaco 编辑器和提交页面。
- 后端完成用户、Spring Security、JWT、CORS、验证码、邮箱验证、头像、题目、提交、MySQL 与 RocketMQ 初始接入。
- 判题服务建立 Go 工程框架、任务处理和结果更新边界。
- 沙箱建立多语言执行、超时与内存监控、结果模型、gRPC、Dockerfile，以及 seccomp/cgroups/ZooKeeper 的早期实现。
- 组织文档提出了 Vue、Spring、Go、MySQL、Redis、RocketMQ、gRPC、Docker 和 Kubernetes 的分布式 OJ 愿景。

这些贡献构成当前工作的基础。与此同时，原型仍存在硬编码配置、敏感信息、模拟判题、隔离实现不完整、测试不足和无法一键部署等问题。

## 2026 平台化

当前迭代不重写原项目，而是逐仓库修复并补齐：平台仓库负责可重复部署、集成测试、文档和协调发版；业务能力继续直接落入原前端、后端、判题和沙箱仓库。ZooKeeper 被 Kubernetes Service/Endpoint 与 Job 调度替代，论坛和题解进入 v1 范围，付费功能暂不实现。

逐条历史记录和已知限制请查看 [`CHANGELOG.md`](https://github.com/CodeRushOJ/croj-platform/blob/main/CHANGELOG.md)。
