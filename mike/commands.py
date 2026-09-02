"""The ten commands of `mike` — every write to the three files goes through here (P3).

Each function takes the case folder (already resolved by main), does its preconditions (exit 4),
validates through the grammar (exit 3) and writes with a fresh stamp. Functions return the lines
to print on success; warnings are collected in `Outcome.warnings` and printed to stderr by main.
"""
import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from . import grammar, migrate, order, stamp, store
from .store import StoreError

MAX_SCREEN = 24_000  # chars: Claude Code truncates tool output around 30K (owner's measurement 2026-08-22)
ENTRY_LIMIT = 10  # P1: last 10 journal entries on entry


@dataclass
class Outcome:
    lines: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def say(self, *ls):
        self.lines.extend(ls)

    def warn(self, *ws):
        self.warnings.extend(ws)

    def absorb(self, report: store.WriteReport):
        for f in report.warnings:
            self.warnings.append(f"{report.path.name}: {f}")
        if report.recovered:
            self.warnings.append(
                f"{report.path.name}: written bypassing mike — rebuilt by grammar, {report.recovered_lines} line(s) moved to "
                f"{report.recovered.name}: re-enter them with mike, then run: rm '{report.recovered}' (S4)")
        elif report.bypassed:
            self.warnings.append(f"{report.path.name}: written bypassing mike — content was valid, stamp renewed (S4)")


def _now():
    t = dt.datetime.now()
    return t.strftime("%Y-%m-%d"), t.strftime("%H:%M")


def _phase_of(todo: grammar.Todo) -> str:
    cur = todo.current()
    return f"p{cur.n}" if cur else "p0"


# ---- TODO rendering (machine-owned text) ---------------------------------------------------------
def render_todo(todo: grammar.Todo) -> str:
    out = [f"# {todo.title}", ""]
    for p in sorted(todo.phases, key=lambda x: x.n):
        mark = "x" if p.done else " "
        head = f"- [{mark}] {p.n} {p.name}"
        if p.summary:
            head += f" — {p.summary}"
        out.append(head)
        for it in [i for i in p.items if not i.held] + [i for i in p.items if i.held]:
            mark = "x" if it.done else ("~" if it.held else " ")
            suffix = f" — hold: {it.hold_reason}" if it.held and it.hold_reason else ""
            out.append(f"  - [{mark}] {it.n}.{it.m} {it.text}{suffix}")
        for w in p.waits:
            out.append(f"  - waits: {w}")
    return "\n".join(out) + "\n"


def _unparsable(case: Path, name: str) -> StoreError:
    """The precise blocker: a legacy file (never stamped, outside the grammar) names `mike migrate`;
    a file mike wrote that broke since names `mike check` (S4 rebuilds it on the next write)."""
    why = migrate.legacy_reason(case, name)
    if why:
        return StoreError(f"{name} is outside mike's grammar and was never stamped by mike ({why}) — a legacy case; "
                          f"nothing is written until it is migrated", 3, recovery=store.MIGRATE_HINT)
    return StoreError(f"{name} is not parsable — see the violations: mike check", 3, recovery="mike check")


def _todo(case: Path, out: Optional[Outcome] = None) -> grammar.Todo:
    if migrate.legacy_reason(case, "TODO.md"):
        raise _unparsable(case, "TODO.md")  # before store.load: a legacy file is never rebuilt
    body, report = store.load(case, "TODO.md")
    if out is not None:
        out.absorb(report)
    todo = grammar.parse_todo(body)
    if todo.errors:
        raise _unparsable(case, "TODO.md")
    return todo


# ---- README helpers -----------------------------------------------------------------------------
def _readme_text(case: Path, out: Optional[Outcome] = None) -> str:
    body, report = store.load(case, "README.md")
    if out is not None:
        out.absorb(report)
    return body


def _set_state_line(readme: str, prefix: str, value: Optional[str]) -> str:
    """Replace (or add / remove when value is None) the `- <prefix>` line inside `## State`.
    A new line goes at the end of the section's text, before the blank line that precedes the
    next heading."""
    lines = readme.rstrip("\n").split("\n")
    out, in_state, done = [], False, False

    def add_line():
        k = len(out)
        while k > 0 and out[k - 1] == "":
            k -= 1
        out.insert(k, f"- {prefix}{value}")

    for ln in lines:
        if ln.startswith("## "):
            if in_state and not done and value is not None:
                add_line()
                done = True
            in_state = ln == "## State"
        if in_state and ln.startswith(f"- {prefix}"):
            if value is not None and not done:
                out.append(f"- {prefix}{value}")
            done = True  # replaced or removed
            continue
        out.append(ln)
    if in_state and not done and value is not None:
        add_line()
    return "\n".join(out) + "\n"


def progress_line(todo: grammar.Todo, case: Optional[Path] = None) -> str:
    """`✓` closed · `▶` opened (its phase file exists) · no mark = planned (F3)."""
    parts = []
    for p in sorted(todo.phases, key=lambda x: x.n):
        opened = case is not None and _phase_file(case, p.n, p.name).exists()
        mark = " ✓" if p.done else (" ▶" if opened else "")
        parts.append(f"{p.n} {p.name}{mark}")
    return " · ".join(parts) if parts else "(no phases yet)"


def _is_project(case: Path) -> bool:
    """Root mode: the case folder is the project folder itself (it holds `.cases/`)."""
    return (case / store.CASES_DIR).is_dir()


def _replace_section(body: str, name: str, new_lines: List[str]) -> str:
    """Replace the lines of `## <name>` in place, leaving every other byte of the README as it is."""
    lines = body.rstrip("\n").split("\n")
    start = next((i for i, ln in enumerate(lines) if ln == f"## {name}"), None)
    if start is None:
        return body
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return "\n".join(lines[: start + 1] + new_lines + ([""] if end < len(lines) else []) + lines[end:]) + "\n"


def _derive_readme(case: Path, body: str) -> str:
    """Refresh what mike owns inside README: `progress:` (from TODO), `last:` (newest RESULT in the
    journal), and the folder/file lines of Links (from the files' own `summary:` lines, F14).
    What the agent wrote stays; only the derived parts move. Unparsable input is returned as is."""
    parsed = grammar.parse_readme(body)
    if parsed.errors:
        return body
    links, _ = order.render_links(case, _is_project(case), parsed.sections.get("Links", []))
    text = _replace_section(body, "Links", links)
    try:
        todo = grammar.parse_todo(store.read(case, "TODO.md"))
        if not todo.errors:
            text = _set_state_line(text, "progress: ", progress_line(todo, case))
    except StoreError:
        pass
    try:
        journal = grammar.parse_journal(store.read(case, "JOURNAL.md"))
        last = next((ev.text for e in journal.entries for ev in e.events if ev.type == "RESULT"), None)
        if last:
            text = _set_state_line(text, "last: ", order._short(last, grammar.README_POINTER_CHARS - 10))
    except StoreError:
        pass
    return _blank_before_headings(text)


def _blank_before_headings(text: str) -> str:
    """Exactly one blank line before every `## ` heading — the shape a reader expects, whatever
    the agent's draft looked like."""
    out: List[str] = []
    for ln in text.rstrip("\n").split("\n"):
        if ln.startswith("## "):
            while out and out[-1] == "":
                out.pop()
            if out:
                out.append("")
        out.append(ln)
    return "\n".join(out) + "\n"


def _write_readme(case: Path, body: str, out: Outcome, anchor: bool = False):
    """Every README write goes through here: derived parts refreshed, `as of` anchored when the
    agent rewrote State (S5), then the stamp door."""
    if anchor:
        try:
            header = order.newest_header(grammar.parse_journal(store.read(case, "JOURNAL.md")))
        except StoreError:
            header = None
        if header:
            body = _set_state_line(body, "as of: ", header)
    out.absorb(store.write(case, "README.md", _derive_readme(case, body)))


def _sync_progress(case: Path, todo: grammar.Todo, out: Outcome):
    _write_readme(case, _readme_text(case, out), out)


# ---- journal ------------------------------------------------------------------------------------
BODY_WRAP = 160


def _render_event(typ: str, text: str):
    """Turn text into journal lines: `  TYPE · headline` + up to 5 wrapped body lines (F7).

    A long text is split at word boundaries instead of being refused — the limit shapes the
    record, it must not block the write (live feedback 2026-08-31).
    """
    text = " ".join(text.split())
    if len(f"{typ} · {text}") <= grammar.EVENT_CHARS:
        return [f"  {typ} · {text}"], False
    # split under the SOFT threshold, so a split line never triggers "close to the limit" later
    head_budget = grammar.EVENT_WARN_CHARS - len(typ) - 3
    words = text.split(" ")
    head, i = "", 0
    while i < len(words) and len(head) + len(words[i]) + 1 <= head_budget - 2:
        head += (" " if head else "") + words[i]
        i += 1
    if not head:  # a single word longer than the whole headline — hard cut
        head, words[0] = words[0][: head_budget - 2], words[0][head_budget - 2:]
        i = 0
    rest, body = " ".join(words[i:]), []
    while rest and len(body) < grammar.EVENT_BODY_LINES:
        if len(rest) <= BODY_WRAP:
            body.append(rest)
            rest = ""
        else:
            cut = rest.rfind(" ", 0, BODY_WRAP)
            cut = cut if cut > 0 else BODY_WRAP
            body.append(rest[:cut])
            rest = rest[cut:].strip()
    if rest:
        raise StoreError(f"event text is too long even for a headline plus {grammar.EVENT_BODY_LINES} body lines (F7) — "
                         f"put the story into the phase file and log a short line with a path", 3)
    return [f"  {typ} · {head} …"] + [f"    {b}" for b in body], True


def _resolve_phase(todo: grammar.Todo, ref: str) -> str:
    """Accept what the user sees — `p1`, `1`, `4.1` or a unique phase name — and return canonical `pN`."""
    ref = ref.strip()
    if re.fullmatch(r"p\d+(\.\d+)?", ref):
        return ref
    if re.fullmatch(r"\d+(\.\d+)?", ref):
        return f"p{ref}"
    named = [p for p in todo.phases if p.name.lower() == ref.lower()]
    if len(named) == 1:
        return f"p{named[0].n}"
    known = " · ".join(f"p{p.n} {p.name}" for p in sorted(todo.phases, key=lambda x: x.n)) or "none yet"
    raise StoreError(f"cannot resolve phase `{ref}` — use the canonical form, e.g. `mike log --phase p1 DECISION \"…\"`; "
                     f"phases here: {known}", 2)


def log(case: Path, typ: str, text: str, phase: Optional[str] = None) -> Outcome:
    out = Outcome()
    typ = typ.upper()
    if typ not in grammar.JOURNAL_TYPES:
        raise StoreError(f"unknown type `{typ}` — allowed: PHASE · DECISION · PROBLEM · RESULT (F8)", 2)
    event_lines, split = _render_event(typ, text)
    if split:
        out.warn(f"event longer than {grammar.EVENT_CHARS} chars — split into headline + {len(event_lines) - 1} body line(s) (F7)")
    todo = _todo(case, out)
    phase = _resolve_phase(todo, phase) if phase else _phase_of(todo)
    date, time = _now()
    if migrate.legacy_reason(case, "JOURNAL.md"):
        raise _unparsable(case, "JOURNAL.md")
    body, report = store.load(case, "JOURNAL.md")
    out.absorb(report)
    lines = body.rstrip("\n").split("\n")
    header = f"- {date} {time} · {phase}"
    first = next((i for i, ln in enumerate(lines) if grammar.ENTRY_RE.match(ln)), None)
    if first is not None and lines[first] == header:
        j = first + 1
        while j < len(lines) and lines[j].startswith("  "):
            j += 1
        lines[j:j] = event_lines
    else:
        at = first if first is not None else len(lines)
        block = [header] + event_lines
        if at < len(lines) and first is not None:
            lines[at:at] = block
        else:
            if lines and lines[-1] != "":
                lines.append("")
            lines.extend(block)
    report = store.write(case, "JOURNAL.md", "\n".join(lines) + "\n")
    inserted = set()
    for idx, ln in enumerate(lines, start=1):
        if ln == header or ln in event_lines:
            inserted.add(idx)
    report.warnings = [w for w in report.warnings if w.line == 0 or w.line in inserted]
    out.absorb(report)
    out.say(f"logged: {typ} → JOURNAL.md ({header[2:]})")
    if typ == "RESULT":  # README `last:` follows the newest RESULT (derived, never hand-written)
        try:
            _write_readme(case, _readme_text(case), out)
        except StoreError as e:
            out.warn(f"README `last:` not refreshed — {e}")
    return out


def _events_for_phase(journal: grammar.Journal, phase: str):
    return [ev for e in journal.entries if e.phase == phase for ev in e.events]


def _journal(case: Path, out: Optional[Outcome] = None) -> grammar.Journal:
    if migrate.legacy_reason(case, "JOURNAL.md"):
        raise _unparsable(case, "JOURNAL.md")
    body, report = store.load(case, "JOURNAL.md")
    if out is not None:
        out.absorb(report)
    j = grammar.parse_journal(body)
    if j.errors:
        raise _unparsable(case, "JOURNAL.md")
    return j


def _trim_suggestion(text: str, limit: int) -> str:
    cut = text.rfind(" ", 0, limit)
    return text[: cut if cut > limit // 2 else limit].rstrip()


# ---- todo ---------------------------------------------------------------------------------------
def todo_done(case: Path, ref: str) -> Outcome:
    out = Outcome()
    m = re.fullmatch(r"(\d+)\.(\d+)", ref)
    if not m:
        raise StoreError("use `mike todo done N.M` for an item or `mike phase close N` for a phase", 2)
    n, k = int(m.group(1)), int(m.group(2))
    todo = _todo(case, out)
    phase = todo.phase(n)
    item = next((it for it in phase.items if it.m == k), None) if phase else None
    if item is None:
        raise StoreError(f"no item {ref} in TODO.md", 4)
    if item.done:
        out.say(f"item {ref} already done — nothing changed")
        return out
    item.done, item.held, item.hold_reason = True, False, ""
    out.absorb(store.write(case, "TODO.md", render_todo(todo)))
    out.say(f"done: {ref} {item.text} → TODO.md")
    return out


def todo_add(case: Path, ref: str, text: str) -> Outcome:
    """Add item N.M (M = next free) to an open phase N; `ref` is the phase number."""
    out = Outcome()
    if not ref.isdigit():
        raise StoreError("use `mike todo add N \"text\"` — N is the phase number", 2)
    todo = _todo(case, out)
    phase = todo.phase(int(ref))
    if phase is None or phase.done:
        raise StoreError(f"phase {ref} is missing or closed", 4)
    text = " ".join(text.split())
    if grammar.visible_len(text) > grammar.TODO_ITEM_CHARS:
        raise StoreError(f"item text is {grammar.visible_len(text)} visible chars, limit {grammar.TODO_ITEM_CHARS} (F13); "
                         f"markdown links count as their name\n"
                         f"  suggestion: \"{_trim_suggestion(text, grammar.TODO_ITEM_CHARS)}\"", 3)
    m = max((it.m for it in phase.items), default=0) + 1
    phase.items.append(grammar.Item(phase.n, m, False, text, 0))
    out.absorb(store.write(case, "TODO.md", render_todo(todo)))
    out.say(f"added: {phase.n}.{m} {text} → TODO.md")
    return out


def _find_item(todo: grammar.Todo, ref: str):
    m = re.fullmatch(r"(\d+)\.(\d+)", ref)
    if not m:
        raise StoreError(f"`{ref}` — use N.M, e.g. 2.3", 2)
    phase = todo.phase(int(m.group(1)))
    item = next((it for it in phase.items if it.m == int(m.group(2))), None) if phase else None
    if item is None:
        raise StoreError(f"no item {ref} in TODO.md", 4)
    if phase.done:
        raise StoreError(f"phase {phase.n} is closed — its items live in the phase file now", 4)
    return phase, item


def todo_edit(case: Path, ref: str, text: str) -> Outcome:
    out = Outcome()
    todo = _todo(case, out)
    phase, item = _find_item(todo, ref)
    text = " ".join(text.split())
    if grammar.visible_len(text) > grammar.TODO_ITEM_CHARS:
        raise StoreError(f"item text is {grammar.visible_len(text)} visible chars, limit {grammar.TODO_ITEM_CHARS} (F13)\n"
                         f"  suggestion: \"{_trim_suggestion(text, grammar.TODO_ITEM_CHARS)}\"", 3)
    old_text, item.text = item.text, text
    out.absorb(store.write(case, "TODO.md", render_todo(todo)))
    out.say(f"edited: {ref} → TODO.md (was: «{old_text}»)")
    return out


def todo_move(case: Path, ref: str, to: str) -> Outcome:
    out = Outcome()
    todo = _todo(case, out)
    phase, item = _find_item(todo, ref)
    m = re.fullmatch(r"(\d+)\.(\d+)", to)
    if not m or int(m.group(1)) != phase.n:
        raise StoreError(f"move works inside one phase: `mike todo move {phase.n}.M {phase.n}.K`; "
                         f"to another phase — drop and add", 2)
    k = int(m.group(2))
    phase.items.remove(item)
    phase.items.insert(max(0, min(k - 1, len(phase.items))), item)
    renumbered = any(it.m != idx for idx, it in enumerate(phase.items, start=1))
    for idx, it in enumerate(phase.items, start=1):  # positions become contiguous
        it.m = idx
    out.absorb(store.write(case, "TODO.md", render_todo(todo)))
    if renumbered:
        out.say(f"numbers of phase {phase.n} recounted — older N.M references in the journal go by text")
    out.say(f"moved: item now at {phase.n}.{item.m}; the phase list:", *(
        f"  - [{'x' if it.done else ' '}] {it.n}.{it.m} {it.text}" for it in phase.items))
    return out


def todo_hold(case: Path, ref: str, reason: str) -> Outcome:
    out = Outcome()
    todo = _todo(case, out)
    phase, item = _find_item(todo, ref)
    if item.done:
        raise StoreError(f"item {ref} is done — nothing to hold", 4)
    item.held, item.hold_reason = True, " ".join(reason.split())
    out.absorb(store.write(case, "TODO.md", render_todo(todo)))
    out.say(f"on hold: {ref} (held items sit at the end of the phase; `mike todo resume {ref}` brings it back)")
    return out


def todo_resume(case: Path, ref: str) -> Outcome:
    out = Outcome()
    todo = _todo(case, out)
    phase, item = _find_item(todo, ref)
    if not item.held:
        out.say(f"item {ref} is not on hold — nothing changed")
        return out
    item.held, item.hold_reason = False, ""
    out.absorb(store.write(case, "TODO.md", render_todo(todo)))
    out.say(f"resumed: {ref} {item.text} → TODO.md")
    return out


def todo_drop(case: Path, ref: str) -> Outcome:
    out = Outcome()
    todo = _todo(case, out)
    phase, item = _find_item(todo, ref)
    phase.items.remove(item)
    out.absorb(store.write(case, "TODO.md", render_todo(todo)))
    out.say(f"dropped: {ref} «{item.text}» (git keeps the history; a decision behind it → mike log DECISION)")
    return out


# ---- phases -------------------------------------------------------------------------------------
def _phase_file(case: Path, n: int, name: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return case / "phases" / f"{n}-{slug}.md"


def _closing_checks(case: Path, prev: grammar.Phase, journal: grammar.Journal) -> List[str]:
    """What P8 demands from a phase before the next one may open."""
    missing = []
    pf0 = _phase_file(case, prev.n, prev.name)
    if pf0.exists():
        parsed0 = grammar.parse_phase_file(pf0.read_text(encoding="utf-8"))
        if not parsed0.errors and parsed0.goal.startswith("migrated from legacy"):
            return []  # closed by `mike migrate`: its RESULT/reflect/align live in the legacy archive
    evs = _events_for_phase(journal, f"p{prev.n}")
    if not any(ev.type == "RESULT" for ev in evs):
        missing.append(f"phase {prev.n}: no RESULT in the journal (F9)")
    if not any(ev.text.startswith("reflect:") for ev in evs):
        missing.append(f"phase {prev.n}: no `DECISION · reflect: …` (P8)")
    if not any(ev.text.startswith("align:") for ev in evs):
        missing.append(f"phase {prev.n}: no `DECISION · align: …` (P8)")
    pf = _phase_file(case, prev.n, prev.name)
    if not pf.exists():
        missing.append(f"phase {prev.n}: {pf.relative_to(case)} is missing (F12)")
    else:
        parsed = grammar.parse_phase_file(pf.read_text(encoding="utf-8"))
        if not parsed.result:
            missing.append(f"phase {prev.n}: `result:` is empty in {pf.relative_to(case)} (F12)")
    if prev.waits:
        missing.append(f"phase {prev.n}: still waits for {', '.join(prev.waits)}")
    return missing


def phase_open(case: Path, n: int, name: str, goal: Optional[str]) -> Outcome:
    out = Outcome()
    if not grammar.PHASE_NAME_RE.match(name):
        raise StoreError(f"phase name `{name}` must be English, 1–3 words (F13)", 2)
    todo = _todo(case, out)
    existing = todo.phase(n)
    if existing and existing.done:
        raise StoreError(f"phase {n} is already closed", 4)
    pf = _phase_file(case, n, existing.name if existing else name)
    if existing and not existing.done and pf.exists():
        out.say(f"phase {n} {existing.name} is already open — nothing changed")
        return out
    prev = max((p for p in todo.phases if p.n < n), key=lambda p: p.n, default=None)
    if prev is not None:
        journal = _journal(case, out)
        missing = [] if prev.done else [f"phase {prev.n} {prev.name} is still open — close it first (P8)"]
        if prev.done:
            missing = _closing_checks(case, prev, journal)
        if missing:
            raise StoreError("cannot open phase %d:\n  " % n + "\n  ".join(missing), 4)
    renamed = None
    if existing is not None and not pf.exists() and name != existing.name:
        # a planned phase may be re-planned at opening (P8 align): the name follows the owner's word
        renamed, existing.name = existing.name, name
        pf = _phase_file(case, n, name)
    if not pf.exists():
        if not goal:
            raise StoreError("a new phase needs `--goal \"one line\"` (F12)", 2)
        pf.parent.mkdir(exist_ok=True)
        pf.write_text(f"# Phase {n} — {name}\ngoal: {' '.join(goal.split())}\nresult:\n\n## Notes\n", encoding="utf-8")
        out.say(f"created: {pf.relative_to(case)}")
    if existing is None:
        todo.phases.append(grammar.Phase(n, name, False, 0))
    out.absorb(store.write(case, "TODO.md", render_todo(todo)))
    _sync_progress(case, todo, out)
    opened = f"{name} открыта" + (f" (запланирована была как «{renamed}»)" if renamed else "")
    out.lines = log(case, "PHASE", opened, f"p{n}").lines + out.lines
    out.say(f"phase {n} {name} is open → TODO.md, README.md State")
    return out


def phase_close(case: Path, n: int, summary: str) -> Outcome:
    out = Outcome()
    todo = _todo(case, out)
    phase = todo.phase(n)
    if phase is None:
        raise StoreError(f"no phase {n} in TODO.md", 4)
    if phase.done:
        out.say(f"phase {n} {phase.name} is already closed — nothing changed")
        return out
    journal = _journal(case, out)
    missing = [m for m in _closing_checks(case, phase, journal) if "result:" not in m]
    if missing:
        raise StoreError("cannot close phase %d:\n  " % n + "\n  ".join(missing), 4)
    summary = " ".join(summary.split())
    date, _ = _now()
    pf = _phase_file(case, n, phase.name)
    text = pf.read_text(encoding="utf-8").split("\n")
    text[2] = f"result: {summary}"
    if phase.items:
        text.append("")
        text.append("## Items at close")
        text.extend(f"- {it.n}.{it.m} {'✓' if it.done else '✗'} {it.text}" for it in phase.items)
    pf.write_text("\n".join(text).rstrip("\n") + "\n", encoding="utf-8")
    rel = f"phases/{pf.name}"
    phase.done, phase.items = True, []
    phase.summary = f"{summary} · {date} · {rel}" if rel not in summary else summary
    out.absorb(store.write(case, "TODO.md", render_todo(todo)))
    _sync_progress(case, todo, out)
    out.lines = log(case, "PHASE", f"{phase.name} закрыта → {summary}", f"p{n}").lines + out.lines
    out.say(f"closed: phase {n} {phase.name} → TODO.md (collapsed), {rel} (result), README.md State")
    return out


# ---- readme -------------------------------------------------------------------------------------
def readme(case: Path, text: str) -> Outcome:
    out = Outcome()
    body, _ = stamp.split(text)
    try:
        todo = _todo(case, out)
        if not re.search(r"^- progress:", body, re.M):
            body = _set_state_line(body, "progress: ", progress_line(todo, case))
    except StoreError as e:  # readme-only mode: the README is written, progress: is not synced
        out.warn(f"progress: not synced — {e} (recovery: {e.recovery})")
    _write_readme(case, body, out, anchor=True)
    out.say("written: README.md (State anchored `as of` the newest journal entry; Links rendered from the files)")
    return out


SECTION_NAMES = {n.lower(): n for n in grammar.README_SECTIONS}


def _readme_sections(case: Path, out: Outcome):
    body = _readme_text(case, out)
    parsed = grammar.parse_readme(body)
    if parsed.errors:
        raise _unparsable(case, "README.md")
    return parsed


def _render_readme(parsed) -> str:
    lines = [f"# {parsed.title}"]
    for name in grammar.README_SECTIONS:
        lines += ["", f"## {name}"] + parsed.sections.get(name, [])
    return "\n".join(lines) + "\n"


def readme_set(case: Path, prefix: str, text: str) -> Outcome:
    """Replace (or create) the `- <prefix>: …` line in State — one line instead of a full rewrite."""
    out = Outcome()
    _readme_sections(case, out)  # ensures the file parses before we touch it
    prefix = prefix.rstrip(":")
    body = _set_state_line(_readme_text(case, out), f"{prefix}: ", " ".join(text.split()))
    _write_readme(case, body, out, anchor=True)
    out.say(f"README State: `- {prefix}: …` set (as of the newest journal entry)")
    return out


def readme_add(case: Path, section: str, line: str) -> Outcome:
    out = Outcome()
    name = SECTION_NAMES.get(section.lower())
    if name is None:
        raise StoreError(f"no section `{section}` — sections: {' · '.join(grammar.README_SECTIONS)}", 2)
    parsed = _readme_sections(case, out)
    parsed.sections.setdefault(name, []).append(f"- {' '.join(line.split())}")
    _write_readme(case, _render_readme(parsed), out, anchor=name == "State")
    out.say(f"README {name}: line added")
    return out


def readme_drop(case: Path, section: str, k: int) -> Outcome:
    out = Outcome()
    name = SECTION_NAMES.get(section.lower())
    if name is None:
        raise StoreError(f"no section `{section}` — sections: {' · '.join(grammar.README_SECTIONS)}", 2)
    parsed = _readme_sections(case, out)
    bullets = [i for i, ln in enumerate(parsed.sections.get(name, [])) if ln.startswith("- ")]
    if not 1 <= k <= len(bullets):
        raise StoreError(f"{name} has {len(bullets)} line(s), nothing at position {k}", 4)
    removed = parsed.sections[name].pop(bullets[k - 1])
    _write_readme(case, _render_readme(parsed), out, anchor=name == "State")
    out.say(f"README {name}: dropped «{removed[2:]}»")
    return out


# ---- cases --------------------------------------------------------------------------------------
def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _case_folder(name: str) -> str:
    """`YYYY-MM-DD-<slug>`. A date already present in the name is used, not doubled (feedback 2026-08-31)."""
    m = store.DATE_PREFIX_RE.match(name.strip())
    if m:
        date, name = name.strip()[:10], name.strip()[11:]
    else:
        date, _ = _now()
    folder = f"{date}-{_slug(name)}"
    if not store.CASE_NAME_RE.match(folder):
        raise StoreError(f"`{folder}` is not a valid case name: date prefix + words of letters/digits, hyphens (L2)", 2)
    return folder


def case_new(root: Path, name: str, goal: str, parent: Optional[Path] = None) -> Path:
    folder = _case_folder(name)
    case = (parent or root) / folder
    if case.exists():
        raise StoreError(f"{case} already exists", 4)
    case.mkdir()
    title = name.strip()
    goal = " ".join(goal.split())
    links = [f"- parent: {parent.name} · фаза {_phase_of(store.todo_of(parent))[1:]}"] if parent else []
    d, t = _now()
    readme_text = "\n".join([
        f"# {title}", "", "## Context", goal, "", "## State", "- progress: (no phases yet)",
        "- next: open phase 1 — `mike phase open 1 <Name> --goal \"…\"`", f"- as of: {d} {t} · p0 (1 event)", "",
        "## Decisions", "", "## Problems", "", "## Links", *links, ""])
    store_write_fresh(case, "README.md", readme_text)
    store_write_fresh(case, "TODO.md", f"# TODO — {title}\n")
    event_lines, _ = _render_event("PHASE", f"дело открыто: {goal}")
    store_write_fresh(case, "JOURNAL.md", "\n".join([f"# JOURNAL — {title}", "", f"- {d} {t} · p0", *event_lines]) + "\n")
    return case


def store_write_fresh(case: Path, name: str, body: str):
    (case / name).write_text(stamp.apply(body), encoding="utf-8")


def case_list(root: Path) -> Outcome:
    out = Outcome()
    cases = store.all_cases(root)  # the project case first in root mode
    rejected0 = store.scan(root)[1]
    if not cases:
        for path, reason in rejected0:
            out.warn(f"not a case, ignored: {path.relative_to(root)} — {reason}")
        out.say("no cases yet — `mike case new <name> --goal \"…\"`")
        return out
    try:
        current = store.hand(root)
    except StoreError:
        current = None
    for path, reason in store.scan(root)[1]:
        out.warn(f"not a case, ignored: {path.relative_to(root)} — {reason}")
    for case in cases:
        depth = max(len(store.chain(case, root)) - 1, 0)
        todo = grammar.parse_todo(store.read(case, "TODO.md"))
        done_n, total = sum(p.done for p in todo.phases), len(todo.phases)
        cur = todo.current()
        waits = [w for p in todo.phases for w in p.waits]
        state = "closed" if not store.is_open(case) else (f"phase {cur.n} {cur.name}" if cur else "no open phase")
        mark = "*" if case == current else " "
        bits = [f"phases {done_n}/{total}", state]
        if waits:
            bits.append("waits: " + ", ".join(waits))
        out.say(f"{mark} {'  ' * depth}{case.name} — {' · '.join(bits)}")
    out.say("", "current is marked *; switch: `mike case use <name>`")
    return out


def case_use(root: Path, name: str) -> Outcome:
    """Switch the hand like `cf target`: bump the target's JOURNAL.md mtime — no state file, no content change."""
    import os as _os

    out = Outcome()
    case = store.resolve_case(root, name)
    if not store.is_open(case):
        raise StoreError(f"{case.name} is closed — the hand only holds open cases", 4)
    _os.utime(case / "JOURNAL.md")
    out.say(f"current case: {' › '.join(store.chain(case, root))}")
    return out


def project_new(root: Path, name: str, goal: str) -> Outcome:
    """Root mode on: the project folder itself becomes the top case (its children live in .cases/)."""
    out = Outcome()
    project = root.parent
    for fname in store.FILES:
        f = store.file_path(project, fname)
        if f.exists():
            raise StoreError(f"{f.name} already exists in {project} — it may be your public readme or docs; "
                             f"move its content aside first, mike will not overwrite it", 4)
    title = name.strip()
    goal = " ".join(goal.split())
    d, t = _now()
    store_write_fresh(project, "README.md", "\n".join([
        f"# {title}", "", "## Context", goal, "", "## State", "- progress: (no phases yet)",
        "- next: open phase 1 — `mike phase open 1 <Name> --goal \"…\"`", f"- as of: {d} {t} · p0 (1 event)", "",
        "## Decisions", "", "## Problems", "", "## Links", ""]))
    store_write_fresh(project, "TODO.md", f"# TODO — {title}\n")
    event_lines, _ = _render_event("PHASE", f"проект открыт: {goal}")
    store_write_fresh(project, "JOURNAL.md", "\n".join([f"# JOURNAL — {title}", "", f"- {d} {t} · p0", *event_lines]) + "\n")
    out.say(f"root mode on: {project.name} is now the top case (README/TODO/JOURNAL in the project root); "
            f"feature cases live in .cases/ — `mike case new \"…\" --goal \"…\"`")
    return out


def spawn(root: Path, parent: Path, name: str, goal: str) -> Outcome:
    out = Outcome()
    todo = _todo(parent, out)
    cur = todo.current()
    if cur is None:
        raise StoreError("parent has no open phase — spawn happens inside a phase (P11)", 4)
    into = root if parent == store.project_case(root) else parent
    child_name = _case_folder(name)
    if (into / child_name).exists():
        raise StoreError(f"{into / child_name} already exists", 4)
    # Parent first, child last: the hand follows the freshest JOURNAL.md, so the child must be written last.
    cur.waits.append(child_name)
    out.absorb(store.write(parent, "TODO.md", render_todo(todo)))
    text = _readme_text(parent, out)
    lines = text.rstrip("\n").split("\n")
    idx = next(i for i, ln in enumerate(lines) if ln == "## State")
    j = idx + 1
    while j < len(lines) and not lines[j].startswith("## "):
        j += 1
    while j > idx + 1 and lines[j - 1] == "":
        j -= 1
    lines.insert(j, f"- ждёт: {child_name}")
    _write_readme(parent, "\n".join(lines) + "\n", out)
    out.lines = log(parent, "PROBLEM", f"{goal} · open → {child_name}/").lines + out.lines
    child = case_new(root, name, goal, parent=None if into == root else parent)
    out.say(f"spawned: {child.relative_to(root)} — hand moves to the child; parent waits in phase {cur.n}")
    return out


def done(root: Path, case: Path, summary: str) -> Outcome:
    out = Outcome()
    todo = _todo(case, out)
    open_phases = [p for p in todo.phases if not p.done]
    if open_phases:
        raise StoreError("cannot close the case: open phases " + ", ".join(f"{p.n} {p.name}" for p in open_phases), 4)
    summary = " ".join(summary.split())
    date, _ = _now()
    text = _set_state_line(_readme_text(case, out), "closed: ", f"{date} · {summary}")
    _write_readme(case, text, out, anchor=True)
    out.lines = log(case, "PHASE", f"дело закрыто → {summary}").lines + out.lines
    parent = store.parent_case(case, root)
    if parent is not None:
        ptodo = _todo(parent, out)
        for p in ptodo.phases:
            if case.name in p.waits:
                p.waits.remove(case.name)
                m = max((it.m for it in p.items), default=0) + 1
                p.items.append(grammar.Item(p.n, m, True, f"{summary} · {case.name}/", 0))
        out.absorb(store.write(parent, "TODO.md", render_todo(ptodo)))
        _write_readme(parent, _set_state_line(_readme_text(parent, out), "ждёт: ", None), out)
        out.lines += log(parent, "PROBLEM", f"закрыто → {summary} · {case.name}/").lines
        out.say(f"parent updated: {parent.name} — hand returns to the parent")
    out.say(f"closed: {case.name}")
    return out


# ---- doctor -------------------------------------------------------------------------------------
def doctor() -> Outcome:
    """Read-only diagnostics: what mike sees from here. Never writes, never rebuilds (feedback #4)."""
    from . import __version__

    out = Outcome()
    out.say(f"mike {__version__} · python OK · cwd: {Path.cwd()} (mike never changes your cwd)")
    try:
        root = store.find_root()
    except StoreError as e:
        out.say(f"root: NOT FOUND — {e}", f"  recovery: {e.recovery}")
        return out
    out.say(f"root: {root}")
    cases = store.all_cases(root)
    rejected = store.scan(root)[1]
    out.say(f"cases: {len(cases)} ({sum(store.is_open(c) for c in cases)} open)")
    for path, reason in rejected:
        out.say(f"  ! not a case, ignored: {path.relative_to(root)} — {reason}")
    try:
        case = store.hand(root)
        out.say(f"hand: {' › '.join(store.chain(case, root))}")
        for name in store.FILES:
            f = store.file_path(case, name)
            if not f.exists():
                out.say(f"  ! {name}: MISSING (L3)")
                continue
            _, state = stamp.verify(f.read_text(encoding="utf-8"))
            note = {"ok": "stamp ok", "missing": "no stamp yet (set on first mike write)",
                    "mismatch": "stamp MISMATCH — edited bypassing mike; next mike write will rebuild (S4)",
                    "not-last": "stamp NOT LAST — something appended after it; next mike write will rebuild (S4)"}[state]
            out.say(f"  {f.name}: {note}")
        for name, why in store.legacy_files(case):
            out.say(f"  ! {name}: legacy — {why}; outside the grammar and never stamped → {store.MIGRATE_HINT}")
        for rec in store.recover_files(case):
            out.say(f"  ! pending {rec.name} — re-enter its lines with mike, then: rm '{rec}'")
        if case != store.project_case(store.find_root()):
            for stray in store.stray_files(case):
                out.say(f"  ! extra file in the case root: {stray.name} — move into a folder by kind (L4)")
    except StoreError as e:
        out.say(f"hand: — ({e})", f"  recovery: {e.recovery}")
    out.say("read-only: doctor changed nothing")
    return out


# ---- feedback -----------------------------------------------------------------------------------
def feedback_dir() -> Path:
    """Feedback pool lives in the mike-cli clone (env MIKE_FEEDBACK_DIR overrides, e.g. in tests) —
    it travels between machines with `git pull`, like elephant's pool."""
    import os as _os

    override = _os.environ.get("MIKE_FEEDBACK_DIR")
    return Path(override) if override else Path(__file__).resolve().parent.parent / "feedback"


def feedback(title: str, expected: str, actual: str, why: str, acceptance: str, repro: str) -> Outcome:
    out = Outcome()
    title = " ".join(title.split())
    if not title or not expected or not actual:
        raise StoreError("feedback needs at least a title, --expected and --actual; add --repro/--why/--acceptance "
                         "when you can", 2)
    d, t = _now()
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "feedback"
    folder = feedback_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{d}-{t.replace(':', '')}-{slug}.md"
    try:
        case = " › ".join(store.chain(store.hand(store.find_root()), store.find_root()))
    except StoreError:
        case = "—"
    from . import __version__
    sections = [f"# {title}", "", f"date: {d} {t} · mike {__version__} · case: {case}", ""]
    for heading, text_ in (("Reproduction", repro), ("Actual", actual), ("Expected", expected),
                           ("Why", why), ("Acceptance", acceptance)):
        if text_:
            sections += [f"## {heading}", text_.strip(), ""]
    path.write_text("\n".join(sections), encoding="utf-8")
    out.say(f"feedback written: {path}")
    return out


# ---- entry, order and check ---------------------------------------------------------------------
def _journal_headlines(journal: grammar.Journal, limit: int) -> List[str]:
    """The last `limit` entries as headlines only: no body lines, no legacy tool noise
    (`DECISION · todo …` written by v0.7–0.8 for every TODO edit). Bodies stay on disk."""
    total = len(journal.entries)
    lines = [f"# JOURNAL — last {min(limit, total)} of {total} entries (headlines; bodies in JOURNAL.md)"]
    for e in journal.entries[:limit]:
        events = [ev for ev in e.events if not (ev.type == "DECISION" and ev.text.startswith("todo "))]
        if not events:
            continue
        lines.append(f"- {e.date} {e.time} · {e.phase}")
        lines.extend(f"  {ev.type} · {ev.text}" for ev in events)
    return lines


def _refresh_readme(case: Path, out: Outcome) -> str:
    """On entry the README follows the folder: Links from the files, `last:` from the journal,
    `progress:` from TODO. Written only when something changed; failures never block the entry."""
    body, _ = stamp.split(store.read(case, "README.md"))
    derived = _derive_readme(case, body)
    if derived != body:
        try:
            out.absorb(store.write(case, "README.md", derived))
            out.say("README refreshed: Links from the files' summary lines · last: from the journal")
            return derived
        except StoreError as e:
            out.warn(f"README not refreshed — {e}")
    return body


def _order_lines(case: Path, root: Path, readme_body: str, journal: Optional[grammar.Journal]) -> List[str]:
    parsed = grammar.parse_readme(readme_body)
    links = parsed.sections.get("Links", []) if not parsed.errors else []
    lines = order.report(case, _is_project(case), readme_body, journal, links)
    legacy = store.legacy_files(case)
    if legacy:
        lines.insert(0, f"legacy file(s) outside mike's grammar, never stamped: {', '.join(n for n, _ in legacy)} → "
                        f"{store.MIGRATE_HINT}")
    for rec in store.recover_files(case):
        lines.append(f"pending {rec.name} → re-enter its lines with mike, then: rm '{rec}' (S4)")
    if case != store.project_case(root):
        for stray in store.stray_files(case):
            lines.append(f"extra file in the case root: {stray.name} → move it into a folder by kind (L4)")
    return lines


def entry(root: Path, case: Path) -> Outcome:
    out = Outcome()
    names = store.chain(case, root)
    out.say(f"mike · case in hand: {' › '.join(names)}", "")
    others = [c.name for c in store.all_cases(root) if store.is_open(c) and c != case]
    if others:
        out.say("other open cases: " + " · ".join(others) + " — switch: `mike case use <name>`", "")
    readme_body = _refresh_readme(case, out)
    out.say(readme_body.rstrip("\n"), "")
    todo_body, _ = stamp.split(store.read(case, "TODO.md"))
    out.say(todo_body.rstrip("\n"), "")
    journal = grammar.parse_journal(store.read(case, "JOURNAL.md"))
    if journal.entries:
        out.say(*_journal_headlines(journal, ENTRY_LIMIT), "")
    issues = _order_lines(case, root, readme_body, journal)
    if issues:
        out.say(f"## Order — {len(issues)} thing(s) to put back", *(f"- {ln}" for ln in issues), "")
    else:
        out.say("## Order", "- ✓ everything in place: files carry summaries, Links follow the files, State is current", "")
    out.say("how to work: mike help start · what goes where: mike help where · rules: .cases/RULES.md · full check: mike check")
    total = "\n".join(out.lines)
    if len(total) > MAX_SCREEN:
        out.lines = [total[:MAX_SCREEN], "", f"[truncated at {MAX_SCREEN} chars — README/TODO/JOURNAL are on disk]"]
    return out


def order_cmd(root: Path, case: Path, adopt: bool = False) -> Outcome:
    """What is out of order in the case in hand, with the command that fixes each line (P12).
    `--adopt`: move the descriptions the agent wrote in README Links into the files as `summary:`
    lines (F14) — the one mechanical fix mike can do on the lower layer."""
    out = Outcome()
    if adopt:
        body = _readme_text(case, out)
        parsed = grammar.parse_readme(body)
        if parsed.errors:
            raise StoreError("README.md is not parsable — run `mike check`", 3)
        _, fallback = order.render_links(case, _is_project(case), parsed.sections.get("Links", []))
        changed = order.adopt(case, fallback)
        for rel in changed:
            out.say(f"summary written into {rel} (from its Links description)")
        if not changed:
            out.say("nothing to adopt: every described file already carries its own summary")
    readme_body = _refresh_readme(case, out)
    journal = grammar.parse_journal(store.read(case, "JOURNAL.md"))
    issues = _order_lines(case, root, readme_body, journal)
    if issues:
        out.say(f"order — {len(issues)} thing(s) to put back:", *(f"- {ln}" for ln in issues))
    else:
        out.say("order: ✓ everything in place")
    return out


def migrate_cmd(case: Path, apply: bool = False) -> Outcome:
    """Legacy case → canonical files (P13). Dry run by default; `--apply` archives and writes."""
    out = Outcome()
    date, time = _now()
    plan = migrate.analyse(case, (date, time))
    if plan.empty:
        out.say(f"nothing to migrate: {case.name} — the three files are in mike's grammar and stamped (or absent)")
        return out
    out.say(*migrate.report(plan, dry=not apply))
    if not apply:
        return out
    for line in migrate.apply(plan):
        out.say(line)
    rel = plan.archive.relative_to(case)
    out.lines += log(case, "PHASE", f"дело перенесено из legacy формата → {rel}/ ({', '.join(sorted(plan.legacy))} byte-for-byte); "
                     f"журнал не конвертирован — перенеси нужное: mike log; State переписать: mike readme set next", "p0").lines
    if "README.md" not in plan.legacy:  # README kept: it still gets the pointer to the archive
        out.lines += readme_add(case, "links", f"{migrate.ARCHIVE_DIR}/ — файлы дела до миграции {date}, byte-for-byte: "
                                f"{', '.join(sorted(plan.legacy))}").lines
    _sync_progress(case, _todo(case, out), out)
    out.say("migrated — now: mike (Order shows what to rewrite) · mike readme set next \"…\" · mike check")
    return out


def check(root: Path, only: Optional[Path] = None) -> Outcome:
    out = Outcome()
    cases = store.all_cases(root)  # the project case first in root mode (feedback 2026-09-01 #1)
    rejected = store.scan(root)[1]
    if only is not None:
        cases = [c for c in cases if c == only or only in c.parents]
    for path, reason in rejected:
        out.warn(f"not a case, ignored: {path.relative_to(root)} — {reason}")
    errors = 0
    log_lines = []
    date, time = _now()
    for case in cases:
        for name, parse in (("README.md", grammar.parse_readme), ("TODO.md", grammar.parse_todo), ("JOURNAL.md", grammar.parse_journal)):
            p = store.file_path(case, name)
            if not p.exists():
                out.say(f"x {case.name}/{name}: missing (L3)")
                errors += 1
                continue
            text = p.read_text(encoding="utf-8")
            r = parse(text)
            for f in r.errors:
                out.say(f"x {case.name}/{name}: {f}")
                log_lines.append(f"{date} {time} · {case.name} · {name} · {f.rule} · {f.message}")
                errors += 1
            for f in r.warnings:
                out.warn(f"{case.name}/{name}: {f}")
            if r.stamp_state in ("mismatch", "not-last"):
                out.warn(f"{case.name}/{name}: stamp {r.stamp_state} — written bypassing mike (S4)")
                log_lines.append(f"{date} {time} · {case.name} · {name} · S4 · stamp {r.stamp_state}")
        for pf in sorted((case / "phases").glob("*.md")) if (case / "phases").exists() else []:
            r = grammar.parse_phase_file(pf.read_text(encoding="utf-8"))
            for f in r.errors:
                out.say(f"x {case.name}/phases/{pf.name}: {f}")
                log_lines.append(f"{date} {time} · {case.name} · phases/{pf.name} · {f.rule} · {f.message}")
                errors += 1
        for rec in store.recover_files(case):
            out.warn(f"{case.name}: pending {rec.name}")
        legacy = store.legacy_files(case)
        if legacy:
            out.say(f"  {case.name}: legacy file(s) never stamped by mike — {', '.join(n for n, _ in legacy)} → {store.MIGRATE_HINT}")
        readme_text_ = store.read(case, "README.md") if store.file_path(case, "README.md").exists() else ""
        for folder in sorted(case.iterdir()):
            if (not folder.is_dir() or folder.name.startswith(".") or folder.name == "phases"
                    or store.is_case_dir(folder) or case == store.project_case(root)):
                continue
            if f"{folder.name}/" not in readme_text_:
                n_files = sum(1 for f in folder.rglob("*") if f.is_file())
                out.warn(f"{case.name}: folder {folder.name}/ ({n_files} file(s)) has no line in README Links — "
                         f"for the owner it does not exist (L5); add: mike readme add links \"{folder.name}/ — …\"")
        if case != store.project_case(root):
            for stray in store.stray_files(case):
                out.say(f"x {case.name}: L4 · extra file in the case root: {stray.name} — only README/TODO/JOURNAL live "
                        f"there; move it into a folder by kind (docs/ research/ logs/ scripts/ …)")
                log_lines.append(f"{date} {time} · {case.name} · {stray.name} · L4 · extra file in the case root")
                errors += 1
        # order of the lower layer (F14, F15, S5): shown, never refused — mike does not write those files;
        # a closed case is an archive — `mike order` still answers there when asked, check stays quiet
        if store.is_open(case) and store.file_path(case, "README.md").exists() and store.file_path(case, "JOURNAL.md").exists():
            rb, _ = stamp.split(readme_text_)
            jr = grammar.parse_journal(store.read(case, "JOURNAL.md"))
            links = grammar.parse_readme(rb).sections.get("Links", [])
            for ln in order.report(case, _is_project(case), rb, jr if not jr.errors else None, links):
                out.warn(f"{case.name}: order · {ln}")
    if log_lines:
        with (root / "checks.log").open("a", encoding="utf-8") as fh:
            fh.write("\n".join(log_lines) + "\n")
    if not cases:
        out.say("cases: 0 — NOTHING WAS CHECKED (no cases found here); a zero here is not a green light")
    else:
        out.say(f"cases: {len(cases)} · violations: {errors} · warnings: {len(out.warnings)}")
    if errors:
        raise StoreError("\n".join(out.lines + [f"warning: {w}" for w in out.warnings]), 3)
    return out
