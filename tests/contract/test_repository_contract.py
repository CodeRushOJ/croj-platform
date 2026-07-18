import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]


class RepositoryContractTest(unittest.TestCase):
    def read_required(self, relative_path):
        path = ROOT / relative_path
        self.assertTrue(path.is_file(), f"required file is missing: {relative_path}")
        return path.read_text()

    def test_version_is_semver(self):
        self.assertRegex(self.read_required("VERSION").strip(), r"^\d+\.\d+\.\d+$")

    def test_changelog_has_current_version(self):
        version = self.read_required("VERSION").strip()
        self.assertIn(f"## [{version}]", self.read_required("CHANGELOG.md"))

    def test_versions_are_pinned(self):
        values = {}
        for line in self.read_required("config/versions.env").splitlines():
            if line and not line.startswith("#"):
                key, value = line.split("=", 1)
                values[key] = value

        required = {
            "KUBERNETES_VERSION",
            "KIND_NODE_IMAGE",
            "ENVOY_GATEWAY_VERSION",
            "MYSQL_VERSION",
            "REDIS_VERSION",
            "ROCKETMQ_VERSION",
            "SEAWEEDFS_VERSION",
        }
        self.assertEqual(required, required & values.keys())
        for key in required:
            self.assertNotIn(values[key], {"latest", "main", "master"})


if __name__ == "__main__":
    unittest.main()
