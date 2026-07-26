# 发版流程

CodeRushOJ 遵循 [SemVer](https://semver.org/) 和协调发布模型。各服务独立测试、生成不可变 commit-SHA 镜像；平台的 `VERSION`、Helm Chart 与兼容矩阵定义一次可部署的系统版本。

## 版本规则

- `MAJOR`：不兼容的 API、数据或部署契约变化。
- `MINOR`：保持兼容的新功能。
- `PATCH`：保持兼容的修复、安全加固或运维改进。
- 正式标签必须是最新 `main` 提交上的 annotated `v<VERSION>`；标签版本、两个 Chart 版本和 `CHANGELOG.md` 条目必须一致。发布不要求把维护者私钥交给 CI。
- 禁止部署 `latest`；主分支镜像至少发布 `sha-<git-sha>`，协调版本另发布不可变版本标签。
- 生产部署只使用 `repository@sha256:...`；版本标签用于发现，digest 才是运行时身份。

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
5. 先合并 Frontend、Backend、Judging Server 与 Sandbox 的候选 PR，并记录四个仓库合并后真实的最新 `main` SHA。禁止把 PR head SHA 当成发布 revision；GitHub merge commit 会产生新的提交。
6. 在上述四个真实 `main` SHA 上创建各组件自己的 annotated SemVer tag；组件 tag 不要求与平台版本相同。等待各仓双架构镜像、SBOM、OIDC provenance 和 digest JSON 全部成功。
7. 把平台 `config/source-lock.json` v3 的 `commit` 更新到四个 tag 实际指向的 40 位 SHA，把 `releaseTag` 更新为对应组件的精确正式 tag，并记录组件专属 `releaseManifestAsset` 与发布资产字节的 64 位小写 `releaseManifestSha256`；同时更新 `VERSION`、Chart、`CHANGELOG.md` 和文档，再用这组最终发布输入重跑完整产品 E2E。候选分支 SHA、tag target、资产 checksum 或镜像 manifest revision 任一不一致时必须 fail closed。
8. 合并平台 PR 后，只在平台最新 `main` 创建 annotated tag。CI 构建双架构 Docs 镜像，收集四个组件的 digest JSON，并严格核对仓库、tag、source lock revision、digest、`linux/amd64`/`linux/arm64` registry index。
9. CI 在首次 registry 写入前用 Actions token 查询并下载同 tag Release，并在所有状态重新下载四组件公开 manifest、按 source lock hash-before-parse 校验和生成可信 preflight。没有 Release 时才生成 `production-images.yaml`/JSON、digest-only render、Chart、release notes 与 SHA-256 checksums，并创建完整 verified draft；已有 draft 时严格验证 bot 作者、精确资产集合、checksums、版本、平台 SHA、source lock 组件 revision/tag，把恢复清单的四组件对象与 preflight 完全比较，核对五镜像 repository/digest/platform 和当前 Chart 内容，并从当前 CHANGELOG/Chart 重建比较 notes/render，复用其中的 Docs digest，不得删除、编辑或替换资产；已有 published Release 只有在相同验证通过且 `immutable=true` 时才视为幂等完成。
10. CI 在 verified draft 存在后才提升 Docs SemVer 镜像 tag。workflow 执行写前检查，仅在未观察到 tag 时创建，已存在且 digest 相同时继续，不同时失败，并在创建后复核；GHCR API 不提供原子 create-if-absent，因此外部 package 管理员的并发写入必须通过最小发布权限和运维互斥避免。提升验证成功后才发布 draft，并再次验证 immutable Release；部署真相只来自该 Release 的 digest-only 资产。
11. 使用 Release 的 `production-images.yaml` 部署，观察 API 错误率、队列滞后、Job 失败和数据库状态；满足观察窗口后关闭发版 Issue。

当前 source lock v3 固定的组件资产为：

| 组件 | Release manifest 资产 | 固定 SHA-256 |
| --- | --- | --- |
| Frontend | `image-artifact.json` | `5af165529a4b8882dc492acf9886c424cf2aaebd43a7a77ea3c76018674d9a17` |
| Backend | `backend-image.json` | `3df4a8d593802e4fbac26f877173539cbb55e8b59aaac15ea7d2a5afbd7468db` |
| Judging Server | `judging-server-image.json` | `813d063d844fb0e19554fa15589d24c6052dbd85aa3cafc1dfdb4b5af2c71fbd` |
| Sandbox | `sandbox-image.json` | `3b729035b7a7760ed25d86905c4db2da76bb21886df2798b0db0f4cdeb14e0ef` |

## 紧急修复

从受支持标签创建修复分支，只包含最小修复、回归测试和必要文档。若 DDL 不可向后兼容，则不得宣称可直接 Rollback；必须提供前滚修复或经过验证的数据恢复步骤。
