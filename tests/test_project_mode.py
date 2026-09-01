"""Root mode: the project folder itself is the top case; .cases/ holds its feature cases."""
import os
import tempfile
import unittest
from pathlib import Path

from mike import grammar, store
from tests.test_commands import run


class ProjectMode(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        self.project = Path(self.tmp.name).resolve()
        os.chdir(self.tmp.name)
        os.environ.pop("MIKE_CASE", None)
        (self.project / "app.py").write_text("print('the app itself')\n")
        run("case", "new", "--root", "my app", "--goal", "большое приложение как верхнее дело")

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()

    def test_root_files_created_and_project_detected(self):
        for f in ("README.md", "TODO.md", "JOURNAL.md"):
            self.assertTrue((self.project / f).exists(), f)
        root = store.find_root()
        self.assertEqual(store.project_case(root), self.project)
        code, out, _ = run()
        self.assertIn(f"case in hand: {self.project.name}", out)

    def test_refuses_when_readme_already_exists(self):
        with tempfile.TemporaryDirectory() as other:
            os.chdir(other)
            Path("README.md").write_text("# public readme\n")
            code, out, err = run("case", "new", "--root", "x y", "--goal", "g")
            self.assertEqual(code, 4)
            self.assertIn("will not overwrite", err)
            self.assertEqual(Path("README.md").read_text(), "# public readme\n")
            os.chdir(self.tmp.name)

    def test_feature_case_and_writeback_on_done(self):
        run("phase", "open", "1", "Foundation", "--goal", "каркас приложения")
        code, out, err = run("spawn", "add payments", "--goal", "оплата картой, причина сложности неизвестна")
        self.assertEqual(code, 0, err)
        child = next(p for p in (self.project / ".cases").iterdir() if p.is_dir() and "add-payments" in p.name)
        self.assertIn("waits: " + child.name, (self.project / "TODO.md").read_text())
        code, out, _ = run()
        self.assertIn(f"{self.project.name} › {child.name}", out)
        # child works and closes; outcome lands in the project files
        run("phase", "open", "1", "Build", "--goal", "g")
        run("log", "RESULT", "оплата работает на тестовой карте")
        run("log", "DECISION", "reflect: lesson")
        run("log", "DECISION", "align: nothing")
        self.assertEqual(run("phase", "close", "1", "готово")[0], 0)
        code, out, err = run("done", "оплата картой работает")
        self.assertEqual(code, 0, err)
        ptodo = grammar.parse_todo((self.project / "TODO.md").read_text())
        self.assertEqual(ptodo.phase(1).waits, [])
        self.assertIn("оплата картой работает", ptodo.phase(1).items[0].text)
        self.assertIn("оплата картой работает", (self.project / "JOURNAL.md").read_text())
        code, out, _ = run()
        self.assertIn(f"case in hand: {self.project.name}\n", out)

    def test_project_root_files_are_not_stray_and_check_is_clean(self):
        (self.project / "setup.py").write_text("# just the app\n")
        code, out, err = run("check")
        self.assertEqual(code, 0, err + out)
        self.assertNotIn("extra file", err + out)

    def test_case_list_shows_project_first_features_indented(self):
        run("case", "new", "some feature", "--goal", "g")
        code, out, err = run("case", "list")
        self.assertEqual(code, 0, err)
        lines = [l for l in out.splitlines() if l.strip()]
        self.assertIn(self.project.name, lines[0])
        feature = next(l for l in lines if "some-feature" in l)
        self.assertTrue(feature.startswith("  ") or feature.startswith("*  ") or feature.startswith("   "), feature)

    def test_plain_mode_untouched(self):
        with tempfile.TemporaryDirectory() as other:
            os.chdir(other)
            run("case", "new", "plain case", "--goal", "g")
            root = store.find_root()
            self.assertIsNone(store.project_case(root))
            code, out, _ = run()
            self.assertIn("plain-case", out.splitlines()[0])
            os.chdir(self.tmp.name)
