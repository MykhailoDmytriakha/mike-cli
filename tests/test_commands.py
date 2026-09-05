"""End-to-end: the ten commands on a temporary project, through `main.run` (exit codes, C5)."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path

from mike import grammar, main, stamp


def run(*argv):
    """Run mike with argv; return (code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main.run(list(argv))
    return code, out.getvalue(), err.getvalue()


class Flow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)
        self.root = Path(self.tmp.name).resolve() / ".cases"
        os.environ.pop("MIKE_CASE", None)

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()

    def case(self):
        return next(p for p in self.root.iterdir() if p.is_dir())

    def test_full_flow(self):
        code, out, err = run("case", "new", "connect database", "--goal", "app talks to the prod database")
        self.assertEqual(code, 0, err)
        case = self.case()
        self.assertRegex(case.name, r"^\d{4}-\d{2}-\d{2}-connect-database$")
        for f in ("README.md", "TODO.md", "JOURNAL.md"):
            self.assertEqual(stamp.verify((case / f).read_text()), (True, "ok"), f)

        # entry with no phases yet
        code, out, _ = run()
        self.assertEqual(code, 0)
        self.assertIn("case in hand: " + case.name, out)
        self.assertIn("progress: (no phases yet)", out)

        # open phase 1
        code, out, err = run("phase", "open", "1", "Local setup", "--goal", "app connects locally")
        self.assertEqual(code, 0, err)
        self.assertTrue((case / "phases" / "1-local-setup.md").exists())
        self.assertIn("progress: 1 Local setup ▶", (case / "README.md").read_text())
        # idempotent
        code, out, _ = run("phase", "open", "1", "Local setup")
        self.assertEqual(code, 0)
        self.assertIn("already open", out)

        # items
        self.assertEqual(run("todo", "add", "1", "install the driver")[0], 0)
        self.assertEqual(run("todo", "add", "1", "run the smoke test")[0], 0)
        self.assertEqual(run("todo", "done", "1.1", "ok")[0], 0)
        code, out, _ = run("todo", "done", "1.1", "ok")
        self.assertIn("already done", out)
        self.assertEqual(run("todo", "done", "9.9", "ok")[0], 4)

        # journal
        code, out, err = run("log", "DECISION", "psycopg over asyncpg because the app is sync")
        self.assertEqual(code, 0, err)
        self.assertEqual(run("log", "WAIT", "nope")[0], 2)
        code, out, err = run("log", "RESULT", "long result " * 30)  # long text splits, not refused
        self.assertEqual(code, 0, err)
        self.assertIn("split into headline", err)
        self.assertEqual(run("log", "RESULT", "x" * 2000)[0], 3)  # too long even for headline + body
        j = grammar.parse_journal((case / "JOURNAL.md").read_text())
        self.assertTrue(j.ok, j.errors)
        self.assertEqual(j.entries[0].phase, "p1")

        # close needs RESULT + reflect + align
        code, out, err = run("phase", "close", "1", "local connection works")
        self.assertEqual(code, 4)
        self.assertIn("reflect:", err)
        self.assertIn("align:", err)
        run("log", "RESULT", "local connection works, 12 ms round trip")
        run("log", "DECISION", "reflect: read the driver docs before guessing flags")
        run("log", "DECISION", "align: phase 2 is the server database, not the app")
        code, out, err = run("phase", "close", "1", "local connection works")
        self.assertEqual(code, 4, "F20: an open item holds the phase open")
        self.assertIn("open items 1.2", err)
        run("todo", "cancel", "1.2", "smoke test is not needed locally")  # the second honest end
        code, out, err = run("phase", "close", "1", "local connection works")
        self.assertEqual(code, 0, err)
        todo = grammar.parse_todo((case / "TODO.md").read_text())
        self.assertTrue(todo.ok, todo.errors)
        self.assertTrue(todo.phase(1).done)
        self.assertEqual(todo.phase(1).items, [])
        self.assertIn("phases/1-local-setup.md", todo.phase(1).summary)
        pf = grammar.parse_phase_file((case / "phases" / "1-local-setup.md").read_text())
        self.assertEqual(pf.result, "local connection works")
        self.assertIn("progress: 1 Local setup ✓", (case / "README.md").read_text())

        # phase 2 opens only because phase 1 passed P8
        code, out, err = run("phase", "open", "2", "Server database", "--goal", "database lives on the server")
        self.assertEqual(code, 0, err)
        self.assertEqual(run("phase", "open", "4", "Too far", "--goal", "x")[0], 4)  # phase 2 still open

        # spawn a nested case; hand moves to the child (freshest journal)
        code, out, err = run("spawn", "db unreachable from server", "--goal", "server cannot reach the database")
        self.assertEqual(code, 0, err)
        child = next(p for p in case.iterdir() if p.is_dir() and p.name.endswith("db-unreachable-from-server"))
        self.assertIn("waits: " + child.name, (case / "TODO.md").read_text())
        self.assertIn("- ждёт: " + child.name, (case / "README.md").read_text())
        self.assertIn("parent: " + case.name, (child / "README.md").read_text())
        code, out, _ = run()
        self.assertIn(f"{case.name} › {child.name}", out)

        # parent cannot close phase 2 while it waits; child works and closes
        self.assertEqual(run("--case", case.name, "phase", "close", "2", "x")[0], 4)
        run("phase", "open", "1", "Diagnose", "--goal", "find why")
        run("log", "RESULT", "firewall blocks 5432 → rule added")
        run("log", "DECISION", "reflect: check the firewall first next time")
        run("log", "DECISION", "align: nothing left")
        self.assertEqual(run("phase", "close", "1", "firewall opened")[0], 0)
        code, out, err = run("done", "firewall rule on 5432")
        self.assertEqual(code, 0, err)
        ptodo = grammar.parse_todo((case / "TODO.md").read_text())
        self.assertEqual(ptodo.phase(2).waits, [])
        self.assertEqual(ptodo.phase(2).items[0].text, f"firewall rule on 5432 · {child.name}/")
        self.assertNotIn("- ждёт:", (case / "README.md").read_text())
        self.assertIn("closed: ", (child / "README.md").read_text())
        # hand is back on the parent
        code, out, _ = run()
        self.assertIn("case in hand: " + case.name + "\n", out)

        # check is clean and logs nothing
        code, out, err = run("check")
        self.assertEqual(code, 0, err + out)
        self.assertIn("violations: 0", out)
        self.assertFalse((self.root / "checks.log").exists())

    def test_hand_edit_is_rebuilt_on_next_write(self):
        run("case", "new", "demo case", "--goal", "g")
        case = self.case()
        run("phase", "open", "1", "Start", "--goal", "g")
        j = case / "JOURNAL.md"
        j.write_text(j.read_text().replace("\n- ", "\nSOMEONE WROTE THIS\n- ", 1))
        code, out, err = run("log", "RESULT", "fine")
        self.assertEqual(code, 0, err)
        self.assertIn("bypassing mike", err)
        self.assertTrue((case / "JOURNAL.md.recover.md").exists())
        self.assertEqual((case / "JOURNAL.md.recover.md").read_text(), "SOMEONE WROTE THIS\n")
        code, out, _ = run()
        self.assertEqual(code, 0)
        code, out, err = run("check")
        self.assertIn("pending JOURNAL.md.recover.md", err)

    def test_check_logs_violations(self):
        run("case", "new", "demo case", "--goal", "g")
        case = self.case()
        t = case / "TODO.md"
        t.write_text(t.read_text().replace("# TODO", "# TODO") + "- [ ] 1 Концепция\n")
        code, out, err = run("check")
        self.assertEqual(code, 3)
        self.assertIn("F13", err)
        self.assertTrue((self.root / "checks.log").exists())
        self.assertIn("F13", (self.root / "checks.log").read_text())

    def test_no_cases_dir(self):
        with tempfile.TemporaryDirectory() as other:
            os.chdir(other)
            code, out, err = run()
            self.assertEqual(code, 4)
            self.assertIn("no `.cases/`", err)
            os.chdir(self.tmp.name)

    def test_unknown_command_is_a_hard_failure(self):
        with self.assertRaises(SystemExit) as ctx:
            run("lgo", "RESULT", "x")
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()


class CaseContext(unittest.TestCase):
    """`mike case list` and `mike case use` — the hand as a switchable context, no state file."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)
        self.root = Path(self.tmp.name).resolve() / ".cases"
        os.environ.pop("MIKE_CASE", None)
        run("case", "new", "first case", "--goal", "g1")
        run("case", "new", "second case", "--goal", "g2")

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()

    def test_hand_follows_last_touched_and_use_switches(self):
        code, out, _ = run()
        self.assertIn("second-case", out.splitlines()[0])
        self.assertIn("other open cases:", out)
        code, out, err = run("case", "use", "first-case")
        self.assertEqual(code, 0, err)
        code, out, _ = run()
        self.assertIn("first-case", out.splitlines()[0])

    def test_list_marks_current_and_shows_state(self):
        run("case", "use", "first-case")
        code, out, err = run("case", "list")
        self.assertEqual(code, 0, err)
        first = next(l for l in out.splitlines() if "first-case" in l)
        second = next(l for l in out.splitlines() if "second-case" in l)
        self.assertTrue(first.startswith("*"), first)
        self.assertTrue(second.startswith(" "), second)
        self.assertIn("phases 0/0", first)
        self.assertFalse((self.root / ".current").exists(), "no state file anywhere")

    def test_use_closed_case_refused(self):
        run("case", "use", "first-case")
        run("done", "closed early")
        code, out, err = run("case", "use", "first-case")
        self.assertEqual(code, 4)
        self.assertIn("closed", err)

    def test_use_unknown_case(self):
        self.assertEqual(run("case", "use", "no-such")[0], 4)
        self.assertEqual(run("case", "use")[0], 2)
