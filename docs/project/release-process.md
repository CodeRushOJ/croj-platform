# 发版流程

CodeRushOJ 遵循 [SemVer](https://semver.org/) 和协调发布模型。各服务独立测试、生成不可变 commit-SHA 镜像；平台的 `VERSION`、Helm Chart 与兼容矩阵定义一次可部署的系统版本。

## 版本规则

- `MAJOR`：不兼容的 API、数据或部署契约变化。
- `MINOR`：保持兼容的新功能。
- `PATCH`：保持兼容的修复、安全加固或运维改进。
- 正式标签必须是签名的 `v<VERSION>`，标签版本、两个 Chart 版本和 `CHANGELOG.md` 条目必须一致。
- 禁止部署 `latest`；主分支镜像至少发布 `sha-<git-sha>`，协调版本另发布不可变版本标签。

## Release note 必需章节

每个协调版本都必须在 `CHANGELOG.md` 和 GitHub Release 中覆盖以下章节；没有内容时明确写“None”。

- **Features**：用户和管理员可见的新能力。
- **Fixes**：缺陷、回归及对应测试。
- **Security**：安全属性变化；未公开漏洞遵循协调披露。
- **Migrations**：DDL、数据回填、配置和兼容窗口。
- **Operations**：资源、监控、告警和 runbook 变化。
- **Known Limitations**：仍未完成或需要规避的限制。
- **Upgrade**：备份、镜像/Chart 升级顺序和验证命令。
- **Rollback**：可回退边界、命令、数据兼容性和恢复验证。

## 发布检查单

1. 冻结目标 Issue，确认 PR 均有 release note 分类、测试证据和迁移/回滚说明。
2. 从空环境安装，并运行平台 smoke 与完整 OJ E2E；保留失败 Pod、日志、截图和测试报告。
3. 从上一支持版本升级，验证 Flyway、RocketMQ 消费、对象版本、判题任务和排行榜。
4. 完成 MySQL 与对象存储备份恢复演练，以 `SELECT 1`、业务抽样和隐藏测试对象校验恢复结果。
5. 更新 `VERSION`、Chart 版本、兼容镜像、`CHANGELOG.md` 和文档。
6. 创建并验证签名标签：`git tag -s v$(cat VERSION) -m "CodeRushOJ v$(cat VERSION)"`。
7. CI 构建文档镜像、打包 Chart、生成 SHA-256 校验值并发布 GitHub Release。
8. 部署版本标签，观察 API 错误率、队列滞后、Job 失败和数据库状态；满足观察窗口后关闭发版 Issue。

## 紧急修复

从受支持标签创建修复分支，只包含最小修复、回归测试和必要文档。若 DDL 不可向后兼容，则不得宣称可直接 Rollback；必须提供前滚修复或经过验证的数据恢复步骤。
