# Skill change — 2026-07-09 (Slack Needs Owner)

## 1. New feature: unanswered Slack questions surface at the top of Needs Owner

**Requested by Nóra:** the public `#t-dxp-headless` channel
(`https://liferay.slack.com/archives/C5E1CRLJY`) gets ad-hoc questions from
outside the team, often with no reply from anyone on Headless. Add these to
the top of the "Pick up next → Needs Owner" section: title + Slack link.

**Why Chrome MCP instead of a Slack connector:** the org has not approved the
Slack connector for this workspace (`plugin:engineering:slack` requires
authorization that could not be granted). Chrome MCP against
`app.slack.com` in the user's already-authenticated browser was verified
live against the real channel as a working substitute — the same
scrape-in-the-user's-browser pattern this skill already uses for GitHub PRs.

**Design constraint (per Nóra, 2026-07-09): minimize prose steps, maximize
Python.** Earlier iterations of this skill's Workflow section have caused
unreliable runs when they asked Claude to make multi-step judgment calls in
prose. Every decision for this feature — lookback window, date parsing,
reply-author-vs-roster matching, sort order, dismiss persistence — lives in
a new standalone script, `assemble_slack_data.py`. Claude's own steps are
reduced to two mechanical scrapes (see SKILL.md → "Slack Needs Owner").

### New file: `assemble_slack_data.py`

Three subcommands:
- `scan` — parses a raw `get_page_text` dump of the channel's message list
  into candidate `[Title]` threads inside a lookback window (default 7
  days, `--window-days`). Only messages whose first content line is a
  bracketed title count — plain bot-relay messages are ignored. Threads
  with zero replies are recognised directly from the channel dump (no need
  to open them) and are unanswered by definition.
- `classify` — joins per-thread reply scrapes (Claude opens each candidate
  with `reply_count > 0` and appends a JSON record) back onto the scan
  candidates by title, extracts each reply's author (skipping the
  restated parent message and same-author continuation lines with no
  repeated name+timestamp header), checks authors against the roster in
  `project_current_sprint.md`'s new `Team Slack Names` section, applies any
  `dismissed` overrides, sorts unanswered threads oldest-first, writes
  `slack_data.json`, and rewrites the `Slack Thread Snapshot` section of
  `project_current_sprint.md` in place. Hard-fails if a candidate with
  replies is missing its detail record, rather than silently
  under-reporting.
- `dismiss --title-contains "..."` — marks one tracked thread hidden
  (handled outside Slack, never got an in-thread reply). Clears
  automatically the next time that thread's reply count changes.

Mirrors `assemble_jira_data.py`'s standalone-script, hard-stop-on-bad-data
style deliberately — no import of `headless_daily_report.py`, so it stays
runnable and testable on its own.

### `project_current_sprint.md` — two new sections

- `## Team Slack Names` — `{display name: Slack display name}`, mirroring
  the existing `Team GitHub Logins` pattern. **This run also corrected the
  underlying roster per Nóra**: added Adolfo Pérez (Staff Software
  Engineer), removed Uge Ortiz Castilla, Bruno Fernández González, and
  Pablo Agulla (no longer on the team).
- `## Slack Thread Snapshot` — `{date, channel_id, channel_name, threads}`,
  the dismiss/audit cache `assemble_slack_data.py` reads and writes.

### `headless_daily_report.py` — new "slack" row type, nothing else moved

- `--slack-data-file PATH` (optional — omitting it just means no Slack rows,
  same graceful degradation as `--no-github`).
- `load_slack_data()` mirrors `load_jira_data()`'s never-crash style.
- `SprintContext` gained `slack_snapshot` (round-tripped through
  `load_sprint_context()` / `save_sprint_context()`, same pattern as
  `pr_snapshot`) and `team_slack_names` (parsed for consistency; the actual
  roster check happens in `assemble_slack_data.py`, which runs standalone).
- `TIER_COLORS["SLACK"]` / `_HTML_TIER_COLORS["SLACK"]` (purple) alongside
  the existing `"PR"` entries.
- `build_slack_cell()` — inlineCard on the Slack permalink, same structural
  requirement `validate_adf()` already enforces for issue/PR cells. The
  human-readable title goes in the Topic cell instead, since Confluence
  cannot be assumed to unfurl a Slack URL into a rich preview the way it
  does Jira/GitHub links.
- `_build_data_row()` / `_html_section_table()` — new `type == "slack"`
  branch in both the ADF and HTML renderers.
- New `section2b_slack_rows` list, built directly from `slack_threads`
  (already fully classified — no owner logic here), sorted oldest-first,
  and **prepended** ahead of `section2b_pr_rows` + `section2b_issue_rows`:
  unanswered Slack questions sit above even cross-team PR flags at the top
  of "2a. Needs Owner" (internal name `section2b` — see the existing
  2026-07-08 label-swap note in `build_adf_document()`'s docstring; nothing
  about that swap changed here).
- `update_caches()` needed no changes — its `type == "pr"` / `== "issue"`
  checks already skip `type == "slack"` rows safely (verified, not just
  assumed — see Verification below).

**Docs updated:** `SKILL.md` — new "Slack Needs Owner" subsection under
Input (the exact scan → open-candidates → classify recipe, plus the
`dismiss` command), a new Workflow step 1b, a `Team Slack Names` /
`assemble_slack_data.py` precondition (explicitly optional — skip cleanly if
Chrome MCP or Slack access isn't available), Data Files entry for
`slack_data.json`, an Approval Gate summary bullet, a Needs Owner routing
note, and four new Chrome tools added to `allowed-tools`
(`find`, `read_page`, `computer`, `file_upload`).

### Verification

- `python3 -m py_compile` on both `headless_daily_report.py` and
  `assemble_slack_data.py` — clean.
- `assemble_slack_data.py scan` run against a **real** `get_page_text` dump
  of `#t-dxp-headless` (captured live during this session) — all 10
  bracketed threads parsed correctly, including per-message dates derived
  from date-separator lines and correct zero-reply detection for a
  synthetic no-reply message appended to the fixture.
- `assemble_slack_data.py classify` run against that scan output plus a
  details fixture built from one **real** captured thread (5 replies,
  correctly classified as answered — the real replies came from Alejandro
  Tardín and Beni Herrero Lorenzo, both on the roster) and eight
  hand-built-but-realistic threads covering the answered/unanswered/
  continuation-line/roster-empty edge cases. 6 unanswered, 4 answered,
  correct oldest-first ordering, correct snapshot write-back.
- `dismiss` run against that snapshot, then `classify` re-run with
  unchanged inputs — the dismissed thread correctly dropped out of the
  unanswered list; snapshot correctly recorded 1 dismissed.
- Full `headless_daily_report.py` pipeline run end-to-end (`--jira-data-file`
  with an empty-but-valid Jira payload, `--no-github`, `--slack-data-file`
  pointed at the classify output) — 5 Slack rows rendered correctly in the
  HTML preview (title in Topic cell, working Slack link in the Issue cell,
  "Nd — no reply" in Days, purple "Unplanned | Slack Q" priority badge).
- Same run repeated with `--dry-run` — `build_adf_document()` +
  `validate_adf()` passed (5 status nodes, no duplicate localIds, all tables
  full-width, and specifically confirmed all 5 Slack rows have a real
  inlineCard node on the Slack permalink in `adf_output.json`).
- Same run repeated with `--confirm-publish` — `update_caches()` /
  `save_sprint_context()` completed without error; diffed the resulting
  `project_current_sprint.md` against the pre-run copy and confirmed
  `Team Slack Names` and `Slack Thread Snapshot` passed through byte-for-byte
  unchanged (as expected — nothing in this run's pipeline mutates
  `ctx.slack_snapshot`, only `assemble_slack_data.py classify` does, in an
  earlier separate step).
- Pre-existing `--test-exclusions` unit tests still pass — no regression in
  the unrelated Jira exclusion logic.

**Known limitations (documented, not blockers):**
- Date-separator parsing (`scan` mode) assumes the current year unless that
  would put the date in the future, in which case it rolls back one year.
  Only matters right at the Jan 1 boundary given the short default window.
- If the channel is high-volume enough that the last 7 days require
  scrolling to fully load, `scan` only sees what's currently rendered —
  SKILL.md does not yet describe a scroll-and-re-scrape loop. Not needed for
  `#t-dxp-headless`'s current volume (~2-3 threads/day) but worth revisiting
  if that changes.
- Reply-author matching is a case-insensitive exact match against Slack
  display names in `Team Slack Names`. A team member whose Slack display
  name doesn't match what's in the roster (nickname drift, etc.) would have
  their replies mis-treated as non-team, over-flagging the thread. Spot-check
  the roster against real Slack display names occasionally.
