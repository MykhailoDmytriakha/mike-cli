"""F0–F13: grammars of README, TODO, JOURNAL and the phase file — correctness and breakage."""
import unittest

from mike import grammar, stamp

JOURNAL_OK = """# JOURNAL — demo

- 2026-08-30 00:10 · p2
  DECISION · chose X over Y because Z
  RESULT · thing works: 120 ms → 48 ms
    detail line one
- 2026-08-29 11:00 · p1
  PHASE · case opened
  RESULT · research done · research/x.md
"""

TODO_OK = """# TODO — demo

- [x] 1 Research — sources gathered · 2026-08-29 · no problems · phases/1-research.md
- [ ] 2 Concept
  - [x] 2.1 pick the folder name
  - [ ] 2.2 write the grammar
  - waits: 2026-08-30-some-child
- [ ] 3 CLI core
"""

README_OK = """# Demo case

## Context
Goal in the owner's words.

## State
- progress: 1 Research ✓ · 2 Concept ▶ · 3 CLI core
- next: write the grammar

## Decisions
- 2026-08-29 · `.cases/` instead of `projects/` · root is the project

## Problems
- open · limits not measured

## Links
- `research/` — what the agent found
"""

PHASE_OK = """# Phase 2 — Concept
goal: agree the structure before code
result:

Free body: findings, dead ends, drafts.
"""


def rules(findings):
    return [f.rule for f in findings]


class JournalTests(unittest.TestCase):
    def test_valid(self):
        r = grammar.parse_journal(stamp.apply(JOURNAL_OK))
        self.assertTrue(r.ok, r.errors)
        self.assertEqual(r.stamp_state, "ok")
        self.assertEqual([e.phase for e in r.entries], ["p2", "p1"])
        self.assertEqual(len(r.entries[0].events), 2)
        self.assertEqual(r.entries[0].events[1].body, ["detail line one"])
        self.assertEqual(r.phases_with_result(), {"p1", "p2"})

    def test_missing_stamp_is_reported_not_fatal(self):
        r = grammar.parse_journal(JOURNAL_OK)
        self.assertTrue(r.ok)
        self.assertEqual(r.stamp_state, "missing")

    def test_unknown_type(self):
        r = grammar.parse_journal(JOURNAL_OK.replace("DECISION ·", "WAIT ·"))
        self.assertIn("F8", rules(r.errors))

    def test_event_too_long(self):
        r = grammar.parse_journal(JOURNAL_OK.replace("chose X over Y because Z", "x" * 201))
        self.assertIn("F7", rules(r.errors))

    def test_event_near_limit_warns(self):
        r = grammar.parse_journal(JOURNAL_OK.replace("chose X over Y because Z", "x" * 185))
        self.assertTrue(r.ok)
        self.assertIn("F7", rules(r.warnings))

    def test_oldest_first_is_rejected(self):
        swapped = JOURNAL_OK.replace("2026-08-30 00:10", "2026-08-28 00:10")
        r = grammar.parse_journal(swapped)
        self.assertIn("F7", rules(r.errors))

    def test_entry_without_events(self):
        r = grammar.parse_journal(JOURNAL_OK + "- 2026-08-28 09:00 · p1\n")
        self.assertIn("F7", rules(r.errors))

    def test_unparsable_line(self):
        r = grammar.parse_journal(JOURNAL_OK.replace("  PHASE · case opened", "PHASE case opened"))
        self.assertIn("F7", rules(r.errors))

    def test_body_too_long(self):
        long_body = JOURNAL_OK.replace("    detail line one\n", "    d\n" * 6)
        r = grammar.parse_journal(long_body)
        self.assertIn("F7", rules(r.errors))

    def test_missing_title(self):
        r = grammar.parse_journal(JOURNAL_OK.replace("# JOURNAL — demo\n", ""))
        self.assertIn("F0", rules(r.errors))


class TodoTests(unittest.TestCase):
    def test_valid(self):
        r = grammar.parse_todo(TODO_OK)
        self.assertTrue(r.ok, r.errors)
        self.assertEqual(r.closed(), {1})
        self.assertEqual(r.current().n, 2)
        self.assertEqual(r.phase(2).waits, ["2026-08-30-some-child"])
        self.assertEqual([it.done for it in r.phase(2).items], [True, False])

    def test_open_phase_may_carry_intent(self):
        r = grammar.parse_todo(TODO_OK.replace("- [ ] 3 CLI core", "- [ ] 3 CLI core — commands, stamp, entry screen"))
        self.assertTrue(r.ok, r.errors)
        self.assertEqual(r.warnings, [])
        self.assertEqual(r.phase(3).summary, "commands, stamp, entry screen")

    def test_closed_phase_without_summary(self):
        r = grammar.parse_todo(TODO_OK.replace(" — sources gathered · 2026-08-29 · no problems · phases/1-research.md", ""))
        self.assertIn("F5", rules(r.errors))

    def test_closed_phase_summary_without_phase_file(self):
        r = grammar.parse_todo(TODO_OK.replace(" · phases/1-research.md", ""))
        self.assertIn("F5", rules(r.errors))

    def test_closed_phase_with_items(self):
        r = grammar.parse_todo(TODO_OK.replace("- [x] 1 Research —", "- [x] 1 Research —").replace(
            "- [ ] 2 Concept\n", "- [ ] 2 Concept\n") + "  - [ ] 3.1 x\n")
        self.assertTrue(r.ok)  # 3.1 under open phase 3 is fine
        r2 = grammar.parse_todo(TODO_OK.replace("phases/1-research.md\n", "phases/1-research.md\n  - [x] 1.1 old item\n"))
        self.assertIn("F5", rules(r2.errors))

    def test_phase_name_not_english(self):
        r = grammar.parse_todo(TODO_OK.replace("2 Concept", "2 Концепция"))
        self.assertIn("F13", rules(r.errors))

    def test_phase_name_too_many_words(self):
        r = grammar.parse_todo(TODO_OK.replace("2 Concept", "2 Concept of the whole thing"))
        self.assertIn("F13", rules(r.errors))

    def test_item_too_long(self):
        r = grammar.parse_todo(TODO_OK.replace("write the grammar", "w" * 81))
        self.assertIn("F13", rules(r.errors))

    def test_third_level_rejected(self):
        r = grammar.parse_todo(TODO_OK.replace("  - [ ] 2.2 write the grammar\n", "  - [ ] 2.2 write the grammar\n    - [ ] 2.2.1 deeper\n"))
        self.assertIn("F13", rules(r.errors))

    def test_item_under_wrong_phase(self):
        r = grammar.parse_todo(TODO_OK.replace("  - [ ] 2.2", "  - [ ] 3.2"))
        self.assertIn("F4", rules(r.errors))

    def test_free_note_line_rejected(self):
        r = grammar.parse_todo(TODO_OK + "  - not in scope: hooks\n")
        self.assertIn("F4", rules(r.errors))

    def test_too_many_lines(self):
        r = grammar.parse_todo(TODO_OK + "".join(f"  - [ ] 3.{i} item\n" for i in range(1, 100)))
        self.assertIn("F4", rules(r.errors))


class ReadmeTests(unittest.TestCase):
    def test_valid(self):
        r = grammar.parse_readme(README_OK)
        self.assertTrue(r.ok, r.errors)
        self.assertEqual(list(r.sections), grammar.README_SECTIONS)
        self.assertEqual(r.warnings, [])

    def test_wrong_order(self):
        r = grammar.parse_readme(README_OK.replace("## State", "## Zzz").replace("## Decisions", "## State").replace("## Zzz", "## Decisions"))
        self.assertIn("F1", rules(r.errors))

    def test_extra_section(self):
        r = grammar.parse_readme(README_OK + "\n## How-to\n- x\n")
        self.assertIn("F1", rules(r.errors))

    def test_missing_section(self):
        r = grammar.parse_readme(README_OK.replace("## Problems\n- open · limits not measured\n\n", ""))
        self.assertIn("F1", rules(r.errors))

    def test_text_before_first_section(self):
        r = grammar.parse_readme(README_OK.replace("# Demo case\n", "# Demo case\nstray text\n"))
        self.assertIn("F1", rules(r.errors))

    def test_no_progress_line_warns(self):
        r = grammar.parse_readme(README_OK.replace("- progress: 1 Research ✓ · 2 Concept ▶ · 3 CLI core\n", ""))
        self.assertTrue(r.ok)
        self.assertIn("F3", rules(r.warnings))

    def test_long_pointer_warns(self):
        r = grammar.parse_readme(README_OK.replace("- open · limits not measured", "- " + "o" * 160))
        self.assertTrue(r.ok)
        self.assertIn("F2", rules(r.warnings))

    def test_size_warning_and_limit(self):
        padding = "".join(f"- line {i}\n" for i in range(210))
        r = grammar.parse_readme(README_OK + padding)
        self.assertTrue(r.ok)
        self.assertIn("F2", rules(r.warnings))
        padding = "".join(f"- line {i}\n" for i in range(310))
        r = grammar.parse_readme(README_OK + padding)
        self.assertIn("F2", rules(r.errors))


class PhaseFileTests(unittest.TestCase):
    def test_valid(self):
        r = grammar.parse_phase_file(PHASE_OK)
        self.assertTrue(r.ok, r.errors)
        self.assertEqual((r.n, r.name, r.goal, r.result), (2, "Concept", "agree the structure before code", ""))

    def test_result_filled(self):
        r = grammar.parse_phase_file(PHASE_OK.replace("result:\n", "result: done and agreed\n"))
        self.assertEqual(r.result, "done and agreed")

    def test_missing_goal(self):
        r = grammar.parse_phase_file(PHASE_OK.replace("goal: agree the structure before code", "goal:"))
        self.assertIn("F12", rules(r.errors))

    def test_bad_title(self):
        r = grammar.parse_phase_file(PHASE_OK.replace("# Phase 2 — Concept", "# Concept"))
        self.assertIn("F12", rules(r.errors))

    def test_checklist_rejected(self):
        r = grammar.parse_phase_file(PHASE_OK + "- [ ] 2.1 duplicate of TODO\n")
        self.assertIn("F12", rules(r.errors))


if __name__ == "__main__":
    unittest.main()
