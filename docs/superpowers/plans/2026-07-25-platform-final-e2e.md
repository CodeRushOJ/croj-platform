# Platform Final E2E Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the locked v1 release candidates deployable together and prove the Kubernetes-native sandbox, internal OJ, external asynchronous REST, OI/SPJ, webhook, CI, and Pages contracts without claiming an unexecuted live pass.

**Architecture:** Keep `croj-platform` as the integration owner. A strict source lock selects immutable component commits; Helm wires only Secret references and Kubernetes DNS; contract tests fail before a costly Kind run when runtime configuration or E2E coverage drifts. The disposable three-node Kind job remains the only live product acceptance environment and always deletes only its owned cluster.

**Tech Stack:** Python `unittest`, Bash, Helm 4, Kubernetes/Kind, Calico, GitHub Actions, VitePress, Playwright.

---

### Task 1: Lock the release candidates and runtime configuration

**Files:**
- Modify: `config/source-lock.json`
- Modify: `scripts/generate-secrets.sh`
- Modify: `charts/coderushoj/templates/deployments.yaml`
- Modify: `tests/contract/test_cross_repo_sources.py`
- Modify: `tests/contract/test_no_secrets.py`
- Modify: `tests/contract/test_application_render.py`

- [ ] Add failing assertions for all five supplied release-candidate revisions and the judging source/callback key-ring Secret references.
- [ ] Run the focused contract tests and verify the new assertions fail for the stale lock and runtime environment.
- [ ] Update the lock, generate root-only versioned key-ring files, and render them as Secret references.
- [ ] Re-run the focused tests and keep Helm schema/render validation green.

### Task 2: Prove Service/Endpoint DNS and round-robin prerequisites

**Files:**
- Modify: `tests/contract/test_product_e2e_contract.py`
- Modify: `tests/e2e/product.sh`
- Modify: `docs/guide/sandbox-deployment.md`
- Modify: `docs/operations/troubleshooting.md`

- [ ] Add failing assertions requiring cluster DNS A-record evidence, two ready EndpointSlice addresses, two sandbox Pods, and judging configuration fixed to `dns:///...` with legacy discovery disabled.
- [ ] Run the focused contract and verify it fails for the missing DNS/runtime assertions.
- [ ] Add bounded, fail-closed checks to the product E2E script and document exact diagnostic commands.
- [ ] Re-run the focused contract and shell lint.

### Task 3: Add repeatable OI/SPJ and webhook product flows

**Files:**
- Create: `tests/e2e/bundle-oi/manifest.json`
- Create: `tests/e2e/bundle-oi/1.in`
- Create: `tests/e2e/bundle-oi/1.out`
- Create: `tests/e2e/bundle-oi/2.in`
- Create: `tests/e2e/bundle-oi/2.out`
- Create: `tests/e2e/bundle-spj/manifest.template.json`
- Create: `tests/e2e/bundle-spj/checker/main.cpp`
- Create: `tests/e2e/bundle-spj/1.in`
- Create: `tests/e2e/bundle-spj/1.out`
- Modify: `scripts/deploy-product-e2e.sh`
- Modify: `tests/e2e/product.sh`
- Modify: `tests/contract/test_product_e2e_contract.py`

- [ ] Add failing structural tests requiring deterministic v2 archives, OI partial-score polling, SPJ acceptance, callback provisioning, signed delivery evidence, and no inline credentials.
- [ ] Run the focused contract and verify the missing fixture/flow failures.
- [ ] Implement the minimum bounded E2E flows supported by the locked APIs. If the SSRF-safe webhook cannot target an in-cluster receiver, keep the workflow fail-closed and exercise it only against an explicitly supplied HTTPS receiver rather than weakening production policy.
- [ ] Re-run contracts, Bash syntax, and ShellCheck.

### Task 4: CI, Pages, documentation, and release evidence

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `.github/workflows/pages.yml`
- Modify: `docs/operations/product-e2e.md`
- Modify: `docs/operations/troubleshooting.md`
- Modify: `docs/guide/github-pages.md`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `tests/contract/test_docs.py`
- Modify: `tests/contract/test_governance.py`

- [ ] Add failing contracts for explicit v2 cross-repository validation, optional real webhook secrets, Pages build verification, timeouts, evidence retention, and immutable Actions.
- [ ] Update workflows and operator docs without embedding any token or claiming a run that did not execute.
- [ ] Run all repository contracts, Helm lint/render, ShellCheck, documentation build, and security scans available locally.
- [ ] Record the exact executed/not-executed live gates in the PR.

### Task 5: Review and publish

- [ ] Review the complete diff against the supplied requirements and fix every critical or important finding.
- [ ] Verify the configured GitHub identity for both author and committer.
- [ ] Commit intentionally, push `codex/platform-final-e2e`, open a draft PR against `main`, and report exact SHA/check results.
