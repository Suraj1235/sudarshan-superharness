import unittest
from unittest import mock

from process_runner import _resolve_argv


class TestProcessRunner(unittest.TestCase):
    def test_windows_resolves_path_commands_to_their_real_launcher(self):
        with mock.patch("process_runner.os.name", "nt"), mock.patch(
            "process_runner.shutil.which", return_value=r"C:\Program Files\nodejs\npm.CMD"
        ) as which:
            resolved = _resolve_argv(["npm", "test"], {"PATH": r"C:\Program Files\nodejs"})

        self.assertEqual(resolved, [r"C:\Program Files\nodejs\npm.CMD", "test"])
        which.assert_called_once_with("npm", path=r"C:\Program Files\nodejs")

    def test_non_windows_keeps_the_original_argument_vector(self):
        with mock.patch("process_runner.os.name", "posix"), mock.patch(
            "process_runner.shutil.which"
        ) as which:
            resolved = _resolve_argv(["npm", "test"], {"PATH": "/usr/bin"})

        self.assertEqual(resolved, ["npm", "test"])
        which.assert_not_called()


if __name__ == "__main__":
    unittest.main()
