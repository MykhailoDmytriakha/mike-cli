"""Order (F14, F15, S5, P12): the case keeps itself tidy — summaries, rendered Links, duplicates,
budgets, the `as of` anchor and the `## Order` block on every entry."""
import os
import tempfile
import unittest
from pathlib import Path

from mike import grammar, order
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

    def doc(self, rel: str, text: str):
        p = self.case / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def readme(self) -> str:
        return (self.case / "README.md").read_text(encoding="utf-8")


class Summaries(Base):
    def test_summary_is_read_from_the_first_lines(self):
        p = self.doc("docs/a.md", "← [README](../README.md)\n# Title\nsummary:  what  this file  is\n\nbody\n")
        self.assertEqual(order.read_summary(p), "what this file is")
        self.assertIsNone(order.read_summary(self.doc("docs/b.md", "# No summary\n\nbody\n")))

    def test_links_are_rendered_from_the_files_on_entry(self):
        self.doc("docs/a.md", "# A\nsummary: лист под звонок\n")
        self.doc("docs/b.md", "# B\n\nno summary here\n")
        self.doc("docs/build.sh", "echo hi\n")
        run("readme", "add", "links", "docs/ — рабочие документы")
        code, out, err = run()
        self.assertEqual(code, 0, err)
        r = self.readme()
        self.assertIn("- docs/ — рабочие документы", r)
        self.assertIn("  - [a.md](docs/a.md) — лист под звонок", r)
        self.assertIn("  - [b.md](docs/b.md) — summary: missing", r)
        self.assertIn("  - other: build.sh", r)
        self.assertIn("1 file(s) without `summary:` — docs/b.md", out)

    def test_folder_without_description_gets_a_placeholder_and_an_order_line(self):
        self.doc("research/facts.md", "# F\nsummary: факты\n")
        code, out, err = run()
        self.assertEqual(code, 0, err)
        self.assertIn('- research/ — (describe this folder: mike readme add links "research/ — …")', self.readme())
        self.assertIn("folder research/ has no description", out)
        run("readme", "add", "links", "research/ — установленные факты")
        code, out, err = run()
        self.assertNotIn("folder research/ has no description", out)
        self.assertNotIn("describe this folder", self.readme())
        self.assertIn("- research/ — установленные факты", self.readme())

    def test_manual_lines_about_the_outside_world_stay_in_order(self):
        run("readme", "add", "links", "Jira PROJ-12 — тикет заказчика")
        run("readme", "add", "links", "Иван — кого спросить про базу")
        self.doc("docs/a.md", "# A\nsummary: s\n")
        run()
        links = grammar.parse_readme(self.readme()).sections["Links"]
        self.assertEqual(links[0], "- Jira PROJ-12 — тикет заказчика")
        self.assertEqual(links[1], "- Иван — кого спросить про базу")
        self.assertTrue(any(l.startswith("- docs/") for l in links))

    def test_adopt_moves_link_descriptions_into_the_files(self):
        self.doc("docs/a.md", "# A\n\nbody\n")
        run("readme", "add", "links", "docs/ — документы")
        run("readme", "add", "links", "[a.md](docs/a.md) — описание из Links")
        code, out, err = run()  # description survives as a fallback
        self.assertIn("  - [a.md](docs/a.md) — описание из Links", self.readme())
        code, out, err = run("order", "--adopt")
        self.assertEqual(code, 0, err)
        self.assertIn("summary written into docs/a.md", out)
        self.assertEqual((self.case / "docs/a.md").read_text().split("\n")[1], "summary: описание из Links")
        self.assertNotIn("without `summary:`", out)

    def test_phases_are_described_by_goal_then_result(self):
        code, out, err = run()
        self.assertIn("  - [1-work.md](phases/1-work.md) — g", self.readme())


class Duplicates(Base):
    def test_two_files_with_the_same_words_are_named(self):
        words = " ".join(f"слово{i}" for i in range(60))
        self.doc("docs/one.md", f"# One\nsummary: a\n{words}\n")
        self.doc("docs/two.md", f"# Two\nsummary: b\n{words} ещё немного других слов здесь\n")
        self.doc("docs/other.md", "# Other\nsummary: c\n" + " ".join(f"иное{i}" for i in range(60)) + "\n")
        code, out, err = run()
        self.assertIn("docs/one.md ≈ docs/two.md", out)
        self.assertNotIn("docs/other.md ≈", out)
        code, out, err = run("check")
        self.assertEqual(code, 0, "duplicates are shown, never refused")
        self.assertIn("order · docs/one.md ≈ docs/two.md", err)

    def test_budgets_name_the_big_file_and_folder(self):
        self.doc("docs/big.md", "# Big\nsummary: s\n" + ("слово " * 4000) + "\n")
        code, out, err = run()
        self.assertIn("docs/big.md is", out)
        self.assertIn("split by summary or trim", out)
        for i in range(4):
            self.doc(f"docs/f{i}.md", f"# F{i}\nsummary: s{i}\n" + (f"текст{i} " * 3000) + "\n")
        code, out, err = run()
        self.assertIn("docs/ is", out)
        self.assertIn("merge or delete before adding", out)


class Anchor(Base):
    def test_state_is_anchored_and_falls_behind_after_a_result(self):
        r = self.readme()
        self.assertRegex(r, r"- as of: \d{4}-\d{2}-\d{2} \d{2}:\d{2} · p0 \(1 event\)")
        code, out, err = run()
        self.assertIn("State is behind", out, "opening a phase is a PHASE event: `next:` still says open phase 1")
        self.assertIn("1 PHASE", out)
        run("readme", "set", "next", "первый пункт фазы")
        code, out, err = run()
        self.assertIn("✓ everything in place", out)
        run("log", "RESULT", "замер снят: 48 ms")
        code, out, err = run()
        self.assertIn("State is behind", out)
        self.assertIn("1 RESULT", out)
        self.assertIn("- last: замер снят: 48 ms", self.readme(), "last: follows the newest RESULT")
        run("readme", "set", "next", "снять второй замер")
        code, out, err = run()
        self.assertNotIn("State is behind", out)
        self.assertIn("✓ everything in place", out)

    def test_phase_close_makes_state_behind_until_rewritten(self):
        run("log", "RESULT", "готово")
        run("log", "DECISION", "reflect: урок")
        run("log", "DECISION", "align: план")
        run("readme", "set", "next", "закрыть фазу")
        code, out, err = run("phase", "close", "1", "сделано")
        self.assertEqual(code, 0, err)
        code, out, err = run()
        self.assertIn("State is behind", out)
        self.assertIn("1 PHASE", out)

    def test_missing_anchor_is_asked_for_once_results_exist(self):
        text = self.readme().replace("\n- as of:", "\n- was:")
        (self.case / "README.md").write_text(text)  # a legacy README without the anchor
        run("log", "RESULT", "x")
        code, out, err = run()
        self.assertIn("State has no `as of` anchor", out)


class Entry(Base):
    def test_journal_shows_headlines_only_and_hides_legacy_noise(self):
        run("log", "RESULT", "короткий результат")
        run("log", "DECISION", "решение " * 40)  # splits into headline + body
        j = (self.case / "JOURNAL.md").read_text()
        j = j.replace("  RESULT · короткий результат", "  DECISION · todo 1.1: «старое» → новый текст в TODO\n  RESULT · короткий результат")
        (self.case / "JOURNAL.md").write_text(j)  # legacy v0.7 noise, written by hand → stamp mismatch is fine here
        code, out, err = run()
        self.assertEqual(code, 0, err)
        self.assertIn("headlines; bodies in JOURNAL.md", out)
        self.assertIn("RESULT · короткий результат", out)
        self.assertNotIn("todo 1.1", out)
        self.assertNotIn("\n    ", out.split("# JOURNAL")[1].split("## Order")[0], "no body lines on entry")

    def test_entry_ends_with_order_and_instructions(self):
        code, out, err = run()
        self.assertIn("## Order", out)
        self.assertIn("how to work: mike help start", out)

    def test_no_cases_prints_onboarding(self):
        with tempfile.TemporaryDirectory() as empty:
            os.chdir(empty)
            code, out, err = run()
            self.assertEqual(code, 4)
            self.assertIn("start here", out)
            self.assertIn("mike case new", out)
            os.chdir(self.tmp.name)


class PhaseRename(Base):
    def test_opening_a_planned_phase_under_a_new_name_renames_it(self):
        run("log", "RESULT", "r")
        run("log", "DECISION", "reflect: x")
        run("log", "DECISION", "align: y")
        run("phase", "close", "1", "done")
        todo = grammar.parse_todo((self.case / "TODO.md").read_text())
        todo.phases.append(grammar.Phase(2, "Agent hookup", False, 0))
        from mike import commands, store
        store.write(self.case, "TODO.md", commands.render_todo(todo))  # a planned phase 2
        code, out, err = run("phase", "open", "2", "Order", "--goal", "tidy by itself")
        self.assertEqual(code, 0, err)
        self.assertTrue((self.case / "phases" / "2-order.md").exists())
        self.assertIn("- [ ] 2 Order", (self.case / "TODO.md").read_text())
        self.assertNotIn("Agent hookup", (self.case / "TODO.md").read_text())
        self.assertIn("запланирована была как «Agent hookup»", (self.case / "JOURNAL.md").read_text())


class RootMode(unittest.TestCase):
    def test_root_mode_scans_only_known_kinds_and_listed_folders(self):
        tmp = tempfile.TemporaryDirectory()
        old = os.getcwd()
        os.chdir(tmp.name)
        try:
            run("case", "new", "--root", "my app", "--goal", "g")
            project = Path(tmp.name)
            (project / "src").mkdir()
            (project / "src" / "notes.md").write_text("# src notes\n")
            (project / "docs").mkdir()
            (project / "docs" / "plan.md").write_text("# plan\nsummary: план\n")
            code, out, err = run()
            self.assertEqual(code, 0, err)
            r = (project / "README.md").read_text()
            self.assertIn("  - [plan.md](docs/plan.md) — план", r)
            self.assertNotIn("src/", r, "source folders are not case content")
            self.assertNotIn("src/notes.md", out)
        finally:
            os.chdir(old)
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
