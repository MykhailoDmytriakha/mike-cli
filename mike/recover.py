"""Rebuild a case file by its grammar (rule S4).

When a stamp does not match, `mike` does not restore bytes — it re-parses the file: lines the grammar
accepts stay, lines it rejects are moved out to `<FILE>.recover.md` for the agent to re-enter through
`mike` commands. Whole-file violations (wrong section order, size over the hard limit) cannot be fixed
by dropping lines and are returned as fatal findings instead.
"""
from typing import Callable, List, Optional, Tuple

from . import grammar, stamp

PARSERS: dict = {
    "README.md": grammar.parse_readme,
    "TODO.md": grammar.parse_todo,
    "JOURNAL.md": grammar.parse_journal,
}
MAX_PASSES = 6


def rebuild(kind: str, text: str) -> Tuple[Optional[str], List[str], List[grammar.Finding]]:
    """Return (rebuilt_text_with_stamp, removed_lines, fatal_findings).

    rebuilt_text is None when fatal findings remain (nothing can be dropped to fix them).
    Removing a journal entry header orphans its events, so parsing is repeated until clean.
    """
    parse: Callable = PARSERS[kind]
    body, _ = stamp.split(text)
    lines = body.rstrip("\n").split("\n") if body.strip() else []
    removed: List[str] = []
    for _ in range(MAX_PASSES):
        result = parse("\n".join(lines) + "\n")
        fatal = [f for f in result.errors if f.line == 0]
        bad = {f.line for f in result.errors if f.line > 0}
        if fatal:
            return None, removed, fatal
        if not bad:
            return stamp.apply("\n".join(lines) + "\n"), removed, []
        if kind == "JOURNAL.md":
            # A rejected entry header takes its indented event/body lines with it — otherwise they
            # would silently re-attach to the previous entry under the wrong date and phase.
            for i in sorted(bad):
                if lines[i - 1].startswith("- "):
                    j = i
                    while j < len(lines) and lines[j].startswith("  "):
                        bad.add(j + 1)
                        j += 1
        removed.extend(l for i, l in enumerate(lines, 1) if i in bad)
        lines = [l for i, l in enumerate(lines, 1) if i not in bad]
    return None, removed, [grammar.Finding("S4", 0, "could not rebuild after several passes")]
