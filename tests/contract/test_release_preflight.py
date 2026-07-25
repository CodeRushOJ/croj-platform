import importlib.util
import json
import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
PREFLIGHT = ROOT / "scripts" / "verify-main-ci.py"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
REVISION = "a" * 40
REQUIRED_JOB = "Real three-node Kind product E2E"


def load_preflight():
    spec = importlib.util.spec_from_file_location("verify_main_ci", PREFLIGHT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeGitHub:
    def __init__(self, runs, jobs=None):
        self.runs = runs
        self.jobs = jobs or {}
        self.calls = []

    def get(self, endpoint, **parameters):
        self.calls.append((endpoint, parameters))
        if endpoint.endswith("/runs"):
            return {"workflow_runs": self.runs}
        run_id = int(endpoint.split("/runs/", 1)[1].split("/", 1)[0])
        return {"total_count": len(self.jobs.get(run_id, [])), "jobs": self.jobs.get(run_id, [])}


def workflow_run(**overrides):
    payload = {
        "id": 101,
        "run_number": 7,
        "event": "push",
        "head_branch": "main",
        "head_sha": REVISION,
        "status": "completed",
        "conclusion": "success",
    }
    payload.update(overrides)
    return payload


def product_job(**overrides):
    payload = {
        "id": 202,
        "name": REQUIRED_JOB,
        "status": "completed",
        "conclusion": "success",
    }
    payload.update(overrides)
    return payload


class ReleasePreflightUnitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.preflight = load_preflight()

    def test_accepts_only_the_exact_successful_main_push_and_product_job(self):
        github = FakeGitHub(
            [
                workflow_run(id=99, event="pull_request"),
                workflow_run(id=100, head_sha="b" * 40),
                workflow_run(),
            ],
            {101: [product_job()]},
        )

        run_id = self.preflight.verify_once(
            github,
            repository="CodeRushOJ/croj-platform",
            workflow="ci.yml",
            revision=REVISION,
            branch="main",
            required_job=REQUIRED_JOB,
        )

        self.assertEqual(101, run_id)
        self.assertEqual(2, len(github.calls))
        self.assertEqual(
            {
                "event": "push",
                "branch": "main",
                "head_sha": REVISION,
                "per_page": "100",
            },
            github.calls[0][1],
        )

    def test_rejects_a_failed_workflow_before_reading_jobs(self):
        github = FakeGitHub([workflow_run(conclusion="failure")])

        with self.assertRaisesRegex(self.preflight.PreflightError, "conclusion is failure"):
            self.preflight.verify_once(
                github,
                repository="CodeRushOJ/croj-platform",
                workflow="ci.yml",
                revision=REVISION,
                branch="main",
                required_job=REQUIRED_JOB,
            )

        self.assertEqual(1, len(github.calls))

    def test_rejects_missing_duplicate_skipped_and_failed_required_jobs(self):
        cases = (
            ([], "found 0"),
            ([product_job(), product_job(id=203)], "found 2"),
            ([product_job(conclusion="skipped")], "conclusion is skipped"),
            ([product_job(conclusion="failure")], "conclusion is failure"),
        )
        for jobs, message in cases:
            with self.subTest(jobs=jobs):
                github = FakeGitHub([workflow_run()], {101: jobs})
                with self.assertRaisesRegex(self.preflight.PreflightError, message):
                    self.preflight.verify_once(
                        github,
                        repository="CodeRushOJ/croj-platform",
                        workflow="ci.yml",
                        revision=REVISION,
                        branch="main",
                        required_job=REQUIRED_JOB,
                    )

    def test_pending_or_absent_run_is_retryable_but_wrong_shape_fails_closed(self):
        for runs in ([], [workflow_run(status="in_progress", conclusion=None)]):
            with self.subTest(runs=runs):
                github = FakeGitHub(runs)
                with self.assertRaises(self.preflight.PreflightPending):
                    self.preflight.verify_once(
                        github,
                        repository="CodeRushOJ/croj-platform",
                        workflow="ci.yml",
                        revision=REVISION,
                        branch="main",
                        required_job=REQUIRED_JOB,
                    )

        malformed_runs = (
            {"id": 101},
            {
                key: value
                for key, value in workflow_run().items()
                if key != "conclusion"
            },
        )
        for malformed_run in malformed_runs:
            with self.subTest(malformed_run=malformed_run):
                github = FakeGitHub([malformed_run])
                with self.assertRaisesRegex(self.preflight.PreflightError, "malformed"):
                    self.preflight.verify_once(
                        github,
                        repository="CodeRushOJ/croj-platform",
                        workflow="ci.yml",
                        revision=REVISION,
                        branch="main",
                        required_job=REQUIRED_JOB,
                    )


class ReleasePreflightCliTest(unittest.TestCase):
    def write_fake_gh(self, directory, *, exit_code=0, response=None):
        executable = pathlib.Path(directory) / "gh"
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            f"sys.exit({exit_code})\n"
            if exit_code
            else "#!/usr/bin/env python3\n"
            "import json\n"
            f"print(json.dumps({response!r}))\n"
        )
        executable.chmod(0o755)
        return executable

    def test_cli_fails_closed_when_github_api_errors(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            gh = self.write_fake_gh(temporary_directory, exit_code=23)
            result = subprocess.run(
                [
                    "python3",
                    str(PREFLIGHT),
                    "--repository",
                    "CodeRushOJ/croj-platform",
                    "--workflow",
                    "ci.yml",
                    "--revision",
                    REVISION,
                    "--timeout-seconds",
                    "0",
                    "--gh-command",
                    str(gh),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("GitHub API request failed", result.stderr)

    def test_cli_times_out_when_the_exact_main_push_run_does_not_exist(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            gh = self.write_fake_gh(
                temporary_directory,
                response={"workflow_runs": []},
            )
            result = subprocess.run(
                [
                    "python3",
                    str(PREFLIGHT),
                    "--repository",
                    "CodeRushOJ/croj-platform",
                    "--workflow",
                    "ci.yml",
                    "--revision",
                    REVISION,
                    "--timeout-seconds",
                    "0",
                    "--poll-interval-seconds",
                    "0",
                    "--gh-command",
                    str(gh),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("timed out", result.stderr)


class ReleaseWorkflowContractTest(unittest.TestCase):
    def test_release_waits_for_the_real_main_product_gate_before_mutation(self):
        workflow = RELEASE_WORKFLOW.read_text()
        preflight = workflow.index("Verify successful main CI and real product E2E")
        component_download = workflow.index(
            "Download the four public component release manifests"
        )
        component_validation = workflow.index(
            "Validate immutable component inputs before publication"
        )
        component_registry = workflow.index(
            "Verify component registry indexes before publication"
        )
        docs_publish = workflow.index(
            "Build and publish staged multi-architecture documentation image"
        )
        login = workflow.index("Log in to GHCR")
        publish = workflow.index("Publish GitHub Release")

        self.assertLess(preflight, component_download)
        self.assertLess(component_download, component_validation)
        self.assertLess(component_validation, component_registry)
        self.assertLess(component_registry, docs_publish)
        self.assertLess(preflight, login)
        self.assertLess(preflight, publish)
        self.assertIn("scripts/verify-main-ci.py", workflow)
        self.assertIn("--revision \"$GITHUB_SHA\"", workflow)
        self.assertIn("--branch main", workflow)
        self.assertIn(f'--required-job "{REQUIRED_JOB}"', workflow)
        self.assertIn("actions: read", workflow)
        self.assertIn("timeout-minutes: 120", workflow)


if __name__ == "__main__":
    unittest.main()
