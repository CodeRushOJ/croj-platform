# CodeRushOJ Platform Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a versioned, testable platform repository that can bootstrap the CodeRushOJ repositories, create a three-node local Kubernetes cluster, deploy pinned infrastructure, expose it through Gateway API, and produce repeatable CI and release artifacts.

**Architecture:** `croj-platform` owns a Docker Compose developer path, local Kubernetes automation, an umbrella Helm chart, Gateway API routes, seed data, smoke tests, documentation, and coordinated release metadata. Service repositories remain independent and are cloned into an ignored `.workspace/repos` directory. Local defaults fit the available 8-core/16-GiB Apple Silicon host; production values remain horizontally scalable.

**Tech Stack:** macOS/Homebrew, Colima, Docker CLI with Compose and Buildx, Kubernetes client 1.36.2, Kind node 1.36.1, Helm 4, Gateway API 1.5.1, Envoy Gateway 1.8.2, MySQL 8.4.10, Redis 8.6.2, RocketMQ 5.5.0, SeaweedFS 4.39, Python 3 standard-library tests, GitHub Actions.

---

## File Map

- `.github/`: platform CI, release workflow, pull-request and issue templates.
- `.workspace/`: ignored local clones, generated secrets, kubeconfig, and diagnostics.
- `charts/coderushoj/`: umbrella application chart and application-facing routes.
- `charts/coderushoj-infra/`: local infrastructure resources with pinned images and constrained defaults.
- `compose.yaml`: pinned single-host stateful dependency stack for development.
- `config/kind/cluster.yaml`: three-node Kind topology and host port mappings.
- `config/versions.env`: reviewed component versions used by scripts and CI.
- `docs/`: VitePress documentation plus architecture, deployment, operations, and release notes.
- `scripts/`: idempotent bootstrap, cluster, deployment, validation, and diagnostics entrypoints.
- `tests/contract/`: repository and rendered-manifest contract tests.
- `tests/smoke/`: live-cluster smoke tests.

### Task 1: Repository contract and version governance

**Files:**
- Create: `.gitignore`
- Create: `VERSION`
- Create: `CHANGELOG.md`
- Create: `config/versions.env`
- Create: `tests/contract/test_repository_contract.py`
- Create: `Makefile`

- [ ] **Step 1: Write the failing repository contract test**

```python
# tests/contract/test_repository_contract.py
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class RepositoryContractTest(unittest.TestCase):
    def test_version_is_semver(self):
        self.assertRegex((ROOT / "VERSION").read_text().strip(), r"^\d+\.\d+\.\d+$")

    def test_changelog_has_current_version(self):
        version = (ROOT / "VERSION").read_text().strip()
        self.assertIn(f"## [{version}]", (ROOT / "CHANGELOG.md").read_text())

    def test_versions_are_pinned(self):
        values = {}
        for line in (ROOT / "config/versions.env").read_text().splitlines():
            if line and not line.startswith("#"):
                key, value = line.split("=", 1)
                values[key] = value
        required = {"KUBERNETES_VERSION", "ENVOY_GATEWAY_VERSION", "MYSQL_VERSION",
                    "REDIS_VERSION", "ROCKETMQ_VERSION", "SEAWEEDFS_VERSION"}
        self.assertEqual(required, required & values.keys())
        for key in required:
            self.assertNotIn(values[key], {"latest", "main", "master"})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `python3 -m unittest tests.contract.test_repository_contract -v`  
Expected: `ERROR` because `VERSION` and `config/versions.env` do not exist.

- [ ] **Step 3: Add pinned versions and release metadata**

```text
# VERSION
0.1.0
```

```dotenv
# config/versions.env
KUBERNETES_VERSION=v1.36.2
ENVOY_GATEWAY_VERSION=v1.8.2
GATEWAY_API_VERSION=v1.6.0
MYSQL_VERSION=8.4.10
REDIS_VERSION=8.6.2
ROCKETMQ_VERSION=5.5.0
SEAWEEDFS_VERSION=4.39
```

`CHANGELOG.md` starts with Keep-a-Changelog headings and `## [0.1.0] - 2026-07-18`, documenting the platform foundation. `.gitignore` excludes `.workspace/`, `.env.local`, generated secret values, rendered charts, test artifacts, macOS metadata, and editor state.

- [ ] **Step 4: Add stable Make targets**

```make
.PHONY: test lint validate bootstrap cluster-up cluster-down deploy smoke diagnostics

test:
	python3 -m unittest discover -s tests -p 'test_*.py' -v

lint:
	shellcheck scripts/*.sh
	helm lint charts/coderushoj-infra
	helm lint charts/coderushoj

validate: test lint

bootstrap:
	./scripts/bootstrap.sh

cluster-up:
	./scripts/cluster-up.sh

cluster-down:
	./scripts/cluster-down.sh

deploy:
	./scripts/deploy.sh

smoke:
	./tests/smoke/platform.sh

diagnostics:
	./scripts/diagnostics.sh
```

- [ ] **Step 5: Run the contract test**

Run: `python3 -m unittest tests.contract.test_repository_contract -v`  
Expected: three passing tests.

- [ ] **Step 6: Commit**

```bash
git add .gitignore VERSION CHANGELOG.md config/versions.env tests/contract/test_repository_contract.py Makefile
git commit -m "chore: establish platform version contract"
```

### Task 2: Reproducible host and repository bootstrap

**Files:**
- Create: `Brewfile`
- Create: `scripts/lib.sh`
- Create: `scripts/bootstrap.sh`
- Create: `scripts/clone-repositories.sh`
- Create: `tests/contract/test_scripts.py`

- [ ] **Step 1: Write failing script contract tests**

`tests/contract/test_scripts.py` asserts every shell file begins with `#!/usr/bin/env bash`, contains `set -Eeuo pipefail`, passes `bash -n`, and that `clone-repositories.sh --print` emits exactly `.github`, `croj-frontend`, `croj-backend`, `croj-judging-server`, and `croj-sandbox` without touching the network.

- [ ] **Step 2: Run tests and verify failure**

Run: `python3 -m unittest tests.contract.test_scripts -v`  
Expected: failure because scripts do not exist.

- [ ] **Step 3: Add the tool manifest and bootstrap scripts**

`Brewfile` installs `colima`, `docker`, `kubectl`, `kind`, `helm`, `jq`, `yq`, `shellcheck`, `trivy`, `gh`, and `kubeconform`. `scripts/bootstrap.sh` verifies macOS and Homebrew, runs `brew bundle --file "$ROOT/Brewfile"`, then calls `clone-repositories.sh`. It never modifies global Git identity.

`scripts/clone-repositories.sh` uses this fixed mapping and clones only missing repositories:

```bash
readonly REPOSITORIES=(
  ".github"
  "croj-frontend"
  "croj-backend"
  "croj-judging-server"
  "croj-sandbox"
)
readonly DESTINATION="${CODERUSHOJ_REPOS_DIR:-$ROOT/.workspace/repos}"
```

The script supports `--print` and `--update`. `--update` performs `git fetch --prune` only; it does not merge, reset, clean, or discard user work.

- [ ] **Step 4: Validate scripts**

Run: `python3 -m unittest tests.contract.test_scripts -v && shellcheck scripts/*.sh`  
Expected: all tests pass and ShellCheck reports no findings.

- [ ] **Step 5: Commit**

```bash
git add Brewfile scripts tests/contract/test_scripts.py
git commit -m "build: add reproducible local bootstrap"
```

### Task 3: Three-node Kind cluster lifecycle

**Files:**
- Create: `config/kind/cluster.yaml`
- Create: `scripts/cluster-up.sh`
- Create: `scripts/cluster-down.sh`
- Create: `tests/contract/test_kind_config.py`

- [ ] **Step 1: Write the failing Kind topology test**

The test loads `config/kind/cluster.yaml` as text and asserts one control-plane node, two worker nodes, the digest-pinned Kubernetes image `kindest/node:v1.36.1`, host ports 8080/8443, and judge-worker labels on both workers.

- [ ] **Step 2: Run it and verify failure**

Run: `python3 -m unittest tests.contract.test_kind_config -v`  
Expected: missing-file failure.

- [ ] **Step 3: Add the cluster configuration**

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: coderushoj
nodes:
  - role: control-plane
    image: kindest/node:v1.36.1@sha256:3489c7674813ba5d8b1a9977baea8a6e553784dab7b84759d1014dbd78f7ebd5
    extraPortMappings:
      - containerPort: 30080
        hostPort: 8080
        protocol: TCP
      - containerPort: 30443
        hostPort: 8443
        protocol: TCP
  - role: worker
    image: kindest/node:v1.36.1@sha256:3489c7674813ba5d8b1a9977baea8a6e553784dab7b84759d1014dbd78f7ebd5
    labels:
      coderushoj.io/judge-worker: "true"
  - role: worker
    image: kindest/node:v1.36.1@sha256:3489c7674813ba5d8b1a9977baea8a6e553784dab7b84759d1014dbd78f7ebd5
    labels:
      coderushoj.io/judge-worker: "true"
```

`cluster-up.sh` starts Colima with 8 GiB memory, 6 CPUs, 50 GiB disk, and the native architecture; creates the cluster only when absent; waits for all nodes; and writes diagnostics on failure. `cluster-down.sh` deletes only the explicit `coderushoj` Kind cluster and leaves Colima running unless `--stop-runtime` is passed.

- [ ] **Step 4: Test and create the cluster**

Run: `python3 -m unittest tests.contract.test_kind_config -v && ./scripts/cluster-up.sh`  
Expected: three Ready nodes, including two labeled judge workers.

- [ ] **Step 5: Commit**

```bash
git add config/kind scripts/cluster-up.sh scripts/cluster-down.sh tests/contract/test_kind_config.py
git commit -m "feat: add three-node local Kubernetes cluster"
```

### Task 4: Gateway API and Envoy Gateway foundation

**Files:**
- Create: `scripts/install-gateway.sh`
- Create: `charts/coderushoj/Chart.yaml`
- Create: `charts/coderushoj/values.yaml`
- Create: `charts/coderushoj/templates/gateway.yaml`
- Create: `charts/coderushoj/templates/routes.yaml`
- Create: `tests/contract/test_gateway_render.py`

- [ ] **Step 1: Write the failing rendered-route test**

The test runs `helm template` and asserts the result contains one `gateway.networking.k8s.io/v1` Gateway and HTTPRoutes for host `coderushoj.local` with `/`, `/api`, and `/docs` matches.

- [ ] **Step 2: Verify the test fails**

Run: `python3 -m unittest tests.contract.test_gateway_render -v`  
Expected: Helm reports the missing chart.

- [ ] **Step 3: Implement the Gateway installation and chart**

`install-gateway.sh` installs Envoy Gateway from its OCI chart at `v1.8.2`, with Gateway API Standard Channel CRDs, waits for `envoy-gateway-system`, and patches only its generated Envoy Service to fixed NodePorts 30080/30443 for Kind.

The application chart defines a `Gateway` using `gatewayClassName: envoy` and HTTPRoutes that direct `/api` to `croj-backend:7999`, `/docs` to `croj-docs:80`, and the remaining traffic to `croj-frontend:80`. Routes use stable Gateway API resources only.

- [ ] **Step 4: Render and validate**

Run: `python3 -m unittest tests.contract.test_gateway_render -v && helm lint charts/coderushoj`  
Expected: passing route contract and lint.

- [ ] **Step 5: Commit**

```bash
git add scripts/install-gateway.sh charts/coderushoj tests/contract/test_gateway_render.py
git commit -m "feat: expose platform through Gateway API"
```

### Task 5: Pinned infrastructure Helm chart

**Files:**
- Create: `charts/coderushoj-infra/Chart.yaml`
- Create: `charts/coderushoj-infra/values.yaml`
- Create: `charts/coderushoj-infra/values-production.yaml`
- Create: `charts/coderushoj-infra/templates/_helpers.tpl`
- Create: `charts/coderushoj-infra/templates/mysql.yaml`
- Create: `charts/coderushoj-infra/templates/redis.yaml`
- Create: `charts/coderushoj-infra/templates/rocketmq.yaml`
- Create: `charts/coderushoj-infra/templates/seaweedfs.yaml`
- Create: `charts/coderushoj-infra/templates/network-policies.yaml`
- Create: `charts/coderushoj-infra/templates/tests.yaml`
- Create: `tests/contract/test_infra_render.py`

- [ ] **Step 1: Write the failing infrastructure render test**

The test renders the chart and verifies StatefulSets/Deployments, Services, PVCs, probes, resource requests/limits, non-`latest` images, checksums on configuration, and default-deny NetworkPolicies. It also asserts the local profile remains below 5.5 GiB total requested memory.

- [ ] **Step 2: Verify it fails**

Run: `python3 -m unittest tests.contract.test_infra_render -v`  
Expected: missing-chart failure.

- [ ] **Step 3: Implement local and production-shaped values**

Local defaults deploy one MySQL 8.4.10 instance, one Redis 8.6.2 instance with AOF, one RocketMQ 5.5.0 name server and broker, and SeaweedFS 4.39 in compact server/S3 mode. Every workload has a ClusterIP or headless Service, PVC, probes, Pod Security settings, and explicit resources. The production values enable replicas or document external managed equivalents without changing application endpoints.

Secrets are referenced by name; plaintext passwords are not present in chart defaults or rendered tests. RocketMQ topics `submission-topic` and `submission-dead-letter-topic` are created by a post-install/post-upgrade Job.

- [ ] **Step 4: Lint and render**

Run: `python3 -m unittest tests.contract.test_infra_render -v && helm lint charts/coderushoj-infra`  
Expected: all contract tests and Helm lint pass.

- [ ] **Step 5: Commit**

```bash
git add charts/coderushoj-infra tests/contract/test_infra_render.py
git commit -m "feat: add pinned platform infrastructure chart"
```

### Task 6: Secret generation, installation, and live smoke tests

**Files:**
- Create: `scripts/generate-secrets.sh`
- Create: `scripts/deploy.sh`
- Create: `scripts/diagnostics.sh`
- Create: `tests/smoke/platform.sh`
- Create: `tests/contract/test_no_secrets.py`

- [ ] **Step 1: Write secret-safety tests**

The Python test scans tracked text files and fails on known legacy values, JWT-looking literals, private keys, and password fields outside documented examples. It verifies `.workspace/secrets` is ignored.

- [ ] **Step 2: Verify the test fails before ignore/secrets rules are complete**

Run: `python3 -m unittest tests.contract.test_no_secrets -v`  
Expected: failure describing the missing generated-secret ignore contract.

- [ ] **Step 3: Implement idempotent secret and deployment scripts**

`generate-secrets.sh` uses `openssl rand`, writes mode-0600 local values beneath `.workspace/secrets`, and uses `kubectl create secret ... --dry-run=client -o yaml | kubectl apply -f -`. It never prints secret values.

`deploy.sh` calls Gateway installation, generates secrets, installs `coderushoj-infra` with `--atomic --wait`, then installs `coderushoj` with application Deployments disabled until service images exist. On failure it runs `diagnostics.sh` and returns non-zero.

`tests/smoke/platform.sh` verifies all infrastructure Pods are Ready, MySQL answers `SELECT 1`, Redis answers `PONG`, RocketMQ topic listing succeeds, SeaweedFS accepts and retrieves an S3 object, the Gateway is Programmed, and no Pod uses a `latest` image.

- [ ] **Step 4: Deploy and smoke test**

Run: `./scripts/deploy.sh && ./tests/smoke/platform.sh`  
Expected: `platform smoke tests: PASS`.

- [ ] **Step 5: Commit**

```bash
git add .gitignore scripts tests/smoke tests/contract/test_no_secrets.py
git commit -m "feat: automate secure local platform deployment"
```

### Task 6.5: Docker Compose developer path

**Files:**
- Create: `compose.yaml`
- Create: `config/rocketmq/broker.conf`
- Create: `tests/contract/test_compose.py`
- Modify: `Brewfile`
- Modify: `Makefile`
- Modify: `scripts/generate-secrets.sh`

- [ ] **Step 1: Write failing Compose contract tests**

Require pinned images, health checks, persistent volumes, loopback-only host ports, file-backed secrets, and a `--files-only` secret-generation mode. Parse the Compose model dynamically when the plugin is installed.

- [ ] **Step 2: Implement and validate the developer stack**

Provide MySQL, Redis, RocketMQ, and SeaweedFS with the same versions and constrained RocketMQ heap settings used by Helm. Run `make compose-up` for a health-checked start and `make compose-down` for a non-destructive stop.

- [ ] **Step 3: Commit**

```bash
git add Brewfile Makefile compose.yaml config/rocketmq scripts/generate-secrets.sh tests/contract/test_compose.py
git commit -m "feat: add Docker Compose developer stack"
```

### Task 7: Web documentation and operator runbooks

**Files:**
- Create: `docs/package.json`
- Create: `docs/pnpm-lock.yaml`
- Create: `docs/.vitepress/config.mts`
- Create: `docs/.vitepress/theme/index.ts`
- Create: `docs/.vitepress/theme/custom.css`
- Create: `docs/index.md`
- Create: `docs/guide/quickstart.md`
- Create: `docs/architecture/platform.md`
- Create: `docs/operations/troubleshooting.md`
- Create: `docs/operations/backup-restore.md`
- Create: `docs/releases/index.md`
- Create: `docs/Dockerfile`
- Create: `tests/contract/test_docs.py`

- [ ] **Step 1: Write failing documentation contract tests**

The test requires navigation links, Mermaid support, command blocks for clean install/upgrade/rollback, troubleshooting for every infrastructure component, backup/restore verification, and a release page linked to `CHANGELOG.md`.

- [ ] **Step 2: Verify failure**

Run: `python3 -m unittest tests.contract.test_docs -v`  
Expected: missing documentation files.

- [ ] **Step 3: Build the VitePress site and runbooks**

Use a Chinese-first, responsive documentation theme sharing CodeRushOJ colors and logos. Quickstart documents `make bootstrap`, `make cluster-up`, `make deploy`, host mapping, expected health output, and cleanup. Architecture explains trust boundaries and the submission flow. Operations pages use copyable diagnostic commands and explicit recovery verification.

- [ ] **Step 4: Build and verify docs**

Run: `cd docs && corepack pnpm install --frozen-lockfile && corepack pnpm build`  
Expected: successful VitePress build with no dead internal links.

- [ ] **Step 5: Commit**

```bash
git add docs tests/contract/test_docs.py
git commit -m "docs: publish platform and operations guide"
```

### Task 8: CI, Issues, milestones, and release logs

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `.github/workflows/release.yml`
- Create: `.github/ISSUE_TEMPLATE/config.yml`
- Create: `.github/ISSUE_TEMPLATE/epic.yml`
- Create: `.github/ISSUE_TEMPLATE/feature.yml`
- Create: `.github/ISSUE_TEMPLATE/bug.yml`
- Create: `.github/ISSUE_TEMPLATE/security.yml`
- Create: `.github/ISSUE_TEMPLATE/docs.yml`
- Create: `.github/PULL_REQUEST_TEMPLATE.md`
- Create: `docs/project/milestones.md`
- Create: `docs/project/release-process.md`
- Create: `tests/contract/test_governance.py`

- [ ] **Step 1: Write failing governance tests**

The test parses template text and requires acceptance criteria, linked issue, test evidence, UI screenshots, migration impact, security impact, operational impact, rollback notes, milestone, and release-note category.

- [ ] **Step 2: Verify failure**

Run: `python3 -m unittest tests.contract.test_governance -v`  
Expected: missing templates.

- [ ] **Step 3: Implement CI and governance assets**

CI runs contract tests, ShellCheck, Helm lint/template, Kubeconform, VitePress build, Trivy filesystem scan, secret scan, and a Kind deployment smoke job. Failed smoke jobs upload diagnostics. The release workflow validates `VERSION`, chart version, and changelog agreement before packaging the chart and documentation image; publication requires a signed `v*` tag.

Milestones are fixed as Platform Foundation, Core OJ, Contests, Community, and v1 Hardening. The release process defines SemVer rules and mandatory release-note sections: Features, Fixes, Security, Migrations, Operations, Known Limitations, Upgrade, and Rollback.

- [ ] **Step 4: Validate governance and workflows**

Run: `python3 -m unittest tests.contract.test_governance -v && make validate`  
Expected: all repository tests, lint, render, and documentation checks pass.

- [ ] **Step 5: Commit**

```bash
git add .github docs/project tests/contract/test_governance.py
git commit -m "ci: enforce issue and release governance"
```

### Task 9: Foundation release rehearsal

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `docs/releases/index.md`
- Create: `artifacts/.gitkeep`

- [ ] **Step 1: Run the clean-room sequence**

Run:

```bash
make validate
make cluster-down
make cluster-up
make deploy
make smoke
```

Expected: validation and smoke tests pass from a clean local cluster.

- [ ] **Step 2: Exercise upgrade and rollback**

Run a no-op `helm upgrade`, verify smoke tests, then `helm rollback` both releases and verify again. Expected: all checks pass and Helm history shows successful revisions.

- [ ] **Step 3: Capture release evidence**

Run `make diagnostics` and store the redacted artifact bundle under `artifacts/platform-foundation-0.1.0/`. Confirm the archive contains versions, rendered manifests, Pod states, events, and smoke output but no Secret data.

- [ ] **Step 4: Final commit**

```bash
git add CHANGELOG.md docs/releases/index.md artifacts/.gitkeep
git commit -m "chore: prepare platform v0.1.0 release"
```

- [ ] **Step 5: Tag only after CI-equivalent validation passes**

Run: `git tag -s v0.1.0 -m "CodeRushOJ platform foundation v0.1.0"`  
Expected: a signed local tag. Do not push or publish until the GitHub remote and release issue are confirmed.

---

## Plan Self-review

- The plan covers every Platform Foundation requirement in the approved design: repositories, governance, toolchain, three-node Kubernetes, Gateway API, pinned infrastructure, secrets, documentation, smoke tests, CI, release log, upgrade, and rollback.
- Application service implementation, business schema migration, judge orchestration, and UI redesign remain in the separately testable Core OJ plan.
- All version fields are pinned; `latest` is explicitly rejected by tests.
- No task requires destructive cleanup of user work or stores plaintext credentials in Git.
