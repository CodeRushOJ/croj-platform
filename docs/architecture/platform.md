# 平台架构

CodeRushOJ 保留 Vue 3、Spring Boot、Go、RocketMQ 与 gRPC 的已有技术积累，同时将无法跑通的发现与执行边界调整为 Kubernetes 原生模型。

```mermaid
flowchart LR
  U["用户 / 管理员"] --> EG["Envoy Gateway"]
  EG --> FE["Vue 前端"]
  EG --> API["Spring 模块化后端"]
  EG --> DOCS["VitePress 文档"]
  API --> MYSQL[("MySQL 8.4\n权威数据")]
  API --> REDIS[("Redis 8.6\n可重建缓存")]
  API --> MQ["RocketMQ 5.5"]
  API --> S3["SeaweedFS S3"]
  MQ --> JUDGE["Go 判题编排器"]
  JUDGE --> KAPI["Kubernetes API"]
  KAPI --> JOB1["临时 Judge Job"]
  KAPI --> JOBN["临时 Judge Job"]
  JOB1 --> S3
  JOBN --> S3
```

## 仓库边界

| 仓库 | 所有权 |
| --- | --- |
| `croj-frontend` | 用户、竞赛、论坛、题解和管理界面 |
| `croj-backend` | 业务规则、MySQL 事务、RBAC、Outbox 与 API |
| `croj-judging-server` | 消息消费、幂等领取、Job 创建、结果归并 |
| `croj-sandbox` | 编译、受限执行、用例结果与判题协议 |
| `croj-platform` | 部署、集成测试、运维文档和协调发版 |

## 提交与判题时序

```mermaid
sequenceDiagram
  actor User as 用户
  participant API as 后端
  participant DB as MySQL
  participant MQ as RocketMQ
  participant Judge as 判题编排器
  participant K8s as Kubernetes API
  participant Job as Sandbox Job
  participant S3 as SeaweedFS

  User->>API: 提交源码
  API->>DB: 提交记录 + Outbox（同一事务）
  API-->>User: submissionId / PENDING
  API->>MQ: 发布版本化判题命令
  MQ->>Judge: 至少一次投递
  Judge->>DB: 条件领取 attempt
  Judge->>K8s: 创建带 deadline 的 Job
  Job->>S3: 读取不可变测试包
  Job-->>Judge: 有界结构化结果
  Judge->>DB: CAS 写入终态与计分
  API-->>User: 查询最终结果
```

## Kubernetes Service/Endpoint 发现

判题服务不再依赖 ZooKeeper。长期运行服务通过 Kubernetes Service 和 EndpointSlice 发现与负载均衡；沙箱计算由 Kubernetes Job 表达，调度器把任务放到带 `judge-worker` 标签的节点。这样服务健康、滚动更新、容量限制和故障重试都由同一控制面观察。

## 数据职责

- MySQL 是用户、题目、提交、竞赛、社区内容和审计记录的唯一权威来源。
- Redis 只保存限流、短期验证、热点榜单与可重建会话状态。
- RocketMQ 只承载标识符和版本元数据，不传递隐藏测试数据。
- SeaweedFS 保存不可变测试包、头像和社区附件；应用只依赖 S3 协议，便于替换为云对象存储。

## 信任边界

后端和判题编排器属于可信控制面；参赛源码与沙箱 Job 属于不可信计算面。目标 Job 采用非 root、只读根文件系统、能力删除、禁止提权、RuntimeDefault seccomp、资源配额、截止时间与默认无网络策略。测试数据凭据只提供给可信初始化步骤，不挂载到参赛程序容器。
