# Chart Package Verifier Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make release chart verification accept only Helm's harmless `Chart.yaml` normalization while rejecting YAML type drift, nested collections, duplicate keys, invalid required metadata, and every byte change outside `Chart.yaml`.

**Architecture:** Keep the verifier dependency-free by replacing its string-only line parser with a deliberately strict parser for a single root YAML mapping whose values are typed scalars. Normalize quoting, field order, and inline comments, retain scalar type tags during equality, validate Helm-required chart fields explicitly, and leave the existing byte dictionary comparison for all other chart files unchanged.

**Tech Stack:** Python 3 standard library, `unittest`, Helm 4 contract fixture, GNU Make validation.

---

### Task 1: Lock down root-only typed YAML parsing

**Files:**
- Modify: `tests/contract/test_release_images.py`
- Modify: `scripts/verify-release-assets.py`

- [x] Add a failing contract test whose source and package both contain block or flow maps/lists and assert the verifier rejects all four forms.
- [x] Run the focused test and record RED when the current parser accepts `{...}` and `[...]`.
- [x] Add a failing duplicate-key test using equivalent plain and quoted root keys and assert the duplicate-key diagnostic.
- [x] Run the focused test and record RED when the current parser reports only generic invalid metadata.
- [x] Add failing semantic-drift subtests for `true`/`"true"`, `null`/`"null"`, and `42`/`"42"`.
- [x] Run the focused test and record RED when the current string-only parser accepts all three.
- [x] Implement strict root mapping parsing with quote-aware key/value splitting, duplicate detection on decoded keys, typed scalar tuples, flow/block collection rejection, and no third-party dependency.
- [x] Run the focused parser contracts and confirm GREEN.

### Task 2: Normalize YAML comments without erasing semantics

**Files:**
- Modify: `tests/contract/test_release_images.py`
- Modify: `scripts/verify-release-assets.py`

- [x] Add a failing test with different inline comments and equivalent quoted/plain string values in source and package.
- [x] Run it and record RED when the current double-quoted parser consumes the comment as part of the value.
- [x] Implement quote-aware inline-comment removal while preserving `#` inside quoted and unquoted scalar content.
- [x] Run the focused test and confirm GREEN.

### Task 3: Enforce Helm chart metadata schema

**Files:**
- Modify: `tests/contract/test_release_images.py`
- Modify: `scripts/verify-release-assets.py`

- [x] Add failing subtests for missing/wrong/non-string `apiVersion` and missing/non-string `name`, `version`, and `appVersion`.
- [x] Run them and record RED for missing/wrong `apiVersion` and imprecise current diagnostics.
- [x] Validate `apiVersion` as the exact string `v2`; require the other three fields to be strings before checking their expected release values.
- [x] Run the focused schema tests and confirm GREEN.

### Task 4: Reproduce Helm quote normalization and retain byte exactness elsewhere

**Files:**
- Modify: `tests/contract/test_release_images.py`

- [x] Add a failing real-Helm fixture test that requires source `appVersion` to be quoted, packages it with Helm, proves the archive removed those quotes, and verifies acceptance.
- [x] Run it and record RED against the current unquoted source fixture.
- [x] Change the shared source fixture to quote `appVersion`, keeping the synthetic default package exact until a test replaces it.
- [x] Add a dedicated regression test that changes only `values.yaml` bytes and requires the exact-content diagnostic.
- [x] Run the focused tests and confirm the real normalization path is accepted and non-`Chart.yaml` drift is rejected.

### Task 5: Validate, self-review, and publish the branch

**Files:**
- Modify only if verification exposes a scoped defect.

- [x] Run `python3 -m unittest tests.contract.test_release_images.ExistingReleaseAssetTest -v`.
- [x] Run `make validate`.
- [x] Run `git diff --check`.
- [x] Review the complete diff against all seven review requirements and confirm no runtime dependency was added.
- [x] Confirm Git author is `HeZephyr <unique.hzf@gmail.com>`.
- [ ] Commit the scoped changes and push `codex/fix-chart-package-verifier` to update PR #27 without merging it.
