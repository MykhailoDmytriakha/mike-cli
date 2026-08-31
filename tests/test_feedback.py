"""Regressions from the live feedback of 2026-08-31: date doubling, long events, write deadlock,
focused check."""
import os
import tempfile
import unittest
from pathlib import Path

from mike import grammar, stamp
from tests.test_commands import run


class Feedback(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)
        self.root = Path(self.tmp.name).resolve() / ".cases"
        os.environ.pop("MIKE_CASE", None)

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()

    def test_date_in_name_is_not_doubled(self):
        code, out, err = run("case", "new", "2026-08-31-mle-prod-release-redis", "--goal", "g")
        self.assertEqual(code, 0, err)
        names = [p.name for p in self.root.iterdir() if p.is_dir()]
        self.assertEqual(names, ["2026-08-31-mle-prod-release-redis"])

    def test_case_new_with_long_goal_leaves_a_valid_journal(self):
        goal = "проверить владение Redis и объём релиза MLE " * 8  # ~350 chars
        code, out, err = run("case", "new", "mle prod release", "--goal", goal)
        self.assertEqual(code, 0, err)
        case = next(p for p in self.root.iterdir() if p.is_dir())
        j = grammar.parse_journal((case / "JOURNAL.md").read_text())
        self.assertTrue(j.ok, j.errors)
        code, out, err = run("log", "DECISION", "a later decision must not be blocked")
        self.assertEqual(code, 0, err)

    def test_preexisting_violation_does_not_deadlock_writes(self):
        run("case", "new", "demo case", "--goal", "g")
        case = next(p for p in self.root.iterdir() if p.is_dir())
        # simulate a file written by an older mike: valid stamp over content with a 300-char line
        body, _ = stamp.split((case / "JOURNAL.md").read_text())
        broken = body.replace("  PHASE · дело открыто: g", "  PHASE · " + "x" * 300)
        (case / "JOURNAL.md").write_text(stamp.apply(broken))
        code, out, err = run("log", "DECISION", "new decision goes through")
        self.assertEqual(code, 0, err)
        self.assertIn("new decision goes through", (case / "JOURNAL.md").read_text())
        rec = case / "JOURNAL.md.recover.md"
        self.assertTrue(rec.exists())
        self.assertIn("x" * 300, rec.read_text())

    def test_check_focused_on_one_case(self):
        run("case", "new", "clean case", "--goal", "g")
        run("case", "new", "broken case", "--goal", "g")
        broken = next(p for p in self.root.iterdir() if "broken" in p.name)
        t = broken / "TODO.md"
        t.write_text(t.read_text() + "- [ ] 1 Плохо\n")
        code, out, err = run("check")
        self.assertEqual(code, 3)
        code, out, err = run("--case", "clean-case", "check")
        self.assertEqual(code, 0, err)
        self.assertIn("violations: 0", out)
