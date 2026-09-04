"""Command line for `mike` (C1–C9): ten commands, text output, exit codes 0/1/2/3/4, no prompts."""
import argparse
import sys
from pathlib import Path

from . import __version__, commands, knowledge, store
from .store import StoreError

EXAMPLES = """examples
  mike                                   where the case in hand stands + next step (read this first)
  mike log DECISION "chose X over Y because Z"
  mike log RESULT "p95 dropped 120 → 48 ms"
  mike todo add 3 "write the parser"      mike todo done 3.1
  mike todo edit 3.1 "new text" · mike todo move 3.7 3.2 (before 3.2; or `last`) · mike todo drop 3.4   numbers never change
  mike todo add 3 "send the material — due: 2026-09-09" · mike todo due 3.2 2026-09-12 · mike todo cancel 3.5 "no longer needed"
  mike todo move 3.6 4                    to another phase (joins its end under the next free number)
  mike readme set due "2026-09-13 · decision meeting"   the case deadline — `mike` counts the days on entry
  mike mv docs/old.md docs/notes/new.md   move a file; every link to it is rewritten (README/TODO/JOURNAL and the documents)
  mike todo hold 3.2 "ждём ответа заказчика" · mike todo resume 3.2
  mike readme set next "call the customer" · mike readme set пауза "" (removes the line) · mike readme add links "docs/contacts.md — кто есть кто"
  mike phase open 3 "CLI core" --goal "single write door with tests"
  mike phase plan 4 "Rollout" --goal "first users on the new build"   name the NEXT phase now, park items under it (todo add 4), open it later
  mike log DECISION "reflect: …"  ·  mike log DECISION "align: …"   (both before closing)
  mike phase close 3 "parsers, stamp and commands work, 55 tests"
  mike readme --file README.md           validate and write a README (progress line kept in sync)
  mike case new "connect database" --goal "app talks to the prod database"
  mike case new --root "my app" --goal "…"   root mode: the project folder itself is the top case
  mike case list                         all cases, current marked *
  mike case use connect-database         switch the hand (like `cf target` / `oc project`)
  mike spawn "db unreachable from server" --goal "server cannot reach the database, cause unknown"
  mike done "database connected and validated"
  mike feedback "log rejects names" --actual "..." --expected "..."   report a mike problem
  mike order                             what is out of order in the case in hand + the fix for each line
  mike order --adopt                     move file descriptions from README Links into the files as `summary:`
  mike migrate                           legacy case (files mike never stamped): dry run — what maps where, nothing changes
  mike migrate --apply                   archive the legacy files byte-for-byte, write canonical ones atomically
  mike check                             all cases against the rules; violations → exit 3
  mike doctor                            read-only diagnostics, changes nothing
  mike --case connect-database check     check one case only
options: --case <name or suffix> (or MIKE_CASE) picks the case; exit codes 0 ok · 1 error · 2 usage · 3 rule violation · 4 precondition
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mike", description="the write door for .cases/ — rules: mike help files · order · limits",
                                epilog=EXAMPLES, formatter_class=argparse.RawDescriptionHelpFormatter, allow_abbrev=False)
    p.add_argument("--case", help="case name or unique suffix (default: MIKE_CASE or the freshest open case)")
    p.add_argument("--version", action="version", version=f"mike {__version__}")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("log", help="add a journal event: PHASE · DECISION · PROBLEM · RESULT", allow_abbrev=False)
    s.add_argument("type")
    s.add_argument("text")
    s.add_argument("--phase", help="p1, 1 or a unique phase name (default: the open phase); e.g. `mike log --phase p1 DECISION \"…\"`")

    s = sub.add_parser("todo", help="add · done · edit · move · drop · hold · resume items — N.M is an item's number for life: drop and move never renumber", allow_abbrev=False)
    s.add_argument("action", choices=["add", "done", "edit", "move", "drop", "hold", "resume", "cancel", "due"])
    s.add_argument("ref", help="phase number for add (N), item for the rest (N.M)")
    s.add_argument("text", nargs="?", default="", help="text for add/edit (may end with `— due: YYYY-MM-DD`); for move: N.K (before K), `last`, or a phase number K; for cancel: why; for due: YYYY-MM-DD or none")

    s = sub.add_parser("phase", help="plan · open · close a phase (plan = name the next one without opening it; close needs RESULT, reflect:, align:)", allow_abbrev=False)
    s.add_argument("action", choices=["plan", "open", "close"])
    s.add_argument("n", type=int)
    s.add_argument("text", nargs="?", default="", help="name for plan/open (open takes it from the plan when omitted), summary for close")
    s.add_argument("--goal", help="one line; required for a new phase unless it was planned with one")

    s = sub.add_parser("readme", help="write from --file/stdin · set <prefix> \"…\" (\"\" removes) · add <section> \"…\" · drop <section> <k> | drop state <prefix>", allow_abbrev=False)
    s.add_argument("action", nargs="?", choices=["set", "add", "drop"])
    s.add_argument("a", nargs="?")
    s.add_argument("b", nargs="?")
    s.add_argument("--file", default="-")

    s = sub.add_parser("case", help="case new <name> --goal … · case list · case use <name> · case new --root", allow_abbrev=False)
    s.add_argument("action", choices=["new", "list", "use"])
    s.add_argument("name", nargs="?")
    s.add_argument("--goal")
    s.add_argument("--root", action="store_true", help="root mode: the project folder itself becomes the top case")

    s = sub.add_parser("mv", help="move/rename a file inside the case; every link to it is rewritten", allow_abbrev=False)
    s.add_argument("old", help="current path, relative to the case (docs/x.md)")
    s.add_argument("new", help="new path or folder (docs/notes/ or docs/notes/y.md)")

    s = sub.add_parser("spawn", help="open a nested case inside the case in hand (P11)", allow_abbrev=False)
    s.add_argument("name")
    s.add_argument("--goal", required=True)

    s = sub.add_parser("done", help="close the case in hand (all phases must be closed)", allow_abbrev=False)
    s.add_argument("summary")

    s = sub.add_parser("feedback", help="report a mike problem or wish — lands in the mike-cli clone's feedback/ pool", allow_abbrev=False)
    s.add_argument("title")
    s.add_argument("--expected", default="")
    s.add_argument("--actual", default="")
    s.add_argument("--why", default="")
    s.add_argument("--acceptance", default="")
    s.add_argument("--repro", default="")

    s = sub.add_parser("order", help="what is out of order in the case in hand, with the fix for each line", allow_abbrev=False)
    s.add_argument("--adopt", action="store_true", help="write `summary:` into files from their README Links descriptions")
    s = sub.add_parser("migrate", help="legacy case → mike's grammar: dry run by default, --apply archives and writes", allow_abbrev=False)
    s.add_argument("--apply", action="store_true", help="archive legacy files under legacy/<date-time>/ and write the canonical files")
    sub.add_parser("check", help="verify every case against the rules", allow_abbrev=False)
    sub.add_parser("doctor", help="read-only diagnostics: what mike sees from here; changes nothing", allow_abbrev=False)
    s = sub.add_parser("help", help="examples; `mike help <topic>` opens a knowledge dose", allow_abbrev=False)
    s.add_argument("topic", nargs="?")
    return p


def run(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.cmd == "help":
            if args.topic:
                dose = knowledge.TOPICS.get(args.topic.lower())
                if dose is None:
                    print(f"mike: no topic `{args.topic}` — topics: {knowledge.topic_list()}", file=sys.stderr)
                    return 2
                print(dose)
                return 0
            parser.print_help()
            print(f"\ntopics (open at the moment of need): mike help <{knowledge.topic_list()}>")
            return 0
        if args.cmd == "feedback":
            out = commands.feedback(args.title, args.expected, args.actual, args.why, args.acceptance, args.repro)
            print("\n".join(out.lines))
            return 0
        if args.cmd == "doctor":
            out = commands.doctor()
            print("\n".join(out.lines))
            return 0
        if args.cmd == "case" and args.action == "new":
            if not args.name or not args.goal:
                raise StoreError("usage: mike case new <name> --goal \"one line\" [--root]", 2)
            root = _root_or_create()
            if args.root:
                out = commands.project_new(root, args.name, args.goal)
                print("\n".join(out.lines))
                return 0
            case = commands.case_new(root, args.name, args.goal)
            print(f"created: {case.relative_to(root.parent)} — now `mike phase open 1 <Name> --goal \"…\"`")
            return 0
        root = store.find_root()
        if args.cmd == "case":
            if args.action == "list":
                out = commands.case_list(root)
            else:
                if not args.name:
                    raise StoreError("usage: mike case use <name or unique suffix>", 2)
                out = commands.case_use(root, args.name)
        elif args.cmd == "check":
            only = store.resolve_case(root, args.case) if args.case else None
            out = commands.check(root, only)
        else:
            case = store.hand(root, args.case)
            if args.cmd is None:
                out = commands.entry(root, case)
            elif args.cmd == "log":
                out = commands.log(case, args.type, args.text, args.phase)
            elif args.cmd == "todo":
                if args.action == "add":
                    out = commands.todo_add(case, args.ref, args.text)
                elif args.action == "done":
                    out = commands.todo_done(case, args.ref)
                elif args.action == "edit":
                    if not args.text:
                        raise StoreError("usage: mike todo edit N.M \"new text\"", 2)
                    out = commands.todo_edit(case, args.ref, args.text)
                elif args.action == "move":
                    if not args.text:
                        raise StoreError("usage: mike todo move N.M N.K", 2)
                    out = commands.todo_move(case, args.ref, args.text)
                elif args.action == "hold":
                    out = commands.todo_hold(case, args.ref, args.text)
                elif args.action == "resume":
                    out = commands.todo_resume(case, args.ref)
                elif args.action == "cancel":
                    out = commands.todo_cancel(case, args.ref, args.text)
                elif args.action == "due":
                    out = commands.todo_due(case, args.ref, args.text)
                else:
                    out = commands.todo_drop(case, args.ref)
            elif args.cmd == "phase":
                if args.action == "open":
                    out = commands.phase_open(case, args.n, args.text, args.goal)  # name may come from the plan
                elif args.action == "plan":
                    if not args.text:
                        raise StoreError("phase plan needs a name: `mike phase plan 3 \"Rollout\" --goal \"one line\"`", 2)
                    out = commands.phase_plan(case, args.n, args.text, args.goal)
                else:
                    if not args.text:
                        raise StoreError("phase close needs a summary: `mike phase close 3 \"what it delivered\"`", 2)
                    out = commands.phase_close(case, args.n, args.text)
            elif args.cmd == "readme":
                if args.action == "set":
                    if not args.a or args.b is None:
                        raise StoreError("usage: mike readme set <prefix> \"text\" (a State line; \"\" removes it)", 2)
                    out = commands.readme_set(case, args.a, args.b)
                elif args.action == "add":
                    if not args.a or not args.b:
                        raise StoreError("usage: mike readme add <section> \"line\"", 2)
                    out = commands.readme_add(case, args.a, args.b)
                elif args.action == "drop":
                    if not args.a or not args.b:
                        raise StoreError("usage: mike readme drop <section> <k> · mike readme drop state <prefix>", 2)
                    out = commands.readme_drop(case, args.a, args.b)
                else:
                    text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
                    out = commands.readme(case, text)
            elif args.cmd == "order":
                out = commands.order_cmd(root, case, args.adopt)
            elif args.cmd == "migrate":
                out = commands.migrate_cmd(case, args.apply)
            elif args.cmd == "mv":
                out = commands.mv(case, args.old, args.new)
            elif args.cmd == "spawn":
                out = commands.spawn(root, case, args.name, args.goal)
            elif args.cmd == "done":
                out = commands.done(root, case, args.summary)
            else:  # pragma: no cover
                parser.print_usage()
                return 2
        for w in out.warnings:
            print(f"warning: {w}", file=sys.stderr)
        print("\n".join(out.lines))
        return 0
    except StoreError as e:
        lines = [f"mike: ERROR [exit {e.code}] {e}"]
        if e.recovery:
            lines.append(f"  recovery: {e.recovery}")
        lines.append(f"  exit {e.code} = {store.EXIT_MEANING.get(e.code, '?')} — `mike help errors`")
        print("\n".join(lines), file=sys.stderr)
        if args.cmd is None:  # the entry command must explain itself on stdout too (feedback #4)
            print("\n".join(lines))
            if e.code == 4 and "no `.cases/`" in str(e):
                print(knowledge.ONBOARDING)
        return e.code


def _root_or_create() -> Path:
    try:
        return store.find_root()
    except StoreError:
        root = Path.cwd() / store.CASES_DIR
        root.mkdir()
        return root


def main():  # pragma: no cover
    sys.exit(run())
