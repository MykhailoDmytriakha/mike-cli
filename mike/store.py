"""Storage layer: find `.cases/`, pick the case in hand, read and write the three files safely.

Rules touched: L1–L3 (layout), S1–S4 (stamp on every write, rebuild on mismatch), C7–C9.
The case "in hand" is computed, never stored: `--case` flag > MIKE_CASE env > the open case whose
JOURNAL.md changed most recently.
"""
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from . import grammar, recover, stamp

CASES_DIR = ".cases"
FILES = ("README.md", "TODO.md", "JOURNAL.md")
# L2 naming policy: a case dir is `YYYY-MM-DD-<slug>`. Detection is case-INsensitive and imposes no
# word count: the invariant is the date prefix plus a non-empty portable slug (letters, digits,
# hyphens). `case new` normalizes NEW names to lowercase; existing dirs are never renamed.
DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-")
CASE_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*$")


def reject_reason(name: str):
    """Why a directory name is not a case name — None when it is one (used for diagnostics)."""
    if CASE_NAME_RE.match(name):
        return None
    if not DATE_PREFIX_RE.match(name):
        return "no YYYY-MM-DD- date prefix"
    rest = name[11:]
    if not rest:
        return "empty name after the date"
    return f"invalid characters in `{rest}` — allowed: letters, digits, hyphen-separated words"


class StoreError(Exception):
    """A refusal: message for the agent and the exit code that names the class of failure (C5)."""

    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


@dataclass
class WriteReport:
    path: Path
    warnings: List[grammar.Finding] = field(default_factory=list)
    recovered: Optional[Path] = None  # set when a mismatched file was rebuilt (S4)
    recovered_lines: int = 0
    bypassed: bool = False  # the file had been written bypassing `mike` (stamp mismatch)


# ---- root and cases ------------------------------------------------------------------------------
def find_root(start: Optional[Path] = None) -> Path:
    """Walk up from `start` (cwd) until a `.cases/` directory is found (C9)."""
    here = (start or Path.cwd()).resolve()
    for d in [here, *here.parents]:
        if (d / CASES_DIR).is_dir():
            return d / CASES_DIR
    raise StoreError(f"no `{CASES_DIR}/` found from {here} upwards — run `mike case new <name>` in the project root", 4)


def is_case_dir(p: Path) -> bool:
    return p.is_dir() and CASE_NAME_RE.match(p.name) is not None


def scan(root: Path):
    """Every case folder under root plus the case-LIKE directories that were rejected, with reasons.

    Rejected means: at the root level — any visible directory that is not a valid case name; inside
    a case — a directory with a date prefix but an invalid tail (content folders like `docs/` are
    not case-like and are not reported). Nothing is ever silently ignored (bug report 2026-08-31).
    """
    found: List[Path] = []
    rejected: List[tuple] = []

    def walk(d: Path, top: bool):
        for child in sorted(d.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            if is_case_dir(child):
                found.append(child)
                walk(child, False)
            elif top or DATE_PREFIX_RE.match(child.name):
                rejected.append((child, reject_reason(child.name)))

    walk(root, True)
    return found, rejected


def all_cases(root: Path) -> List[Path]:
    return scan(root)[0]


def file_path(case: Path, name: str) -> Path:
    """The single resolver for the three case files: canonical name first, any-case legacy second.

    Legacy cases may hold `todo.md` / `journal.md`; those are read and written in place, never
    renamed. When the file does not exist at all, the canonical path is returned for creation.
    """
    # Real stored names via iterdir, not `.exists()`: on case-insensitive filesystems (macOS APFS)
    # `(case / "JOURNAL.md").exists()` is true for `journal.md` too, and writing through the
    # canonical spelling would silently rename the user's file.
    if case.is_dir():
        insensitive = None
        for child in case.iterdir():
            if not child.is_file():
                continue
            if child.name == name:
                return child
            if child.name.lower() == name.lower():
                insensitive = child
        if insensitive is not None:
            return insensitive
    return case / name


def read(case: Path, name: str) -> str:
    p = file_path(case, name)
    if not p.exists():
        raise StoreError(f"{p} is missing (L3)", 4)
    return p.read_text(encoding="utf-8")


def todo_of(case: Path) -> grammar.Todo:
    return grammar.parse_todo(read(case, "TODO.md"))


def is_open(case: Path) -> bool:
    """A case is open until `mike done` writes `- closed: …` into README State."""
    try:
        text = read(case, "README.md")
    except StoreError:
        return False
    return re.search(r"^- closed: ", text, re.M) is None


def load(case: Path, name: str):
    """Read one of the three files through the stamp door: verify (rebuild on mismatch), return (body, report)."""
    report = check_stamp(case, name)
    body, _ = stamp.split(read(case, name))
    return body, report


def resolve_case(root: Path, name: Optional[str]) -> Path:
    """Find a case by name (exact folder name, nested allowed) or by unique suffix."""
    cases = all_cases(root)
    exact = [c for c in cases if c.name == name] or [c for c in cases if name and c.name.lower() == name.lower()]
    if exact:
        return exact[0]
    partial = [c for c in cases if name and c.name.lower().endswith(name.lower())]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        raise StoreError(f"`{name}` matches several cases: {', '.join(c.name for c in partial)}", 2)
    raise StoreError(f"no case named `{name}` under {root}", 4)


def hand(root: Path, explicit: Optional[str] = None) -> Path:
    """The case in hand: flag > MIKE_CASE > open case with the freshest JOURNAL.md (P2, C9)."""
    name = explicit or os.environ.get("MIKE_CASE")
    if name:
        return resolve_case(root, name)
    open_cases = [c for c in all_cases(root) if is_open(c)]
    if not open_cases:
        raise StoreError("no open case — `mike case new <name>` to start one", 4)
    def freshness(c: Path):
        j = file_path(c, "JOURNAL.md")
        return j.stat().st_mtime if j.exists() else 0

    return max(open_cases, key=freshness)


def chain(case: Path, root: Path) -> List[str]:
    """Names from the top-level case down to `case` (for nested cases)."""
    names = []
    p = case
    while p != root and is_case_dir(p):
        names.append(p.name)
        p = p.parent
    return list(reversed(names))


# ---- writing with stamp discipline ---------------------------------------------------------------
def _atomic_write(path: Path, text: str):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def check_stamp(case: Path, name: str) -> WriteReport:
    """S3/S4: verify the stamp before writing. Mismatch → rebuild by grammar, move the rest out."""
    path = file_path(case, name)
    report = WriteReport(path)
    text = read(case, name)
    ok, state = stamp.verify(text)
    if ok or state == "missing":  # S2: no stamp yet → it will be set by this write
        return report
    report.bypassed = True
    rebuilt, removed, fatal = recover.rebuild(name, text)
    if rebuilt is None:
        details = "; ".join(str(f) for f in fatal)
        raise StoreError(f"{name}: stamp {state} and the file cannot be rebuilt — {details}", 3)
    _atomic_write(path, rebuilt)
    if removed:
        rec = case / f"{path.name}.recover.md"
        rec.write_text("\n".join(removed) + "\n", encoding="utf-8")
        report.recovered, report.recovered_lines = rec, len(removed)
    return report


def write(case: Path, name: str, body: str) -> WriteReport:
    """Validate `body` by its grammar, then write it with a fresh stamp (C8: nothing is touched on refusal).

    A violation the command did NOT introduce (the broken line already sits in the current file —
    e.g. left by an older mike version) must not deadlock every future write: the file is rebuilt,
    the broken lines go to `<FILE>.recover.md`, the write proceeds with a warning (S4 semantics).
    """
    report = check_stamp(case, name)
    result = recover.PARSERS[name](body)
    if result.errors:
        current, _ = stamp.split(read(case, name)) if file_path(case, name).exists() else ("", None)
        current_lines = set(current.split("\n"))
        new_lines = body.rstrip("\n").split("\n")
        introduced = [f for f in result.errors
                      if f.line == 0 or f.line > len(new_lines) or new_lines[f.line - 1] not in current_lines]
        if introduced:
            details = "\n".join(f"  {f}" for f in introduced)
            raise StoreError(f"{name}: refused, {len(introduced)} rule violation(s):\n{details}", 3)
        rebuilt, removed, fatal = recover.rebuild(name, body)
        if rebuilt is None:
            details = "; ".join(str(f) for f in fatal)
            raise StoreError(f"{name}: pre-existing violations and the file cannot be rebuilt — {details}", 3)
        _atomic_write(file_path(case, name), rebuilt)
        if removed:
            rec = case / f"{file_path(case, name).name}.recover.md"
            rec.write_text("\n".join(removed) + "\n", encoding="utf-8")
            report.recovered, report.recovered_lines = rec, len(removed)
        report.warnings = result.warnings
        return report
    report.warnings = result.warnings
    _atomic_write(file_path(case, name), stamp.apply(body))
    return report


def recover_files(case: Path) -> List[Path]:
    return sorted(case.glob("*.recover.md"))
