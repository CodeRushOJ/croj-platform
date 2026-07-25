import pathlib
import re
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]


class SecretSafetyTest(unittest.TestCase):
    def test_generated_secret_directory_is_ignored(self):
        result = subprocess.run(
            ["git", "check-ignore", ".workspace/secrets/local.env"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_secret_generator_is_local_idempotent_and_quiet(self):
        path = ROOT / "scripts/generate-secrets.sh"
        self.assertTrue(path.is_file(), "generate-secrets.sh is missing")
        contents = path.read_text()
        self.assertIn("openssl rand", contents)
        self.assertIn("tr -d", contents)
        self.assertIn("chmod 600", contents)
        self.assertIn("--dry-run=client", contents)
        self.assertNotRegex(contents, r"echo\s+\$\{?(?:MYSQL|REDIS|S3)_")

    def test_secret_generator_covers_application_runtime_keys(self):
        contents = (ROOT / "scripts/generate-secrets.sh").read_text()
        for key in (
            "jwt-secret",
            "judge-result-service-token",
            "external-api-auth-pepper-base64",
            "external-idempotency-pepper-base64",
            "external-cursor-key-base64",
            "external-source-keys-json",
            "judge-callback-keys-json",
            "judge-database-dsn",
            "smtp-password",
        ):
            self.assertIn(key, contents)
        self.assertIn("openssl rand -base64", contents)
        self.assertIn("EXTERNAL_SOURCE_KEY_VERSION", contents)
        self.assertIn("JUDGE_CALLBACK_KEY_VERSION", contents)

    def test_tracked_files_have_no_private_keys_or_jwts(self):
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        private_key = "-----BEGIN " + "PRIVATE KEY-----"
        jwt = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
        findings = []
        for relative_path in result.stdout.splitlines():
            path = ROOT / relative_path
            if not path.is_file():
                continue
            try:
                contents = path.read_text()
            except UnicodeDecodeError:
                continue
            if private_key in contents or jwt.search(contents):
                findings.append(relative_path)
        self.assertEqual([], findings)


if __name__ == "__main__":
    unittest.main()
