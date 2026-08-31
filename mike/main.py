"""Command line for `mike` (C1–C9): ten commands, text output, exit codes 0/1/2/3/4, no prompts."""
import argparse
import sys
from pathlib import Path

from . import __version__, commands, store
from .store import StoreError

EXAMPLES = """examples
  mike                                   where the case in hand stands + next step (read this first)
  mike log DECISION "chose X over Y because Z"
  mike log RESULT "p95 dropped 120 → 48 ms"
  mike todo add 3 "write the parser"      mike todo done 3.1
  mike phase open 3 "CLI core" --goal "single write door with tests"
  mike log DECISION "reflect: …"  ·  mike log DECISION "align: …"   (both before closing)
  mike phase close 3 "parsers, stamp and commands work, 55 tests"
  mike readme --file README.md           validate and write a README (progress line kept in sync)
  mike case new "connect database" --goal "app talks to the prod database"
  mike case list                         all cases, current marked *
  mike case use connect-database         switch the hand (like `cf target` / `oc project`)
  mike spawn "db unreachable from server" --goal "server cannot reach the database, cause unknown"
  mike done "database connected and validated"
  mike check                             all cases against RULES.md; violations → exit 3
options: --case <name or suffix> (or MIKE_CASE) picks the case; exit codes 0 ok · 1 error · 2 usage · 3 rule violation · 4 precondition
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mike", description="the write door for .cases/ — see .cases/RULES.md",
                                epilog=EXAMPLES, formatter_class=argparse.RawDescriptionHelpFormatter, allow_abbrev=False)
    p.add_argument("--case", help="case name or unique suffix (default: MIKE_CASE or the freshest open case)")
    p.add_argument("--version", action="version", version=f"mike {__version__}")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("log", help="add a journal event: PHASE · DECISION · PROBLEM · RESULT", allow_abbrev=False)
    s.add_argument("type")
    s.add_argument("text")
    s.add_argument("--phase", help="pN (default: the open phase)")

    s = sub.add_parser("todo", help="add an item or mark it done", allow_abbrev=False)
    s.add_argument("action", choices=["add", "done"])
    s.add_argument("ref", help="phase number for add (N), item for done (N.M)")
    s.add_argument("text", nargs="?", default="")

    s = sub.add_parser("phase", help="open or close a phase (close needs RESULT, reflect:, align:)", allow_abbrev=False)
    s.add_argument("action", choices=["open", "close"])
    s.add_argument("n", type=int)
    s.add_argument("text", nargs="?", default="", help="name for open, summary for close")
    s.add_argument("--goal", help="one line, required for a new phase")

    s = sub.add_parser("readme", help="validate and write README.md from --file or stdin", allow_abbrev=False)
    s.add_argument("--file", default="-")

    s = sub.add_parser("case", help="case new <name> --goal … · case list · case use <name>", allow_abbrev=False)
    s.add_argument("action", choices=["new", "list", "use"])
    s.add_argument("name", nargs="?")
    s.add_argument("--goal")

    s = sub.add_parser("spawn", help="open a nested case inside the case in hand (P11)", allow_abbrev=False)
    s.add_argument("name")
    s.add_argument("--goal", required=True)

    s = sub.add_parser("done", help="close the case in hand (all phases must be closed)", allow_abbrev=False)
    s.add_argument("summary")

    sub.add_parser("check", help="verify every case against the rules", allow_abbrev=False)
    sub.add_parser("help", help="show examples", allow_abbrev=False)
    return p


def run(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.cmd == "help":
            parser.print_help()
            return 0
        if args.cmd == "case" and args.action == "new":
            if not args.name or not args.goal:
                raise StoreError("usage: mike case new <name> --goal \"one line\"", 2)
            root = _root_or_create()
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
            out = commands.check(root)
        else:
            case = store.hand(root, args.case)
            if args.cmd is None:
                out = commands.entry(root, case)
            elif args.cmd == "log":
                out = commands.log(case, args.type, args.text, args.phase)
            elif args.cmd == "todo":
                out = commands.todo_done(case, args.ref) if args.action == "done" else commands.todo_add(case, args.ref, args.text)
            elif args.cmd == "phase":
                if args.action == "open":
                    if not args.text:
                        raise StoreError("phase open needs a name: `mike phase open 3 \"CLI core\" --goal …`", 2)
                    out = commands.phase_open(case, args.n, args.text, args.goal)
                else:
                    if not args.text:
                        raise StoreError("phase close needs a summary: `mike phase close 3 \"what it delivered\"`", 2)
                    out = commands.phase_close(case, args.n, args.text)
            elif args.cmd == "readme":
                text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
                out = commands.readme(case, text)
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
        print(f"mike: {e}", file=sys.stderr)
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
