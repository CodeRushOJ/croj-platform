#!/usr/bin/env python3
"""Wait for the exact main-push CI run and its real product E2E release gate."""

import argparse
import json
import re
import subprocess
import sys
import time


REVISION = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
WORKFLOW = re.compile(r"^[A-Za-z0-9_.-]+\.ya?ml$")
PENDING_STATUSES = {"queued", "in_progress", "pending", "requested", "waiting"}


class PreflightError(Exception):
    """The release must stop without performing a mutation."""


class PreflightPending(Exception):
    """The required trusted CI result is not available yet."""


class GitHubClient:
    def __init__(self, gh_command="gh"):
        self.gh_command = gh_command

    def get(self, endpoint, **parameters):
        command = [self.gh_command, "api", "-X", "GET", endpoint]
        for key, value in parameters.items():
            command.extend(("-f", f"{key}={value}"))
        try:
            result = subprocess.run(
                command,
                text=True,
                capture_output=True,
                check=False,
            )
        except OSError as error:
            raise PreflightError(f"GitHub API client could not start: {error}") from error
        if result.returncode:
            detail = result.stderr.strip() or f"exit code {result.returncode}"
            raise PreflightError(f"GitHub API request failed: {detail}")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise PreflightError("GitHub API returned invalid JSON") from error
        if not isinstance(payload, dict):
            raise PreflightError("GitHub API returned a non-object response")
        return payload


def require_run_shape(run):
    required = {
        "id": int,
        "run_number": int,
        "event": str,
        "head_branch": str,
        "head_sha": str,
        "status": str,
    }
    if not isinstance(run, dict):
        raise PreflightError("GitHub API returned a malformed workflow run")
    for field, expected_type in required.items():
        if not isinstance(run.get(field), expected_type):
            raise PreflightError(f"GitHub API returned a malformed workflow run: {field}")
    if "conclusion" not in run:
        raise PreflightError("GitHub API returned a malformed workflow run: conclusion")
    conclusion = run["conclusion"]
    if conclusion is not None and not isinstance(conclusion, str):
        raise PreflightError("GitHub API returned a malformed workflow run: conclusion")


def select_exact_run(payload, revision, branch):
    runs = payload.get("workflow_runs")
    if not isinstance(runs, list):
        raise PreflightError("GitHub API response has no workflow_runs list")
    for run in runs:
        require_run_shape(run)
    matching = [
        run
        for run in runs
        if run["event"] == "push"
        and run["head_branch"] == branch
        and run["head_sha"] == revision
    ]
    if not matching:
        raise PreflightPending(
            f"no {branch} push CI run exists yet for immutable revision {revision}"
        )
    return max(matching, key=lambda run: (run["run_number"], run["id"]))


def verify_required_job(payload, required_job):
    jobs = payload.get("jobs")
    total_count = payload.get("total_count")
    if not isinstance(jobs, list) or not isinstance(total_count, int):
        raise PreflightError("GitHub API response has no complete jobs list")
    if total_count != len(jobs):
        raise PreflightError(
            f"GitHub API jobs response was truncated: expected {total_count}, got {len(jobs)}"
        )
    matching = []
    for job in jobs:
        if not isinstance(job, dict):
            raise PreflightError("GitHub API returned a malformed workflow job")
        if job.get("name") == required_job:
            matching.append(job)
    if len(matching) != 1:
        raise PreflightError(
            f"required CI job {required_job!r}: found {len(matching)}, expected exactly 1"
        )
    job = matching[0]
    if not isinstance(job.get("status"), str):
        raise PreflightError(f"required CI job {required_job!r} has malformed status")
    conclusion = job.get("conclusion")
    if conclusion is not None and not isinstance(conclusion, str):
        raise PreflightError(f"required CI job {required_job!r} has malformed conclusion")
    if job["status"] != "completed":
        raise PreflightError(
            f"required CI job {required_job!r} status is {job['status']}, expected completed"
        )
    if conclusion != "success":
        raise PreflightError(
            f"required CI job {required_job!r} conclusion is {conclusion}, expected success"
        )


def verify_once(
    github,
    *,
    repository,
    workflow,
    revision,
    branch,
    required_job,
):
    runs = github.get(
        f"repos/{repository}/actions/workflows/{workflow}/runs",
        event="push",
        branch=branch,
        head_sha=revision,
        per_page="100",
    )
    run = select_exact_run(runs, revision, branch)
    if run["status"] in PENDING_STATUSES:
        raise PreflightPending(
            f"main CI run {run['id']} is still {run['status']} for revision {revision}"
        )
    if run["status"] != "completed":
        raise PreflightError(f"main CI run {run['id']} has unknown status {run['status']}")
    if run["conclusion"] != "success":
        raise PreflightError(
            f"main CI run {run['id']} conclusion is {run['conclusion']}, expected success"
        )
    jobs = github.get(
        f"repos/{repository}/actions/runs/{run['id']}/jobs",
        filter="latest",
        per_page="100",
    )
    verify_required_job(jobs, required_job)
    return run["id"]


def nonnegative_number(value):
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--workflow", default="ci.yml")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--branch", default="main")
    parser.add_argument(
        "--required-job",
        default="Real three-node Kind product E2E",
    )
    parser.add_argument("--timeout-seconds", type=nonnegative_number, default=5400)
    parser.add_argument("--poll-interval-seconds", type=nonnegative_number, default=20)
    parser.add_argument("--gh-command", default="gh", help=argparse.SUPPRESS)
    return parser.parse_args()


def validate_args(args):
    if not REPOSITORY.fullmatch(args.repository):
        raise PreflightError("repository must be an owner/name GitHub repository")
    if not WORKFLOW.fullmatch(args.workflow):
        raise PreflightError("workflow must be a workflow YAML filename")
    if not REVISION.fullmatch(args.revision):
        raise PreflightError("revision must be a lowercase 40-character Git object ID")
    if not args.branch or any(character.isspace() for character in args.branch):
        raise PreflightError("branch must be a non-empty name without whitespace")
    if not args.required_job.strip():
        raise PreflightError("required job must be non-empty")


def main():
    args = parse_args()
    try:
        validate_args(args)
        github = GitHubClient(args.gh_command)
        deadline = time.monotonic() + args.timeout_seconds
        while True:
            try:
                run_id = verify_once(
                    github,
                    repository=args.repository,
                    workflow=args.workflow,
                    revision=args.revision,
                    branch=args.branch,
                    required_job=args.required_job,
                )
            except PreflightPending as pending:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PreflightError(
                        f"timed out waiting for release CI preflight: {pending}"
                    ) from pending
                print(f"release CI preflight pending: {pending}", file=sys.stderr)
                time.sleep(min(args.poll_interval_seconds, remaining))
                continue
            print(
                f"release CI preflight passed: run {run_id}, job {args.required_job}",
                flush=True,
            )
            return 0
    except PreflightError as error:
        print(f"release CI preflight failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
