"""Grammars of the case files — rules F0–F13 of .cases/RULES.md as parsers.

Each parser returns a Result: a structured model plus `errors` (rule violations → the write
is refused, exit code 3) and `warnings` (thresholds crossed → the write passes with a notice).
Every finding names the rule it comes from, so `mike` can print "F7 · line 14 · ..." and the
agent can look the rule up. Nothing here touches the filesystem.
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional

from . import stamp as stamp_mod

# ---- limits (F2, F4, F7, F13; owner decisions 2026-08-30) --------------------------------------
README_WARN_LINES, README_WARN_BYTES = 200, 8 * 1024
README_MAX_LINES, README_MAX_BYTES = 300, 12 * 1024
README_POINTER_CHARS = 150
TODO_MAX_LINES = 100
TODO_ITEM_CHARS = 80
EVENT_CHARS = 200
EVENT_WARN_CHARS = 180
EVENT_BODY_LINES = 5

README_SECTIONS = ["Context", "State", "Decisions", "Problems", "Links"]
JOURNAL_TYPES = {"PHASE", "DECISION", "PROBLEM", "RESULT"}

TITLE_RE = re.compile(r"^# \S.*$")
ENTRY_RE = re.compile(r"^- (\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}) · (p\d+(?:\.\d+)?)$")
EVENT_RE = re.compile(r"^  (PHASE|DECISION|PROBLEM|RESULT|[A-Z]+) · (.+)$")
BODY_RE = re.compile(r"^    (.+)$")
PHASE_LINE_RE = re.compile(r"^- \[( |x)\] (\d+) (.+?)(?: — (.+))?$")
PHASE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]*(?: [A-Za-z0-9-]+){0,2}$")  # F13: English, 1–3 words
ITEM_RE = re.compile(r"^  - \[( |x|~)\] (\d+)\.(\d+) (.+)$")  # `~` = on hold
LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def visible_len(text: str) -> int:
    """Length as the reader sees it: markdown links `[name](path)` count as `name` (feedback 2026-09-01)."""
    return len(LINK_RE.sub(r"\1", text))
DEEP_ITEM_RE = re.compile(r"^\s+- \[( |x)\] \d+\.\d+\.\d+")
WAITS_RE = re.compile(r"^  - waits: (\S+)$")
SECTION_RE = re.compile(r"^## (.+)$")
PHASE_TITLE_RE = re.compile(r"^# Phase (\d+) — (.+)$")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
CHECKBOX_RE = re.compile(r"^\s*- \[( |x)\] ")


@dataclass
class Finding:
    rule: str
    line: int  # 1-based; 0 = whole file
    message: str

    def __str__(self):
        where = f"line {self.line}" if self.line else "file"
        return f"{self.rule} · {where} · {self.message}"


@dataclass
class Result:
    title: Optional[str] = None
    stamp: Optional[str] = None
    stamp_state: str = "missing"  # ok | missing | not-last | mismatch
    errors: List[Finding] = field(default_factory=list)
    warnings: List[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, rule, line, message):
        self.errors.append(Finding(rule, line, message))

    def warn(self, rule, line, message):
        self.warnings.append(Finding(rule, line, message))


# ---- common: title + stamp (F0, S1) ------------------------------------------------------------
def _frame(text: str, result: Result):
    """Check first line (title) and last line (stamp); return body lines without the stamp."""
    body, found = stamp_mod.split(text)
    ok, state = stamp_mod.verify(text)
    result.stamp, result.stamp_state = found, state
    lines = body.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    if not lines or not TITLE_RE.match(lines[0]):
        result.error("F0", 1, "first line must be a title: `# <Title>`")
    else:
        result.title = lines[0][2:].strip()
    return lines


# ---- JOURNAL (F7, F8, F9, P5) ------------------------------------------------------------------
@dataclass
class Event:
    type: str
    text: str
    line: int
    body: List[str] = field(default_factory=list)


@dataclass
class Entry:
    date: str
    time: str
    phase: str
    line: int
    events: List[Event] = field(default_factory=list)


@dataclass
class Journal(Result):
    entries: List[Entry] = field(default_factory=list)

    def phases_with_result(self):
        return {e.phase for e in self.entries for ev in e.events if ev.type == "RESULT"}

    def last(self, n: int):
        return self.entries[:n]


def parse_journal(text: str) -> Journal:
    r = Journal()
    lines = _frame(text, r)
    entry, event, prev_key = None, None, None
    for i, raw in enumerate(lines[1:], start=2):
        if raw.strip() == "":
            continue
        m = ENTRY_RE.match(raw)
        if m:
            date, time, phase = m.groups()
            key = (date, time)
            if prev_key is not None and key > prev_key:
                r.error("F7", i, f"entries must be newest first: {date} {time} comes after an older entry")
            prev_key = key
            if entry is not None and not entry.events:
                r.error("F7", entry.line, "entry has no event lines under it")
            entry = Entry(date, time, phase, i)
            r.entries.append(entry)
            event = None
            continue
        m = EVENT_RE.match(raw)
        if m:
            if entry is None:
                r.error("F7", i, "event line before any entry header")
                continue
            typ, txt = m.groups()
            if typ not in JOURNAL_TYPES:
                r.error("F8", i, f"unknown event type `{typ}`; allowed: PHASE · DECISION · PROBLEM · RESULT")
            n = len(raw.strip())
            if n > EVENT_CHARS:
                r.error("F7", i, f"event line is {n} chars, limit {EVENT_CHARS}: move details into a body line")
            elif n > EVENT_WARN_CHARS:
                r.warn("F7", i, f"event line is {n} chars, close to the limit {EVENT_CHARS}")
            event = Event(typ, txt, i)
            entry.events.append(event)
            continue
        m = BODY_RE.match(raw)
        if m:
            if event is None:
                r.error("F7", i, "body line without an event above it")
                continue
            event.body.append(m.group(1))
            if len(event.body) > EVENT_BODY_LINES:
                r.error("F7", i, f"event body longer than {EVENT_BODY_LINES} lines")
            continue
        r.error("F7", i, "unparsable line: expected `- YYYY-MM-DD HH:MM · pN`, `  TYPE · text` or `    body`")
    if entry is not None and not entry.events:
        r.error("F7", entry.line, "entry has no event lines under it")
    return r


# ---- TODO (F4, F5, F6, F13) ---------------------------------------------------------------------
@dataclass
class Item:
    n: int
    m: int
    done: bool
    text: str
    line: int
    held: bool = False
    hold_reason: str = ""
    due: str = ""        # YYYY-MM-DD from the `— due: …` suffix; the tool counts dates it can parse


@dataclass
class Phase:
    n: int
    name: str
    done: bool
    line: int
    summary: Optional[str] = None
    items: List[Item] = field(default_factory=list)
    waits: List[str] = field(default_factory=list)


@dataclass
class Todo(Result):
    phases: List[Phase] = field(default_factory=list)

    def phase(self, n: int):
        return next((p for p in self.phases if p.n == n), None)

    def closed(self):
        return {p.n for p in self.phases if p.done}

    def current(self):
        return next((p for p in self.phases if not p.done), None)


def parse_todo(text: str) -> Todo:
    r = Todo()
    lines = _frame(text, r)
    if len(lines) > TODO_MAX_LINES:
        r.error("F4", 0, f"TODO is {len(lines)} lines, limit {TODO_MAX_LINES}")
    phase, seen = None, set()
    for i, raw in enumerate(lines[1:], start=2):
        if raw.strip() == "":
            continue
        if DEEP_ITEM_RE.match(raw):
            r.error("F13", i, "no items deeper than N.M — third level belongs in the phase file")
            continue
        m = PHASE_LINE_RE.match(raw)
        if m:
            done, n, name, summary = m.group(1) == "x", int(m.group(2)), m.group(3).strip(), m.group(4)
            if n in seen:
                r.error("F4", i, f"phase {n} appears twice")
            seen.add(n)
            if not PHASE_NAME_RE.match(name):
                r.error("F13", i, f"phase name `{name}` must be English, 1–3 words, letters/digits/hyphen")
            if done:
                if not summary:
                    r.error("F5", i, f"closed phase {n} needs a summary: `— result · date · … · phases/{n}-name.md`")
                else:
                    if not DATE_RE.search(summary):
                        r.error("F5", i, f"closed phase {n}: summary has no date")
                    if not re.search(rf"phases/{n}-[a-z0-9-]+\.md", summary):
                        r.error("F5", i, f"closed phase {n}: summary must end with `phases/{n}-name.md`")
            # An open phase may carry `— <one-line intent>` (rolling wave); only closed phases need a summary.
            phase = Phase(n, name, done, i, summary)
            r.phases.append(phase)
            continue
        m = ITEM_RE.match(raw)
        if m:
            if phase is None:
                r.error("F4", i, "item before any phase")
                continue
            mark, n, k, txt = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4).strip()
            held, reason, due = mark == "~", "", ""
            if held and " — hold: " in txt:
                txt, reason = txt.rsplit(" — hold: ", 1)
            if " — due: " in txt:
                txt, due = txt.rsplit(" — due: ", 1)
                due = due.strip()
                if not DATE_RE.fullmatch(due):
                    r.error("F4", i, f"item {n}.{k}: `due:` must be YYYY-MM-DD, got `{due}`")
            if n != phase.n:
                r.error("F4", i, f"item {n}.{k} listed under phase {phase.n}")
            if visible_len(txt) > TODO_ITEM_CHARS:
                r.error("F13", i, f"item {n}.{k} text is {visible_len(txt)} visible chars, limit {TODO_ITEM_CHARS}")
            if phase.done:
                r.error("F5", i, f"closed phase {phase.n} still lists items — they belong in the phase file")
            phase.items.append(Item(n, k, mark == "x", txt, i, held, reason, due))
            continue
        m = WAITS_RE.match(raw)
        if m:
            if phase is None:
                r.error("F6", i, "`waits:` before any phase")
            else:
                phase.waits.append(m.group(1))
            continue
        r.error("F4", i, "unparsable line: expected `- [ ] N Name`, `  - [ ] N.M text` or `  - waits: <case>`")
    return r


# ---- README (F1, F2, F3) ------------------------------------------------------------------------
@dataclass
class Readme(Result):
    sections: dict = field(default_factory=dict)  # name -> list of lines (without the heading)
    lines: int = 0
    bytes: int = 0
    rendered_lines: int = 0   # Links lines mike renders from the files — not counted by F2
    rendered_bytes: int = 0


def parse_readme(text: str) -> Readme:
    r = Readme()
    lines = _frame(text, r)
    r.lines, r.bytes = len(lines), len("\n".join(lines).encode("utf-8"))
    order, current = [], None
    for i, raw in enumerate(lines[1:], start=2):
        m = SECTION_RE.match(raw)
        if m:
            current = m.group(1).strip()
            if current in r.sections:
                r.error("F1", i, f"section `{current}` appears twice")
            r.sections[current] = []
            order.append(current)
            continue
        if raw.strip() == "":
            continue
        if current is None:
            r.error("F1", i, "text before the first section")
            continue
        r.sections[current].append(raw)
        if raw.startswith("- ") and visible_len(raw.strip()) > README_POINTER_CHARS:
            r.warn("F2", i, f"pointer line is {visible_len(raw.strip())} visible chars, over {README_POINTER_CHARS}")
    # F2 counts the text people write. The nested Links lines (files, sub-folders, `other:`) are
    # rendered by mike from the files and cannot be shortened in README — they are reported, not
    # counted (feedback 2026-09-03: a growing file index squeezed the owner's own five lines out).
    rendered = [ln for ln in r.sections.get("Links", []) if ln.startswith("  ")]
    r.rendered_lines, r.rendered_bytes = len(rendered), sum(len(ln.encode("utf-8")) + 1 for ln in rendered)
    own_lines, own_bytes = r.lines - r.rendered_lines, r.bytes - r.rendered_bytes
    aside = (f" (Links rendered by mike: {r.rendered_lines} lines / {r.rendered_bytes} bytes more, not counted)"
             if rendered else "")
    if own_lines > README_MAX_LINES or own_bytes > README_MAX_BYTES:
        r.error("F2", 0, f"README is {own_lines} lines / {own_bytes} bytes of your text, limit {README_MAX_LINES} / {README_MAX_BYTES}{aside}")
    elif own_lines > README_WARN_LINES or own_bytes > README_WARN_BYTES:
        r.warn("F2", 0, f"README is {own_lines} lines / {own_bytes} bytes of your text, over {README_WARN_LINES} / {README_WARN_BYTES}: "
                        f"move a section into a file{aside}")
    if order != README_SECTIONS:
        r.error("F1", 0, f"sections must be exactly {' · '.join(README_SECTIONS)}, got {' · '.join(order) or 'none'}")
    state = r.sections.get("State", [])
    if not any(ln.lstrip("- ").startswith("progress:") for ln in state):
        r.warn("F3", 0, "State has no `progress:` line")
    return r


# ---- phase file (F12) ---------------------------------------------------------------------------
@dataclass
class PhaseFile(Result):
    n: Optional[int] = None
    name: Optional[str] = None
    goal: str = ""
    result: str = ""
    body: List[str] = field(default_factory=list)


def parse_phase_file(text: str) -> PhaseFile:
    r = PhaseFile()
    lines = text.rstrip("\n").split("\n")
    m = PHASE_TITLE_RE.match(lines[0]) if lines else None
    if not m:
        r.error("F12", 1, "first line must be `# Phase N — Name`")
    else:
        r.title, r.n, r.name = lines[0][2:], int(m.group(1)), m.group(2).strip()
        if not PHASE_NAME_RE.match(r.name):
            r.error("F13", 1, f"phase name `{r.name}` must be English, 1–3 words")
    if len(lines) < 2 or not lines[1].startswith("goal:") or not lines[1][5:].strip():
        r.error("F12", 2, "second line must be `goal: <one line>`")
    else:
        r.goal = lines[1][5:].strip()
    if len(lines) < 3 or not lines[2].startswith("result:"):
        r.error("F12", 3, "third line must be `result:` (empty while the phase is open)")
    else:
        r.result = lines[2][7:].strip()
    r.body = lines[3:]
    for i, raw in enumerate(r.body, start=4):
        if CHECKBOX_RE.match(raw):
            r.error("F12", i, "no checklist in the phase file — that duplicates TODO")
            break
    return r
