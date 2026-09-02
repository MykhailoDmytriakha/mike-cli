"""Migrate a legacy case into mike's grammar without losing a byte (P13 of .cases/RULES.md).

A legacy file is one of README.md / TODO.md / JOURNAL.md that mike did not stamp and that its
grammar rejects — a case written before mike, or rewritten by hand since. Every write refuses
such a file, and rebuilding it by grammar (S4) would move most of it into `.recover.md`; so the
door was a dead end (feedback 2026-09-02).

`analyse` builds a plan and changes nothing; `apply` executes it:
- the legacy files are copied byte-for-byte into `legacy/<date-time>/` first, and verified;
- README: title kept; sections mapped by name (Context ← goal/context/summary …, Decisions,
  Problems ← problems/risks/open …, Links); everything else stays in the archive and is listed;
- TODO: headings become phases (name trimmed to 1–3 English words, else `Legacy N`), checkbox
  lines become items (long ones trimmed, the full text is in the archive); a phase whose items
  are all done is closed with a phase file marked `migrated from legacy` — P8 gates skip it;
- JOURNAL: not converted — events need a type and ≤ 200 chars, guessing would be lying; the new
  journal opens with one PHASE event pointing at the archive;
- the three canonical files are validated by their grammars BEFORE anything is touched, then
  written atomically; on any failure the archive copies are put back.
Ambiguity is reported for review, never resolved silently.
"""
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import grammar, stamp, store

ARCHIVE_DIR = "legacy"
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
CHECKBOX_RE = re.compile(r"^\s*[-*+]\s+\[( |x|X)\]\s+(.+?)\s*$")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
SECTION_MAX_LINES = 40
README_SYNONYMS = {
    "Context": {"context", "goal", "goals", "purpose", "summary", "overview", "objective", "цель", "контекст",
                "задача", "о деле", "описание", "background"},
    "Decisions": {"decisions", "decision log", "decided", "решения", "принято"},
    "Problems": {"problems", "risks", "issues", "blockers", "open questions", "open", "проблемы", "риски",
                 "блокеры", "открытые вопросы", "вопросы"},
    "Links": {"links", "references", "resources", "see also", "ссылки", "источники", "где что"},
}
PHASE_WORD_RE = re.compile(r"^(phase|фаза|этап|stage|step)\s*", re.I)


@dataclass
class Plan:
    case: Path
    stamp_at: str                      # "YYYY-MM-DD HH:MM"
    legacy: Dict[str, str] = field(default_factory=dict)      # file → why it is legacy
    archive: Optional[Path] = None
    bodies: Dict[str, str] = field(default_factory=dict)      # file → canonical body (no stamp)
    phase_files: Dict[Path, str] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)            # what maps where
    review: List[str] = field(default_factory=list)           # ambiguous / lossy / unmapped
    title: str = ""
    journal_lines: int = 0

    @property
    def empty(self) -> bool:
        return not self.legacy


# ---- helpers ------------------------------------------------------------------------------------
def _trim(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if grammar.visible_len(text) <= limit:
        return text
    cut = text.rfind(" ", 0, limit - 1)
    return text[: cut if cut > limit // 2 else limit - 1].rstrip() + "…"


def _sections(lines: List[str]) -> Tuple[List[str], List[Tuple[str, List[str]]]]:
    """(preamble lines, [(heading text, lines)]) — headings of any level after the title."""
    pre: List[str] = []
    out: List[Tuple[str, List[str]]] = []
    cur: Optional[List[str]] = None
    for ln in lines:
        m = HEADING_RE.match(ln)
        if m and len(m.group(1)) >= 2:
            cur = []
            out.append((m.group(2).strip(), cur))
            continue
        (cur if cur is not None else pre).append(ln)
    return pre, out


def _phase_name(heading: str, n: int, review: List[str]) -> str:
    raw = PHASE_WORD_RE.sub("", heading.strip()).strip(" :—–-.")
    raw = re.sub(r"^\d+[.)]?\s*", "", raw)
    words = [w for w in re.split(r"\s+", raw) if w]
    words = [re.sub(r"[^A-Za-z0-9-]", "", w) for w in words]
    words = [w for w in words if w][:3]
    name = " ".join(words)
    if words and grammar.PHASE_NAME_RE.match(name):
        if name != heading.strip():
            review.append(f"TODO phase {n}: heading «{heading.strip()}» → «{name}» (F13: English, 1–3 words)")
        return name
    review.append(f"TODO phase {n}: heading «{heading.strip()}» has no usable English name → «Legacy {n}» (rename: it is a planned line in TODO.md)")
    return f"Legacy {n}"


# ---- analysis -----------------------------------------------------------------------------------
def legacy_reason(case: Path, name: str) -> Optional[str]:
    """Why the file is legacy: grammar errors AND no valid mike stamp. None when it is fine."""
    p = store.file_path(case, name)
    if not p.exists():
        return None
    text = p.read_text(encoding="utf-8")
    ok, state = stamp.verify(text)
    result = {"README.md": grammar.parse_readme, "TODO.md": grammar.parse_todo, "JOURNAL.md": grammar.parse_journal}[name](text)
    # Legacy = the grammar rejects it AND mike never stamped it. A stamped file that broke since
    # (mismatch / not-last) is the S4 case: hand edit → rebuilt by grammar on the next write.
    if result.errors and state == "missing":
        return f"{len(result.errors)} rule violation(s), never stamped"
    return None


def analyse(case: Path, now: Tuple[str, str]) -> Plan:
    date, time = now
    plan = Plan(case, f"{date} {time}")
    for name in store.FILES:
        why = legacy_reason(case, name)
        if why:
            plan.legacy[name] = why
    if plan.empty:
        return plan
    stamp_dir = f"{date}-{time.replace(':', '')}"
    archive = case / ARCHIVE_DIR / stamp_dir
    k = 2
    while archive.exists():
        archive = case / ARCHIVE_DIR / f"{stamp_dir}-{k}"
        k += 1
    plan.archive = archive
    rel_archive = f"{ARCHIVE_DIR}/{archive.name}"
    plan.title = _title(case)
    plan.notes.append(f"archive → {rel_archive}/ ({', '.join(sorted(plan.legacy))} byte-for-byte)")
    if "README.md" in plan.legacy:
        plan.bodies["README.md"] = _plan_readme(case, plan, rel_archive)
    if "TODO.md" in plan.legacy:
        plan.bodies["TODO.md"] = _plan_todo(case, plan, rel_archive)
    if "JOURNAL.md" in plan.legacy:
        text = store.read(case, "JOURNAL.md")
        lines = [l for l in stamp.split(text)[0].split("\n") if l.strip()]
        plan.journal_lines = len(lines)
        dated = sum(1 for l in lines if HEADING_RE.match(l) and DATE_RE.search(l))
        plan.bodies["JOURNAL.md"] = f"# JOURNAL — {plan.title}\n"
        plan.notes.append(f"JOURNAL: {len(lines)} lines, {dated} dated heading(s) → not converted (an event needs a type and ≤ 200 chars; "
                          f"guessing would be lying) — kept in the archive; the new journal opens with one PHASE event pointing there")
        plan.review.append(f"JOURNAL: re-enter what still matters with `mike log DECISION|PROBLEM|RESULT \"…\"` from {rel_archive}/JOURNAL.md")
    return plan


def _title(case: Path) -> str:
    for name in ("README.md", "TODO.md"):
        p = store.file_path(case, name)
        if p.exists():
            for ln in p.read_text(encoding="utf-8").split("\n")[:5]:
                m = HEADING_RE.match(ln)
                if m and len(m.group(1)) == 1:
                    t = re.sub(r"^(TODO|JOURNAL)\s*[—–-]\s*", "", m.group(2).strip())
                    if t:
                        return t
    return case.name


def _plan_readme(case: Path, plan: Plan, rel_archive: str) -> str:
    text, _ = stamp.split(store.read(case, "README.md"))
    lines = text.split("\n")
    body_lines = lines[1:] if lines and HEADING_RE.match(lines[0]) and len(HEADING_RE.match(lines[0]).group(1)) == 1 else lines
    pre, sections = _sections(body_lines)
    mapped: Dict[str, List[str]] = {s: [] for s in grammar.README_SECTIONS}
    used = []
    for heading, content in sections:
        key = heading.lower().strip(" :")
        target = next((s for s, names in README_SYNONYMS.items() if key in names), None)
        content = [l for l in content if l.strip()]
        if target is None:
            plan.review.append(f"README section «{heading}» ({len(content)} lines) → not mapped, stays in {rel_archive}/README.md")
            continue
        used.append(heading)
        kept = content[:SECTION_MAX_LINES]
        if len(content) > SECTION_MAX_LINES:
            plan.review.append(f"README «{heading}»: {len(content) - SECTION_MAX_LINES} lines beyond {SECTION_MAX_LINES} stay in the archive")
        for l in kept:
            s = l.rstrip()
            if s.lstrip().startswith(("- ", "* ", "+ ")):
                s = "- " + s.lstrip()[2:]
                if grammar.visible_len(s) > grammar.README_POINTER_CHARS:
                    plan.review.append(f"README «{heading}»: a line trimmed to {grammar.README_POINTER_CHARS} chars (full text in the archive)")
                    s = _trim(s, grammar.README_POINTER_CHARS)
            elif s.startswith("#"):
                s = "- " + HEADING_RE.match(s).group(2) if HEADING_RE.match(s) else s
            mapped[target].append(s)
        plan.notes.append(f"README: {target} ← «{heading}» ({len(kept)} lines)")
    pre = [l for l in pre if l.strip()]
    if not mapped["Context"] and pre:
        mapped["Context"] = [l.rstrip() for l in pre[:5]]
        plan.notes.append(f"README: Context ← text before the first heading ({len(mapped['Context'])} lines)")
    elif pre:
        plan.review.append(f"README: {len(pre)} line(s) before the first heading → not mapped, stay in the archive")
    if not mapped["Context"]:
        mapped["Context"] = [f"(перенесено из legacy формата {plan.stamp_at[:10]}; цель словами владельца — переписать: см. {rel_archive}/README.md)"]
    mapped["State"] = ["- progress: (kept by mike)",
                       f"- next: прочитать {rel_archive}/README.md и переписать State — mike readme set next \"…\"",
                       f"- as of: {plan.stamp_at} · p0 (1 event)"]
    mapped["Links"] = [f"- {ARCHIVE_DIR}/ — файлы дела до миграции {plan.stamp_at[:10]}, byte-for-byte: {', '.join(sorted(plan.legacy))}"] + mapped["Links"]
    out = [f"# {plan.title}"]
    for s in grammar.README_SECTIONS:
        out += ["", f"## {s}"] + mapped[s]
    return "\n".join(out) + "\n"


def _plan_todo(case: Path, plan: Plan, rel_archive: str) -> str:
    from . import commands  # lazy: commands imports this module

    text, _ = stamp.split(store.read(case, "TODO.md"))
    lines = text.split("\n")
    if lines and HEADING_RE.match(lines[0]) and len(HEADING_RE.match(lines[0]).group(1)) == 1:
        lines = lines[1:]
    todo = grammar.Todo(title=f"TODO — {plan.title}")
    phase: Optional[grammar.Phase] = None
    unmapped = 0
    orphans = 0
    trimmed = 0
    for ln in lines:
        if not ln.strip():
            continue
        m = HEADING_RE.match(ln)
        if m:
            n = len(todo.phases) + 1
            phase = grammar.Phase(n, _phase_name(m.group(2), n, plan.review), False, 0)
            todo.phases.append(phase)
            continue
        m = CHECKBOX_RE.match(ln)
        if m:
            if phase is None:
                phase = grammar.Phase(1, "Legacy", False, 0)
                todo.phases.append(phase)
                orphans += 1
            elif phase.n == 1 and phase.name == "Legacy" and orphans:
                orphans += 1
            item_text = m.group(2)
            if grammar.visible_len(item_text) > grammar.TODO_ITEM_CHARS:
                item_text = _trim(item_text, grammar.TODO_ITEM_CHARS)
                trimmed += 1
            phase.items.append(grammar.Item(phase.n, len(phase.items) + 1, m.group(1).lower() == "x", item_text, 0))
            continue
        unmapped += 1
    if orphans:
        plan.review.append(f"TODO: {orphans} checkbox line(s) before any heading → phase 1 «Legacy» (review their phase)")
    if trimmed:
        plan.review.append(f"TODO: {trimmed} item(s) trimmed to {grammar.TODO_ITEM_CHARS} visible chars (full text in {rel_archive}/TODO.md)")
    if unmapped:
        plan.review.append(f"TODO: {unmapped} non-checkbox line(s) (prose, nested evidence) → not mapped, stay in {rel_archive}/TODO.md")
    for p in todo.phases:
        if p.items and all(it.done for it in p.items):
            pf = case / "phases" / f"{p.n}-{re.sub(r'[^a-z0-9]+', '-', p.name.lower()).strip('-')}.md"
            if pf.exists():
                parsed = grammar.parse_phase_file(pf.read_text(encoding="utf-8"))
                if parsed.errors:
                    plan.review.append(f"TODO phase {p.n} {p.name}: all items done, but phases/{pf.name} exists and does not parse → left OPEN")
                    continue
            else:
                plan.phase_files[pf] = "\n".join([
                    f"# Phase {p.n} — {p.name}", f"goal: migrated from legacy TODO — see {rel_archive}/TODO.md",
                    f"result: migrated from legacy TODO: {len(p.items)} items done", "", "## Items at migration",
                    *(f"- {it.n}.{it.m} ✓ {it.text}" for it in p.items), ""])
            p.summary = f"migrated from legacy TODO: {len(p.items)} items done · {plan.stamp_at[:10]} · phases/{pf.name}"
            p.done, p.items = True, []
    plan.notes.append("TODO: " + (" · ".join(
        f"{p.n} {p.name} ({'closed' if p.done else str(len(p.items)) + ' items, ' + str(sum(i.done for i in p.items)) + ' done'})"
        for p in todo.phases) if todo.phases else "no headings and no checkbox lines → empty TODO (phases: mike phase open 1 …)"))
    return commands.render_todo(todo)


# ---- apply ---------------------------------------------------------------------------------------
def validate(plan: Plan) -> List[str]:
    """Grammar errors of the planned bodies — must be empty before anything is touched."""
    problems = []
    parsers = {"README.md": grammar.parse_readme, "TODO.md": grammar.parse_todo, "JOURNAL.md": grammar.parse_journal}
    for name, body in plan.bodies.items():
        r = parsers[name](stamp.apply(body))
        problems += [f"{name}: {f}" for f in r.errors]
    for pf, text in plan.phase_files.items():
        r = grammar.parse_phase_file(text)
        problems += [f"{pf.name}: {f}" for f in r.errors]
    return problems


def apply(plan: Plan) -> List[str]:
    """Archive, then write; put the archive back on any failure. Returns what was done."""
    done: List[str] = []
    problems = validate(plan)
    if problems:
        raise store.StoreError("migration plan does not pass the grammars — nothing touched:\n  " + "\n  ".join(problems), 1)
    plan.archive.mkdir(parents=True, exist_ok=False)
    originals: Dict[str, Path] = {}
    for name in plan.legacy:
        src = store.file_path(plan.case, name)
        dst = plan.archive / src.name
        shutil.copy2(src, dst)
        if dst.read_bytes() != src.read_bytes():
            raise store.StoreError(f"archive copy of {name} differs from the original — aborted before any change", 1)
        originals[name] = src
    done.append(f"archived: {plan.archive.relative_to(plan.case)}/ — {', '.join(p.name for p in originals.values())}")
    written: List[Path] = []
    try:
        for pf, text in plan.phase_files.items():
            pf.parent.mkdir(exist_ok=True)
            pf.write_text(text, encoding="utf-8")
            written.append(pf)
            done.append(f"created: {pf.relative_to(plan.case)}")
        for name, body in plan.bodies.items():
            store._atomic_write(originals[name], stamp.apply(body))
            done.append(f"written: {originals[name].name} (canonical, stamped)")
    except Exception as e:  # put everything back from the archive, then say so
        for name, src in originals.items():
            shutil.copy2(plan.archive / src.name, src)
        for pf in written:
            pf.unlink(missing_ok=True)
            if pf.parent.exists() and not any(pf.parent.iterdir()):
                pf.parent.rmdir()
        raise store.StoreError(f"migration failed and was rolled back — the originals are back in place, the archive "
                               f"{plan.archive.relative_to(plan.case)}/ is kept: {e}", 1) from e
    return done


def report(plan: Plan, dry: bool) -> List[str]:
    out = [f"legacy case: {plan.case.name} — " + "; ".join(f"{n}: {w}" for n, w in sorted(plan.legacy.items()))]
    out += plan.notes
    if plan.review:
        out.append(f"review ({len(plan.review)}):")
        out += [f"  - {r}" for r in plan.review]
    if dry:
        out.append("dry run — nothing changed. Apply: mike migrate --apply")
    return out
