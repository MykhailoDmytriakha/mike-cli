"""Order — what keeps a case tidy by itself (rules F14, F15, S5, P12 of .cases/RULES.md).

The three files are held by their grammars; the layer below them (docs/, research/, …) is where
water used to settle: a new file is cheap, merging two is never done. This module makes that layer
visible from the top:
- every .md file in a content folder carries `summary: <one line>` near its top (F14) — the file
  describes itself, README Links is rendered from those lines and never rots;
- two files that share their TEXT are named aloud (F15): verbatim phrasing, not vocabulary — two
  documents about one subject always share the words, only a copy shares the sentences;
- a file over its budget is named aloud (F15) — split by summary or trim; a folder total is not
  (a byte count cannot tell deliverables from water);
- README State carries `as of: <journal entry>`: RESULT/PHASE events after it mean the "now" is
  behind the history (S5).
Nothing here refuses a write: the lower layer is written by the agent directly, so the tool can
only show what is out of order, with the command that fixes it — on every entry (P12).
"""
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import grammar

SUMMARY_RE = re.compile(r"^summary: (.+)$")
SUMMARY_SCAN_LINES = 5
SUMMARY_CHARS = 120
FILE_WARN_BYTES = 24 * 1024
# F15 duplicate = verbatim overlap: word 3-grams (shingles) of the smaller file found in the other.
# Measured 2026-09-03 on a live case (8 documents in one folder): the pair the 0.10 word-set metric
# flagged at 0.46 — a document drawn from another, kept apart on purpose — shares 0.34 of its
# phrasing; every other pair ≤ 0.11; a copy scores 0.8+. 0.50 sits between with margin.
SHINGLE_WORDS = 3
DUP_SHARE = 0.50
DUP_MIN_SHINGLES = 30  # a file of ~30 words is too short to call anything a copy of it
TOKEN_RE = re.compile(r"[a-zа-яё0-9]+", re.I)
SKIP_DIRS = {"phases", "node_modules", "scripts", "legacy"}  # legacy/ = byte-for-byte archive, never nagged
# L4 kinds — in root mode only these (plus folders already listed in Links) are content folders,
# because the project folder also holds source code, build output and whatever else.
KNOWN_KINDS = {"docs", "research", "logs", "meetings", "jira", "data", "inbox", "notes", "forms",
               "briefing", "print", "reports", "letters", "evidence", "correspondence"}
POINTER_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)|`([^`]+)`|(?<![\w/])((?:[\w.-]+/)+[\w.-]*)")
FOLDER_LINE_RE = re.compile(r"^- (?:`|\[)?([\w.-]+(?:/[\w.-]+)*)/(?:`|\]\([\w./-]+\))?(?:\s*[—–-]\s*(.*))?$")  # `docs/` or nested `docs/notes/`
STATE_ANCHOR_RE = re.compile(r"^- as of: (\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})(?: · (p\d+(?:\.\d+)?))?(?: \((\d+) events?\))?\s*$", re.M)
PLACEHOLDER_FOLDER = "(describe this folder:"
PLACEHOLDER_FILE = "summary: missing"
LINK_RE = re.compile(r"(\]\()([^)\s]+)(\))")  # a markdown link target
CODE_RE = re.compile(r"```.*?```|`[^`\n]*`", re.S)  # fenced blocks and inline code: examples, not links


def outside_code(text: str):
    """(segment, is_code) pieces of a markdown text — a link written inside code is an example
    (`[name](path)` in a rule or a help text) and is neither checked nor rewritten."""
    out, at = [], 0
    for m in CODE_RE.finditer(text):
        if m.start() > at:
            out.append((text[at:m.start()], False))
        out.append((m.group(0), True))
        at = m.end()
    if at < len(text):
        out.append((text[at:], False))
    return out


@dataclass
class Doc:
    rel: str            # path relative to the case, e.g. docs/brief.md
    path: Path
    summary: Optional[str]
    bytes: int


@dataclass
class Folder:
    name: str            # path relative to the case: `docs`, nested `docs/notes`
    path: Path
    docs: List[Doc] = field(default_factory=list)          # markdown files directly inside
    subs: List["Folder"] = field(default_factory=list)     # sub-folders, scanned the same way
    other: List[str] = field(default_factory=list)         # non-md files, as short labels
    md_bytes: int = 0

    def all_docs(self) -> List[Doc]:
        """Every markdown file in the folder and below — what summaries, duplicates and budgets look at."""
        out = list(self.docs)
        for s in self.subs:
            out.extend(s.all_docs())
        return out


# ---- scanning ------------------------------------------------------------------------------------
def read_summary(path: Path) -> Optional[str]:
    """`summary: …` within the first lines of a markdown file (F14); None when absent."""
    try:
        with path.open(encoding="utf-8", errors="ignore") as fh:
            for _ in range(SUMMARY_SCAN_LINES):
                line = fh.readline()
                if not line:
                    break
                m = SUMMARY_RE.match(line.rstrip("\n"))
                if m:
                    return " ".join(m.group(1).split())
    except OSError:
        return None
    return None


def phase_summary(path: Path) -> Optional[str]:
    """A phase file describes itself by `result:` when closed, `goal:` while it runs (F12)."""
    try:
        parsed = grammar.parse_phase_file(path.read_text(encoding="utf-8"))
    except OSError:
        return None
    if parsed.errors:
        return None
    return parsed.result or parsed.goal or None


def _is_case_dir(p: Path) -> bool:
    from . import store  # local import: store imports order for the README render
    return store.is_case_dir(p)


def content_folders(case: Path, root_mode: bool, listed: Optional[set] = None) -> List[Folder]:
    """Folders of the case that hold content, each with its markdown files and their summaries.

    Normal case: every visible folder except phases/ (rendered separately), scripts/ and nested cases.
    Root mode: only known kinds (L4) and folders the README already lists — the project folder
    holds code too, and code is not case content.
    """
    listed = listed or set()
    out: List[Folder] = []
    if not case.is_dir():
        return out
    for d in sorted(case.iterdir()):
        if not d.is_dir() or d.name.startswith(".") or d.name in SKIP_DIRS or _is_case_dir(d):
            continue
        if root_mode and d.name not in KNOWN_KINDS and d.name not in listed:
            continue
        out.append(_scan_folder(d, d.name))
    return out


def _scan_folder(d: Path, rel: str) -> Folder:
    """A content folder with its markdown files, its sub-folders (the same way, any depth) and its
    other files. Sorting documents into sub-folders by kind is normal housekeeping — the map must
    see into them, or a third of a case goes invisible (feedback 2026-09-03)."""
    folder = Folder(rel, d)
    for child in sorted(d.iterdir()):
        if child.name.startswith("."):
            continue
        if child.is_dir():
            if not _is_case_dir(child) and child.name not in SKIP_DIRS:
                folder.subs.append(_scan_folder(child, f"{rel}/{child.name}"))
        elif child.suffix.lower() == ".md":
            size = child.stat().st_size
            folder.docs.append(Doc(f"{rel}/{child.name}", child, read_summary(child), size))
            folder.md_bytes += size
        else:
            folder.other.append(child.name)
    return folder


def phases_folder(case: Path) -> Optional[Folder]:
    d = case / "phases"
    if not d.is_dir():
        return None
    folder = Folder("phases", d)
    for child in sorted(d.glob("*.md"), key=lambda p: (int(re.match(r"(\d+)", p.name).group(1)) if re.match(r"\d+", p.name) else 0, p.name)):
        folder.docs.append(Doc(f"phases/{child.name}", child, phase_summary(child), child.stat().st_size))
        folder.md_bytes += child.stat().st_size
    return folder


# ---- nested cases: the parent's line is rendered from the child's own header (F18) ---------------
CASES_DIR = ".cases"
CASE_STATE_RE = re.compile(r"^- (progress|next|closed): (.*)$")
CASE_LINE_RE = re.compile(r"^- (?:closed: )?\[[^\]]+\]\(([^)]+)/README\.md\)")
CASES_SHOWN_CLOSED = 5


def child_cases(case: Path, root_mode: bool) -> List[Path]:
    """Direct nested cases: under `.cases/` for the project case, inside the folder for a normal one."""
    base = case / CASES_DIR if root_mode else case
    if not base.is_dir():
        return []
    return sorted(d for d in base.iterdir() if _is_case_dir(d))


def child_status(child: Path) -> Tuple[str, str, str, str]:
    """('open' | 'closed' | 'broken', progress, next, closed) read from the child's own README —
    the child describes itself; a README mike cannot parse makes the child BROKEN, and a broken
    child holds its parent open (F18)."""
    from . import store, stamp  # local: store imports order for the README render
    try:
        body, _ = stamp.split(store.read(child, "README.md"))
    except Exception:  # noqa: BLE001 — missing or unreadable README = broken, never silent
        return ("broken", "", "", "")
    parsed = grammar.parse_readme(body)
    if parsed.errors:
        return ("broken", "", "", "")
    state: Dict[str, str] = {}
    for ln in parsed.sections.get("State", []):
        m = CASE_STATE_RE.match(ln)
        if m:
            state[m.group(1)] = m.group(2).strip()
    if state.get("closed"):
        return ("closed", state.get("progress", ""), "", state["closed"])
    return ("open", state.get("progress", ""), state.get("next", ""), "")


def _render_cases(case: Path, root_mode: bool) -> List[str]:
    """The cases block of Links: open children one line each (progress · next), closed ones as a
    count plus the latest few — a root with hundreds of closed cases must not drown its README."""
    kids = child_cases(case, root_mode)
    if not kids:
        return []
    prefix = f"{CASES_DIR}/" if root_mode else ""
    rows = [(k, child_status(k)) for k in kids]
    live = [(k, s) for k, s in rows if s[0] != "closed"]
    closed = sorted(((k, s) for k, s in rows if s[0] == "closed"), key=lambda ks: ks[1][3], reverse=True)
    out = [f"- cases: {len(live)} open · {len(closed)} closed — every case: mike case list"]
    for k, s in live:
        link = f"[{k.name}]({prefix}{k.name}/README.md)"
        if s[0] == "broken":
            out.append(f"  - {link} — BROKEN: README unparsable, holds this case open → mike --case {k.name} check")
        else:
            desc = s[1] + (f" · next: {s[2]}" if s[2] else "")
            out.append(f"  - {link} — {_short(desc or '(no State yet)', SUMMARY_CHARS)}")
    for k, s in closed[:CASES_SHOWN_CLOSED]:
        out.append(f"  - closed: [{k.name}]({prefix}{k.name}/README.md) — {_short(s[3], SUMMARY_CHARS)}")
    if len(closed) > CASES_SHOWN_CLOSED:
        out.append(f"  - … +{len(closed) - CASES_SHOWN_CLOSED} closed earlier — mike case list")
    return out


def _is_cases_line(stripped: str, case: Path, root_mode: bool) -> bool:
    """A line of the rendered cases block — re-rendered every time, never kept as manual."""
    if stripped.startswith("- cases: ") or stripped.startswith("- … +"):
        return True
    m = CASE_LINE_RE.match(stripped)
    return bool(m) and _is_case_dir(case / m.group(1))


# ---- README Links rendering (F3: folder and file lines come from the files themselves) -----------
def _pointer_target(line: str) -> Optional[str]:
    for m in POINTER_RE.finditer(line):
        target = m.group(1) or m.group(2) or m.group(3)
        if target:
            return target.strip()
    return None


def _classify(line: str, case: Path):
    """('folder', name, description) | ('file', rel, description) | ('manual', line, None)."""
    if not line.startswith("- "):
        return ("manual", line, None)
    m = FOLDER_LINE_RE.match(line)
    if m and (case / m.group(1)).is_dir():
        return ("folder", m.group(1), (m.group(2) or "").strip())
    target = _pointer_target(line[2:])
    if target:
        t = target.split("#")[0].rstrip("/")
        p = case / t
        if t and "/" in t and p.is_file() and p.suffix.lower() == ".md" and not t.startswith("..") and t.split("/")[0] not in (".cases",):
            desc = line[2:]
            # description = what follows the pointer: `- [x](y) — desc` / `- `y` — desc`
            k = desc.find(" — ")
            return ("file", t, desc[k + 3:].strip() if k >= 0 else "")
    return ("manual", line, None)


def _short(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if grammar.visible_len(text) <= limit:
        return text
    cut = text.rfind(" ", 0, limit - 1)
    return text[: cut if cut > limit // 2 else limit - 1].rstrip() + "…"


def render_links(case: Path, root_mode: bool, manual_lines: List[str]) -> Tuple[List[str], Dict[str, str]]:
    """Rebuild the Links section: the agent's lines about the outside world stay in their order,
    then one block per folder — the folder line (agent's description) with the folder's files
    nested under it, each described by its own `summary:` line (F14).

    Returns (lines, fallback) where fallback maps file rel-path → description the agent had written
    in Links for a file that has no summary line yet (kept so nothing is lost; `mike order --adopt`
    moves it into the file).
    """
    manual: List[str] = []
    folder_desc: Dict[str, str] = {}
    fallback: Dict[str, str] = {}
    fallback_raw: Dict[str, str] = {}
    for raw in manual_lines:
        stripped = raw.lstrip()
        if _is_cases_line(stripped, case, root_mode):
            continue  # the cases block is rendered from the children's READMEs (F18)
        kind, a, b = _classify(stripped if stripped.startswith("- ") else raw, case)  # nested lines: by content, any depth
        if kind == "folder" and ((a.split("/")[0] in SKIP_DIRS and a != "phases") or a.startswith(".")):
            manual.append(raw)  # a folder mike does not render (legacy/, scripts/ …): the agent's line stays as written
        elif kind == "folder":
            # the newest real description wins; a placeholder we rendered earlier counts as none
            if b and not b.startswith(PLACEHOLDER_FOLDER):
                folder_desc[a] = b
            else:
                folder_desc.setdefault(a, "")
        elif kind == "file":
            if b and not b.startswith(PLACEHOLDER_FILE):
                fallback[a] = b
                fallback_raw[a] = raw
        elif stripped.startswith("- other: "):
            continue  # rendered by us
        else:
            manual.append(raw)
    listed = {n.split("/")[0] for n in folder_desc} | {r.split("/")[0] for r in fallback}
    folders = content_folders(case, root_mode, listed)
    ph = phases_folder(case)
    if ph and ph.docs:
        folders.append(ph)
    rendered: set = set()
    blocks: List[str] = []
    for f in folders:
        desc = folder_desc.get(f.name, "")
        if f.name == "phases" and not desc:
            desc = "по фазам: goal → result"
        if desc:
            blocks.append(f"- {f.name}/ — {desc}")
        else:
            blocks.append(f"- {f.name}/ — {PLACEHOLDER_FOLDER} mike readme add links \"{f.name}/ — …\")")
        _render_folder(f, 1, folder_desc, fallback, rendered, blocks)
    # a line the agent wrote for a file mike does not render here (outside the content folders) is
    # never dropped: it stays among the manual lines — `line added` must stay true (feedback 2026-09-03)
    out = manual + [raw for rel, raw in fallback_raw.items() if rel not in rendered] + blocks + _render_cases(case, root_mode)
    return out, {rel: desc for rel, desc in fallback.items() if rel in rendered}


def _render_folder(f: Folder, depth: int, folder_desc: Dict[str, str], fallback: Dict[str, str],
                   rendered: set, out: List[str]):
    """Under a folder line: its files by their summaries, then each sub-folder one level deeper
    (full path `- docs/notes/`, so the line re-parses as that folder), then the other files."""
    ind = "  " * depth
    for d in f.docs:
        rendered.add(d.rel)
        summary = d.summary or fallback.get(d.rel)
        if summary:
            out.append(f"{ind}- [{d.path.name}]({d.rel}) — {_short(summary, SUMMARY_CHARS)}")
        else:
            out.append(f"{ind}- [{d.path.name}]({d.rel}) — {PLACEHOLDER_FILE} → add `summary: …` as line 2")
    for s in f.subs:
        desc = folder_desc.get(s.name, "")
        out.append(f"{ind}- {s.name}/" + (f" — {desc}" if desc else ""))
        _render_folder(s, depth + 1, folder_desc, fallback, rendered, out)
    if f.other:
        shown = f.other[:6]
        more = f" … +{len(f.other) - 6}" if len(f.other) > 6 else ""
        out.append(f"{ind}- other: {', '.join(shown)}{more}")


def adopt(case: Path, fallback: Dict[str, str]) -> List[str]:
    """Write `summary: <description>` into files that lack one, taking the text the agent had
    written for them in README Links. Returns the files changed."""
    changed = []
    for rel, desc in fallback.items():
        p = case / rel
        if rel.startswith("phases/") or not p.is_file() or read_summary(p):
            continue  # a phase file describes itself by goal:/result: (F12) — never touched
        lines = p.read_text(encoding="utf-8").split("\n")
        at = next((i + 1 for i, ln in enumerate(lines[:SUMMARY_SCAN_LINES]) if ln.startswith("# ")), 0)
        lines.insert(at, f"summary: {_short(desc, SUMMARY_CHARS)}")
        p.write_text("\n".join(lines), encoding="utf-8")
        changed.append(rel)
    return changed


# ---- duplicates and budgets (F15) ---------------------------------------------------------------
def _shingles(path: Path) -> set:
    """Word 3-grams of a file, lowercased. Shared vocabulary is not shared text; shared phrasing is."""
    try:
        toks = [w.lower() for w in TOKEN_RE.findall(path.read_text(encoding="utf-8", errors="ignore"))]
    except OSError:
        return set()
    return set(tuple(toks[i:i + SHINGLE_WORDS]) for i in range(len(toks) - SHINGLE_WORDS + 1))


def duplicates(folders: List[Folder]) -> List[Tuple[str, str, float]]:
    """(smaller file, other file, share of the smaller file's phrasing found verbatim in the other)."""
    docs = [d for f in folders if f.name != "phases" for d in f.all_docs()]
    shingles = {d.rel: _shingles(d.path) for d in docs}
    pairs = []
    for i, a in enumerate(docs):
        for b in docs[i + 1:]:
            sa, sb = shingles[a.rel], shingles[b.rel]
            if len(sa) < DUP_MIN_SHINGLES or len(sb) < DUP_MIN_SHINGLES:
                continue
            small, other = (a, b) if len(sa) <= len(sb) else (b, a)
            share = len(sa & sb) / min(len(sa), len(sb))
            if share >= DUP_SHARE:
                pairs.append((small.rel, other.rel, share))
    return sorted(pairs, key=lambda x: -x[2])


def budgets(folders: List[Folder]) -> List[str]:
    """A file over its budget is named. A folder total is not (dropped in 0.11): a byte count cannot
    tell deliverables from water — a live case 2026-09-03: a folder over the limit held only working
    documents, nothing stale — and a line that can only be closed by deleting good work teaches to skip Order."""
    out = []
    for f in folders:
        if f.name == "phases":
            continue
        for d in f.all_docs():
            if d.bytes > FILE_WARN_BYTES:
                out.append(f"{d.rel} is {-(-d.bytes // 1024)} KB (limit {FILE_WARN_BYTES // 1024}) → split by summary or trim")
    return out


# ---- State staleness (S5) -----------------------------------------------------------------------
def anchor(readme_body: str):
    """(date, time, phase|None, events|None) from the `as of` line; None when the State has none."""
    m = STATE_ANCHOR_RE.search(readme_body)
    if not m:
        return None
    return (m.group(1), m.group(2), m.group(3), int(m.group(4)) if m.group(4) else None)


def stale(journal: grammar.Journal, key) -> Tuple[int, int, int]:
    """(entries touched after the anchor, RESULT events among them, PHASE events among them).

    Position, not time: `log` appends to the newest entry when the minute and phase repeat, so the
    anchor names the entry AND how many events it had. Entries above it are newer; events past the
    count inside it are newer too. A legacy anchor without a count falls back to the time key.
    """
    if key is None:
        return 0, 0, 0
    date, time, phase, count = key
    new_events = []
    touched = 0
    idx = next((i for i, e in enumerate(journal.entries)
                if (e.date, e.time) == (date, time) and (phase is None or e.phase == phase)), None)
    if idx is None:
        for e in journal.entries:
            if (e.date, e.time) > (date, time):
                touched += 1
                new_events.extend(e.events)
    else:
        for e in journal.entries[:idx]:
            touched += 1
            new_events.extend(e.events)
        if count is not None and len(journal.entries[idx].events) > count:
            touched += 1
            new_events.extend(journal.entries[idx].events[count:])
    r = sum(1 for ev in new_events if ev.type == "RESULT")
    p = sum(1 for ev in new_events if ev.type == "PHASE")
    return touched, r, p


def newest_header(journal: grammar.Journal) -> Optional[str]:
    """The anchor text for State: the newest entry's header plus its event count."""
    if not journal.entries:
        return None
    e = journal.entries[0]
    n = len(e.events)
    return f"{e.date} {e.time} · {e.phase} ({n} event{'' if n == 1 else 's'})"


# ---- broken links: a link that points at nothing is a map that lies ---------------------------------
def broken_links(case: Path, folders: List[Folder], readme_body: str, todo_body: str) -> List[Tuple[str, str]]:
    """(file, target) for every relative markdown link whose target does not exist — in README and
    TODO bodies, the phase files and the content folders. The journal is history and is not checked;
    a moved file keeps its links alive through `mike mv` (feedback 2026-09-03)."""
    out: List[Tuple[str, str]] = []

    def scan(rel: str, text: str, base: Path):
        text = "".join(seg if not code else " " * len(seg) for seg, code in outside_code(text))
        for m in LINK_RE.finditer(text):
            target = m.group(2)
            if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
                continue
            path = target.partition("#")[0]
            if path and not (base / path).exists():
                out.append((rel, path))

    scan("README.md", readme_body, case)
    scan("TODO.md", todo_body, case)
    ph = phases_folder(case)
    docs = [d for f in folders for d in f.all_docs()] + (ph.docs if ph else [])
    for d in docs:
        try:
            scan(d.rel, d.path.read_text(encoding="utf-8", errors="ignore"), d.path.parent)
        except OSError:
            continue
    return out


# ---- unreferenced: nothing in the work points at it (F21) -----------------------------------------
UNREF_SKIP = {"archive", "legacy"}


BARE_MD_RE = re.compile(r"(?<![\w/(])((?:[\w.-]+/)+[\w.-]+\.md)\b")


def _link_targets(text: str, base: Path, case: Optional[Path] = None) -> List[Path]:
    """Resolved targets `text` points at: markdown links (relative to the file), plus bare paths to
    `.md` files (`research/survey.md`, also in backticks) — that is how agents and closed phase lines
    cite files, and a citation is a reference. Fenced code blocks are examples, not references."""
    out = []
    text = "".join(seg if not (code and seg.startswith("```")) else " " * len(seg) for seg, code in outside_code(text))
    for m in LINK_RE.finditer(text):
        target = m.group(2)
        if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
            continue
        path = target.partition("#")[0]
        if path:
            out.append((base / path).resolve())
    for m in BARE_MD_RE.finditer(text):
        out.append((base / m.group(1)).resolve())
        if case is not None:
            out.append((case / m.group(1)).resolve())  # bare paths are case-relative by convention
    return out


def unreferenced(case: Path, folders: List[Folder], readme_body: str, todo_body: str,
                 journal: Optional[grammar.Journal]) -> List[str]:
    """Documents nothing in the work points at (F21). Roots: the hand-written README lines (the
    rendered Links lines are the index, not a reference), the TODO, the phase files, and the
    RESULT/DECISION events of the journal (evidence keeps its material alive — a Codex finding).
    Live = reachable from the roots through links, transitively through documents. `archive/` and
    `legacy/` are never named: parking is the agent's honest answer to "nothing uses this"."""
    docs = {}
    for f in folders:
        if f.name.split("/")[0] in UNREF_SKIP:
            continue
        for d in f.all_docs():
            if d.rel.split("/")[0] in UNREF_SKIP or "/archive/" in f"/{d.rel}":
                continue
            docs[d.path.resolve()] = d
    if not docs:
        return []
    roots: List[Tuple[str, Path]] = []
    manual_readme = "\n".join(ln for ln in readme_body.split("\n") if not ln.startswith("  ") and not ln.startswith("- cases: "))
    roots.append((manual_readme, case))
    roots.append((todo_body, case))
    ph = phases_folder(case)
    if ph:
        for d in ph.docs:
            try:
                roots.append((d.path.read_text(encoding="utf-8", errors="ignore"), d.path.parent))
            except OSError:
                continue
    if journal is not None:
        evidence = "\n".join(ev.text + "\n" + "\n".join(ev.body) for e in journal.entries for ev in e.events
                             if ev.type in ("RESULT", "DECISION"))
        roots.append((evidence, case))
    live: set = set()
    frontier: List[Path] = []
    for text, base in roots:
        for t in _link_targets(text, base, case):
            if t in docs and t not in live:
                live.add(t)
                frontier.append(t)
    while frontier:  # a document that is alive keeps alive what it links to
        p = frontier.pop()
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for t in _link_targets(text, p.parent, case):
            if t in docs and t not in live:
                live.add(t)
                frontier.append(t)
    return [d.rel for p, d in sorted(docs.items(), key=lambda kv: kv[1].rel) if p not in live]


# ---- the report shown on every entry (P12) ------------------------------------------------------
def report(case: Path, root_mode: bool, readme_body: str, journal: Optional[grammar.Journal],
           links_lines: List[str], link_violations: Optional[list] = None) -> List[str]:
    """Lines for the `## Order` block: each one names what is out of order and the command that
    puts it back. Empty list = everything in place. With `link_violations` (a list), broken links
    in README/TODO are collected there for `check` to report as violations (F16) instead."""
    out: List[str] = []
    described: Dict[str, str] = {}
    for ln in links_lines:
        m = FOLDER_LINE_RE.match(ln)
        if m:
            described[m.group(1)] = (m.group(2) or "").strip()
    listed = set(described)
    folders = content_folders(case, root_mode, listed)
    closed = re.search(r"^- closed: ", readme_body, re.M) is not None
    if journal is not None and not closed:  # a closed case has no "now" to keep current
        key = anchor(readme_body)
        if key is None:
            if any(ev.type in ("RESULT", "PHASE") for e in journal.entries for ev in e.events):
                out.append("State has no `as of` anchor → rewrite it once: mike readme set next \"…\" (sets the anchor)")
        else:
            n, r, p = stale(journal, key)
            if r or p:
                out.append(f"State is behind: {n} journal entr{'y' if n == 1 else 'ies'} touched since as of {key[0]} {key[1]} "
                           f"({r} RESULT, {p} PHASE) → mike readme set next \"…\" · or mike readme --file README.md")
    missing = [d.rel for f in folders for d in f.all_docs() if not d.summary]
    if missing:
        shown = ", ".join(missing[:4]) + (f" … +{len(missing) - 4}" if len(missing) > 4 else "")
        out.append(f"{len(missing)} file(s) without `summary:` — {shown} → add `summary: one line` as line 2, "
                   f"or mike order --adopt (takes the descriptions from Links)")
    for f in folders:
        desc = described.get(f.name, "")
        if not desc or desc.startswith(PLACEHOLDER_FOLDER):
            out.append(f"folder {f.name}/ has no description → mike readme add links \"{f.name}/ — что здесь\"")
    for k in child_cases(case, root_mode):
        if child_status(k)[0] == "broken":
            out.append(f"nested case {k.name}: README unparsable — it holds this case open (F18) → mike --case {k.name} check")
    for small, other, share in duplicates(folders):
        out.append(f"{small} ≈ {other}: {int(share * 100)} % of {small.rsplit('/', 1)[-1]}'s text is verbatim in "
                   f"{other.rsplit('/', 1)[-1]} → say the difference in each summary, or merge")
    out.extend(budgets(folders))
    try:
        from . import store, stamp  # local: store imports order for the README render
        todo_body = stamp.split(store.read(case, "TODO.md"))[0]
    except Exception:  # noqa: BLE001 — no TODO, no links to check there
        todo_body = ""
    dead = unreferenced(case, folders, readme_body, todo_body, journal)
    if dead:
        shown = ", ".join(dead[:4]) + (f" … +{len(dead) - 4}" if len(dead) > 4 else "")
        out.append(f"{len(dead)} file(s) nothing in the work points at — {shown} → link it from an item, a phase file or a "
                   f"decision · park it: mike mv <file> archive/ · or delete it (F21)")
    broken = broken_links(case, folders, readme_body, todo_body)
    if link_violations is not None:
        link_violations.extend((f, t) for f, t in broken if f in ("README.md", "TODO.md"))
        broken = [(f, t) for f, t in broken if f not in ("README.md", "TODO.md")]
    if broken:
        shown = ", ".join(f"{f} → {t}" for f, t in broken[:4]) + (f" … +{len(broken) - 4}" if len(broken) > 4 else "")
        out.append(f"{len(broken)} broken link(s): {shown} → fix the link, or move files with `mike mv old new` (links follow)")
    return out
