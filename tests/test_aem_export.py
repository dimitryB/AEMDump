import argparse
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aem_export import AemWebDavExporter, DavItem, resolve_password


class TargetPathTests(unittest.TestCase):
    def _make_exporter(self, remote_root: str, local_root: Path) -> AemWebDavExporter:
        return AemWebDavExporter(
            base_url="https://example.invalid/crx/repository/crx.default",
            username="user",
            password="pass",
            remote_root=remote_root,
            local_root=local_root,
        )

    def test_target_file_within_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            local_root = Path(temp_dir)
            exporter = self._make_exporter("/content/dam", local_root)

            target = exporter._target_file_for_repo_path("/content/dam/folder/file.txt")

            self.assertEqual(target, (local_root / "folder" / "file.txt").resolve(strict=False))

    def test_target_file_rejects_outside_remote_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            local_root = Path(temp_dir)
            exporter = self._make_exporter("/content/dam", local_root)

            with self.assertRaisesRegex(ValueError, "outside export root"):
                exporter._target_file_for_repo_path("/content/other/file.txt")

    def test_target_file_rejects_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            local_root = Path(temp_dir)
            exporter = self._make_exporter("/content/dam", local_root)

            with self.assertRaisesRegex(ValueError, "outside export root"):
                exporter._target_file_for_repo_path("/content/dam/../../etc/passwd")


class PasswordResolutionTests(unittest.TestCase):
    def test_password_argument_has_priority(self) -> None:
        args = argparse.Namespace(
            password="cli-secret",
            password_env="AEM_PASSWORD",
            no_password_prompt=False,
        )

        with mock.patch.dict("os.environ", {"AEM_PASSWORD": "env-secret"}, clear=True):
            self.assertEqual(resolve_password(args), "cli-secret")

    def test_password_from_environment(self) -> None:
        args = argparse.Namespace(
            password=None,
            password_env="AEM_PASSWORD",
            no_password_prompt=False,
        )

        with mock.patch.dict("os.environ", {"AEM_PASSWORD": "env-secret"}, clear=True):
            self.assertEqual(resolve_password(args), "env-secret")

    def test_password_prompt_disabled_raises(self) -> None:
        args = argparse.Namespace(
            password=None,
            password_env="AEM_PASSWORD",
            no_password_prompt=True,
        )

        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(ValueError, "Password not provided"):
                resolve_password(args)

    def test_password_from_prompt(self) -> None:
        args = argparse.Namespace(
            password=None,
            password_env="AEM_PASSWORD",
            no_password_prompt=False,
        )

        with mock.patch.dict("os.environ", {}, clear=True):
            with mock.patch("sys.stdin.isatty", return_value=True):
                with mock.patch("getpass.getpass", return_value="prompt-secret"):
                    self.assertEqual(resolve_password(args), "prompt-secret")


class WalkTests(unittest.TestCase):
    def test_walk_handles_deep_tree_without_recursion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            local_root = Path(temp_dir)

            class FakeExporter(AemWebDavExporter):
                def __init__(self, local_root: Path) -> None:
                    super().__init__(
                        base_url="https://example.invalid/crx/repository/crx.default",
                        username="user",
                        password="pass",
                        remote_root="/root",
                        local_root=local_root,
                    )

                def list_children(self, repo_path: str) -> list[DavItem]:
                    if repo_path == "/root":
                        return [DavItem(repo_path="/root/dir0", is_collection=True)]

                    if repo_path.startswith("/root/dir"):
                        depth = int(repo_path.rsplit("dir", 1)[1])
                        if depth < 1250:
                            return [DavItem(repo_path=f"/root/dir{depth + 1}", is_collection=True)]
                        return [DavItem(repo_path=f"/root/dir{depth}/leaf.txt", is_collection=False)]

                    return []

            exporter = FakeExporter(local_root)
            items = list(exporter.walk("/root"))

            self.assertEqual(items[-1].repo_path, "/root/dir1250/leaf.txt")
            self.assertEqual(sum(1 for item in items if item.is_collection), 1251)


if __name__ == "__main__":
    unittest.main()
