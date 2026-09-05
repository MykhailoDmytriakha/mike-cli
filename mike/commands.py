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
            suffix = ((f" — after: {', '.join(it.after)}" if it.after else "") + (f" — due: {it.due}" if it.due else "")
                      + (f" — hold: {it.hold_reason}" if it.held and it.hold_reason else ""))
            out.append(f"  - [{mark}] {it.n}.{it.m} {it.text}{suffix}")
        for w in p.waits:
            out.append(f"  - waits: {w}")
    return "\n".join(out) + "\n"


def _derive_todo(case: Path, todo: grammar.Todo) -> bool:
    """F18: the line of an open phase carries its `goal:` and the path to its file — rendered from
    the file, never typed; a planned phase (no file yet) keeps its intent. Returns True on change."""
    changed = False
    for p in todo.phases:
        if p.done:
            continue
        pf = _phase_file(case, p.n, p.name)
        if not pf.exists():
            continue
        try:
            parsed = grammar.parse_phase_file(pf.read_text(encoding="utf-8"))
        except OSError:
            continue
        if parsed.errors or not parsed.goal:
            continue
        tail = f"{order._short(parsed.goal, 110)} · phases/{pf.name}"
        if p.summary != tail:
            p.summary, changed = tail, True
    return changed


def _write_todo(case: Path, todo: grammar.Todo):
    """The one door for TODO writes: derived lines first (F18), then the stamp door."""
    _derive_todo(case, todo)
    return store.write(case, "TODO.md", render_todo(todo))


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
        cancelled = p.done and (p.summary or "").startswith("снято")
        mark = (" ✗" if cancelled else " ✓") if p.done else (" ▶" if opened else "")
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
def todo_done(case: Path, ref: str, outcome: str = "") -> Outcome:
    """Done with evidence (F20): `mike todo done N.M "what came out"` — the outcome goes to the journal
    as `RESULT · N.M: …`. Nothing to say? Then it was not done: `mike todo cancel N.M "why"`."""
    out = Outcome()
    m = re.fullmatch(r"(\d+)\.(\d+)", ref)
    if not m:
        raise StoreError("use `mike todo done N.M \"what came out\"` for an item or `mike phase close N` for a phase", 2)
    outcome = " ".join(outcome.split())
    if not outcome:
        raise StoreError(f"done needs what came out (F20): mike todo done {ref} \"what came out\" — "
                         f"nothing came out? then it was not done: mike todo cancel {ref} \"why\"", 2)
    n, k = int(m.group(1)), int(m.group(2))
    todo = _todo(case, out)
    phase = todo.phase(n)
    item = next((it for it in phase.items if it.m == k), None) if phase else None
    if item is None:
        raise StoreError(f"no item {ref} in TODO.md", 4)
    if item.done:
        out.say(f"item {ref} already done — nothing changed")
        return out
    blockers = _blocking(case, todo).get(ref, [])
    item.done, item.held, item.hold_reason = True, False, ""
    out.absorb(_write_todo(case, todo))
    out.lines += log(case, "RESULT", f"{ref}: {outcome}", f"p{n}").lines
    if blockers:
        out.warn(f"{ref} was after {', '.join(r for r, _ in blockers)}, still open — was the dependency wrong, or the order?")
    out.say(f"done: {ref} {item.text} → TODO.md · RESULT in the journal")
    return out


def _split_suffixes(text: str):
    """`text — after: N.M, case — due: YYYY-MM-DD` → (text, due, after); either suffix may be absent.
    A date the tool can parse is a date it can count (feedback 2026-09-03); a dependency the tool
    can parse is a dependency it can check (F19)."""
    text = " ".join(text.split())
    due, after = "", []
    if " — due: " in text:
        text, d = text.rsplit(" — due: ", 1)
        due = _valid_date(d.strip())
    if " — after: " in text:
        text, refs = text.rsplit(" — after: ", 1)
        after = [x.strip() for x in refs.split(",") if x.strip()]
    return text.strip(), due, after


def _all_items(todo: grammar.Todo) -> List[grammar.Item]:
    return [it for p in todo.phases for it in p.items]


def _find_cycle(todo: grammar.Todo) -> Optional[List[str]]:
    """A cycle among `after` edges between items, as a path; None when the graph is a DAG."""
    graph = {f"{it.n}.{it.m}": [r for r in it.after if re.fullmatch(r"\d+\.\d+", r)] for it in _all_items(todo)}
    color = {k: 0 for k in graph}
    stack: List[str] = []

    def visit(u: str):
        color[u] = 1
        stack.append(u)
        for v in graph.get(u, []):
            if v not in graph:
                continue
            if color[v] == 1:
                return stack[stack.index(v):] + [v]
            if color[v] == 0:
                found = visit(v)
                if found:
                    return found
        stack.pop()
        color[u] = 2
        return None

    for k in graph:
        if color[k] == 0:
            found = visit(k)
            if found:
                return found
    return None


def _set_after(case: Path, todo: grammar.Todo, item: grammar.Item, refs: List[str]):
    """Validate and set `after` (F19): every N.M exists (any phase) and is not the item itself, a
    name is a nested case; no cycle appears. Raises before anything is written."""
    kids = {k.name for k in order.child_cases(case, _is_project(case))}
    items = {f"{it.n}.{it.m}" for it in _all_items(todo)}
    me = f"{item.n}.{item.m}"
    clean: List[str] = []
    for ref in refs:
        if not grammar.AFTER_REF_RE.fullmatch(ref):
            raise StoreError(f"`{ref}` — after expects N.M or a nested case name (F19)", 2)
        if re.fullmatch(r"\d+\.\d+", ref):
            if ref == me:
                raise StoreError(f"{me} cannot be after itself", 2)
            if ref not in items:
                raise StoreError(f"no item {ref} to be after — check the number or add it first (mike todo add N \"…\")", 4)
        elif ref not in kids:
            raise StoreError(f"`{ref}` is neither an item N.M nor a nested case here" + (f" (cases: {', '.join(sorted(kids))})" if kids else ""), 4)
        if ref not in clean:
            clean.append(ref)
    old, item.after = item.after, clean
    cycle = _find_cycle(todo)
    if cycle:
        item.after = old
        raise StoreError(f"after would close a cycle: {' → '.join(cycle)} (F19)", 3)


def _next_number(case: Path, todo: grammar.Todo, phase: grammar.Phase) -> int:
    """The next free number in a phase: above every item present, every `after` reference and every
    number the journal already speaks of — a number someone still refers to is never reused (F19,
    the Codex finding: a moved item freed its number and `after` would have pointed at a stranger)."""
    used = {it.m for it in phase.items}
    for it in _all_items(todo):
        for r in it.after:
            m = re.fullmatch(rf"{phase.n}\.(\d+)", r)
            if m:
                used.add(int(m.group(1)))
    try:
        journal = grammar.parse_journal(store.read(case, "JOURNAL.md"))
    except StoreError:
        journal = None
    if journal is not None:
        pat = re.compile(rf"(?<![\d.]){phase.n}\.(\d+)(?![\d.])")
        for e in journal.entries:
            for ev in e.events:
                for m in pat.finditer(ev.text):
                    used.add(int(m.group(1)))
    return max(used, default=0) + 1


def _blocking(case: Path, todo: grammar.Todo) -> Dict[str, List[Tuple[str, str]]]:
    """item key → [(ref, 'open' | 'case open' | 'gone')] for open items with unsatisfied `after`."""
    items = {f"{it.n}.{it.m}": it for it in _all_items(todo)}
    kids = {k.name: order.child_status(k)[0] for k in order.child_cases(case, _is_project(case))}
    out: Dict[str, List[Tuple[str, str]]] = {}
    for it in _all_items(todo):
        if it.done or not it.after:
            continue
        blockers = []
        for r in it.after:
            if r in items:
                if not items[r].done:
                    blockers.append((r, "open"))
            elif r in kids:
                if kids[r] != "closed":
                    blockers.append((r, "case open"))
            else:
                blockers.append((r, "gone"))
        if blockers:
            out[f"{it.n}.{it.m}"] = blockers
    return out


def _unblocked_line(case: Path, todo: grammar.Todo) -> Optional[str]:
    """Printed on entry only when the case declares dependencies: open items whose blockers are all
    done, ordered by due date then position — candidates, not the owner's `next:` (Codex: ready ≠
    what should happen next; never persisted into README)."""
    if not any(it.after for it in _all_items(todo)):
        return None
    blocking = _blocking(case, todo)
    open_items = [it for p in todo.phases if not p.done for it in p.items if not it.done and not it.held]
    ready = sorted((it for it in open_items if f"{it.n}.{it.m}" not in blocking), key=lambda it: (it.due or "9999-99-99", it.n, it.m))
    blocked = [(it, blocking[f"{it.n}.{it.m}"]) for it in open_items if f"{it.n}.{it.m}" in blocking]
    shown = ", ".join(f"{it.n}.{it.m} «{order._short(it.text, 40)}»" for it in ready[:6]) + (f" … +{len(ready) - 6}" if len(ready) > 6 else "")
    parts = [f"unblocked: {shown or 'none'}"]
    if blocked:
        parts.append("blocked: " + ", ".join(f"{it.n}.{it.m} (after {', '.join(r for r, _ in bl)})" for it, bl in blocked[:6])
                     + (f" … +{len(blocked) - 6}" if len(blocked) > 6 else ""))
    return " · ".join(parts)


def _gone_lines(case: Path, todo: grammar.Todo) -> List[str]:
    """Order: an item waiting for something that no longer exists (cancelled or dropped) has two exits."""
    out = []
    for key, blockers in _blocking(case, todo).items():
        gone = [r for r, st in blockers if st == "gone"]
        if gone:
            out.append(f"{key} is after {', '.join(gone)}, which is gone (cancelled or dropped) → mike todo after {key} <refs|none> · or mike todo cancel {key} \"why\"")
    return out


def todo_after(case: Path, ref: str, refs: str) -> Outcome:
    """Set (or clear with `none`) what item N.M waits for: `mike todo after 2.5 "2.3, 1.7, case-name"`."""
    out = Outcome()
    todo = _todo(case, out)
    phase, item = _find_item(todo, ref)
    if refs.strip().lower() in ("", "none", "-", "clear"):
        item.after = []
        out.absorb(_write_todo(case, todo))
        out.say(f"after cleared: {ref} waits for nothing")
        return out
    _set_after(case, todo, item, [x.strip() for x in refs.split(",") if x.strip()])
    out.absorb(_write_todo(case, todo))
    out.say(f"after: {ref} waits for {', '.join(item.after)} → TODO.md")
    return out


def _valid_date(due: str) -> str:
    if not grammar.DATE_RE.fullmatch(due):
        raise StoreError(f"`due:` must be YYYY-MM-DD, got `{due}` — e.g. `— due: 2026-09-13`", 2)
    try:
        dt.date.fromisoformat(due)
    except ValueError:
        raise StoreError(f"`{due}` is not a calendar date", 2)
    return due


def todo_add(case: Path, ref: str, text: str) -> Outcome:
    """Add item N.M (M = next free) to an open or planned phase N; `ref` is the phase number.
    The text may end with `— due: YYYY-MM-DD`."""
    out = Outcome()
    if not ref.isdigit():
        raise StoreError("use `mike todo add N \"text\"` — N is the phase number", 2)
    todo = _todo(case, out)
    phase = todo.phase(int(ref))
    if phase is None or phase.done:
        raise StoreError(f"phase {ref} is missing or closed", 4)
    text, due, after = _split_suffixes(text)
    if grammar.visible_len(text) > grammar.TODO_ITEM_CHARS:
        raise StoreError(f"item text is {grammar.visible_len(text)} visible chars, limit {grammar.TODO_ITEM_CHARS} (F13); "
                         f"markdown links count as their name\n"
                         f"  suggestion: \"{_trim_suggestion(text, grammar.TODO_ITEM_CHARS)}\"", 3)
    m = _next_number(case, todo, phase)
    item = grammar.Item(phase.n, m, False, text, 0, due=due)
    phase.items.append(item)
    if after:
        _set_after(case, todo, item, after)
    out.absorb(_write_todo(case, todo))
    out.say(f"added: {phase.n}.{m} {text}{f' — after: {chr(44).join(item.after)}' if item.after else ''}{f' — due: {due}' if due else ''} → TODO.md")
    _remind_link(case, f"{phase.n}.{m}", text, out)
    return out


def _remind_link(case: Path, ref: str, text: str, out: Outcome):
    """At the moment of writing, not at the next entry: the rule was forgotten twenty times in one
    session while every item looked fine on its own line (feedback 2026-09-03)."""
    try:
        body = _readme_text(case)
    except StoreError:
        return
    if _items_link_rule(body) and "](" not in text:
        out.warn(f"{ref} has no link to its material — this case's rule: items link their material; "
                 f"mike todo edit {ref} \"{text} — [name](docs/file.md)\"")


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
    text, due, after = _split_suffixes(text)  # a date or dependency kept in the item stays unless the new text carries one
    if after:
        _set_after(case, todo, item, after)
    if grammar.visible_len(text) > grammar.TODO_ITEM_CHARS:
        raise StoreError(f"item text is {grammar.visible_len(text)} visible chars, limit {grammar.TODO_ITEM_CHARS} (F13)\n"
                         f"  suggestion: \"{_trim_suggestion(text, grammar.TODO_ITEM_CHARS)}\"", 3)
    old_text, item.text = item.text, text
    if due:
        item.due = due
    out.absorb(_write_todo(case, todo))
    out.say(f"edited: {ref} → TODO.md (was: «{old_text}»)")
    _remind_link(case, ref, text, out)
    return out


def _list_lines(phase: grammar.Phase) -> List[str]:
    """The phase as TODO renders it — active items in order, held ones last."""
    items = [i for i in phase.items if not i.held] + [i for i in phase.items if i.held]
    return [f"  - [{'x' if it.done else ('~' if it.held else ' ')}] {it.n}.{it.m} {it.text}" for it in items]


def _number_ranges(phase: grammar.Phase) -> str:
    """`2.1–2.6, 2.8, 2.17` — which numbers the phase holds now (gaps are normal: numbers are kept)."""
    ms = sorted(it.m for it in phase.items)
    parts, i = [], 0
    while i < len(ms):
        j = i
        while j + 1 < len(ms) and ms[j + 1] == ms[j] + 1:
            j += 1
        parts.append(f"{phase.n}.{ms[i]}" if i == j else f"{phase.n}.{ms[i]}–{phase.n}.{ms[j]}")
        i = j + 1
    return ", ".join(parts) or "(empty)"


def todo_move(case: Path, ref: str, to: str) -> Outcome:
    """Put item N.M before item N.K, or `last`. Numbers never change: N.M is the item's number for
    life and the list order is a separate thing, so a batch aimed at numbers read a moment ago stays
    correct (feedback 2026-09-03: move renumbered while drop did not — two rules for one list, and
    an edit landed on the wrong item). No clamping either: an unknown target is refused."""
    out = Outcome()
    todo = _todo(case, out)
    phase, item = _find_item(todo, ref)
    if to.strip().isdigit():
        # to another phase: the item joins its end under the next free number there — the one time a
        # number changes, said aloud (feedback 2026-09-03: re-cutting a phase meant drop + add × 15)
        dest = todo.phase(int(to))
        if dest is None or dest.done:
            raise StoreError(f"phase {to} is missing or closed — plan it first: mike phase plan {to} \"Name\"", 4)
        if dest is phase:
            out.say(f"{ref} is already in phase {to} — nothing changed")
            return out
        phase.items.remove(item)
        item.n, item.m = dest.n, _next_number(case, todo, dest)
        dest.items.append(item)
        new = f"{item.n}.{item.m}"
        followers = []
        for it in _all_items(todo):  # references follow the item, like links follow a moved file (F19)
            if ref in it.after:
                it.after = [new if r == ref else r for r in it.after]
                followers.append(f"{it.n}.{it.m}")
        out.absorb(_write_todo(case, todo))
        out.say(f"moved: {ref} → {new} «{item.text}» (end of phase {dest.n}; the number changes with the phase)"
                + (f" · after-references rewritten in {', '.join(followers)}" if followers else ""))
        return out
    if to.strip().lower() in ("last", "end"):
        target = None
    else:
        m = re.fullmatch(r"(\d+)\.(\d+)", to)
        if not m or int(m.group(1)) != phase.n:
            raise StoreError(f"move works inside one phase: `mike todo move {phase.n}.M {phase.n}.K` (before K) "
                             f"or `mike todo move {phase.n}.M last`; to another phase — drop and add", 2)
        target = next((it for it in phase.items if it.m == int(m.group(2))), None)
        if target is None:
            raise StoreError(f"no item {to} in phase {phase.n} (items: {_number_ranges(phase)}); "
                             f"to put it last: mike todo move {ref} last", 4)
        if target is item:
            out.say(f"{ref} is already there — nothing changed")
            return out
    phase.items.remove(item)
    phase.items.insert(len(phase.items) if target is None else phase.items.index(target), item)
    out.absorb(_write_todo(case, todo))
    where = "last" if target is None else f"before {phase.n}.{target.m}"
    out.say(f"moved: {ref} now {where} — numbers never change; the phase list:", *_list_lines(phase))
    return out


def todo_hold(case: Path, ref: str, reason: str) -> Outcome:
    out = Outcome()
    todo = _todo(case, out)
    phase, item = _find_item(todo, ref)
    if item.done:
        raise StoreError(f"item {ref} is done — nothing to hold", 4)
    item.held, item.hold_reason = True, " ".join(reason.split())
    out.absorb(_write_todo(case, todo))
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
    out.absorb(_write_todo(case, todo))
    out.say(f"resumed: {ref} {item.text} → TODO.md")
    return out


def todo_drop(case: Path, ref: str) -> Outcome:
    out = Outcome()
    todo = _todo(case, out)
    phase, item = _find_item(todo, ref)
    ref_by = [f"{it.n}.{it.m}" for it in _all_items(todo) if ref in it.after]
    if ref_by:  # F19: an item others wait for does not vanish silently
        raise StoreError(f"{ref} is a dependency of {', '.join(ref_by)} — rewire them first (mike todo after N.M <refs|none>) "
                         f"or cancel {ref} with a reason (mike todo cancel {ref} \"why\")", 4)
    phase.items.remove(item)
    out.absorb(_write_todo(case, todo))
    # the numbers of the others are kept (N.M is for life) — and said aloud, so the next command in a
    # batch is aimed at a number the caller has just been shown (feedback 2026-09-03)
    out.say(f"dropped: {ref} «{item.text}» — numbers kept, phase {phase.n} now reads {_number_ranges(phase)} "
            f"(git keeps the history; a decision behind it → mike log DECISION)")
    return out


def todo_cancel(case: Path, ref: str, why: str) -> Outcome:
    """The item stopped being needed (not done, not dropped by mistake): it leaves TODO — the list is
    what remains to do (P4) — and the reason goes to the journal as a DECISION, so the record stays
    honest (feedback 2026-09-03: `edit` + `done` wrote "completed" over work that was cancelled)."""
    out = Outcome()
    why = " ".join(why.split())
    if not why:
        raise StoreError("cancel needs a reason: `mike todo cancel N.M \"why it is no longer needed\"`", 2)
    todo = _todo(case, out)
    phase, item = _find_item(todo, ref)
    phase.items.remove(item)
    out.absorb(_write_todo(case, todo))
    out.lines += log(case, "DECISION", f"снято {ref} «{item.text}» — {why}", f"p{phase.n}").lines
    out.say(f"cancelled: {ref} «{item.text}» — out of TODO, the reason is in the journal; phase {phase.n} now reads {_number_ranges(phase)}")
    return out


def todo_due(case: Path, ref: str, date: str) -> Outcome:
    """Set or clear (`none`) the date of an item: `— due: YYYY-MM-DD` — the tool counts it on entry."""
    out = Outcome()
    todo = _todo(case, out)
    phase, item = _find_item(todo, ref)
    date = date.strip().lower()
    if date in ("", "none", "-", "clear"):
        item.due = ""
        out.absorb(_write_todo(case, todo))
        out.say(f"due cleared: {ref} {item.text}")
        return out
    item.due = _valid_date(date)
    out.absorb(_write_todo(case, todo))
    out.say(f"due: {ref} {item.text} — {item.due} → TODO.md")
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


def phase_plan(case: Path, n: int, name: str, goal: Optional[str]) -> Outcome:
    """Name the next phase now, open it later: `- [ ] N Name — <intent>` in TODO, no phase file, no
    journal event (a plan is not an event, P5). Items may be parked under it (`todo add N`); it
    opens with `mike phase open N` once the previous phase is closed — P8 stays: planned ≠ open.
    Feedback 2026-09-03: a dated deadline outside the current phase had nowhere to live in TODO."""
    out = Outcome()
    if not grammar.PHASE_NAME_RE.match(name):
        raise StoreError(f"phase name `{name}` must be English, 1–3 words (F13)", 2)
    todo = _todo(case, out)
    existing = todo.phase(n)
    if existing is not None:
        state = "closed" if existing.done else ("open" if _phase_file(case, n, existing.name).exists() else "already planned")
        free = max(p.n for p in todo.phases) + 1
        raise StoreError(f"phase {n} {existing.name} exists ({state}) — pick the next number: mike phase plan {free} \"{name}\"", 4)
    intent = " ".join(goal.split()) if goal else None
    if intent and grammar.visible_len(intent) > grammar.TODO_ITEM_CHARS:
        raise StoreError(f"intent is {grammar.visible_len(intent)} visible chars, limit {grammar.TODO_ITEM_CHARS} — one line in TODO (F13); "
                         f"the story goes into the phase file once it opens\n"
                         f"  suggestion: \"{_trim_suggestion(intent, grammar.TODO_ITEM_CHARS)}\"", 3)
    todo.phases.append(grammar.Phase(n, name, False, 0, intent))
    out.absorb(_write_todo(case, todo))
    _sync_progress(case, todo, out)
    out.say(f"planned: phase {n} {name} → TODO.md (no phase file until it opens) · items now: mike todo add {n} \"…\" · "
            f"open once the previous phase is closed: mike phase open {n}")
    return out


def phase_open(case: Path, n: int, name: str, goal: Optional[str]) -> Outcome:
    out = Outcome()
    todo = _todo(case, out)
    existing = todo.phase(n)
    if not name and existing is not None and not existing.done:
        name = existing.name  # `mike phase open N` opens the planned phase under its planned name
    if not name:
        raise StoreError(f"phase open needs a name: `mike phase open {n} \"CLI core\" --goal …` — no planned phase {n} to take it from", 2)
    if not grammar.PHASE_NAME_RE.match(name):
        raise StoreError(f"phase name `{name}` must be English, 1–3 words (F13)", 2)
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
        goal = goal or (existing.summary if existing else None)  # a planned phase carries its intent
        if not goal:
            raise StoreError("a new phase needs `--goal \"one line\"` (F12)", 2)
        pf.parent.mkdir(exist_ok=True)
        pf.write_text(f"# Phase {n} — {name}\ngoal: {' '.join(goal.split())}\nresult:\n\n## Notes\n", encoding="utf-8")
        out.say(f"created: {pf.relative_to(case)}")
    if existing is None:
        todo.phases.append(grammar.Phase(n, name, False, 0))
    out.absorb(_write_todo(case, todo))
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
    open_items = [f"{it.n}.{it.m}" for it in phase.items if not it.done]
    if open_items:  # F20: a phase closes only when every item ended — done with evidence, or cancelled with a reason
        missing.append(f"phase {n}: open items {', '.join(open_items)} — each must end one of two ways: "
                       f"mike todo done N.M \"what came out\" · mike todo cancel N.M \"why\" (or cancel the phase: mike phase cancel {n} \"why\")")
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
    out.absorb(_write_todo(case, todo))
    _sync_progress(case, todo, out)
    out.lines = log(case, "PHASE", f"{phase.name} закрыта → {summary}", f"p{n}").lines + out.lines
    out.say(f"closed: phase {n} {phase.name} → TODO.md (collapsed), {rel} (result), README.md State")
    return out


def _cancel_phase(case: Path, todo: grammar.Todo, phase: grammar.Phase, why: str, out: Outcome) -> str:
    """Collapse a phase with a reason (F20): its file gets `result: снято: …`, its items are listed there
    as cancelled, the TODO line becomes one closed line marked «снято». Returns the journal text."""
    date, _ = _now()
    pf = _phase_file(case, phase.n, phase.name)
    if not pf.exists():  # a planned phase: the file is born closed, so the collapsed line has somewhere to point
        pf.parent.mkdir(exist_ok=True)
        pf.write_text(f"# Phase {phase.n} — {phase.name}\ngoal: {phase.summary or '—'}\nresult:\n\n## Notes\n", encoding="utf-8")
    lines = pf.read_text(encoding="utf-8").split("\n")
    lines[2] = f"result: снято: {why}"
    if phase.items:
        lines += ["", "## Items at cancel", *(f"- {it.n}.{it.m} {'✓' if it.done else '✗'} {it.text}" for it in phase.items)]
    pf.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    items = ", ".join(f"{it.n}.{it.m}" for it in phase.items if not it.done)
    waits = ", ".join(phase.waits)
    phase.done, phase.items, phase.waits = True, [], []
    phase.summary = f"снято: {why} · {date} · phases/{pf.name}"
    text = f"снята фаза {phase.n} {phase.name} — {why}"
    if items:
        text += f" (пункты сняты: {items})"
    if waits:
        out.warn(f"phase {phase.n} waited for {waits} — the nested case stays open on its own; close or cancel it separately")
    return text


def phase_cancel(case: Path, n: int, why: str) -> Outcome:
    """The branch is not needed: `mike phase cancel N "why"` — the second honest end of a node (F20)."""
    out = Outcome()
    why = " ".join(why.split())
    if not why:
        raise StoreError(f"cancel needs a reason: mike phase cancel {n} \"why the phase is no longer needed\"", 2)
    todo = _todo(case, out)
    phase = todo.phase(n)
    if phase is None:
        raise StoreError(f"no phase {n} in TODO.md", 4)
    if phase.done:
        raise StoreError(f"phase {n} {phase.name} is already closed", 4)
    text = _cancel_phase(case, todo, phase, why, out)
    out.absorb(_write_todo(case, todo))
    _sync_progress(case, todo, out)
    out.lines = log(case, "DECISION", text, f"p{n}").lines + out.lines
    out.say(f"cancelled: phase {n} {phase.name} → one line in TODO («снято»), reason in the journal, phases/{_phase_file(case, n, phase.name).name}")
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
    text = " ".join(text.split())
    if not text:  # an empty value removes the line — what the caller tries first (feedback 2026-09-03)
        return readme_drop(case, "state", prefix)
    body = _set_state_line(_readme_text(case, out), f"{prefix}: ", text)
    _write_readme(case, body, out, anchor=True)
    out.say(f"README State: `- {prefix}: …` set (as of the newest journal entry)")
    return out


STATE_OWNED = grammar.STATE_OWNED  # lines mike derives on every write — not yours to remove


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


def readme_drop(case: Path, section: str, ref: str) -> Outcome:
    """Drop line k of a section; in State a line is addressed by its prefix (`mike readme drop
    state пауза`) — State lines were one-way before (feedback 2026-09-03)."""
    out = Outcome()
    name = SECTION_NAMES.get(section.lower())
    if name is None:
        raise StoreError(f"no section `{section}` — sections: {' · '.join(grammar.README_SECTIONS)}", 2)
    parsed = _readme_sections(case, out)
    ref = str(ref).strip()
    if not ref.isdigit():
        if name != "State":
            raise StoreError(f"usage: mike readme drop {name.lower()} <k> — a position; only State lines go by prefix", 2)
        prefix = ref.rstrip(":")
        if prefix.lower() in STATE_OWNED:
            raise StoreError(f"`- {prefix}:` is held by mike (derived on every write) — it does not get removed (F3)", 2)
        at = next((i for i, ln in enumerate(parsed.sections.get("State", [])) if ln.startswith(f"- {prefix}:")), None)
        if at is None:
            have = ", ".join(ln[2:].split(":")[0] for ln in parsed.sections.get("State", []) if ln.startswith("- "))
            raise StoreError(f"no `- {prefix}:` line in State (lines: {have})", 4)
        removed = parsed.sections["State"].pop(at)
        _write_readme(case, _render_readme(parsed), out, anchor=True)
        out.say(f"README State: `- {prefix}: …` removed")
        return out
    k = int(ref)
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
    out.absorb(_write_todo(parent, todo))
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
    live = [(k.name, order.child_status(k)[0]) for k in order.child_cases(case, _is_project(case))]
    live = [f"{n} ({st})" for n, st in live if st != "closed"]
    if live:  # F20: a parent closes only when every child is done or cancelled; BROKEN holds it open (F18)
        raise StoreError("cannot close the case: nested cases still open — " + ", ".join(live) +
                         " → close each (mike --case <name> done \"…\") or cancel it with a reason", 4)
    summary = " ".join(summary.split())
    date, _ = _now()
    text = _set_state_line(_readme_text(case, out), "closed: ", f"{date} · {summary}")
    _write_readme(case, text, out, anchor=True)
    out.lines = log(case, "PHASE", f"дело закрыто → {summary}").lines + out.lines
    parent = store.parent_case(case, root)
    if parent is not None:
        ptodo = _todo(parent, out)
        awaited = False
        for p in ptodo.phases:
            if case.name in p.waits:
                awaited = True
                p.waits.remove(case.name)
                m = _next_number(parent, ptodo, p)
                p.items.append(grammar.Item(p.n, m, True, f"{summary} · {case.name}/", 0))
        out.absorb(_write_todo(parent, ptodo))
        _write_readme(parent, _set_state_line(_readme_text(parent, out), "ждёт: ", None), out)
        # the child always reports to its parent, however it was created (F18): an awaited child
        # closes the PROBLEM that spawned it, any other child lands as a RESULT
        out.lines += log(parent, "PROBLEM" if awaited else "RESULT",
                         (f"закрыто → {summary} · {case.name}/" if awaited else f"дело закрыто → {summary} · {case.name}/")).lines
        out.say(f"parent updated: {parent.name} — hand returns to the parent")
    out.say(f"closed: {case.name}")
    return out


def case_cancel(root: Path, case: Path, why: str) -> Outcome:
    """The whole case is not needed (F20): open phases collapse with the reason, the case closes as
    «снято», the parent gets one line. Nested cases must already be closed or cancelled."""
    out = Outcome()
    why = " ".join(why.split())
    if not why:
        raise StoreError("cancel needs a reason: mike case cancel \"why the case is no longer needed\"", 2)
    todo = _todo(case, out)
    if re.search(r"^- closed: ", _readme_text(case, out), re.M):
        raise StoreError(f"{case.name} is already closed", 4)
    live = [f"{k.name} ({order.child_status(k)[0]})" for k in order.child_cases(case, _is_project(case)) if order.child_status(k)[0] != "closed"]
    if live:
        raise StoreError("cannot cancel the case: nested cases still open — " + ", ".join(live) + " → close or cancel each first", 4)
    for p in todo.phases:
        if not p.done:
            out.lines += log(case, "DECISION", _cancel_phase(case, todo, p, why, out), f"p{p.n}").lines
    out.absorb(_write_todo(case, todo))
    date, _ = _now()
    text = _set_state_line(_readme_text(case, out), "closed: ", f"{date} · снято: {why}")
    _write_readme(case, text, out, anchor=True)
    out.lines = log(case, "DECISION", f"дело снято → {why}").lines + out.lines
    parent = store.parent_case(case, root)
    if parent is not None:
        ptodo = _todo(parent, out)
        for p in ptodo.phases:
            if case.name in p.waits:
                p.waits.remove(case.name)
                m = _next_number(parent, ptodo, p)
                p.items.append(grammar.Item(p.n, m, True, f"снято: {why} · {case.name}/", 0))
        out.absorb(_write_todo(parent, ptodo))
        _write_readme(parent, _set_state_line(_readme_text(parent, out), "ждёт: ", None), out)
        out.lines += log(parent, "DECISION", f"снято → {why} · {case.name}/").lines
        out.say(f"parent updated: {parent.name}")
    out.say(f"cancelled: {case.name} — closed as «снято», reason in the journal")
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


# ---- mv: a file moves, its links follow -----------------------------------------------------------
def _rewrite_links(text: str, base: Path, src: Path, dst: Path, new_base: Optional[Path] = None):
    """Markdown link targets in `text` (a file living in `base`) that resolve to `src` now point at
    `dst`; when the file itself moves (`new_base`), every relative target is re-based as well.
    Returns (text, number of links rewritten). URLs and anchors are left alone."""
    import os
    count = 0

    def fix(m):
        nonlocal count
        target = m.group(2)
        if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
            return m.group(0)
        path, _, anchor = target.partition("#")
        resolved = (base / path).resolve()
        if resolved == src.resolve():
            new = os.path.relpath(dst, new_base or base)
        elif new_base is not None and new_base != base:
            new = os.path.relpath(resolved, new_base)
        else:
            return m.group(0)
        if new == path:
            return m.group(0)
        count += 1
        return f"{m.group(1)}{new}{'#' + anchor if anchor else ''}{m.group(3)}"

    text = "".join(seg if code else order.LINK_RE.sub(fix, seg) for seg, code in order.outside_code(text))
    return text, count


def mv(case: Path, old: str, new: str) -> Outcome:
    """Move or rename a file inside the case and rewrite every markdown link to it — in the three
    owned files (through the stamp door) and in the case's own documents — so the map stays true
    (feedback 2026-09-03: one folder split broke 33 links, found only by a hand-written checker).
    An action, not an event: git keeps the history."""
    out = Outcome()
    src = (case / old)
    if not src.is_file():
        raise StoreError(f"{old} is not a file in the case (paths are relative to the case: docs/x.md)", 4)
    if src.name in store.FILES and src.parent == case:
        raise StoreError(f"{src.name} is one of the three case files — it does not move (L3)", 2)
    dst = case / new
    if new.endswith("/") or dst.is_dir():
        dst = dst / src.name
    for p in (src, dst):
        if case.resolve() not in p.resolve().parents:
            raise StoreError("mv works inside the case folder only", 2)
    if dst.exists():
        raise StoreError(f"{dst.relative_to(case)} already exists — mv never overwrites", 4)
    old_rel, new_rel = src.relative_to(case).as_posix(), dst.relative_to(case).as_posix()
    touched: List[str] = []
    # 1. the moved file's own links follow it
    body, n = _rewrite_links(src.read_text(encoding="utf-8"), src.parent, src, dst, new_base=dst.parent)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(body, encoding="utf-8")
    src.unlink()
    if n:
        touched.append(f"{new_rel} ({n} of its own)")
    # 2. the three owned files: links and `old/path` pointers, written through the stamp door;
    #    README last, so its derived lines (`last:` from the journal) see the rewritten journal
    for name in ("JOURNAL.md", "TODO.md", "README.md"):
        p = store.file_path(case, name)
        if not p.exists():
            continue
        text, _ = stamp.split(store.read(case, name))
        new_text, n = _rewrite_links(text, case, src, dst)
        k = new_text.count(f"`{old_rel}`")
        new_text = new_text.replace(f"`{old_rel}`", f"`{new_rel}`")
        if new_text != text:
            if name == "README.md":
                _write_readme(case, new_text, out)
            else:
                out.absorb(store.write(case, name, new_text))
            touched.append(f"{name} ({n + k})")
    # 3. every other markdown file of the case (documents, phase files), never the legacy archive
    for p in sorted(case.rglob("*.md")):
        rel = p.relative_to(case)
        if p == dst or any(part.startswith(".") or part in ("node_modules", "legacy") for part in rel.parts):
            continue
        if rel.parts[0] == store.CASES_DIR or any(store.is_case_dir(case / Path(*rel.parts[:i + 1])) for i in range(len(rel.parts) - 1)):
            continue
        if p.parent == case and p.name in store.FILES:
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        new_text, n = _rewrite_links(text, p.parent, src, dst)
        if n:
            p.write_text(new_text, encoding="utf-8")
            touched.append(f"{rel.as_posix()} ({n})")
    if "README.md" not in " ".join(touched):
        _refresh_readme(case, out)  # Links follow the files
    out.say(f"moved: {old_rel} → {new_rel}" + (f" · links rewritten: {', '.join(touched)}" if touched else " · no links pointed at it"))
    return out


# ---- dates: what the tool can count -----------------------------------------------------------------
STATE_DUE_RE = re.compile(r"^- due: (\d{4}-\d{2}-\d{2})(?:\s*[·—–-]?\s*(.*))?$", re.M)


def _dated(todo: grammar.Todo, readme_body: str, today: dt.date):
    """(overdue, due today, next 7 days, deadline) — from `— due:` items of open phases and the
    State line `- due: YYYY-MM-DD · what` (the case deadline). Held and done items do not count."""
    items = []
    for p in todo.phases:
        if p.done:
            continue
        for it in p.items:
            if it.due and not it.done and not it.held:
                try:
                    items.append((it, dt.date.fromisoformat(it.due)))
                except ValueError:
                    continue
    overdue = [(it, d) for it, d in items if d < today]
    due_today = [it for it, d in items if d == today]
    week = [(it, d) for it, d in items if today < d <= today + dt.timedelta(days=7)]
    deadline = None
    m = STATE_DUE_RE.search(readme_body)
    if m:
        try:
            deadline = (dt.date.fromisoformat(m.group(1)), (m.group(2) or "").strip())
        except ValueError:
            deadline = None
    return overdue, due_today, week, deadline


def _dates_line(todo: grammar.Todo, readme_body: str) -> Optional[str]:
    today = dt.date.today()
    overdue, due_today, week, deadline = _dated(todo, readme_body, today)
    if not (overdue or due_today or week or deadline):
        return None
    parts = [f"today {today.isoformat()}"]
    if due_today:
        parts.append("due today: " + ", ".join(f"{it.n}.{it.m} «{it.text}»" for it in due_today))
    if week:
        parts.append("next 7 days: " + ", ".join(f"{it.n}.{it.m} ({d.isoformat()[5:]})" for it, d in week))
    if overdue:
        parts.append(f"overdue: {len(overdue)} — see Order")
    if deadline:
        d, what = deadline
        days = (d - today).days
        when = "today" if days == 0 else (f"in {days} day{'s' if days != 1 else ''}" if days > 0 else f"{-days} day{'s' if days != -1 else ''} ago")
        parts.append(f"deadline {d.isoformat()}{f' «{what}»' if what else ''} {when}")
    return "dates: " + " · ".join(parts)


RULE_ITEMS_LINK_RE = re.compile(r"^- rule: items link", re.M)
RULE_ITEMS_LINK = 'rule: items link their material'


def _items_link_rule(readme_body: str) -> bool:
    """The case rule «every item links the material it needs» — a Context line
    `- rule: items link their material`. Opt-in: a coding case rarely needs a document per item, a
    coordination case always does, and only the case can say which it is (feedback 2026-09-03)."""
    return RULE_ITEMS_LINK_RE.search(readme_body) is not None


def _blind_items(todo: grammar.Todo, readme_body: str) -> List[str]:
    if not _items_link_rule(readme_body):
        return []
    blind = [it for p in todo.phases if not p.done for it in p.items if not it.done and "](" not in it.text]
    if not blind:
        return []
    shown = ", ".join(f"{it.n}.{it.m}" for it in blind[:6]) + (f" … +{len(blind) - 6}" if len(blind) > 6 else "")
    return [f"{len(blind)} item(s) without a link to their material — {shown} → mike todo edit N.M \"text — [name](docs/file.md)\" "
            f"(this case's rule: items link their material)"]


def _overdue_lines(todo: grammar.Todo, readme_body: str) -> List[str]:
    overdue = _dated(todo, readme_body, dt.date.today())[0]
    return [f"overdue: {it.n}.{it.m} «{it.text}» was due {d.isoformat()} → mike todo done {it.n}.{it.m} · "
            f"mike todo due {it.n}.{it.m} <date> · mike todo cancel {it.n}.{it.m} \"why\"" for it, d in overdue]


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
    try:
        todo_now = store.todo_of(case)
        lines.extend(_overdue_lines(todo_now, readme_body))  # a date that passed is out of order
        lines.extend(_blind_items(todo_now, readme_body))    # an item with nowhere to go (case rule)
        lines.extend(_gone_lines(case, todo_now))              # waiting for something that no longer exists (F19)
    except StoreError:
        pass
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


RULES_TOPICS = "mike help model · files · order · limits"


def _rules_pointer(root: Path) -> str:
    """Where the rules can be read FROM HERE. The help topics always answer; the spec file only where
    it exists (the mike-cli clone) — `case new` ships no RULES.md into a project, and a pointer printed
    on every entry must resolve (feedback 2026-09-03: root case, `.cases/` empty, pointer dead)."""
    spec = root / "RULES.md"
    return f"{spec.relative_to(root.parent)} · {RULES_TOPICS}" if spec.is_file() else RULES_TOPICS


def entry(root: Path, case: Path) -> Outcome:
    out = Outcome()
    names = store.chain(case, root)
    out.say(f"mike · case in hand: {' › '.join(names)}", "")
    others = [c.name for c in store.all_cases(root) if store.is_open(c) and c != case]
    if others:
        out.say("other open cases: " + " · ".join(others) + " — switch: `mike case use <name>`", "")
    readme_body = _refresh_readme(case, out)
    todo_body, _ = stamp.split(store.read(case, "TODO.md"))
    todo = grammar.parse_todo(todo_body)
    if not todo.errors and _derive_todo(case, todo):  # phase lines follow their files (F18)
        try:
            out.absorb(store.write(case, "TODO.md", render_todo(todo)))
            todo_body = render_todo(todo)
            out.say("TODO refreshed: open phase lines follow their phase files (goal · path)")
        except StoreError as e:
            out.warn(f"TODO not refreshed — {e}")
    dates = _dates_line(todo, readme_body) if not todo.errors else None
    if dates:
        out.say(dates, "")  # what the tool can count: due today, this week, overdue, the deadline
    unblocked = _unblocked_line(case, todo) if not todo.errors else None
    if unblocked:
        out.say(unblocked, "")  # candidates by the dependency graph (F19) — the owner's `next:` stays the direction
    out.say(readme_body.rstrip("\n"), "")
    out.say(todo_body.rstrip("\n"), "")
    journal = grammar.parse_journal(store.read(case, "JOURNAL.md"))
    if journal.entries:
        out.say(*_journal_headlines(journal, ENTRY_LIMIT), "")
    issues = _order_lines(case, root, readme_body, journal)
    if issues:
        out.say(f"## Order — {len(issues)} thing(s) to put back", *(f"- {ln}" for ln in issues), "")
    else:
        out.say("## Order", "- ✓ everything in place: files carry summaries, Links follow the files, State is current", "")
    out.say(f"how to work: mike help start · what goes where: mike help where · rules: {_rules_pointer(root)} · full check: mike check")
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
            dead: list = []
            for ln in order.report(case, _is_project(case), rb, jr if not jr.errors else None, links, link_violations=dead):
                out.warn(f"{case.name}: order · {ln}")
            # a dead link in the files mike holds is a violation, not a warning: the owner clicks and
            # nothing opens, and `violations: 0` is what gets read (feedback 2026-09-03)
            for f, t in dead:
                out.say(f"x {case.name}/{f}: F16 · broken link → {t} — fix the link, or move files with `mike mv old new` (links follow)")
                log_lines.append(f"{date} {time} · {case.name} · {f} · F16 · broken link → {t}")
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
