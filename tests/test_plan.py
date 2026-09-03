"""Planned phases — feedback 2026-09-03 (BibleTruck): a dated deadline outside the current phase had
nowhere to live in TODO; `mike phase plan` names the next phase without opening it (P8: planned ≠ open)."""
import os
import tempfile
import unittest
from pathlib import Path

from mike import grammar
from tests.test_commands import run


class PlannedPhase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)
        os.environ.pop("MIKE_CASE", None)
        run("case", "new", "demo case", "--goal", "g")
        run("phase", "open", "1", "Calls", "--goal", "phone the partners")
        self.case = next(p for p in (Path(self.tmp.name) / ".cases").iterdir() if p.is_dir())

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()

    def read(self, name: str) -> str:
        return (self.case / name).read_text(encoding="utf-8")

    def close_phase_1(self):
        run("log", "RESULT", "calls done")
        run("log", "DECISION", "reflect: x")
        run("log", "DECISION", "align: y")
        code, out, err = run("phase", "close", "1", "partners phoned")
        self.assertEqual(code, 0, err)

    def test_plan_parks_the_next_phase_and_its_items_while_the_current_one_runs(self):
        code, out, err = run("phase", "plan", "2", "Council", "--goal", "agenda for the council on 13 Sept")
        self.assertEqual(code, 0, err)
        self.assertIn("planned: phase 2 Council", out)
        self.assertIn("mike todo add 2", out)
        self.assertIn("- [ ] 2 Council — agenda for the council on 13 Sept", self.read("TODO.md"))
        self.assertFalse((self.case / "phases" / "2-council.md").exists(), "planned is not open: no phase file")
        self.assertIn("- progress: 1 Calls ▶ · 2 Council", self.read("README.md"))
        code, out, err = run("todo", "add", "2", "draft the agenda")
        self.assertEqual(code, 0, err)
        self.assertIn("  - [ ] 2.1 draft the agenda", self.read("TODO.md"))
        code, out, err = run("phase", "open", "2", "Council")
        self.assertEqual(code, 4, "one phase in flight (P8): a planned phase does not open over an open one")
        self.assertIn("phase 1 Calls is still open", err)
        run("log", "RESULT", "first call done")
        journal = grammar.parse_journal(self.read("JOURNAL.md"))
        newest = journal.entries[0]
        self.assertEqual(newest.phase, "p1", "events go to the open phase, not the planned one")
        self.assertTrue(any(ev.text == "first call done" for ev in newest.events))
        self.assertNotIn("Council", self.read("JOURNAL.md"), "a plan is not a journal event (P5)")

    def test_planned_phase_opens_under_its_own_name_and_goal(self):
        run("phase", "plan", "2", "Council", "--goal", "agenda for 13 Sept")
        self.close_phase_1()
        code, out, err = run("phase", "open", "2")
        self.assertEqual(code, 0, err)
        pf = self.case / "phases" / "2-council.md"
        self.assertTrue(pf.exists())
        self.assertIn("goal: agenda for 13 Sept", pf.read_text(encoding="utf-8"))
        self.assertIn("- progress: 1 Calls ✓ · 2 Council ▶", self.read("README.md"))
        self.assertEqual(grammar.parse_todo(self.read("TODO.md")).phase(2).name, "Council")
        self.assertIn("Council открыта", self.read("JOURNAL.md"))

    def test_planned_phase_without_intent_still_needs_a_goal_to_open(self):
        run("phase", "plan", "2", "Council")
        self.assertIn("- [ ] 2 Council\n", self.read("TODO.md"))
        self.close_phase_1()
        code, out, err = run("phase", "open", "2")
        self.assertEqual(code, 2)
        self.assertIn("--goal", err)
        code, out, err = run("phase", "open", "2", "--goal", "agenda")
        self.assertEqual(code, 0, err)

    def test_plan_refuses_a_taken_number_a_bad_name_and_a_long_intent(self):
        code, out, err = run("phase", "plan", "1", "Again", "--goal", "x")
        self.assertEqual(code, 4)
        self.assertIn("phase 1 Calls exists (open)", err)
        self.assertIn('mike phase plan 2 "Again"', err)
        code, out, err = run("phase", "plan", "2", "Совет", "--goal", "x")
        self.assertEqual(code, 2)
        self.assertIn("F13", err)
        code, out, err = run("phase", "plan", "2", "Council", "--goal", "слово " * 30)
        self.assertEqual(code, 3)
        self.assertIn("suggestion:", err)
        run("phase", "plan", "2", "Council")
        code, out, err = run("phase", "plan", "2", "Council")
        self.assertEqual(code, 4)
        self.assertIn("already planned", err)

    def test_open_without_a_name_and_nothing_planned_is_actionable(self):
        self.close_phase_1()
        code, out, err = run("phase", "open", "2")
        self.assertEqual(code, 2)
        self.assertIn("needs a name", err)
        self.assertIn("no planned phase 2", err)


if __name__ == "__main__":
    unittest.main()
