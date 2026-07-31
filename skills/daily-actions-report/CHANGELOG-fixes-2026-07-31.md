
# Skill fixes — 2026-07-31

A routine daily run (in a fresh, sandboxed Cowork session — no prior local
state) surfaced two structural gaps that the 2026-07-29 hardening pass didn't
cover. Neither is a data/classification bug like 2026-07-29's; both are
"the skill can't write where it thinks it can" problems, one already
partially solved (context storage) and one not, until now (script output
files). Both are fixed in this release (`SKILL_VERSION` bumped to 2.1.1 in
all three scripts). Nóra is out on PTO starting the Monday after this run, so
this file — plus the inline notes in SKILL.md — exists so the next person
who runs this doesn't need to rediscover either problem, and so the fixes
themselves are documented for anyone who wants to verify them.

## 1. `assemble_slack_data.py`'s section-parser never got the 2026-07-29 blank-line fix — FIXED

**Symptom:** both Slack candidate threads this run ("Do we have rules on
choosing the value for ERCs?", 19 replies; "PR review request", 5 replies)
were initially classified as **unanswered**, even though real team members
(Pablo Agulla, Carlos Correa García) had clearly replied in both. The script
printed a warning (`No '## Team Slack Names' section found`) but did not
hard-fail, so this could easily have gone unnoticed and shipped two false
"needs owner" rows.

**Root cause:** `CHANGELOG-fixes-2026-07-29.md` (fix #1) patched
`load_sprint_context()` inside `headless_daily_report.py` so a blank line
between a `## Section Name` heading and its ` ```json ` fence no longer
breaks parsing — Confluence's markdown round-trip introduces exactly this
blank line as a matter of course. `assemble_slack_data.py` has its **own**,
independently-implemented copy of this parsing logic
(`_read_md_json_section()`, deliberately duplicated rather than imported —
see the comment above it), and that copy was never updated. Its regex is
still the old, strict form:

```python
r"^## " + re.escape(section_name) + r"\n```json\n(.*?)```"
```

— a literal single `\n`, zero tolerance for a blank line. Since the shared
context page had just come back through a `getConfluencePage` →
`updateConfluencePage` round trip (same as every run), every section in
`context_scratch.md` had a blank line after its heading, and
`_read_md_json_section("Team Slack Names")` returned `None` for a page that
plainly had a populated roster. Every reply in both threads was then
treated as a stranger, and 19+5 real replies were not enough to mark either
thread "answered."

**This run's workaround (data-side, not code-side):** stripped the blank
line after every `## Section Name` heading in `context_scratch.md` by hand
before calling `assemble_slack_data.py classify` (`re.sub(r'(^## .+\n)\n(```json)', r'\1\2', text, flags=re.MULTILINE)`). Re-ran classify after —
both threads correctly flipped to "answered." This is a per-run patch, not a
fix; the next run will hit the exact same bug the moment the context page
round-trips through Confluence again, which is every run.

**Fix applied (2.1.1):** the identical one-line change 2026-07-29 already
made in `headless_daily_report.py`'s `load_sprint_context()`, applied to both
the read and write regexes in `assemble_slack_data.py` (lines ~115 and ~130):

```python
# _read_md_json_section() and _write_md_json_section(), both occurrences:
- r"^## " + re.escape(section_name) + r"\n```json\n"
+ r"^## " + re.escape(section_name) + r"\n+```json\n"
```

**Verified:** re-ran `assemble_slack_data.py classify` (v2.1.1) against a
deliberately blank-line-corrupted copy of today's `context_scratch.md`
(reproducing the exact Confluence round-trip condition that broke this) —
both threads correctly classified as answered, no roster warning. The
`⚠ No '## Team Slack Names' section found` / `⚠ Team roster is empty`
warnings should no longer fire on a page with a genuinely populated roster;
if they do, the roster section itself is missing or malformed beyond a
blank line, not this bug recurring.

## 2. `headless_daily_report.py`'s default output directory is the skill's own (often read-only) folder — FIXED

**Symptom:** both the plain preview run and `--publish` failed with
`OSError: [Errno 30] Read-only file system` trying to write
`daily_actions_report_<date>.html` (and later `adf_output.json`,
`publish_adf_loader.js`, `publish_snippet.js`,
`publish_<sprint>_console.js`).

**Root cause:** `OUTPUT_DIR = Path(__file__).parent` (line ~100) — every
output file the script produces is written next to `headless_daily_report.py`
itself, i.e. inside `SKILL_DIR`. That's fine on a machine where the skill was
installed by the same user who has write access to that folder. It is **not**
fine in a Cowork session, where the skill folder is a read-only mounted
cache (see the skill-instructions note: "Skill files at `<location>` are a
read-only cache — editing them does not change the user's saved skill").
This is the exact same class of problem that motivated the 2026-07-28
Shared Context Storage migration (`CHANGELOG.md` 2.0.0) — except that change
only moved the run-to-run *cache/roster data* onto Confluence. The *output
files* (HTML preview, ADF, publish snippets) were never touched and still
default to a location that doesn't exist as writable in exactly the
environment the 2.0.0 migration was built for.

**This run's workaround:** copied the entire skill folder (all `.py`/`.md`
files) into a writable scratch directory and ran `headless_daily_report.py`
from there instead of from the mounted skill path. The script's logic is
unmodified — it just needed a writable `__file__.parent` to exist. This adds
an extra step every run and is easy to forget (the first attempt at
`--publish` failed and had to be redone after the copy).

**Fix applied (2.1.1):** new `--output-dir` CLI flag, independent of
`--sprint-context-file`, defaulting to the old `OUTPUT_DIR` behavior for
backward compatibility but overridable:

```python
parser.add_argument("--output-dir", default=None, metavar="PATH",
                     help="Where to write daily_actions_report_*.html, "
                          "adf_output.json, and the publish_*.js files. "
                          "Defaults to OUTPUT_DIR (the skill's own folder), "
                          "which is read-only in sandboxed/Cowork sessions — "
                          "pass a writable path there instead.")
...
# applied right after argparse, before OUTPUT_DIR is read anywhere else:
if args.output_dir:
    global OUTPUT_DIR
    OUTPUT_DIR = Path(args.output_dir)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
```

**Verified:** ran the full pipeline (`--jira-data-file`, `--pr-data-file`,
`--slack-data-file`, `--sprint-context-file` pointed at today's real data)
directly from the skill's own read-only-mounted folder, with only
`--output-dir` pointed at a writable scratch path — completed successfully,
`daily_actions_report_2026-07-31.html` landed in the writable path, nothing
was written to (or attempted against) the read-only skill folder. The
"copy the whole skill folder to a writable scratch directory" workaround is
no longer needed for any of preview, `--publish`, or `--confirm-publish`.

## Files touched
- `assemble_slack_data.py`: `_read_md_json_section()` and
  `_write_md_json_section()` regexes (`\n` → `\n+`); `SKILL_VERSION` bump
  to 2.1.1.
- `headless_daily_report.py`: new `--output-dir` argument; `OUTPUT_DIR`
  override applied right after `argparse`; `SKILL_VERSION` bump to 2.1.1.
- `assemble_jira_data.py`: `SKILL_VERSION` bump to 2.1.1 (lockstep only, no
  functional change — this script was never affected by either bug).
- `SKILL.md`: Configuration and Shared Context Storage/Slack Needs Owner
  sections updated from "known issue, not yet fixed" to describe the 2.1.1
  fixes and the new `--output-dir` usage; version line bumped to 2.1.1.
- `CHANGELOG.md`: "Known issues — 2.1.0" entry replaced with a proper
  "2.1.1 — 2026-07-31" version entry.
- This file: updated from "fix needed" to "fix applied," with verification
  notes for both.
