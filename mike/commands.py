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

from . import grammar, stamp, store
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
                f"{report.recovered.name}: re-enter them with mike, then delete that file (S4)")
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
        for it in p.items:
            out.append(f"  - [{'x' if it.done else ' '}] {it.n}.{it.m} {it.text}")
        for w in p.waits:
            out.append(f"  - waits: {w}")
    return "\n".join(out) + "\n"


def _todo(case: Path, out: Optional[Outcome] = None) -> grammar.Todo:
    body, report = store.load(case, "TODO.md")
    if out is not None:
        out.absorb(report)
    todo = grammar.parse_todo(body)
    if todo.errors:
        raise StoreError("TODO.md is not parsable — run `mike check`", 3)
    return todo


# ---- README helpers -----------------------------------------------------------------------------
def _readme_text(case: Path, out: Optional[Outcome] = None) -> str:
    body, report = store.load(case, "README.md")
    if out is not None:
        out.absorb(report)
    return body


def _set_state_line(readme: str, prefix: str, value: Optional[str]) -> str:
    """Replace (or add / remove when value is None) the `- <prefix>` line inside `## State`."""
    lines = readme.rstrip("\n").split("\n")
    out, in_state, done = [], False, False
    for ln in lines:
        if ln.startswith("## "):
            if in_state and not done and value is not None:
                out.append(f"- {prefix}{value}")
                done = True
            in_state = ln == "## State"
        if in_state and ln.startswith(f"- {prefix}"):
            if value is not None and not done:
                out.append(f"- {prefix}{value}")
            done = True  # replaced or removed
            continue
        out.append(ln)
    if in_state and not done and value is not None:
        out.append(f"- {prefix}{value}")
    return "\n".join(out) + "\n"


def progress_line(todo: grammar.Todo, case: Optional[Path] = None) -> str:
    """`✓` closed · `▶` opened (its phase file exists) · no mark = planned (F3)."""
    parts = []
    for p in sorted(todo.phases, key=lambda x: x.n):
        opened = case is not None and _phase_file(case, p.n, p.name).exists()
        mark = " ✓" if p.done else (" ▶" if opened else "")
        parts.append(f"{p.n} {p.name}{mark}")
    return " · ".join(parts) if parts else "(no phases yet)"


def _sync_progress(case: Path, todo: grammar.Todo, out: Outcome):
    text = _set_state_line(_readme_text(case, out), "progress: ", progress_line(todo, case))
    out.absorb(store.write(case, "README.md", text))


# ---- journal ------------------------------------------------------------------------------------
def log(case: Path, typ: str, text: str, phase: Optional[str] = None) -> Outcome:
    out = Outcome()
    typ = typ.upper()
    if typ not in grammar.JOURNAL_TYPES:
        raise StoreError(f"unknown type `{typ}` — allowed: PHASE · DECISION · PROBLEM · RESULT (F8)", 2)
    text = " ".join(text.split())
    event = f"  {typ} · {text}"
    if len(event.strip()) > grammar.EVENT_CHARS:
        raise StoreError(f"event line is {len(event.strip())} chars, limit {grammar.EVENT_CHARS} (F7): shorten the headline, "
                         f"put details in the phase file", 3)
    phase = phase or _phase_of(_todo(case, out))
    if not re.fullmatch(r"p\d+(\.\d+)?", phase):
        raise StoreError(f"phase must look like p3 or p4.1, got `{phase}`", 2)
    date, time = _now()
    body, report = store.load(case, "JOURNAL.md")
    out.absorb(report)
    lines = body.rstrip("\n").split("\n")
    header = f"- {date} {time} · {phase}"
    first = next((i for i, ln in enumerate(lines) if grammar.ENTRY_RE.match(ln)), None)
    if first is not None and lines[first] == header:
        j = first + 1
        while j < len(lines) and lines[j].startswith("  "):
            j += 1
        lines.insert(j, event)
    else:
        at = first if first is not None else len(lines)
        block = [header, event]
        if at < len(lines) and first is not None:
            lines[at:at] = block
        else:
            if lines and lines[-1] != "":
                lines.append("")
            lines.extend(block)
    out.absorb(store.write(case, "JOURNAL.md", "\n".join(lines) + "\n"))
    out.say(f"logged: {typ} → JOURNAL.md ({header[2:]})")
    return out


def _events_for_phase(journal: grammar.Journal, phase: str):
    return [ev for e in journal.entries if e.phase == phase for ev in e.events]


def _journal(case: Path, out: Optional[Outcome] = None) -> grammar.Journal:
    body, report = store.load(case, "JOURNAL.md")
    if out is not None:
        out.absorb(report)
    j = grammar.parse_journal(body)
    if j.errors:
        raise StoreError("JOURNAL.md is not parsable — run `mike check`", 3)
    return j


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
    item.done = True
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
    if len(text) > grammar.TODO_ITEM_CHARS:
        raise StoreError(f"item text is {len(text)} chars, limit {grammar.TODO_ITEM_CHARS} (F13)", 3)
    m = max((it.m for it in phase.items), default=0) + 1
    phase.items.append(grammar.Item(phase.n, m, False, text, 0))
    out.absorb(store.write(case, "TODO.md", render_todo(todo)))
    out.say(f"added: {phase.n}.{m} {text} → TODO.md")
    return out


# ---- phases -------------------------------------------------------------------------------------
def _phase_file(case: Path, n: int, name: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return case / "phases" / f"{n}-{slug}.md"


def _closing_checks(case: Path, prev: grammar.Phase, journal: grammar.Journal) -> List[str]:
    """What P8 demands from a phase before the next one may open."""
    missing = []
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
    out.lines = log(case, "PHASE", f"{name} открыта", f"p{n}").lines + out.lines
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
    todo = _todo(case, out)
    if not re.search(r"^- progress:", body, re.M):
        body = _set_state_line(body, "progress: ", progress_line(todo, case))
    out.absorb(store.write(case, "README.md", body))
    out.say("written: README.md")
    return out


# ---- cases --------------------------------------------------------------------------------------
def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _case_folder(name: str) -> str:
    date, _ = _now()
    folder = f"{date}-{_slug(name)}"
    if not store.CASE_NAME_RE.match(folder):
        raise StoreError(f"`{folder}` is not a valid case name: 2–5 English words, hyphens (L2)", 2)
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
    readme_text = "\n".join([
        f"# {title}", "", "## Context", goal, "", "## State", "- progress: (no phases yet)",
        "- next: open phase 1 — `mike phase open 1 <Name> --goal \"…\"`", "", "## Decisions", "",
        "## Problems", "", "## Links", *links, ""])
    store_write_fresh(case, "README.md", readme_text)
    store_write_fresh(case, "TODO.md", f"# TODO — {title}\n")
    d, t = _now()
    store_write_fresh(case, "JOURNAL.md", f"# JOURNAL — {title}\n\n- {d} {t} · p0\n  PHASE · дело открыто: {goal}\n")
    return case


def store_write_fresh(case: Path, name: str, body: str):
    (case / name).write_text(stamp.apply(body), encoding="utf-8")


def case_list(root: Path) -> Outcome:
    out = Outcome()
    cases, rejected0 = store.scan(root)
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
        depth = len(store.chain(case, root)) - 1
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


def spawn(root: Path, parent: Path, name: str, goal: str) -> Outcome:
    out = Outcome()
    todo = _todo(parent, out)
    cur = todo.current()
    if cur is None:
        raise StoreError("parent has no open phase — spawn happens inside a phase (P11)", 4)
    child_name = _case_folder(name)
    if (parent / child_name).exists():
        raise StoreError(f"{parent / child_name} already exists", 4)
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
    out.absorb(store.write(parent, "README.md", "\n".join(lines) + "\n"))
    out.lines = log(parent, "PROBLEM", f"{goal} · open → {child_name}/").lines + out.lines
    child = case_new(root, name, goal, parent=parent)
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
    out.absorb(store.write(case, "README.md", text))
    out.lines = log(case, "PHASE", f"дело закрыто → {summary}").lines + out.lines
    parent = case.parent
    if store.is_case_dir(parent):
        ptodo = _todo(parent, out)
        for p in ptodo.phases:
            if case.name in p.waits:
                p.waits.remove(case.name)
                m = max((it.m for it in p.items), default=0) + 1
                p.items.append(grammar.Item(p.n, m, True, f"{summary} · {case.name}/", 0))
        out.absorb(store.write(parent, "TODO.md", render_todo(ptodo)))
        out.absorb(store.write(parent, "README.md", _set_state_line(_readme_text(parent, out), "ждёт: ", None)))
        out.lines += log(parent, "PROBLEM", f"закрыто → {summary} · {case.name}/").lines
        out.say(f"parent updated: {parent.name} — hand returns to the parent")
    out.say(f"closed: {case.name}")
    return out


# ---- entry and check ----------------------------------------------------------------------------
def entry(root: Path, case: Path) -> Outcome:
    out = Outcome()
    names = store.chain(case, root)
    out.say(f"mike · case in hand: {' › '.join(names)}", "")
    others = [c.name for c in store.all_cases(root) if store.is_open(c) and c != case]
    if others:
        out.say("other open cases: " + " · ".join(others) + " — switch: `mike case use <name>`", "")
    readme_body, _ = stamp.split(store.read(case, "README.md"))
    out.say(readme_body.rstrip("\n"), "")
    todo_body, _ = stamp.split(store.read(case, "TODO.md"))
    out.say(todo_body.rstrip("\n"), "")
    journal = grammar.parse_journal(store.read(case, "JOURNAL.md"))
    jlines, _ = stamp.split(store.read(case, "JOURNAL.md"))
    jl = jlines.rstrip("\n").split("\n")
    if journal.entries:
        cut = journal.entries[ENTRY_LIMIT].line - 1 if len(journal.entries) > ENTRY_LIMIT else len(jl)
        out.say(f"# JOURNAL — last {min(ENTRY_LIMIT, len(journal.entries))} of {len(journal.entries)} entries")
        out.say("\n".join(jl[1:cut]).strip("\n"), "")
    rec = store.recover_files(case)
    if rec:
        out.warn(*(f"pending: {r.name} — re-enter its lines with mike, then delete it (S4)" for r in rec))
    out.say("rules: .cases/RULES.md · stuck? grep -ril '<error words>' .howto/ · next command: mike help")
    total = "\n".join(out.lines)
    if len(total) > MAX_SCREEN:
        out.lines = [total[:MAX_SCREEN], "", f"[truncated at {MAX_SCREEN} chars — README/TODO/JOURNAL are on disk]"]
    return out


def check(root: Path) -> Outcome:
    out = Outcome()
    cases, rejected = store.scan(root)
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
    if log_lines:
        with (root / "checks.log").open("a", encoding="utf-8") as fh:
            fh.write("\n".join(log_lines) + "\n")
    out.say(f"cases: {len(cases)} · violations: {errors} · warnings: {len(out.warnings)}")
    if errors:
        raise StoreError("\n".join(out.lines), 3)
    return out
