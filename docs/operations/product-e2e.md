# 三节点产品 E2E

`platform-product-e2e` 是 CodeRushOJ v1 的真实跨仓库产品门禁。它不复用开发者本地集群，也不启动常驻的本机产品进程。每次 GitHub Actions run 都创建一个
`croj-product-e2e-<run-id>-<attempt>` 集群，并在 `always()` 清理阶段只接受并删除这个命名格式的精确集群。

## 门禁边界

流水线从 `config/source-lock.json` 检出 frontend、backend、judging-server 和 sandbox 四个外部仓库的不可变提交，并从当前 workflow checkout 构建 Docs。五个镜像都带 OCI source/revision 标签：外部组件对应源码锁，Docs 对应当前 `GITHUB_SHA`。随后镜像被加载到一个控制平面和两个工作节点组成的 Kind 集群。产品 E2E 使用禁用 kindnet 的专用配置，并安装版本与清单 SHA-256 均固定的 Calico；因此后续的 NetworkPolicy 负向探测验证的是实际隔离，不是只检查 YAML。

集群安装 MySQL 8.4、Redis、RocketMQ、SeaweedFS S3、Mailpit、Gateway API、Envoy Gateway 和全部应用工作负载。应用 Chart 的 `adminBootstrap.enabled` 默认是 `false`。CI 临时启用它，让 Backend 正式镜像以 `CROJ_MODE=bootstrap-admin` 运行一次性 Job；用户名、邮箱和密码只从独立 Secret 引用。Job 成功后，Helm 立即移除 Job，Kubernetes Secret 也立即删除。长期 Backend Deployment 从不引用 bootstrap Secret。

随后流水线在 Judging Pod 内执行镜像自带的 `/app/judge-admin`，创建隔离租户和最小 scope API key。一次性明文只写入权限为 `0600` 的 Git 忽略目录，不写日志或 artifact。

## 真实验收流

`tests/e2e/product.sh` 通过 Envoy Gateway 的真实 HTTP 入口执行以下流程：

1. 请求真实验证码 JPEG 和 `Captcha-Key`。测试只在 disposable 集群内部从真实 Redis 读取该 key 对应的值，再调用未修改的生产登录接口。这是明确的白盒 anti-bot 测试夹具，不是生产绕过或 Mock。
2. 通过 `POST /api/problem` 创建私有草稿，从版本管理 API 读取唯一 `DRAFT` 及强 ETag，生成 limits 与题目严格一致、路径位于 `cases/` 的 TestBundle v1 ZIP。测试依次用 `If-Match` 调用元数据读取、multipart 上传和原子发布接口，并以匿名题目详情验证它已公开。
3. 使用锁定 Backend 源码携带的 LGPL/NOTICE FPS 样例做 preflight 和 commit，从题目列表按唯一标题找到题目，再通过管理 API 读取唯一的 `PUBLISHED` 不可变版本。测试不会直读 MySQL。
4. 提交正确 C++ 程序，轮询 Backend 提交详情直到 `ACCEPTED`，由真实 RocketMQ、Judging、TestBundle、headless sandbox Service 和内部回调完成闭环。
5. 创建并公开全局公告、题目关联讨论、绑定题目版本的题解，以及编排了该不可变题目版本的公开比赛。
6. 调用邮件验证码接口，并通过临时、受控的 Mailpit API port-forward 验证 SMTP 投递。port-forward 由脚本 EXIT trap 终止。
7. 上传包含两个测试点的外部 TestBundle，调用异步 `POST /api/v1/judge-jobs` 并轮询终态；结果必须只有一个成功的 compile 状态和两个 `ACCEPTED` case。随后读取 `sandbox-workers` EndpointSlice，要求至少两个 ready endpoint 分布在两个带 sandbox 标签的 worker node，且 Service 必须保持 headless。
8. 检查 Frontend、Backend、Docs、Judge 健康入口，再从未授权 Pod 探测 Backend 和 sandbox Service。Calico 必须阻断两个连接，Gateway 和 Judge 的合法业务流此前必须已成功。

Webhook 不通过放宽 SSRF 或私网地址保护在此集群内回调。它继续由 Judging 仓库的注入 DNS/TLS MySQL integration gate 覆盖。

## 真实浏览器验收

API 流完成数据准备后，`scripts/run-browser-product-e2e.sh` 在同一个 owned
cluster 上启动固定版本 Playwright/Chromium。Chromium 通过 host resolver 将
`coderushoj.local` 指向 runner 回环地址，所有页面、静态资源和 `/api` 请求仍经过
实际 Envoy Gateway、Frontend 和 Backend；测试不启动 `webServer`，也不拦截或
伪造网络响应。

浏览器旅程使用可访问性 role、label 和稳定的可见状态，覆盖：

1. 打开真实登录页，等待 `/api/captcha` 返回 `Captcha-Key`，从 disposable
   集群的真实 Redis 读取该验证码并填入表单，再等待真实 `/api/user/login`
   成功。它复用 API 流已有的 white-box anti-bot 夹具，不注入 token、不改
   localStorage 认证状态，也不跳过路由守卫。
2. 从题目列表搜索 `A+B Problem` 并进入详情，分别查看题目关联讨论和题解。
3. 打开 Monaco 提交代码页，输入正确 C++，调用真实提交接口，并由前端自己的
   轮询逻辑等待终态 `ACCEPTED`；测试代码不使用固定 `sleep`。
4. 从公告列表进入公告详情并验证正文，再从竞赛列表进入公开比赛详情，查看其
   编排的不可变题目。
5. 进入管理工作台，验证“题目导入”的文件入口和“测试包管理”的题目 ID
   入口可发现。题目包发布和 TestBundle 上传/发布的完整写操作继续由前置 API
   流覆盖，避免 UI 验收重复制造题目版本。

Playwright 固定为 lockfile 中的精确版本，Node.js 与 Chromium 安装步骤都有独立
CI timeout，npm 下载缓存按 `package-lock.json` 建键。浏览器项目只运行一个
worker，整个 journey 有全局上限；GitHub Actions 的并发组启用
`cancel-in-progress`，集群删除仍位于 `always()` 路径。

## 失败诊断和安全清理

失败时先调用受限集群诊断采集器：不读取 Secret，不抓取应用日志，不保存验证码、JWT、API key、源代码或隐藏测试内容。集群诊断 artifact 只包含节点/Pod 元数据、事件、describe 和 Helm 状态。浏览器失败另保留 Playwright `trace`、`screenshot`、`video` 和 HTML report 到 `artifacts/product-e2e-browser/`，便于还原真实页面和网络时序。浏览器证据可能包含本次 disposable run 的页面与请求数据，应按敏感 CI 证据限制访问；CI 在上传前删除 owned cluster，使临时管理员凭据和会话失效。两类 artifact 都保留 14 天。

产品流的请求/响应临时目录与 Mailpit port-forward 在脚本退出时删除。浏览器 runner
只读取权限为 `0600` 的 bootstrap 用户名和密码文件，不复制它们到平台日志。

清理脚本拒绝 `coderushoj`、空字符串和任意非 `croj-product-e2e-<数字>-<数字>` 名称。即使 checkout、构建、集群创建、部署或验收失败，`always()` 步骤也只按本次 run 生成的精确名称调用 Kind。

## 本地静态验证

完整门禁会构建四个锁定组件镜像和当前平台 checkout 的 Docs 镜像并创建集群，不属于普通本地 lint。提交前执行：

```bash
actionlint
shellcheck scripts/*.sh tests/e2e/*.sh
node --check tests/e2e/browser/playwright.config.js
node --check tests/e2e/browser/product.spec.js
helm lint charts/coderushoj
helm lint charts/coderushoj-infra
python3 -m unittest tests.contract.test_product_e2e_contract -v
```

如需手工复现完整流程，必须显式使用符合所有权格式的独立集群名，并确认没有同名集群。不要把示例名改成共享的 `coderushoj`，也不要跳过清理。
