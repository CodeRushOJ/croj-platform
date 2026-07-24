import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]


class KindConfigContractTest(unittest.TestCase):
    def test_three_node_topology_is_pinned_and_exposed(self):
        path = ROOT / "config/kind/cluster.yaml"
        self.assertTrue(path.is_file(), "Kind cluster configuration is missing")
        contents = path.read_text()

        self.assertEqual(1, contents.count("role: control-plane"))
        self.assertEqual(2, contents.count("role: worker"))
        image = (
            "kindest/node:v1.36.1@sha256:"
            "3489c7674813ba5d8b1a9977baea8a6e553784dab7b84759d1014dbd78f7ebd5"
        )
        self.assertEqual(3, contents.count(f"image: {image}"))
        self.assertIn("hostPort: 8080", contents)
        self.assertIn("hostPort: 8443", contents)
        self.assertEqual(2, contents.count("coderushoj.io/judge-worker"))
        self.assertEqual(2, contents.count("coderushoj.io/sandbox"))


if __name__ == "__main__":
    unittest.main()
