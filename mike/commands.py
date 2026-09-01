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
    old_short = old_text if len(old_text) <= 40 else old_text[:40].rstrip() + "…"
    out.lines += log(case, "DECISION", f"todo {ref}: «{old_short}» → новый текст в TODO", f"p{phase.n}").lines
    out.say(f"edited: {ref} → TODO.md (old text kept in the journal)")
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
        anchor = item.text if len(item.text) <= 40 else item.text[:40].rstrip() + "…"
        out.lines += log(case, "DECISION",
                         f"todo «{anchor}» переставлен → {phase.n}.{item.m}; номера фазы {phase.n} пересчитаны, "
                         f"старые ссылки N.M в журнале смотри по тексту", f"p{phase.n}").lines
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
    why = f" — {item.hold_reason}" if item.hold_reason else ""
    out.lines += log(case, "DECISION", f"todo {ref} отложен: «{item.text}»{why}", f"p{phase.n}").lines
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
    out.lines += log(case, "DECISION", f"todo {ref} снят: «{item.text}»", f"p{phase.n}").lines
    out.say(f"dropped: {ref} «{item.text}» → text kept in the journal")
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


SECTION_NAMES = {n.lower(): n for n in grammar.README_SECTIONS}


def _readme_sections(case: Path, out: Outcome):
    body = _readme_text(case, out)
    parsed = grammar.parse_readme(body)
    if parsed.errors:
        raise StoreError("README.md is not parsable — run `mike check`", 3)
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
    out.absorb(store.write(case, "README.md", body))
    out.say(f"README State: `- {prefix}: …` set")
    return out


def readme_add(case: Path, section: str, line: str) -> Outcome:
    out = Outcome()
    name = SECTION_NAMES.get(section.lower())
    if name is None:
        raise StoreError(f"no section `{section}` — sections: {' · '.join(grammar.README_SECTIONS)}", 2)
    parsed = _readme_sections(case, out)
    parsed.sections.setdefault(name, []).append(f"- {' '.join(line.split())}")
    out.absorb(store.write(case, "README.md", _render_readme(parsed)))
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
    out.absorb(store.write(case, "README.md", _render_readme(parsed)))
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
    readme_text = "\n".join([
        f"# {title}", "", "## Context", goal, "", "## State", "- progress: (no phases yet)",
        "- next: open phase 1 — `mike phase open 1 <Name> --goal \"…\"`", "", "## Decisions", "",
        "## Problems", "", "## Links", *links, ""])
    store_write_fresh(case, "README.md", readme_text)
    store_write_fresh(case, "TODO.md", f"# TODO — {title}\n")
    d, t = _now()
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
    store_write_fresh(project, "README.md", "\n".join([
        f"# {title}", "", "## Context", goal, "", "## State", "- progress: (no phases yet)",
        "- next: open phase 1 — `mike phase open 1 <Name> --goal \"…\"`", "", "## Decisions", "",
        "## Problems", "", "## Links", ""]))
    store_write_fresh(project, "TODO.md", f"# TODO — {title}\n")
    d, t = _now()
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
    out.absorb(store.write(parent, "README.md", "\n".join(lines) + "\n"))
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
    out.absorb(store.write(case, "README.md", text))
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
        out.absorb(store.write(parent, "README.md", _set_state_line(_readme_text(parent, out), "ждёт: ", None)))
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
        out.warn(*(f"pending: {r.name} — re-enter its lines with mike, then run: rm '{r}' (S4)" for r in rec))
    out.say("rules: .cases/RULES.md · stuck? grep -ril '<error words>' .howto/ · next command: mike help")
    total = "\n".join(out.lines)
    if len(total) > MAX_SCREEN:
        out.lines = [total[:MAX_SCREEN], "", f"[truncated at {MAX_SCREEN} chars — README/TODO/JOURNAL are on disk]"]
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
