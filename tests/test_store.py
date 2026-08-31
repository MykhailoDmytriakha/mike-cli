"""S2–S4 and C7–C9: rebuild on mismatch, refusal on violations, finding root and hand."""
import os
import tempfile
import unittest
from pathlib import Path

from mike import grammar, recover, stamp, store
from tests.test_grammar import JOURNAL_OK, README_OK, TODO_OK


def make_case(root: Path, name: str, journal=JOURNAL_OK, todo=TODO_OK, readme=README_OK) -> Path:
    case = root / name
    case.mkdir(parents=True)
    (case / "README.md").write_text(stamp.apply(readme))
    (case / "TODO.md").write_text(stamp.apply(todo))
    (case / "JOURNAL.md").write_text(stamp.apply(journal))
    return case


class RecoverTests(unittest.TestCase):
    def test_rebuild_keeps_good_lines_and_moves_bad_ones(self):
        hacked = JOURNAL_OK.replace("  PHASE · case opened\n", "  PHASE · case opened\nhand-written garbage\n  WAIT · not a type\n")
        rebuilt, removed, fatal = recover.rebuild("JOURNAL.md", hacked)
        self.assertEqual(fatal, [])
        self.assertEqual(removed, ["hand-written garbage", "  WAIT · not a type"])
        self.assertTrue(grammar.parse_journal(rebuilt).ok)
        self.assertEqual(stamp.verify(rebuilt), (True, "ok"))

    def test_rebuild_drops_orphaned_events_with_their_header(self):
        hacked = JOURNAL_OK + "- 30.08.2026 bad header\n  RESULT · orphan\n"
        rebuilt, removed, fatal = recover.rebuild("JOURNAL.md", hacked)
        self.assertEqual(fatal, [])
        self.assertEqual(removed, ["- 30.08.2026 bad header", "  RESULT · orphan"])

    def test_rebuild_reports_fatal_for_whole_file_problems(self):
        broken = README_OK.replace("## Links", "## Zzz")
        rebuilt, removed, fatal = recover.rebuild("README.md", broken)
        self.assertIsNone(rebuilt)
        self.assertEqual([f.rule for f in fatal], ["F1"])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        self.root = self.project / ".cases"
        self.root.mkdir()
        self.case = make_case(self.root, "2026-08-30-demo-case")

    def tearDown(self):
        self.tmp.cleanup()

    def test_find_root_walks_up(self):
        deep = self.project / "src" / "pkg"
        deep.mkdir(parents=True)
        self.assertEqual(store.find_root(deep), self.root.resolve())

    def test_find_root_missing(self):
        with tempfile.TemporaryDirectory() as other:
            with self.assertRaises(store.StoreError) as ctx:
                store.find_root(Path(other))
            self.assertEqual(ctx.exception.code, 4)

    def test_hand_picks_freshest_open_case(self):
        older = make_case(self.root, "2026-08-29-older-case")
        os.utime(older / "JOURNAL.md", (1, 1))
        self.assertEqual(store.hand(self.root), self.case)

    def test_hand_by_suffix_and_env(self):
        self.assertEqual(store.hand(self.root, "demo-case"), self.case)
        os.environ["MIKE_CASE"] = "demo-case"
        try:
            self.assertEqual(store.hand(self.root), self.case)
        finally:
            del os.environ["MIKE_CASE"]

    def test_closed_case_is_not_in_hand(self):
        closed_readme = README_OK.replace("## State\n", "## State\n- closed: 2026-08-29 · done\n")
        make_case(self.root, "2026-08-28-closed-case", readme=closed_readme)
        self.assertEqual(store.hand(self.root), self.case)

    def test_write_refuses_violation_and_touches_nothing(self):
        before = (self.case / "JOURNAL.md").read_text()
        with self.assertRaises(store.StoreError) as ctx:
            store.write(self.case, "JOURNAL.md", JOURNAL_OK.replace("DECISION ·", "WAIT ·"))
        self.assertEqual(ctx.exception.code, 3)
        self.assertEqual((self.case / "JOURNAL.md").read_text(), before)

    def test_write_stamps(self):
        report = store.write(self.case, "JOURNAL.md", JOURNAL_OK)
        self.assertIsNone(report.recovered)
        self.assertEqual(stamp.verify((self.case / "JOURNAL.md").read_text()), (True, "ok"))

    def test_write_after_hand_edit_rebuilds_and_recovers(self):
        p = self.case / "JOURNAL.md"
        p.write_text(p.read_text().replace("  PHASE · case opened\n", "  PHASE · case opened\nsneaky line\n"))
        self.assertEqual(stamp.verify(p.read_text())[1], "mismatch")
        report = store.write(self.case, "JOURNAL.md", JOURNAL_OK)
        self.assertEqual(report.recovered, self.case / "JOURNAL.md.recover.md")
        self.assertEqual(report.recovered.read_text(), "sneaky line\n")
        self.assertEqual(stamp.verify(p.read_text()), (True, "ok"))

    def test_valid_hand_edit_is_accepted_without_recover_file(self):
        p = self.case / "JOURNAL.md"
        p.write_text(p.read_text().replace("  PHASE · case opened\n", "  PHASE · case opened\n  DECISION · added by hand, valid\n"))
        self.assertEqual(stamp.verify(p.read_text())[1], "mismatch")
        report = store.check_stamp(self.case, "JOURNAL.md")
        self.assertTrue(report.bypassed)
        self.assertIsNone(report.recovered)
        self.assertIn("added by hand, valid", p.read_text())
        self.assertEqual(stamp.verify(p.read_text()), (True, "ok"))

    def test_chain_for_nested_case(self):
        child = make_case(self.case, "2026-08-31-child-case")
        self.assertEqual(store.chain(child, self.root), ["2026-08-30-demo-case", "2026-08-31-child-case"])
        self.assertIn(child, store.all_cases(self.root))


if __name__ == "__main__":
    unittest.main()
