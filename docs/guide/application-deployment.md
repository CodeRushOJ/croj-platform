# 应用服务 Kubernetes 部署

应用 Chart 为 `croj-backend`、`croj-frontend` 和 `croj-judging-server` 提供可审查的 Deployment 合同。三个组件默认都是 `enabled=false`，本页所有 `helm template` 命令只离线渲染，不会启动 Pod；只有最后的 `helm upgrade --install` 会修改集群。

## 当前镜像门禁

Chart 清单已经通过 schema、合同测试和 kubeconform，但组件镜像状态必须如实区分：

- backend production Dockerfile、non-root/read-only 镜像与 Actuator probe 已在 [croj-backend PR #16](https://github.com/CodeRushOJ/croj-backend/pull/16) 实现，并继续由 [croj-backend/issues/10](https://github.com/CodeRushOJ/croj-backend/issues/10) 跟踪至合并发布；
- frontend unprivileged nginx、SPA fallback、`/healthz` 与只读根文件系统合同已在 [croj-frontend PR #10](https://github.com/CodeRushOJ/croj-frontend/pull/10) 实现，并继续由 [croj-frontend/issues/5](https://github.com/CodeRushOJ/croj-frontend/issues/5) 跟踪至合并发布；
- judging 已有 distroless/non-root 镜像，但尚无可探测的 HTTP/exec/TCP 健康端点，Chart 默认不伪造 probe，后续由 [croj-judging-server/issues/7](https://github.com/CodeRushOJ/croj-judging-server/issues/7) 提供原生健康接口；
- backend 文件上传迁移到 S3/MinIO 的长期方案由 [croj-backend/issues/11](https://github.com/CodeRushOJ/croj-backend/issues/11) 跟踪。

在这些镜像 Issue 合并并发布版本/digest 前，只执行 render、lint 和 kubeconform，不要执行安装命令。

## 外部 Secret

Helm 不创建凭据，也不通过 `lookup` 读取集群，因此离线渲染是确定性的。启用 backend 或 judging 时，`backend.existingSecret.name` 与 `judgingServer.existingSecret.name` 必填；每个 key mapping 也受 schema 约束。两端固定从同一个 `JUDGE_RESULT_SERVICE_TOKEN` key 读取回调令牌。

以下命令从终端静默读取已有凭据，并在本机生成 JWT/回调随机值。值不会写入仓库或显示到屏幕；示例 Secret 名可按环境修改：

```bash
read -rsp 'MySQL application password: ' database_password; printf '\n'
read -rsp 'Redis password: ' redis_password; printf '\n'
read -rsp 'RocketMQ access key: ' rocketmq_access_key; printf '\n'
read -rsp 'RocketMQ secret key: ' rocketmq_secret_key; printf '\n'
read -rsp 'SMTP username: ' smtp_username; printf '\n'
read -rsp 'SMTP password: ' smtp_password; printf '\n'
read -rsp 'S3 access key: ' s3_access_key; printf '\n'
read -rsp 'S3 secret key: ' s3_secret_key; printf '\n'
jwt_secret="$(openssl rand -base64 48 | tr -d '\n')"
judge_result_token="$(openssl rand -base64 48 | tr -d '\n')"

kubectl create secret generic coderushoj-application \
  --namespace coderushoj \
  --from-literal=DATABASE_USERNAME=coderushoj \
  --from-literal=DATABASE_PASSWORD="$database_password" \
  --from-literal=REDIS_PASSWORD="$redis_password" \
  --from-literal=ROCKETMQ_ACCESS_KEY="$rocketmq_access_key" \
  --from-literal=ROCKETMQ_SECRET_KEY="$rocketmq_secret_key" \
  --from-literal=JWT_SECRET="$jwt_secret" \
  --from-literal=SMTP_USERNAME="$smtp_username" \
  --from-literal=SMTP_PASSWORD="$smtp_password" \
  --from-literal=OBJECT_STORAGE_ACCESS_KEY="$s3_access_key" \
  --from-literal=OBJECT_STORAGE_SECRET_KEY="$s3_secret_key" \
  --from-literal=JUDGE_RESULT_SERVICE_TOKEN="$judge_result_token" \
  --dry-run=client -o yaml | kubectl apply -f -

unset database_password redis_password rocketmq_access_key rocketmq_secret_key
unset smtp_username smtp_password s3_access_key s3_secret_key jwt_secret judge_result_token
```

安装前验证 Secret 存在且 key 非空。脚本只打印 Secret 名、key 名与数量，不读取或打印明文：

```bash
./scripts/preflight-application-secrets.sh \
  --namespace coderushoj \
  --secret coderushoj-application \
  --required-key DATABASE_USERNAME \
  --required-key DATABASE_PASSWORD \
  --required-key REDIS_PASSWORD \
  --required-key ROCKETMQ_ACCESS_KEY \
  --required-key ROCKETMQ_SECRET_KEY \
  --required-key JWT_SECRET \
  --required-key SMTP_USERNAME \
  --required-key SMTP_PASSWORD \
  --required-key OBJECT_STORAGE_ACCESS_KEY \
  --required-key OBJECT_STORAGE_SECRET_KEY \
  --required-key JUDGE_RESULT_SERVICE_TOKEN
```

## 配置与服务发现

backend 与 judging 使用同一版本化消息主题 `coderushoj.submission.v1`；judging consumer group 是 `coderushoj-judging-v1`。judging 固定使用：

backend Deployment 显式设置 `SPRING_PROFILES_ACTIVE=prod`，确保优雅停机与生产日志配置确实生效，而不是仅把 `application-prod.yml` 留在镜像中却从未激活。

```text
BACKEND_INTERNAL_URL=http://croj-backend:7999/api
SANDBOX_SERVICE=croj-sandbox
SANDBOX_PORT_NAME=grpc
JUDGE_RESULT_CALLBACK_TIMEOUT=10s
```

它通过 namespace 级 ServiceAccount/Role 列出 EndpointSlice，不能读取 Secret、Pod、Node 或集群级资源。backend Service 必须保持 `croj-backend:7999`，frontend Service 必须保持 `croj-frontend:80`，否则 values schema 会拒绝破坏 Gateway route 的配置。

hidden bundle 的 `OBJECT_STORAGE_ENDPOINT/BUCKET/REGION/USE_TLS` 是普通配置，`OBJECT_STORAGE_ACCESS_KEY/SECRET_KEY` 仍只来自外部 Secret。`OBJECT_STORAGE_ENDPOINT` 必须是 `host[:port]`（默认 `coderushoj-infra-seaweedfs.coderushoj.svc:8333`），不能包含 `http://` 或 `https://`；协议只由 `OBJECT_STORAGE_USE_TLS` 决定。judging 将 `/tmp` 挂成默认 `2Gi`、schema 最大允许 `4Gi` 的 `emptyDir`；缓存只是可删除、可重建的副本，S3/MinIO 才是 bundle 的权威真相源。

Chart 将 judging-server 已冻结的全部安全边界显式注入 Pod，整数始终渲染为十进制字符串，避免 Helm 大整数科学计数法破坏 Go 环境变量解析：

| 环境变量 | 默认值 | 约束用途 |
| --- | ---: | --- |
| `JUDGE_BUNDLE_CACHE_DIR` | `/tmp/croj-bundles` | 专用 `emptyDir` 缓存目录 |
| `JUDGE_BUNDLE_CACHE_MAX_BYTES` | `2147483648` | 进程缓存最大 2 GiB |
| `JUDGE_BUNDLE_CACHE_TTL` | `24h` | 已下载 bundle 的最长复用时间 |
| `JUDGE_BUNDLE_MAX_OBJECT_BYTES` | `536870912` | 对象下载最大 512 MiB |
| `JUDGE_BUNDLE_MAX_FILES` | `20001` | ZIP 文件数量上限 |
| `JUDGE_BUNDLE_MAX_MANIFEST_BYTES` | `1048576` | manifest 最大 1 MiB |
| `JUDGE_BUNDLE_MAX_CASE_BYTES` | `67108864` | 单个 case 文件最大 64 MiB |
| `JUDGE_BUNDLE_MAX_UNCOMPRESSED_BYTES` | `536870912` | 总解压体积最大 512 MiB |
| `JUDGE_BUNDLE_MAX_COMPRESSION_RATIO` | `200` | zip bomb 压缩比上限 |
| `JUDGE_BUNDLE_MAX_INFRA_ATTEMPTS` | `3` | 单 case 更换 sandbox endpoint 的次数上限 |

除缓存 TTL 外的数值均受 values schema 正整数约束；TTL 使用 Go duration 形式。生产覆盖这些参数时，应同时满足 `JUDGE_BUNDLE_CACHE_MAX_BYTES` 不大于 `/tmp` `emptyDir` 的 `bundleCacheSizeLimit`，并为运行时临时文件保留余量。

## 上传存储

默认开发 profile 使用 `backend.storage.type=emptyDir` 挂载 `/app/uploads`；Pod 重启会丢数据，多个副本也不共享，因此只能用于可丢弃数据的开发渲染。

`values-production.yaml` 自动切换到 `existingClaim`，启用 backend 时必须设置 `backend.storage.existingClaim`。该 PVC 必须由集群管理员预先创建，并提供适合多副本的 `ReadWriteMany` 能力：

```bash
kubectl get pvc coderushoj-uploads -n coderushoj \
  -o jsonpath='{.status.phase}{" accessModes="}{.spec.accessModes}{"\n"}'
```

输出必须为 `Bound` 且包含 `ReadWriteMany`，并同时核对存储后端文档。Chart 不自动创建 PVC，避免猜测 StorageClass、容量、备份与回收策略。

## 离线渲染

开发配置允许可变 tag，仅用于清单联调：

```bash
helm template coderushoj ./charts/coderushoj \
  --namespace coderushoj \
  --set backend.enabled=true \
  --set frontend.enabled=true \
  --set judgingServer.enabled=true \
  --set backend.existingSecret.name=coderushoj-application \
  --set judgingServer.existingSecret.name=coderushoj-application \
  | kubeconform -strict -summary -ignore-missing-schemas
```

Production profile 对三个镜像都强制 digest，并对 backend 强制 existing RWX claim：

```bash
helm template coderushoj ./charts/coderushoj \
  --namespace coderushoj \
  --values ./charts/coderushoj/values-production.yaml \
  --set backend.enabled=true \
  --set frontend.enabled=true \
  --set judgingServer.enabled=true \
  --set backend.existingSecret.name=coderushoj-application \
  --set judgingServer.existingSecret.name=coderushoj-application \
  --set backend.storage.existingClaim=coderushoj-uploads \
  --set-string backend.image.digest=sha256:BACKEND_DIGEST \
  --set-string frontend.image.digest=sha256:FRONTEND_DIGEST \
  --set-string judgingServer.image.digest=sha256:JUDGING_DIGEST
```

`BACKEND_DIGEST` 等标记必须替换为 registry 返回的 64 位小写 sha256；占位符本身会被 schema 拒绝。`backend.image.digest`、`frontend.image.digest` 和 `judgingServer.image.digest` 任一缺失都会 fail closed。

## 安装、验证与回滚

只有镜像阻塞 Issue 已解决、Secret/PVC 预检通过并取得真实 digest 后才安装：

```bash
case "$(helm version --template '{{.Version}}')" in
  v3.*) application_rollback_flag=--atomic ;;
  v4.*) application_rollback_flag=--rollback-on-failure ;;
  *) echo 'unsupported Helm version' >&2; exit 1 ;;
esac

helm upgrade --install coderushoj ./charts/coderushoj \
  --namespace coderushoj --create-namespace \
  --values ./charts/coderushoj/values-production.yaml \
  --values ./application-production-values.yaml \
  "$application_rollback_flag" --wait --timeout 10m
```

`application-production-values.yaml` 只保存 enabled、Secret 名、PVC 名和 image digest，不保存 Secret 值。验证：

```bash
kubectl get deploy,svc,pdb -n coderushoj \
  -l app.kubernetes.io/instance=coderushoj
kubectl get endpointslice -n coderushoj \
  -l kubernetes.io/service-name=croj-backend
kubectl rollout status deployment/croj-backend -n coderushoj --timeout=5m
kubectl rollout status deployment/croj-frontend -n coderushoj --timeout=5m
kubectl rollout status deployment/croj-judging-server -n coderushoj --timeout=5m
```

回滚不会恢复上传文件或数据库：

```bash
helm history coderushoj -n coderushoj
helm rollback coderushoj PREVIOUS_REVISION -n coderushoj --wait
```

## NetworkPolicy 边界

`networkPolicy.enabled=false` 是默认值。只有安装并验证支持策略的 CNI 后才显式开启。Kind 默认 kindnet 不执行 NetworkPolicy；即使 API 中存在策略对象，也不能据此宣称 frontend/backend/judging/sandbox 已完成网络隔离。

开启后，Gateway ingress 通过 `envoy-gateway-system` namespace 与 Envoy owning-gateway Pod label 双重选择；应用到 MySQL、Redis、RocketMQ NameServer `9876`、Broker `10911/10909`（兼容 Java VIP channel）、SeaweedFS、backend 与 sandbox 的流量通过同 namespace workload label 选择，DNS 单独限制到 `kube-system` CoreDNS。标准 NetworkPolicy 不能按 FQDN 限制外部 SMTP 或 Kubernetes API，因此 backend/judging 开启策略时必须分别设置 CIDR，否则 Helm 拒绝渲染：

```bash
kubernetes_api_ip="$(kubectl get service kubernetes -n default -o jsonpath='{.spec.clusterIP}')"
helm template coderushoj ./charts/coderushoj \
  --namespace coderushoj \
  --set backend.enabled=true \
  --set judgingServer.enabled=true \
  --set backend.existingSecret.name=coderushoj-application \
  --set judgingServer.existingSecret.name=coderushoj-application \
  --set networkPolicy.enabled=true \
  --set networkPolicy.external.smtpCidrs[0]=SMTP_IPV4_CIDR \
  --set "networkPolicy.external.kubernetesApiCidrs[0]=${kubernetes_api_ip}/32"
```

`SMTP_IPV4_CIDR` 必须由邮件服务商提供并经过变更管理；不要填 `0.0.0.0/0`。Service IP 的 NetworkPolicy 行为依赖 CNI 在 DNAT 前后的实现，production 还必须用允许/拒绝双向探针验证，不能只凭 render 结果上线。

## 题库导入

[Free Problem Set](https://github.com/zhblue/freeproblemset/tree/master)（FPS）是 LGPL-3.0 的 XML 题目交换格式。CodeRushOJ 的 FPS 解析适配器由 [croj-backend#20](https://github.com/CodeRushOJ/croj-backend/pull/20) 交付，兼容 1.1/1.2/1.4，并以固定上游提交的真实题包验证官方 PUBLIC DOCTYPE、分组测试点和 fail-closed 实体处理；测试包的私有 S3/MinIO 存储及发布门禁由 [croj-backend#22](https://github.com/CodeRushOJ/croj-backend/pull/22) 交付。导入必须先预检并由管理员确认，记录许可、来源 URL、解析器版本和原包 SHA-256；不要手工直灌数据库，也不要绕过统一题目发布门禁。
