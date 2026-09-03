"""Knowledge doses for `mike help <topic>` — the manual lives inside the tool.

Each topic is one screen the agent opens at the moment of need, instead of reading everything
up front. Sourced from .cases/RULES.md of the mike-cli repo; keep both in sync when rules change.
"""

ONBOARDING = """start here — no `.cases/` from this folder upwards
  mike case new "name" --goal "goal in the owner's words"        a case folder under .cases/
  mike case new --root "name" --goal "…"                          or: this folder IS the project (root mode)
then: `mike` shows where the case stands · `mike help start` — how a day goes · `mike help where` — what goes where"""

TOPICS = {
    "start": """a day with mike
1. `mike` — prints the case in hand: README (the "now"), TODO (phases), journal headlines, and the
   `## Order` block: what is out of order and the command that fixes each line. Read this, nothing
   else; first say in your own words where the case stands and what the next step is — then go.
2. Work as usual. When something is worth remembering — `mike log <TYPE> "…"`.
3. Every new file in docs/ research/ … starts with `summary: <one line>` right under its title —
   README Links is rendered from those lines, so the map never rots (F14).
4. Stuck? First search the knowledge base: grep -ril "<error words>" .howto/ — maybe it is solved.
   Solved a problem yourself → `mike log PROBLEM "problem → root cause → fix"` AND write a recipe
   file into .howto/ (first line `when: <error words>`).
5. Finished a piece → `mike todo done N.M`; a phase → `mike help phases`; the case → `mike done "…"`.
6. Before you stop: `mike` again — if Order says "State is behind", rewrite State
   (`mike readme set next "…"` or `mike readme --file`). The next session starts from that line.
7. Never edit README.md / TODO.md / JOURNAL.md by hand — mike is the only write door; hand edits
   are detected by the stamp and moved aside.""",

    "order": """order — the case keeps itself tidy (F14, F15, S5, P12)
Every `mike` entry ends with `## Order`: each line = one thing out of place + the command that fixes it.
- files without `summary:` → add `summary: one line` as line 2 of the file (under its title);
  descriptions already written in README Links → `mike order --adopt` moves them into the files.
- folder without a description → `mike readme add links "docs/ — что здесь"` (the folder line is
  yours; the file lines under it are rendered by mike from the summaries).
- two files sharing their text (≥ 50 % of the smaller one's phrasing appears verbatim in the other)
  → say the difference in each summary, or merge. Shared vocabulary is not shared text: two
  documents about one call share the names and dates and stay two documents.
- a file over 24 KB of markdown → split by summary or trim. There is no folder total: a byte
  count cannot tell eight deliverables from water.
- State is behind → RESULT/PHASE events were logged after `as of` → rewrite State.
Nothing here is refused (mike does not write those files); it is shown on every entry until fixed.
Why: a limit on README alone pushed the water one layer down — new files were cheap, merging never
happened. Now the lower layer is visible from the top, and the top is rendered from it.""",

    "files": """three files per case + folders by content
- README.md — the "now": Context (goal in the owner's words) · State (progress, last result, next
  step, what we wait for) · Decisions · Problems (open only) · Links. Always current, stale lines
  are removed, not kept. Written via `mike readme`.
- TODO.md — phases only: `- [ ] N Name` with items `N.M`; a closed phase collapses to one summary
  line. Written via `mike todo` / `mike phase`.
- JOURNAL.md — history, newest on top, a report for the owner who was not in the session. Written
  via `mike log`.
- Everything else lives in folders by KIND of content: phases/ research/ scripts/ docs/ logs/
  meetings/ data/ … (English lowercase names, created with their first file). Each .md file there
  starts with `summary: <one line>` under its title (F14); README Links is rendered by mike: your
  folder line (`- docs/ — что здесь`) with the files nested under it, described by their summaries.
  Recipes are NOT per-case: they go to the project-root .howto/.
- README State carries lines mike owns: `progress:` (from TODO), `last:` (newest RESULT),
  `as of:` (the journal entry State was last rewritten against, S5). Yours: next, ждёт, срок …""",

    "journal": """journal events — `mike log <TYPE> "text"`
Types: PHASE (phase opened/closed, with outcome) · DECISION (chose X over Y, why) ·
PROBLEM (problem → root cause → fix) · RESULT (measurement, number, verdict — in plain words).
- An event is something that changes what the next reader should know. Actions (read a file, ran
  a command, edited a line, moved a TODO item) are NOT events — git holds those; mike itself
  writes none since 0.9 (a decision behind an edit → `mike log DECISION` yourself).
- Every phase needs at least one RESULT before it can close.
- No open phase? The entry lands in p0 — the case-level lane (gathering info, talking it over).
- `--phase p1`, `--phase 1` or a unique phase name select the phase explicitly.
- Long text is split automatically into a headline + body lines; keep headlines meaningful.""",

    "phases": """phases — `mike phase plan|open|close N "Name"`
- plan: `mike phase plan 3 "Council" --goal "one line"` — names the NEXT phase while the current one
  runs: a `- [ ] 3 Council — intent` line in TODO, no phase file, no journal event. Park its items
  there now (`mike todo add 3 "…"`); it opens later with `mike phase open 3` (name and goal come
  from the plan). One phase in flight stays the rule: planned is not open.
- open: `mike phase open 2 "Server database" --goal "one line"` — creates phases/2-server-database.md
  (goal:/result: header + free body for details, dead ends, drafts). Name: English, 1–3 words.
- while it runs: items live in TODO (`mike todo add 2 "…"`, `mike todo done 2.1`), the story lives
  in the phase file. TODO holds WHAT, the phase file holds HOW and WHY.
- close: needs in the journal — a RESULT for pN, `DECISION · reflect: <lesson about the process>`
  and `DECISION · align: <next phase re-planned with what we now know>`. Then
  `mike phase close 2 "what it delivered"` fills result:, collapses TODO, updates README State.
- the next phase will not open until the previous one passed all of the above.""",

    "cases": """cases — units of work longer than a session
- `mike case new "name" --goal "…"` — new case folder .cases/YYYY-MM-DD-name/ with the three files.
- `mike case list` — every case, current marked *; `mike case use <name>` — switch the hand.
- The hand follows the freshest journal; one agent works one case at a time.
- Rule of nesting: know what to do → an item N.M; do NOT know the cause / needs its own research /
  longer than a session → `mike spawn "name" --goal "…"` — a nested case of the same shape inside
  the parent. The parent shows one `waits:` line; `mike done "outcome"` in the child writes one
  summary line back and returns the hand.
- `mike done "outcome"` closes the case (all phases must be closed first).
- Root mode: `mike case new --root "my app" --goal "…"` makes the PROJECT FOLDER itself the top
  case (README/TODO/JOURNAL in the project root; refused if a README.md already exists there).
  Feature cases live in .cases/ as usual and report their outcome back to the project on `done`.""",

    "where": """what goes where
- read / ran / edited a line            → nowhere, git holds it
- fact needed to continue the case      → README State or Decisions (via `mike readme`)
- solved a problem                      → `mike log PROBLEM` + a recipe in .howto/ (when: line)
- a way to do a frequent operation      → .howto/<task-verb>.md; its script → scripts/
- received a file / doc / log / meeting → a case folder by kind, `summary:` as its line 2;
                                          Links picks it up by itself (folder line is yours)
- two files sharing their text (Order names them) → say the difference in each summary, or merge
- finished for today                     → `mike` → Order says "State is behind"? rewrite State
- closed a phase                        → `mike phase close N "…"` (does TODO+journal+README itself)
- took a measurement                    → `mike log RESULT "…"` + the number in README State
- cause unknown or work too big         → `mike spawn` — a nested case
- mike itself misbehaves                → `mike feedback "title" --actual … --expected …`""",

    "stamp": """stamp — the write-door fingerprint
- The last line of the three files is `stamp: <hash>` over everything above it. Only mike writes it.
- A hand edit makes the stamp mismatch. On the next mike write the file is re-parsed: valid lines
  stay, invalid ones move to <FILE>.recover.md, the write proceeds with a warning.
- If a *.recover.md exists: re-enter its lines through mike commands, then `rm` the file (the
  warning prints the exact command). Data is never lost silently.""",

    "feedback": """reporting a mike problem or wish
`mike feedback "short title" --actual "what happened" --expected "what should happen"`
optional: --repro "commands" --why "…" --acceptance "…"
The artifact lands in the mike-cli clone's feedback/ pool (travels with git) and the path is
printed. Title + --actual + --expected are required; nothing from your environment is included.""",
    "limits": """the numbers (all enforced at write time)
README: 200 lines / 8 KB → warning · 300 lines / 12 KB → refusal; pointer line ≤ 150 chars (warning).
TODO: ≤ 100 lines; item text ≤ 80 VISIBLE chars — markdown links [name](path) count as `name`
  (a refusal prints a ready trimmed suggestion);
  phase name — English, 1–3 words; no items deeper than N.M.
JOURNAL: event headline ≤ 200 chars (soft 180); long text splits automatically into headline +
  up to 5 body lines of ≤ 160 chars; body beyond that → put the story in the phase file.
Lower layer (shown, not refused): file `summary:` ≤ 120 chars; a file over 24 KB → split by summary
  or trim; two files where ≥ 50 % of the smaller one's phrasing is verbatim in the other → duplicate.
  No folder total (dropped in 0.11): a byte count cannot tell deliverables from water.
Why limits exist: they keep the entry screen readable and squeeze water out — the detail belongs
in phase files and folders, pointers belong in README. A limit on the top layer alone moves the
water one layer down — that is why the lower layer has a budget too (F15).""",

    "migrate": """migrate — a legacy case into mike's grammar (P13)
A legacy file = README/TODO/JOURNAL that mike never stamped and the grammar rejects (written
before mike, or by hand since). Every write into it is refused — rebuilding by grammar (S4)
would move most of it into .recover.md, and that is not migration.
- `mike migrate` — dry run: which files are legacy, what maps where, what stays in the archive
  for review. Changes nothing.
- `mike migrate --apply` — copies the legacy files byte-for-byte into legacy/<date-time>/ (verified),
  then writes the canonical files atomically; any failure puts the archive back.
What maps: README sections by name (goal/context/summary → Context; decisions; problems/risks/
open → Problems; links) · TODO headings → phases (English 1–3 words, else `Legacy N`), checkbox
lines → items (long ones trimmed; a phase with all items done is closed, its phase file says
`migrated from legacy` and P8 gates skip it) · JOURNAL → not converted: guessing types would be
lying; the new journal opens with one PHASE event pointing at the archive — re-enter what still
matters with `mike log`.
After apply: `mike` (Order shows what to rewrite), `mike readme set next "…"`, `mike check`.""",

    "errors": """exit codes and what to do
0 — done. 1 — internal error. 2 — wrong usage (the message shows the correct form).
3 — rule violation: the write was REFUSED, no file was touched; fix the input as the message says.
    "outside mike's grammar and was never stamped" = a legacy file → `mike migrate` (see `mike help migrate`).
4 — precondition not met: no .cases/ from here upwards · every case closed · a case file missing ·
    a phase not ready to open/close. The message names the check and a recovery command.
Diagnostics without any writes: `mike doctor`. Facts that save an investigation:
- mike never reads or writes AGENTS.md / CLAUDE.md — they only point at mike;
- mike never changes your shell's cwd (a child process cannot);
- errors go to stderr; the bare `mike` entry also mirrors them to stdout.""",
}


def topic_list() -> str:
    return " · ".join(sorted(TOPICS))
