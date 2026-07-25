# 版本与变更

平台使用 SemVer；每次协调发版会固定前端、后端、判题服务、沙箱、文档和 Helm Chart 的版本或镜像 digest。

完整变更记录位于仓库根目录的 [`CHANGELOG.md`](https://github.com/CodeRushOJ/croj-platform/blob/main/CHANGELOG.md)。其中 `0.0.1` 是根据原仓库 Git 历史重建的 2025 原型里程碑，不冒充当时存在的统一标签；`0.1.0` 是平台底座版本，`1.0.0` 是当前完整 OJ 协调发布。

## 发布说明必填项

- Features
- Fixes
- Security
- Migrations
- Operations
- Known limitations
- Upgrade
- Rollback

正式 annotated 标签只能在 `make validate`、干净集群部署、`make smoke`、升级/回滚和备份恢复演练全部通过后创建。部署清单禁止使用 `latest`，GitHub Release 会附带 digest-only `production-images.yaml`/JSON、生产 render 和 checksums。

详细门禁、必需的 release note 章节和 annotated 标签命令见[发版流程](/project/release-process)，跨仓库交付顺序见[里程碑与 Issue 管理](/project/milestones)。
