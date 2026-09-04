"""A live project re-cuts itself daily — feedback 2026-09-03 (wish): dates the tool can count,
cancel as an honest state, items moving across phases, files moving with their links intact."""
import datetime as dt
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
        run("phase", "open", "1", "Build", "--goal", "g")
        self.case = next(p for p in (Path(self.tmp.name) / ".cases").iterdir() if p.is_dir())

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()

    def read(self, name: str) -> str:
        return (self.case / name).read_text(encoding="utf-8")

    def todo(self) -> grammar.Todo:
        return grammar.parse_todo(self.read("TODO.md"))

    def doc(self, rel: str, text: str):
        p = self.case / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p


class Dates(Base):
    def test_due_suffix_is_parsed_rendered_and_counted_on_entry(self):
        today = dt.date.today()
        yesterday, in3, in10 = today - dt.timedelta(days=1), today + dt.timedelta(days=3), today + dt.timedelta(days=10)
        run("todo", "add", "1", f"send the material — due: {today}")
        run("todo", "add", "1", f"call back — due: {yesterday}")
        run("todo", "add", "1", f"book the hall — due: {in3}")
        run("todo", "add", "1", "no date")
        self.assertIn(f"  - [ ] 1.1 send the material — due: {today}", self.read("TODO.md"))
        first = self.todo().phase(1).items[0]
        self.assertEqual((first.text, first.due), ("send the material", today.isoformat()))
        run("readme", "set", "due", f"{in10} · decision meeting")
        code, out, err = run()
        self.assertEqual(code, 0, err)
        self.assertIn(f"dates: today {today}", out)
        self.assertIn("due today: 1.1 «send the material»", out)
        self.assertIn(f"next 7 days: 1.3 ({in3.isoformat()[5:]})", out)
        self.assertIn("overdue: 1 — see Order", out)
        self.assertIn(f"deadline {in10} «decision meeting» in 10 days", out)
        self.assertIn(f"overdue: 1.2 «call back» was due {yesterday} → mike todo done 1.2 · mike todo due 1.2 <date> · "
                      f"mike todo cancel 1.2 \"why\"", out)
        run("todo", "done", "1.2")
        self.assertNotIn("overdue", run()[1], "a done item stops counting")
        run("todo", "due", "1.1", "none")
        self.assertIn("  - [ ] 1.1 send the material\n", self.read("TODO.md"))
        run("todo", "due", "1.4", in3.isoformat())
        self.assertIn(f"  - [ ] 1.4 no date — due: {in3}", self.read("TODO.md"))
        code, out, err = run("todo", "due", "1.4", "9 sep")
        self.assertEqual(code, 2)
        self.assertIn("YYYY-MM-DD", err)
        run("todo", "edit", "1.4", "no date edited")
        self.assertIn(f"  - [ ] 1.4 no date edited — due: {in3}", self.read("TODO.md"), "edit keeps the date")
        run("todo", "hold", "1.4", "waiting")
        self.assertIn(f"  - [~] 1.4 no date edited — due: {in3} — hold: waiting", self.read("TODO.md"))
        self.assertNotIn("1.4", run()[1].split("dates:")[1].split("\n")[0], "a held item stops counting")

    def test_no_dates_no_line(self):
        run("todo", "add", "1", "x")
        self.assertNotIn("dates:", run()[1])

    def test_a_bad_due_in_the_file_is_a_grammar_error(self):
        parsed = grammar.parse_todo("# T\n\n- [ ] 1 Work\n  - [ ] 1.1 x — due: 9 sep\n")
        self.assertTrue(any("due" in e.message for e in parsed.errors), [e.message for e in parsed.errors])


class Cancel(Base):
    def test_cancel_removes_the_item_and_logs_the_reason(self):
        run("todo", "add", "1", "wire the hall")
        run("todo", "add", "1", "keep")
        code, out, err = run("todo", "cancel", "1.1", "solved itself")
        self.assertEqual(code, 0, err)
        self.assertIn("cancelled: 1.1 «wire the hall»", out)
        self.assertIn("phase 1 now reads 1.2", out)
        self.assertNotIn("wire the hall", self.read("TODO.md"))
        self.assertIn("DECISION · снято 1.1 «wire the hall» — solved itself", self.read("JOURNAL.md"))
        self.assertEqual(run("todo", "cancel", "1.2", "")[0], 2, "a reason is required")
        self.assertEqual(run("todo", "cancel", "1.9", "x")[0], 4)


class CrossPhaseMove(Base):
    def test_move_to_another_phase_takes_the_next_free_number_there(self):
        for t in ("a", "b", "c"):
            run("todo", "add", "1", t)
        run("phase", "plan", "2", "Rollout", "--goal", "g")
        run("todo", "add", "2", "z")
        code, out, err = run("todo", "move", "1.2", "2")
        self.assertEqual(code, 0, err)
        self.assertIn("moved: 1.2 → 2.2 «b» (end of phase 2", out)
        self.assertEqual([it.text for it in self.todo().phase(1).items], ["a", "c"])
        self.assertEqual([(it.n, it.m, it.text) for it in self.todo().phase(2).items], [(2, 1, "z"), (2, 2, "b")])
        self.assertIn("already in phase 1", run("todo", "move", "1.1", "1")[1])
        code, out, err = run("todo", "move", "1.1", "5")
        self.assertEqual(code, 4)
        self.assertIn("mike phase plan 5", err)
        self.assertNotIn("moved", self.read("JOURNAL.md"), "a move is an action, not an event (P5)")


class Mv(Base):
    def test_mv_rewrites_links_everywhere_including_the_moved_files_own(self):
        self.doc("docs/old.md", "# Old\nsummary: старый\n← [README](../README.md) · see [peer](peer.md)\n")
        self.doc("docs/peer.md", "# Peer\nsummary: сосед\nsee [old](old.md) and [old again](old.md#top)\n")
        self.doc("docs/notes/deep.md", "# Deep\nsummary: глубокий\nup: [old](../old.md)\n")
        run("readme", "add", "links", "docs/ — документы")
        run("readme", "add", "problems", "open · see [old](docs/old.md) and `docs/old.md`")
        run("todo", "add", "1", "read [old](docs/old.md)")
        run("log", "RESULT", "wrote [old](docs/old.md)")
        run()
        code, out, err = run("mv", "docs/old.md", "docs/notes/")
        self.assertEqual(code, 0, err)
        self.assertIn("moved: docs/old.md → docs/notes/old.md", out)
        self.assertIn("links rewritten:", out)
        self.assertFalse((self.case / "docs/old.md").exists())
        moved = (self.case / "docs/notes/old.md").read_text(encoding="utf-8")
        self.assertIn("[README](../../README.md)", moved)
        self.assertIn("[peer](../peer.md)", moved)
        self.assertIn("see [old](notes/old.md) and [old again](notes/old.md#top)", (self.case / "docs/peer.md").read_text())
        self.assertIn("up: [old](old.md)", (self.case / "docs/notes/deep.md").read_text())
        r = self.read("README.md")
        self.assertIn("see [old](docs/notes/old.md) and `docs/notes/old.md`", r)
        self.assertIn("[old.md](docs/notes/old.md) — старый", r, "Links follow the file")
        self.assertNotIn("(docs/old.md)", r)
        self.assertIn("read [old](docs/notes/old.md)", self.read("TODO.md"))
        self.assertIn("wrote [old](docs/notes/old.md)", self.read("JOURNAL.md"))
        code, out, err = run("check")
        self.assertEqual(code, 0, err + out)  # the three files went through the stamp door
        self.assertNotIn("broken link", run()[1])

    def test_mv_refuses_the_three_files_overwrites_and_the_outside(self):
        self.doc("docs/a.md", "# A\nsummary: a\n")
        self.doc("docs/b.md", "# B\nsummary: b\n")
        self.assertEqual(run("mv", "README.md", "docs/r.md")[0], 2)
        self.assertEqual(run("mv", "docs/a.md", "docs/b.md")[0], 4)
        self.assertEqual(run("mv", "docs/zzz.md", "docs/y.md")[0], 4)
        self.assertEqual(run("mv", "docs/a.md", "../out.md")[0], 2)
        self.assertTrue((self.case / "docs/a.md").exists())

    def test_broken_links_are_named_in_order(self):
        self.doc("docs/a.md", "# A\nsummary: a\nsee [gone](gone.md), [web](https://x.y/z) and [anchor](#top)\n")
        run("readme", "add", "links", "docs/ — документы")
        run("todo", "add", "1", "read [b](docs/b.md)")
        code, out, err = run()
        self.assertEqual(code, 0, err)
        self.assertIn("2 broken link(s): TODO.md → docs/b.md, docs/a.md → gone.md → fix the link, or move files with `mike mv old new`", out)
        # check: a dead link in the files mike holds is a violation (F16); in a document — a warning
        code, out, err = run("check")
        self.assertEqual(code, 3, "the owner reads `violations:` — a dead link in TODO must count there")
        self.assertIn("F16 · broken link → docs/b.md", out + err)
        self.assertIn("docs/a.md → gone.md", err)
        self.assertNotIn("TODO.md → docs/b.md", err, "not reported twice")
        run("todo", "drop", "1.1")
        code, out, err = run("check")
        self.assertEqual(code, 0, err + out)
        self.assertIn("docs/a.md → gone.md", err)


class StateLines(Base):
    def test_a_state_line_can_be_removed_by_empty_set_or_drop(self):
        # feedback 2026-09-03: `readme set пауза ""` was a usage error — State lines were one-way
        run("readme", "set", "пауза", "ждём ответа")
        self.assertIn("- пауза: ждём ответа", self.read("README.md"))
        code, out, err = run("readme", "set", "пауза", "")
        self.assertEqual(code, 0, err)
        self.assertIn("`- пауза: …` removed", out)
        self.assertNotIn("пауза", self.read("README.md"))
        run("readme", "set", "пауза", "снова")
        code, out, err = run("readme", "drop", "state", "пауза")
        self.assertEqual(code, 0, err)
        self.assertNotIn("пауза", self.read("README.md"))
        code, out, err = run("readme", "drop", "state", "пауза")
        self.assertEqual(code, 4)
        self.assertIn("no `- пауза:` line", err)
        code, out, err = run("readme", "set", "progress", "")
        self.assertEqual(code, 2)
        self.assertIn("held by mike", err)
        self.assertIn("- progress:", self.read("README.md"))
        self.assertEqual(run("readme", "drop", "decisions", "пауза")[0], 2, "only State goes by prefix")


class ReadmeBudget(Base):
    def test_rendered_links_do_not_count_against_the_readme_cap(self):
        # feedback 2026-09-03: the file index mike renders squeezed the owner's own lines out of 8 KB
        for i in range(110):
            self.doc(f"docs/f{i:03d}.md", f"# F{i}\nsummary: {'описание ' * 12}{i}\n")
        run("readme", "add", "links", "docs/ — документы")
        code, out, err = run()
        self.assertEqual(code, 0, err)
        r = self.read("README.md")
        self.assertIn("[f109.md](docs/f109.md)", r, "README refreshed although the rendered index alone is over 12 KB")
        self.assertGreater(len(r.encode("utf-8")), 12 * 1024)
        self.assertNotIn("F2", err)
        for i in range(70):
            run("readme", "add", "decisions", f"2026-09-03 · решение номер {i} · " + "потому что " * 10)
        code, out, err = run("readme", "add", "decisions", "ещё одно")
        self.assertEqual(code, 0, err)
        self.assertIn("of your text", err)
        self.assertIn("Links rendered by mike:", err)
        self.assertIn("not counted", err)


if __name__ == "__main__":
    unittest.main()
