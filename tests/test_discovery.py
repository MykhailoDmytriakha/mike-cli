"""Regression tests for case discovery (bug report 2026-08-31): uppercase names, legacy
lowercase filenames, invalid dirs are diagnosed — never silently ignored."""
import os
import tempfile
import unittest
from pathlib import Path

from mike import stamp, store
from tests.test_commands import run
from tests.test_grammar import JOURNAL_OK, README_OK, TODO_OK
from tests.test_store import make_case


class Discovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)
        self.root = Path(self.tmp.name).resolve() / ".cases"
        self.root.mkdir()
        os.environ.pop("MIKE_CASE", None)

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()

    # --- names: lowercase, UPPERCASE, MixedCase are all detected; original name preserved ---
    def test_upper_mixed_and_lower_names_are_detected(self):
        names = [
            "2026-08-27-PEPFS-33598-sre-sdk-ingestion",
            "2026-08-27-pepfs-33598-sre-sdk-ingestion2",
            "2026-08-27-PepFs-33598-SRE-SDK-ingestion3",
        ]
        for n in names:
            make_case(self.root, n)
        found = [c.name for c in store.all_cases(self.root)]
        self.assertEqual(sorted(found), sorted(names), "original directory names preserved as-is")

    def test_no_word_count_limit(self):
        long_name = "2026-08-27-" + "-".join(f"w{i}" for i in range(9))
        make_case(self.root, long_name)
        self.assertEqual(store.all_cases(self.root)[0].name, long_name)

    # --- invalid dirs are diagnosed, not silently ignored ---
    def test_invalid_dirs_are_reported_with_reasons(self):
        (self.root / "notes").mkdir()
        (self.root / "2026-08-27-").mkdir()
        (self.root / "2026-08-27-плохое-имя").mkdir()
        cases, rejected = store.scan(self.root)
        self.assertEqual(cases, [])
        reasons = {p.name: r for p, r in rejected}
        self.assertIn("date prefix", reasons["notes"])
        self.assertIn("empty name after the date", reasons["2026-08-27-"])
        self.assertIn("invalid characters", reasons["2026-08-27-плохое-имя"])

    def test_case_list_and_check_print_diagnostics(self):
        (self.root / "2026-08-27-").mkdir()
        code, out, err = run("case", "list")
        self.assertEqual(code, 0)
        self.assertIn("not a case, ignored: 2026-08-27-", err)
        self.assertIn("no cases yet", out)
        make_case(self.root, "2026-08-27-PEPFS-33598-sre-sdk-ingestion")
        code, out, err = run("check")
        self.assertEqual(code, 0, err)
        self.assertIn("not a case, ignored: 2026-08-27-", err)

    # --- hand / use / selection with uppercase dirs ---
    def test_hand_and_use_with_uppercase_dir(self):
        make_case(self.root, "2026-08-27-PEPFS-33598-sre-sdk-ingestion")
        self.assertEqual(store.hand(self.root).name, "2026-08-27-PEPFS-33598-sre-sdk-ingestion")
        code, out, err = run("case", "use", "pepfs-33598-sre-sdk-ingestion")  # lowercase suffix
        self.assertEqual(code, 0, err)
        code, out, _ = run()
        self.assertIn("PEPFS-33598-sre-sdk-ingestion", out.splitlines()[0])

    # --- legacy lowercase filenames: one resolver everywhere, written back in place ---
    def _make_legacy(self, name="2026-08-27-legacy-case"):
        case = make_case(self.root, name)
        (case / "TODO.md").rename(case / "todo.md")
        (case / "JOURNAL.md").rename(case / "journal.md")
        return case

    def test_legacy_filenames_read_written_in_place(self):
        case = self._make_legacy()
        self.assertTrue(store.is_open(case))
        self.assertEqual(store.hand(self.root), case)
        code, out, err = run("log", "DECISION", "written into the legacy file")
        self.assertEqual(code, 0, err)
        names = {p.name for p in case.iterdir() if p.is_file()}
        self.assertIn("journal.md", names, "legacy file kept under its own name")
        self.assertNotIn("JOURNAL.md", names, "no canonical duplicate, no silent rename (macOS!)")
        self.assertIn("written into the legacy file", (case / "journal.md").read_text())
        self.assertEqual(stamp.verify((case / "journal.md").read_text()), (True, "ok"))
        code, out, err = run("case", "list")
        self.assertEqual(code, 0, err)
        self.assertIn("phases 1/3", out)

    def test_legacy_recover_file_named_after_actual_file(self):
        case = self._make_legacy()
        j = case / "journal.md"
        j.write_text(j.read_text().replace("  PHASE · case opened\n", "  PHASE · case opened\ngarbage\n"))
        code, out, err = run("log", "RESULT", "fine")
        self.assertEqual(code, 0, err)
        self.assertTrue((case / "journal.md.recover.md").exists())

    def test_canonical_uppercase_filenames_still_work(self):
        case = make_case(self.root, "2026-08-27-canonical-case")
        code, out, err = run("log", "RESULT", "fine")
        self.assertEqual(code, 0, err)
        self.assertIn("fine", (case / "JOURNAL.md").read_text())


if __name__ == "__main__":
    unittest.main()
