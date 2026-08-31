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


class PhaseReference(unittest.TestCase):
    """Feedback 2026-08-31 #2: --phase accepts what the user sees; canonical pN stays in JOURNAL."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)
        self.root = Path(self.tmp.name).resolve() / ".cases"
        os.environ.pop("MIKE_CASE", None)
        run("case", "new", "feedback probe", "--goal", "probe")
        run("phase", "open", "1", "Release validation", "--goal", "probe")

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()

    def journal(self):
        case = next(p for p in self.root.iterdir() if p.is_dir())
        return (case / "JOURNAL.md").read_text()

    def test_accepts_p1_bare_number_and_unique_name(self):
        self.assertEqual(run("log", "--phase", "p1", "DECISION", "by id")[0], 0)
        self.assertEqual(run("log", "--phase", "1", "DECISION", "by number")[0], 0)
        self.assertEqual(run("log", "--phase", "Release validation", "DECISION", "by name")[0], 0)
        j = self.journal()
        for probe in ("by id", "by number", "by name"):
            self.assertIn(probe, j)
        self.assertNotIn("· pRelease", j, "canonical pN preserved in JOURNAL")

    def test_unknown_reference_is_actionable(self):
        code, out, err = run("log", "--phase", "No Such Phase", "DECISION", "x")
        self.assertEqual(code, 2)
        self.assertIn("mike log --phase p1", err)
        self.assertIn("p1 Release validation", err)


class FeedbackCommand(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)
        os.environ["MIKE_FEEDBACK_DIR"] = str(Path(self.tmp.name) / "pool")
        run("case", "new", "probe case", "--goal", "g")

    def tearDown(self):
        del os.environ["MIKE_FEEDBACK_DIR"]
        os.chdir(self.old)
        self.tmp.cleanup()

    def test_writes_artifact_and_prints_path(self):
        code, out, err = run("feedback", "log rejects names", "--actual", "exit 2 on visible name",
                             "--expected", "resolve or hint", "--repro", "mike log --phase 'Release validation' …")
        self.assertEqual(code, 0, err)
        self.assertIn("feedback written: ", out)
        path = Path(out.split("feedback written: ", 1)[1].strip())
        text = path.read_text()
        for piece in ("# log rejects names", "## Reproduction", "## Actual", "## Expected", "case: "):
            self.assertIn(piece, text)

    def test_malformed_feedback_refused(self):
        self.assertEqual(run("feedback", "only a title")[0], 2)
        self.assertFalse(any(Path(os.environ["MIKE_FEEDBACK_DIR"]).glob("*")) if Path(os.environ["MIKE_FEEDBACK_DIR"]).exists() else False)


class HelpTopics(unittest.TestCase):
    """Knowledge doses inside the tool: `mike help <topic>`."""

    def test_every_topic_prints(self):
        from mike import knowledge
        for topic in knowledge.TOPICS:
            code, out, err = run("help", topic)
            self.assertEqual(code, 0, f"{topic}: {err}")
            self.assertGreater(len(out.strip()), 100, topic)

    def test_help_lists_topics_and_unknown_is_actionable(self):
        code, out, _ = run("help")
        self.assertEqual(code, 0)
        self.assertIn("topics (open at the moment of need)", out)
        code, out, err = run("help", "nope")
        self.assertEqual(code, 2)
        self.assertIn("journal", err)
