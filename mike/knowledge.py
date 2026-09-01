"""Knowledge doses for `mike help <topic>` — the manual lives inside the tool.

Each topic is one screen the agent opens at the moment of need, instead of reading everything
up front. Sourced from .cases/RULES.md of the mike-cli repo; keep both in sync when rules change.
"""

TOPICS = {
    "start": """a day with mike
1. `mike` — prints the case in hand: README (the "now"), TODO (phases), last journal entries,
   other open cases. Read this, nothing else, and continue from "next step".
2. Work as usual. When something is worth remembering — `mike log <TYPE> "…"`.
3. Stuck? First search the knowledge base: grep -ril "<error words>" .howto/ — maybe it is solved.
   Solved a problem yourself → `mike log PROBLEM "problem → root cause → fix"` AND write a recipe
   file into .howto/ (first line `when: <error words>`).
4. Finished a piece → `mike todo done N.M`; a phase → `mike help phases`; the case → `mike done "…"`.
5. Never edit README.md / TODO.md / JOURNAL.md by hand — mike is the only write door; hand edits
   are detected by the stamp and moved aside.""",

    "files": """three files per case + folders by content
- README.md — the "now": Context (goal in the owner's words) · State (progress, last result, next
  step, what we wait for) · Decisions · Problems (open only) · Links. Always current, stale lines
  are removed, not kept. Written via `mike readme`.
- TODO.md — phases only: `- [ ] N Name` with items `N.M`; a closed phase collapses to one summary
  line. Written via `mike todo` / `mike phase`.
- JOURNAL.md — history, newest on top, a report for the owner who was not in the session. Written
  via `mike log`.
- Everything else lives in folders by KIND of content: phases/ research/ scripts/ docs/ logs/
  meetings/ data/ … (English lowercase names, created with their first file, each one gets a line
  in README Links). Recipes are NOT per-case: they go to the project-root .howto/.""",

    "journal": """journal events — `mike log <TYPE> "text"`
Types: PHASE (phase opened/closed, with outcome) · DECISION (chose X over Y, why) ·
PROBLEM (problem → root cause → fix) · RESULT (measurement, number, verdict — in plain words).
- An event is something that changes what the next reader should know. Actions (read a file, ran
  a command, edited a line) are NOT events — git holds those.
- Every phase needs at least one RESULT before it can close.
- No open phase? The entry lands in p0 — the case-level lane (gathering info, talking it over).
- `--phase p1`, `--phase 1` or a unique phase name select the phase explicitly.
- Long text is split automatically into a headline + body lines; keep headlines meaningful.""",

    "phases": """phases — `mike phase open|close N "Name"`
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
- received a file / doc / log / meeting → a case folder by kind + a line in README Links
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
Why limits exist: they keep the entry screen readable and squeeze water out — the detail belongs
in phase files and folders, pointers belong in README.""",

    "errors": """exit codes and what to do
0 — done. 1 — internal error. 2 — wrong usage (the message shows the correct form).
3 — rule violation: the write was REFUSED, no file was touched; fix the input as the message says.
4 — precondition not met: no .cases/ from here upwards · every case closed · a case file missing ·
    a phase not ready to open/close. The message names the check and a recovery command.
Diagnostics without any writes: `mike doctor`. Facts that save an investigation:
- mike never reads or writes AGENTS.md / CLAUDE.md — they only point at mike;
- mike never changes your shell's cwd (a child process cannot);
- errors go to stderr; the bare `mike` entry also mirrors them to stdout.""",
}


def topic_list() -> str:
    return " · ".join(sorted(TOPICS))
