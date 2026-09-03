"""Regressions from the Bible Truck live-session feedback (2026-09-01, 2026-09-03): editable TODO,
section-level README edits, warning noise, trim suggestions, dangling folders, move range."""
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
    def test_edit_rewrites_text_and_shows_the_old(self):
        run("todo", "add", "1", "позвонить заказчику")
        code, out, err = run("todo", "edit", "1.1", "позвонить заказчику до пятницы")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.todo().phase(1).items[0].text, "позвонить заказчику до пятницы")
        self.assertIn("was: «позвонить заказчику»", out)
        # P5: an edit is not an event — since 0.9 mike writes no journal line for it (git keeps history)
        self.assertNotIn("todo 1.1", (self.case / "JOURNAL.md").read_text())

    def test_move_reorders_and_renumbers(self):
        for t in ("a", "b", "c", "d"):
            run("todo", "add", "1", t)
        code, out, err = run("todo", "move", "1.4", "1.1")
        self.assertEqual(code, 0, err)
        self.assertEqual([it.text for it in self.todo().phase(1).items], ["d", "a", "b", "c"])
        self.assertEqual([it.m for it in self.todo().phase(1).items], [1, 2, 3, 4])
        self.assertEqual(run("todo", "move", "1.2", "2.1")[0], 2)  # cross-phase → usage error

    def test_drop_removes_and_shows_the_text(self):
        run("todo", "add", "1", "лишний пункт")
        code, out, err = run("todo", "drop", "1.1")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.todo().phase(1).items, [])
        self.assertIn("«лишний пункт»", out)
        self.assertNotIn("лишний пункт", (self.case / "JOURNAL.md").read_text())

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
        code, out, err = run("readme", "add", "problems", "open · нет ответа от заказчика")
        self.assertEqual(code, 0, err)
        code, out, err = run("readme", "drop", "problems", "1")
        self.assertEqual(code, 0, err)
        self.assertNotIn("нет ответа от заказчика", (self.case / "README.md").read_text())
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


class RootCaseCheck(unittest.TestCase):
    """Feedback 2026-09-01 #1: check must verify the project case in root mode; zero is not green."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)
        os.environ.pop("MIKE_CASE", None)

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()

    def test_root_case_violations_are_caught(self):
        run("case", "new", "--root", "bible truck", "--goal", "g")
        t = Path("TODO.md")
        t.write_text(t.read_text().replace("# TODO — bible truck",
                     "# TODO — bible truck\n\n- [ ] 2 Calls\n  - [ ] 2.1 " + "и" * 174))
        code, out, err = run("check")
        self.assertEqual(code, 3, "root-case violation must fail check")
        self.assertIn("F13", err + out)
        self.assertIn("stamp mismatch", err, "stamp mismatch from the hand edit is reported too")

    def test_zero_cases_is_not_a_green_light(self):
        (Path(self.tmp.name) / ".cases").mkdir()
        code, out, err = run("check")
        self.assertEqual(code, 0)
        self.assertIn("NOTHING WAS CHECKED", out)
        self.assertNotIn("violations: 0", out)


class MoveJournaling(Base):
    def test_move_says_renumbering_but_writes_no_journal_noise(self):
        for t in ("первый", "второй", "третий"):
            run("todo", "add", "1", t)
        code, out, err = run("todo", "move", "1.3", "1.1")
        self.assertEqual(code, 0, err)
        self.assertIn("numbers of phase 1 recounted", out)
        j = (self.case / "JOURNAL.md").read_text()
        self.assertNotIn("переставлен", j)
        self.assertEqual(j.count("DECISION"), 0, "a move is an action, not an event (P5)")


class HoldResume(Base):
    def test_hold_groups_at_end_resume_restores(self):
        run("todo", "add", "1", "позвонить в Спокан")
        run("todo", "add", "1", "составить бюджет")
        code, out, err = run("todo", "hold", "1.1", "возможно позвоню позже")
        self.assertEqual(code, 0, err)
        todo_text = (self.case / "TODO.md").read_text()
        self.assertIn("- [~] 1.1 позвонить в Спокан — hold: возможно позвоню позже", todo_text)
        lines = [l for l in todo_text.splitlines() if l.startswith("  - [")]
        self.assertTrue(lines[-1].startswith("  - [~]"), "held items sit at the end")
        self.assertNotIn("отложен", (self.case / "JOURNAL.md").read_text())
        item = self.todo().phase(1).items
        held = next(i for i in item if i.held)
        self.assertEqual((held.text, held.hold_reason), ("позвонить в Спокан", "возможно позвоню позже"))
        run("todo", "resume", "1.1")
        self.assertNotIn("[~]", (self.case / "TODO.md").read_text())

    def test_done_clears_hold(self):
        run("todo", "add", "1", "пункт")
        run("todo", "hold", "1.1", "")
        code, out, err = run("todo", "done", "1.1")
        self.assertEqual(code, 0, err)
        self.assertIn("- [x] 1.1 пункт", (self.case / "TODO.md").read_text())


class VisibleLength(Base):
    def test_markdown_link_counts_as_its_name(self):
        text = "[call-spokane](docs/very/long/path/to/the/call-spokane-notes-file.md) — дозвониться"
        self.assertGreater(len(text), 80)
        code, out, err = run("todo", "add", "1", text)
        self.assertEqual(code, 0, err)
        code, out, err = run("check")
        self.assertEqual(code, 0, err + out)

    def test_edit_keeps_the_journal_clean(self):
        long_text = "очень длинный пункт про поездку в Спокан седьмого сентября с ночёвкой и бюджетом"
        run("todo", "add", "1", long_text)
        code, out, err = run("todo", "edit", "1.1", "короткий текст")
        self.assertEqual(code, 0, err)
        self.assertIn(long_text, out, "the old text is shown to the caller")
        self.assertNotIn(long_text, (self.case / "JOURNAL.md").read_text())


class MoveRange(Base):
    def test_move_past_the_end_is_refused_not_clamped(self):
        # feedback 2026-09-03: `todo move 2.5 2.37` in a 24-item phase answered "now at 2.24" — silently clamped
        for t in ("a", "b", "c"):
            run("todo", "add", "1", t)
        code, out, err = run("todo", "move", "1.1", "1.7")
        self.assertEqual(code, 2)
        self.assertIn("phase 1 has items 1.1–1.3 — there is no 1.7", err)
        self.assertIn("mike todo move 1.1 1.3", err)
        self.assertEqual([it.text for it in self.todo().phase(1).items], ["a", "b", "c"], "nothing moved")
        self.assertEqual(run("todo", "move", "1.1", "1.0")[0], 2)
        code, out, err = run("todo", "move", "1.1", "1.3")
        self.assertEqual(code, 0, err)
        self.assertEqual([it.text for it in self.todo().phase(1).items], ["b", "c", "a"])
