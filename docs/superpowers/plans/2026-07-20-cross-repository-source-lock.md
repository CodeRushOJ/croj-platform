# Cross-Repository Source Lock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and load all five CodeRushOJ development images from auditable, immutable Git commits without starting a cluster or relying on mutable branches or tags.

**Architecture:** A versioned JSON document is the single source of truth for repository URLs, 40-character commit IDs, Docker build paths, and exact `:dev` image names. A dependency-free Python validator exposes normalized rows to small strict-mode Bash scripts; checkout uses commit-addressed directories, build uses BuildKit with OCI source/revision labels, and Kind loading is a separate explicit operation.

**Tech Stack:** JSON, Python 3 standard library, Bash, Git, Docker Buildx, Kind, unittest, ShellCheck.

---

### Task 1: Lock schema and validator

**Files:**
- Create: `config/source-lock.json`
- Create: `scripts/verify-source-lock.py`
- Create: `tests/contract/test_cross_repo_sources.py`

- [x] **Step 1: Write failing contract tests**

Test that the lock contains exactly `frontend`, `backend`, `judging-server`, `sandbox`, and `docs`; every source uses an HTTPS CodeRushOJ GitHub URL, a lowercase 40-character commit, a safe relative build context/Dockerfile, and one of the five exact Chart `:dev` images. Test malformed locks and duplicate images through the validator CLI.

- [x] **Step 2: Verify the tests fail for missing artifacts**

Run: `python3 -m unittest tests.contract.test_cross_repo_sources -v`

Expected: FAIL because `config/source-lock.json` and `scripts/verify-source-lock.py` do not exist.

- [x] **Step 3: Add the immutable lock and validator**

Implement `validate` and `rows` commands using only Python's standard library. Reject unknown fields, mutable refs, unsafe paths, non-CodeRushOJ remotes, non-`:dev` image names, duplicate images, and an incomplete component set. Emit tab-separated normalized rows only after full validation.

- [x] **Step 4: Verify lock tests pass**

Run: `python3 -m unittest tests.contract.test_cross_repo_sources -v`

Expected: PASS.

### Task 2: Commit-addressed checkout

**Files:**
- Create: `scripts/checkout-sources.sh`
- Modify: `tests/contract/test_cross_repo_sources.py`
- Modify: `tests/contract/test_scripts.py`

- [x] **Step 1: Write failing checkout tests**

Use a temporary local bare Git remote and a generated valid lock to prove checkout lands on the locked commit in `<root>/<component>/<commit>`, is detached, reuses a clean exact checkout, and rejects a dirty existing checkout.

- [x] **Step 2: Verify checkout tests fail**

Run: `python3 -m unittest tests.contract.test_cross_repo_sources.CrossRepositoryCheckoutTest -v`

Expected: FAIL because `scripts/checkout-sources.sh` does not exist.

- [x] **Step 3: Implement atomic exact-commit checkout**

Validate the lock first, fetch the exact commit into a temporary directory, check out detached HEAD, verify the resulting object ID, and atomically rename it into the commit-addressed cache. Never reset or clean an existing directory; fail if it is dirty or mismatched.

- [x] **Step 4: Verify checkout tests pass**

Run: `python3 -m unittest tests.contract.test_cross_repo_sources.CrossRepositoryCheckoutTest -v`

Expected: PASS.

### Task 3: Five-image build and explicit Kind load

**Files:**
- Create: `scripts/build-dev-images.sh`
- Create: `scripts/load-dev-images.sh`
- Modify: `tests/contract/test_cross_repo_sources.py`
- Modify: `tests/contract/test_scripts.py`
- Modify: `Makefile`

- [x] **Step 1: Write failing command-contract tests**

Run scripts against fake `docker` and `kind` executables. Assert that build invokes exactly five `docker buildx build --load` commands with the locked Dockerfile/context, exact `:dev` image, and OCI source/revision labels; assert load invokes one `kind load docker-image` with exactly the five images and the selected cluster name.

- [x] **Step 2: Verify command-contract tests fail**

Run: `python3 -m unittest tests.contract.test_cross_repo_sources.CrossRepositoryImageWorkflowTest -v`

Expected: FAIL because the build/load scripts do not exist.

- [x] **Step 3: Implement thin build/load orchestration**

Consume validator rows rather than reparsing JSON in Bash. Build all five checked-out sources, then load only pre-existing locked images into Kind. Do not create, start, deploy to, or delete any cluster.

- [x] **Step 4: Verify workflow tests pass**

Run: `python3 -m unittest tests.contract.test_cross_repo_sources.CrossRepositoryImageWorkflowTest -v`

Expected: PASS with five builds and one load operation captured by the fake CLIs.

### Task 4: Operator documentation and complete validation

**Files:**
- Modify: `README.md`
- Modify: `docs/guide/quickstart.md`
- Modify: `CHANGELOG.md`
- Modify: `tests/contract/test_docs.py`

- [x] **Step 1: Write failing documentation assertions**

Require the README and quickstart to explain immutable commit verification, checkout/build/load commands, the commit update workflow, local cache location, and the fact that build/load does not create a cluster.

- [x] **Step 2: Verify documentation assertions fail**

Run: `python3 -m unittest tests.contract.test_docs -v`

Expected: FAIL because the new commands and lock workflow are not documented.

- [x] **Step 3: Document the source-of-truth workflow**

Add concise operator commands and explain that the backend and judging-server commit values are intentionally replaceable only by reviewed 40-character integration commits. Record the feature in `CHANGELOG.md` without claiming the full Kind product loop is complete.

- [x] **Step 4: Run all gates**

Run: `python3 -m unittest discover -s tests/contract -p 'test_*.py' -v`

Expected: all contract tests PASS.

Run: `shellcheck scripts/*.sh tests/smoke/*.sh`

Expected: no findings.

Run: `git diff --check`

Expected: no output.

- [x] **Step 5: Commit the completed first stage**

Stage only the source-lock workflow, tests, documentation, and plan. Confirm `.github/workflows/ci.yml` and `scripts/deploy.sh` are unchanged, then commit with `feat(platform): lock cross-repository dev images`.
