"""Regressions from the Bible Truck live-session feedback (2026-09-01): editable TODO,
section-level README edits, warning noise, trim suggestions, dangling folders."""
import os
import tempfile
import unittest
from pathlib import Path

from mike import grammar
from tests.test_commands import run


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)
        os.environ.pop("MIKE_CASE", None)
        run("case", "new", "demo case", "--goal", "g")
        run("phase", "open", "1", "Work", "--goal", "g")
        self.case = next(p for p in (Path(self.tmp.name) / ".cases").iterdir() if p.is_dir())

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()

    def todo(self):
        return grammar.parse_todo((self.case / "TODO.md").read_text())


class EditableTodo(Base):
    def test_edit_rewrites_text_and_journals_the_old(self):
        run("todo", "add", "1", "позвонить пастору")
        code, out, err = run("todo", "edit", "1.1", "позвонить пастору до пятницы")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.todo().phase(1).items[0].text, "позвонить пастору до пятницы")
        self.assertIn("todo 1.1: «позвонить пастору»", (self.case / "JOURNAL.md").read_text())

    def test_move_reorders_and_renumbers(self):
        for t in ("a", "b", "c", "d"):
            run("todo", "add", "1", t)
        code, out, err = run("todo", "move", "1.4", "1.1")
        self.assertEqual(code, 0, err)
        self.assertEqual([it.text for it in self.todo().phase(1).items], ["d", "a", "b", "c"])
        self.assertEqual([it.m for it in self.todo().phase(1).items], [1, 2, 3, 4])
        self.assertEqual(run("todo", "move", "1.2", "2.1")[0], 2)  # cross-phase → usage error

    def test_drop_removes_and_journals(self):
        run("todo", "add", "1", "лишний пункт")
        code, out, err = run("todo", "drop", "1.1")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.todo().phase(1).items, [])
        self.assertIn("todo 1.1 снят: «лишний пункт»", (self.case / "JOURNAL.md").read_text())

    def test_too_long_item_prints_a_ready_suggestion(self):
        code, out, err = run("todo", "add", "1", "слово " * 30)
        self.assertEqual(code, 3)
        self.assertIn("suggestion: \"", err)


class ReadmeSections(Base):
    def test_set_add_drop(self):
        code, out, err = run("readme", "set", "next", "позвонить в церковь Шорлайна")
        self.assertEqual(code, 0, err)
        self.assertIn("- next: позвонить в церковь Шорлайна", (self.case / "README.md").read_text())
        run("readme", "set", "next", "другое")  # replace, not duplicate
        text = (self.case / "README.md").read_text()
        self.assertEqual(text.count("- next:"), 1)
        code, out, err = run("readme", "add", "links", "docs/contacts.md — кто есть кто")
        self.assertEqual(code, 0, err)
        self.assertIn("- docs/contacts.md — кто есть кто", (self.case / "README.md").read_text())
        code, out, err = run("readme", "add", "problems", "open · нет ответа от пастора")
        self.assertEqual(code, 0, err)
        code, out, err = run("readme", "drop", "problems", "1")
        self.assertEqual(code, 0, err)
        self.assertNotIn("нет ответа от пастора", (self.case / "README.md").read_text())
        self.assertEqual(run("readme", "add", "nosuch", "x")[0], 2)
        self.assertEqual(run("readme", "drop", "problems", "9")[0], 4)


class WarningNoise(Base):
    def test_log_does_not_warn_about_old_lines(self):
        near = "х" * 190
        run("log", "RESULT", near)  # old line close to the limit
        code, out, err = run("log", "DECISION", "короткая свежая запись")
        self.assertEqual(code, 0)
        self.assertNotIn("close to the limit", err, "old lines are check's business, not log's")
        code, out, err = run("check")  # check still reports them
        self.assertIn("close to the limit", err)


class DanglingFolders(Base):
    def test_check_warns_about_folder_missing_from_links(self):
        (self.case / "docs").mkdir()
        (self.case / "docs" / "contract.md").write_text("x\n")
        code, out, err = run("check")
        self.assertEqual(code, 0, "warning, not violation")
        self.assertIn("docs/ (1 file(s)) has no line in README Links", err)
        run("readme", "add", "links", "docs/ — договорённости и письма")
        code, out, err = run("check")
        self.assertNotIn("has no line in README Links", err)


class Hints(Base):
    def test_limits_topic_and_root_hint(self):
        code, out, _ = run("help", "limits")
        self.assertEqual(code, 0)
        self.assertIn("80", out)
        with tempfile.TemporaryDirectory() as other:
            os.chdir(other)
            code, out, err = run()
            self.assertIn("--root", err + out)
            os.chdir(self.tmp.name)
