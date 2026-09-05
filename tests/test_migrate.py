"""Legacy case → mike's grammar (P13): the exact shape from the 2026-09-02 feedback — rich Markdown
README, a TODO with `Completed obligations` / `Phase SIT NC` headings, prose and nested evidence,
a journal with dated headings, no stamps anywhere."""
import os
import tempfile
import unittest
from pathlib import Path

from mike import grammar, stamp
from tests.test_commands import run

LEGACY_README = """# PEPFS-33598 SRE SDK ingestion

## Goal
Ingest SRE SDK results into the estimator and validate them against LNP.
Owner: platform team.

## Evidence
- run 2026-08-27: 1 240 rows, 0 rejects
  - nested: reject log empty
- run 2026-08-28: 1 250 rows, 3 rejects

## Decisions
- 2026-08-27 · batch size 500 over 1000 because the SDK times out above 700
- keep the old parser until SIT passes

## Risks
- SDK version drift between SIT and NC

## Timeline
- 08-27 kickoff
- 08-28 first ingestion
"""

LEGACY_TODO = """# TODO

- [x] request SDK credentials
- [ ] confirm ingestion window with the SRE team

## Completed obligations
- [x] wire the SDK client
  - evidence: PR 4412 merged
- [x] map result schema to the estimator tables — this line is deliberately far longer than eighty characters to be trimmed
- [x] smoke test on SIT
Notes: schema mapping reviewed by the data team.

## Phase SIT NC
- [x] load 2026-08-27 batch
- [ ] validate latest LNP SRE results
- [ ] sign-off from NC
"""

LEGACY_JOURNAL = """# Journal

## 2026-08-27 — session 1
- kickoff with the SRE team, credentials requested
- decided: batch size 500

### Evidence
- log excerpt: 0 rejects

## 2026-08-28 — session 2
- first ingestion ran; 3 rejects to investigate
"""


class LegacyCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)
        os.environ.pop("MIKE_CASE", None)
        self.case = Path(self.tmp.name) / ".cases" / "2026-08-27-pepfs-33598-sre-sdk-ingestion"
        self.case.mkdir(parents=True)
        (self.case / "README.md").write_text(LEGACY_README, encoding="utf-8")
        (self.case / "TODO.md").write_text(LEGACY_TODO, encoding="utf-8")
        (self.case / "JOURNAL.md").write_text(LEGACY_JOURNAL, encoding="utf-8")

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()

    def snapshot(self):
        return {n: (self.case / n).read_bytes() for n in ("README.md", "TODO.md", "JOURNAL.md")}

    def test_every_write_refuses_with_the_exact_recovery_and_changes_nothing(self):
        before = self.snapshot()
        for argv in (("log", "RESULT", "validated latest LNP SRE results"),
                     ("readme", "--file", str(self.case / "README.md")),
                     ("todo", "add", "1", "x"),
                     ("readme", "set", "next", "x")):
            code, out, err = run(*argv)
            self.assertEqual(code, 3, argv)
            self.assertIn("never stamped", err, argv)
            self.assertIn("mike migrate", err, argv)
        self.assertEqual(self.snapshot(), before, "a refused write must not touch the legacy files")
        self.assertEqual(list(self.case.glob("*.recover.md")), [], "a legacy file is never gutted into .recover.md")

    def test_entry_and_doctor_name_the_legacy_files(self):
        code, out, err = run()
        self.assertEqual(code, 0, err)
        self.assertIn("legacy file(s) outside mike's grammar", out)
        self.assertIn("mike migrate", out)
        code, out, err = run("doctor")
        self.assertIn("legacy —", out)

    def test_dry_run_reports_the_mapping_and_changes_nothing(self):
        before = self.snapshot()
        code, out, err = run("migrate")
        self.assertEqual(code, 0, err)
        self.assertIn("dry run — nothing changed", out)
        self.assertIn("README: Context ← «Goal»", out)
        self.assertIn("README: Decisions ← «Decisions»", out)
        self.assertIn("README: Problems ← «Risks»", out)
        self.assertIn("README section «Evidence»", out)
        self.assertIn("README section «Timeline»", out)
        self.assertIn("2 Completed obligations (closed)", out)
        self.assertIn("«Phase SIT NC» → «SIT NC»", out)
        self.assertIn("checkbox line(s) before any heading → phase 1 «Legacy»", out)
        self.assertIn("trimmed to 80", out)
        self.assertIn("non-checkbox line(s)", out)
        self.assertIn("JOURNAL:", out)
        self.assertIn("not converted", out)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.case / "legacy").exists())

    def test_apply_archives_byte_for_byte_and_makes_every_command_work(self):
        before = self.snapshot()
        code, out, err = run("migrate", "--apply")
        self.assertEqual(code, 0, err + out)
        archives = list((self.case / "legacy").iterdir())
        self.assertEqual(len(archives), 1)
        for name, raw in before.items():
            self.assertEqual((archives[0] / name).read_bytes(), raw, f"{name} must be archived byte-for-byte")
        for name in ("README.md", "TODO.md", "JOURNAL.md"):
            self.assertEqual(stamp.verify((self.case / name).read_text())[0], True, name)
        todo = grammar.parse_todo((self.case / "TODO.md").read_text())
        self.assertTrue(todo.ok, todo.errors)
        names = [(p.n, p.name, p.done) for p in todo.phases]
        self.assertEqual(names, [(1, "Legacy", False), (2, "Completed obligations", True), (3, "SIT NC", False)])
        self.assertTrue((self.case / "phases" / "2-completed-obligations.md").exists())
        self.assertEqual(len(todo.phase(3).items), 3)
        readme = (self.case / "README.md").read_text()
        self.assertIn("Ingest SRE SDK results", readme)
        self.assertIn("batch size 500", readme)
        self.assertIn("SDK version drift", readme)
        self.assertIn("- legacy/ — файлы дела до миграции", readme)
        self.assertNotIn("Timeline", readme)
        journal = (self.case / "JOURNAL.md").read_text()
        self.assertIn("PHASE · дело перенесено из legacy формата", journal)
        # every write door now opens
        code, out, err = run("log", "RESULT", "validated latest LNP SRE results")
        self.assertEqual(code, 0, err)
        code, out, err = run("readme", "set", "next", "sign-off from NC")
        self.assertEqual(code, 0, err)
        code, out, err = run("todo", "add", "3", "re-run with SDK 2.4")
        self.assertEqual(code, 0, err)
        code, out, err = run("todo", "done", "3.2", "ok")
        self.assertEqual(code, 0, err)
        code, out, err = run("check")
        self.assertEqual(code, 0, err + out)
        code, out, err = run("doctor")
        self.assertEqual(out.count("stamp ok"), 3, out)
        self.assertNotIn("legacy —", out)
        code, out, err = run()
        self.assertEqual(code, 0, err)
        self.assertNotIn("legacy file(s)", out)
        # the archive is never nagged about summaries
        self.assertNotIn("legacy/", out.split("## Order")[1])

    def test_a_phase_closed_by_migration_does_not_block_the_next_one(self):
        (self.case / "TODO.md").write_text("# TODO\n\n## Completed obligations\n- [x] wire the SDK client\n- [x] smoke test on SIT\n", encoding="utf-8")
        code, out, err = run("migrate", "--apply")
        self.assertEqual(code, 0, err + out)
        code, out, err = run("phase", "open", "2", "Validation", "--goal", "NC sign-off")
        self.assertEqual(code, 0, err + out)
        self.assertIn("- [ ] 2 Validation", (self.case / "TODO.md").read_text())

    def test_apply_rolls_back_when_a_write_fails(self):
        before = self.snapshot()
        from mike import migrate, store
        real = store._atomic_write

        def boom(path, text):
            if path.name == "JOURNAL.md":
                raise OSError("disk full")
            real(path, text)
        store._atomic_write = boom
        try:
            code, out, err = run("migrate", "--apply")
        finally:
            store._atomic_write = real
        self.assertEqual(code, 1, err)
        self.assertIn("rolled back", err)
        self.assertEqual(self.snapshot(), before, "originals restored from the archive")
        self.assertFalse((self.case / "phases").exists(), "phase files created before the failure are removed")


class PartlyLegacy(unittest.TestCase):
    """Only one file is legacy: README writes work (readme-only mode), the legacy file is protected."""

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

    def test_readme_writes_work_when_only_todo_is_legacy(self):
        (self.case / "TODO.md").write_text(LEGACY_TODO, encoding="utf-8")
        code, out, err = run("readme", "set", "next", "call the team")
        self.assertEqual(code, 0, err)
        self.assertIn("- next: call the team", (self.case / "README.md").read_text())
        code, out, err = run("readme", "--file", str(self.case / "README.md"))
        self.assertEqual(code, 0, err)
        self.assertIn("progress: not synced", err)
        code, out, err = run("log", "RESULT", "x")
        self.assertEqual(code, 3)
        self.assertIn("mike migrate", err)

    def test_legacy_journal_is_never_rebuilt_into_recover(self):
        (self.case / "JOURNAL.md").write_text(LEGACY_JOURNAL, encoding="utf-8")
        code, out, err = run("log", "RESULT", "x")
        self.assertEqual(code, 3)
        self.assertIn("JOURNAL.md is outside mike's grammar", err)
        self.assertEqual((self.case / "JOURNAL.md").read_text(), LEGACY_JOURNAL)
        self.assertEqual(list(self.case.glob("*.recover.md")), [])
        code, out, err = run("migrate")
        self.assertIn("JOURNAL.md:", out)
        self.assertNotIn("README.md:", out.split("\n")[0])

    def test_current_case_has_nothing_to_migrate(self):
        before = {n: (self.case / n).read_bytes() for n in ("README.md", "TODO.md", "JOURNAL.md")}
        code, out, err = run("migrate", "--apply")
        self.assertEqual(code, 0, err)
        self.assertIn("nothing to migrate", out)
        self.assertEqual({n: (self.case / n).read_bytes() for n in before}, before)
        self.assertFalse((self.case / "legacy").exists())


if __name__ == "__main__":
    unittest.main()
