# Headless Daily Actions Report

**Skill Version:** 2.1.1 — 2026-07-31 (see `CHANGELOG.md` for what changed at each version; the many dated `CHANGELOG-fixes-*.md` files hold the detailed forensic history behind each fix)

Fetch fresh data from Jira and GitHub; build an HTML preview; get approval; then publish to Confluence. The Test section is static (a Confluence Include Page macro) and needs no data collection. Optionally also surfaces unanswered questions from the `#t-dxp-headless` Slack channel (Chrome-scraped — no Slack connector for this org) at the top of Needs Owner.

## Configuration

After installing this skill, set these two paths to match the installer's machine:

- **`SKILL_DIR`** — the folder where this skill was installed (contains `headless_daily_report.py`)
- **`WORK_DIR`** — the folder where scratch files (`jira_data.json`, `pr_data.json`, `slack_data.json`, and — as of v2.0.0 — `context_scratch.md`, the synced copy of the shared context page) will be written during a run (can be the same as `SKILL_DIR`)

**v2.0.0+:** Sprint Metadata, rosters, and the four run-to-run caches no longer live only in a local file on the installer's machine — they're synced from a shared Confluence page at the start of every run and pushed back after publish. See **Shared Context Storage** below before your first run; it replaces most of what used to be manual `project_current_sprint.md` bootstrapping.

`SKILL_DIR/.env` is **optional** — do not block a run or ask the user for
credentials if it is missing. All primary data collection (Jira issues,
Confluence page, changelogs) goes through the Atlassian MCP and Chrome MCP,
which need no `.env` at all. If you want to create one anyway:

```
ATLASSIAN_EMAIL=your@email.com
ATLASSIAN_TOKEN=your_atlassian_api_token
```

**2026-07-08 (per Nóra — "do these really matter?"):** an audit of
`headless_daily_report.py` found:
- `GITHUB_TOKEN` / `_github_headers()` is **dead code** — defined but never
  called anywhere in the script. It is a leftover from before PR data
  collection moved to Chrome-based scraping. Do not ask the user for a
  GitHub token; it does nothing.
- `ATLASSIAN_TOKEN` only feeds a handful of **fallback** HTTPS calls
  (`jira_get_issue`, used for live PR→parent resolution, BPR "Original Fix
  Committed" date, and LPP/LPD last-action-date) that only fire when Claude
  hasn't already pre-fetched that data via the MCP into `jira_data.json`'s
  `changelogs` field. As of 2026-07-08 that pre-fetch is a **required**
  Workflow step (see Workflow → 1a), not an optional nice-to-have — do it on
  every run so this HTTPS fallback is rarely needed. Every call site still
  wraps the fallback in `try/except` and degrades gracefully — it prints a
  warning and skips that one enrichment, it never crashes the run — but the
  code's own comments note these direct HTTPS calls are usually
  proxy-blocked in the Claude sandbox anyway, token or not.

**Net effect: a missing `.env` should never stop a run.** If it's absent,
proceed normally — expect only a few extra "changelog fetch failed" warnings
in the console output for edge cases, not a broken report.

**✅ Read-only skill mounts (Cowork / sandboxed sessions) — fixed in 2.1.1 (2026-07-31).**
`headless_daily_report.py` used to default `OUTPUT_DIR` to its own folder
(`Path(__file__).parent`, i.e. `SKILL_DIR`) — every output file it writes
(`daily_actions_report_<date>.html`, `adf_output.json`,
`publish_adf_loader.js`, `publish_snippet.js`, `publish_<sprint>_console.js`)
went there, which fails with `OSError: [Errno 30] Read-only file system` in
any session where the skill folder is a **read-only mounted cache** (every
Cowork session). **Fix:** pass `--output-dir WORK_DIR` (or any writable path)
to `headless_daily_report.py` — it now writes every output file there instead
of next to the script. This replaces the old "copy the whole skill folder to
a writable scratch directory" workaround entirely; the skill folder itself
can now stay wherever it's mounted, read-only or not. See
`CHANGELOG-fixes-2026-07-31.md` for the exact diff.

## Preconditions

- `SKILL_DIR/headless_daily_report.py` exists
- `SKILL_DIR/assemble_jira_data.py` exists (builds and validates `jira_data.json` from MCP result files)
- The shared context Confluence page (`context_page_id` — see **Shared Context Storage**) is reachable via the Atlassian MCP and has a current Sprint Metadata section, and a `Team GitHub Logins` JSON section (display name → GitHub login) used for cross-team PR detection (dedup rule 3). Source rosters from the team page: https://liferay.atlassian.net/wiki/spaces/ENGHEADLESS/overview — keep them in sync when the roster changes (anyone with edit access to that Confluence page can update rosters directly — no code/skill-file edit needed). If the section is missing/empty, cross-team detection silently does nothing. A local `SKILL_DIR/headless-daily-actions-report/project_current_sprint.md` template still ships with the skill purely as a **one-time bootstrap seed** for creating that page — see Shared Context Storage — it is not read at runtime once the shared page exists.

  **Roster completeness (recurring failure pattern, seen 2026-07-10 and again 2026-07-29):** a person can be added to one roster (say, `Team GitHub Logins`, because their PR needed cross-team-detection to work) without being added to the others (`Account IDs`, which several exclusion rules check assignee ownership against). The person then looks like a non-Headless outsider to any rule that only consults the roster they're missing from, even though they're clearly doing Headless work. If a Section 1 exclusion or a cross-team flag looks wrong for someone you know is on the team, check whether they're present in *all* the rosters they'd plausibly need to be in, not just the one that's already correct — and add them everywhere they're missing, not just the one place the current symptom points at.

  **Team ownership changes (an issue stops being Headless work):** this happens through normal churn — an issue gets reassigned to another team, or was only ever pulled in by a shared filter/iteration label it doesn't actually belong to. There's no automatic way to detect this for every project (LPD has a sprint-field/team/assignee ownership check; LPP does not). When a team member says an issue "isn't Headless anymore," the correct, permanent fix is to add the `headless-board-out` label directly on that Jira issue (`should_exclude()` Rule 1 excludes it unconditionally, for any project) rather than trying to patch it out of a single run's data — the label persists across every future run with no code change needed.
- `SKILL_DIR/.env` is optional (see Configuration above) — never block on it or prompt the user for credentials.
- Chrome MCP is available (required for GitHub PR scraping and, if enabled, Slack scraping)
- The Atlassian MCP is available (cloudId: `5d1aaa67-5d5e-4cca-b668-33b9742cfb4a`)
- `SKILL_DIR/assemble_slack_data.py` exists (turns Chrome-scraped Slack text into `slack_data.json` — see "Slack Needs Owner" below). There is no Slack connector for this org, so this whole section is a Chrome-scraping workaround — but it is **run by default, not optional-by-default**. **2026-07-15 incident:** a run silently skipped this step (reasonable-sounding at the time — it used to be framed as optional) and a new unanswered thread went completely unreported until a team meeting caught it. Only skip it if Chrome MCP is genuinely unavailable, or the user has explicitly said to skip it for this specific run — never skip it by default or to save time/tool-calls, and never skip it without calling it out to the user BEFORE the approval gate (not just noting it after the fact in a summary). The synced context scratch file (`WORK_DIR/context_scratch.md`, see Shared Context Storage) must have a `Team Slack Names` JSON section (display name → Slack display name) for reply matching to work — if it's missing, `assemble_slack_data.py` will warn and over-flag rather than silently under-report.

  **✅ `assemble_slack_data.py`'s parser now matches `headless_daily_report.py`'s — fixed in 2.1.1 (2026-07-31).** The 2026-07-29 fix that let `load_sprint_context()` tolerate a blank line between a `## Section Name` heading and its ` ```json ` fence had **not** been applied to `assemble_slack_data.py`'s own, separately-implemented `_read_md_json_section()`/`_write_md_json_section()` — since Confluence's markdown round-trip reliably reintroduces that blank line, `assemble_slack_data.py classify` was silently seeing an **empty `Team Slack Names` roster on every run**, misclassifying answered threads as unanswered (confirmed 2026-07-31: 19-reply and 5-reply threads with real team replies both came back "unanswered" until this was caught). Both regexes now tolerate one or more blank lines, same as `headless_daily_report.py`. If you still see `⚠ No '## Team Slack Names' section found` or `⚠ Team roster is empty` on a context page that should have a populated roster, that means the section itself is genuinely missing or malformed beyond a blank line — treat it as a hard stop and inspect `context_scratch.md` directly. See `CHANGELOG-fixes-2026-07-31.md` for the exact diff applied.

## Permanent Page Policy

**The Daily Actions Report uses a single permanent Confluence page — forever.**

- `actions_report_page_id` is set once and **never changes**, not even when rolling to a new sprint or a new release cycle.
- `report_page_title` is the fixed Confluence page title. It also never changes.
- Every daily run PUTs fresh content to this same page. The page header, sprint label, dates, and remaining days are all updated in the content body — but the page ID and title stay constant.
- When rolling to a new sprint (e.g. DEV#12 → DEV#13), update only: `sprint_label`, `sprint_field`, `label_dev`, `label_dis`, `start_date`, `end_date`, and the State Snapshot / PR Snapshot sections. **Do not touch `actions_report_page_id` or `report_page_title`.**
- Confluence version history is unlimited — every past daily run is preserved and browsable via the page history.

## Shared Context Storage (v2.0.0+)

**Sprint Metadata, both rosters (Account IDs, Designer Account IDs, Team GitHub Logins, Team Slack Names), and the four run-to-run caches (Changelog Cache, State Snapshot, PR Snapshot, Slack Thread Snapshot) live on a single permanent Confluence page — shared by the whole team, not the machine that happens to run this skill.**

**Why this changed:** before v2.0.0, all of the above lived only in `SKILL_DIR/headless-daily-actions-report/project_current_sprint.md` — a file inside this skill's own local install. That's fine as long as the same person on the same machine always runs the report, but it breaks in two ways that actually happened: (1) a teammate covering during someone's PTO runs the skill on their own machine and sees a stale or entirely different cache than the owner's, and (2) a sandboxed/read-only session (e.g. a fresh Claude session with the skill folder mounted read-only) can build a perfectly correct report but can't persist the cache update anywhere — exactly what happened on 2026-07-28, where the cache-write step failed silently on a read-only mount. Moving the cache onto Confluence — which every session already reaches via the Atlassian MCP to publish the report — fixes both: any session can read/write it, and Confluence's own version history means every past cache state is still recoverable (the same benefit the report page already gets from the Permanent Page Policy above).

**Note (2026-07-31):** this migration fixed the *cache/roster data* half of the read-only-mount problem. The *script output files* (HTML preview, ADF, publish snippets) were fixed separately in 2.1.1 via the `--output-dir` flag — see the "Read-only skill mounts" note in Configuration above.

**Permanent Context Page Policy** (mirrors the report page's policy above):

- `context_page_id` is set once and **never changes**. Bootstrapped 2026-07-29: `context_page_id: 5190975505` (space `ENGHEADLESS`, title "Headless Daily Report — Shared Context", <https://liferay.atlassian.net/wiki/spaces/ENGHEADLESS/pages/5190975505/Headless+Daily+Report+Shared+Context>). **This page already exists — do not re-bootstrap.** Only go through the bootstrap step below if this ID is ever blanked out again (e.g. a fresh install of this skill for a different team/space).
- The page body holds the *exact same* section structure `project_current_sprint.md` always used — `## Sprint Metadata` (key: value lines) followed by `## Section Name` headers each containing a fenced ` ```json ` block (Changelog Cache, State Snapshot, Account IDs, Designer Account IDs, Team GitHub Logins, PR Snapshot, Team Slack Names, Slack Thread Snapshot). This is deliberate — `headless_daily_report.py`'s `load_sprint_context()`/`save_sprint_context()` and `assemble_slack_data.py`'s `--sprint-context` parsing didn't need to change internally at all, only *where* that content is stored and how it gets there each run.
- **Bootstrap (one-time, only if `context_page_id` is still blank above):** read the shipped template at `SKILL_DIR/headless-daily-actions-report/project_current_sprint.md` (this ships purely as bootstrap seed content now — it is never read at runtime once the page exists) and call `createConfluencePage` with that content, space `ENGHEADLESS`, title as above. Record the returned page ID into this section of `SKILL.md` so every future run knows where to look. Tell the user you're doing this and why — creating new shared team infrastructure is worth a heads-up even though it's just a data page.
- Roster edits (new hire, someone leaves, a GitHub/Slack handle changes) can now be made by **any team member directly on the Confluence page** — no engineering change or skill-file edit required, unlike the old local-file approach.

**Every run, in order:**

1. **Sync in (Workflow → Step 0, before Step 1):** `getConfluencePage(context_page_id)`, write its content verbatim to `WORK_DIR/context_scratch.md`. A tight format (heading directly followed by its ` ```json ` fence, no blank line) is still the safest target since Confluence's own markdown rendering on the read-back can reformat things you don't control, but as of 2.1.1 both `load_sprint_context()` (2026-07-29 fix) and `assemble_slack_data.py`'s `_read_md_json_section()`/`_write_md_json_section()` (2026-07-31 fix) tolerate one or more blank lines there, and both raise loudly rather than silently loading empty rosters if the fences are missing entirely.
2. **Mandatory sanity check, before doing anything else with the synced data:** confirm the sync actually produced non-empty rosters/caches. A one-line check is enough — e.g. load the file and print the length of `account_ids`, `team_github_logins`, and `state_snapshot`. If any of these come back unexpectedly empty on a page that should already have data (i.e. this isn't the very first bootstrap), stop and investigate before building anything — don't let an empty roster silently produce a report with wrong exclusions. (This check would have caught the 2026-07-29 incident immediately instead of three rounds of user bug reports.)
3. **Point every script at the scratch copy, not the skill folder's local file:** `headless_daily_report.py ... --sprint-context-file WORK_DIR/context_scratch.md` (new flag — falls back to the local file if omitted, so the script still works standalone/offline for testing) and `assemble_slack_data.py classify/dismiss ... --sprint-context WORK_DIR/context_scratch.md` (this flag already existed — just point it here instead of the local file now).
4. **Sync back out (Workflow → 3.1, only after the browser publish returns HTTP 200):** read the now-updated `WORK_DIR/context_scratch.md` (written by `--confirm-publish`) and call `updateConfluencePage(context_page_id, content)` with it. This is the one case where using the Confluence MCP's `updateConfluencePage` tool directly is correct and expected — the ⛔ warning against it in Workflow → 3b is specific to the **Daily Actions Report page's ADF/full-width-table requirements**, which don't apply here: the context page is a plain markdown/JSON dump, not a rendered report.

**Version tracking:** the shared context page also carries a `latest_skill_version` key in its Sprint Metadata, stamped automatically by `headless_daily_report.py` every time `--confirm-publish` succeeds. Every run compares its own `SKILL_VERSION` constant against that value and prints a loud (non-blocking) console warning if it's running an older copy than the one that last touched the shared page — see CHANGELOG.md.

## Input

### Sprint Metadata

Read only the **Sprint Metadata** section of `WORK_DIR/context_scratch.md` (the local copy synced from the shared Confluence context page in Workflow → Step 0 — see Shared Context Storage) — sprint label, start/end dates, `actions_report_page_id`, `report_page_title`, and `latest_skill_version`. Fail fast if the file is missing or the section is absent.

**`sprint_field` vs `sprint_label` — do not confuse them.** `sprint_label` (e.g. `26M2|DEV#13|Jun15-Jun26`) is the shared iteration label used by **every** product team — it is for display only (report header/filename) and must never be used to identify Headless work. `sprint_field` is the real Jira Sprint value (`customfield_10020`) and **must start with `HL`** (e.g. `HL26M2|DEV#13|Jun15-Jun26`); it is the only reliable signal of Headless team ownership. The loader now **requires** `sprint_field` and **fails loudly** if it is missing or does not start with `HL` (no silent fallback to the label). When rolling sprints, update both — and make sure `sprint_field` keeps its `HL` prefix.

### Jira Sprint Data

Three MCP queries via `searchJiraIssuesUsingJql` — **run them SEQUENTIALLY, never in parallel.** Parallel Jira MCP calls have returned crossed/duplicated responses (two different queries answered with the same cached payload), which produced a wrong report two days in a row in June 2026.

- **Sprint issues** — JQL: `filter=54796 AND status not in (Closed,Completed,Resolved,Answered)`, maxResults 100, fields: `key, summary, status, assignee, labels, issuetype, priority, project, updated, created, duedate, comment, customfield_10804, customfield_10168, parent, customfield_10001, customfield_10020, issuelinks`
- **SEV bugs** — JQL: `project=LPD AND issuetype=Bug AND "Cross Cutting Properties[Checkboxes]" = "Security Vulnerability" AND status not in (closed)`, fields: `key, summary, status, labels, issuelinks` (issuelinks is required — see BPR-linkage note below, not just default fields)
- **SEV BPRs** — JQL: `filter=15069 AND status not in (closed)`

#### ⚠️ MANDATORY: re-verify SEV bugs/BPRs immediately before build — never reuse an earlier-session fetch

**Root cause of the LPD-97411 miss (2026-07-15):** a SEV bug (LPD-97411) closed
between an early fetch in the session and the final `assemble_jira_data.py`
build/publish. A fresher re-fetch taken later in the same session had already
correctly dropped it, but the stale, earlier fetch was reused anyway (to stay
"consistent" with an already-approved preview) — so the closed bug still
appeared in the published report. Separately, its two backport tickets
(BPR-91107, BPR-91108) didn't exist yet at the time of the SEV BPRs fetch —
they're auto-created by the Branch Manager once the fix is committed, which
can lag behind the SEV bug's own status change — so `filter=15069` alone
missed them.

Two rules, both mandatory:

1. **Freshness:** run the SEV bugs and SEV BPRs queries as the LAST data
   fetch before calling `assemble_jira_data.py`, as close to publish time as
   possible. If there's any gap since an earlier fetch — an approval-gate
   wait, a retry, a multi-session run — re-fetch fresh rather than reusing an
   older result file, even if that changes counts you already showed the
   user. Never pick between two fetches of the same query by which one is
   more convenient; always take the most recent.
2. **BPR linkage:** don't rely on `filter=15069` as the sole source of SEV
   BPRs. `assemble_jira_data.py` also unions in any `BPR-*` issue found in
   each SEV bug's own `issuelinks` (hence the explicit `issuelinks` field
   above) — this catches backport tickets the saved filter hasn't picked up
   yet. `assemble_jira_data.py` also auto-drops any SEV issue that is already
   closed/resolved by build time as a defense-in-depth safety net (belt-and-
   suspenders on top of rule 1, not a substitute for it).

#### ⚠️ MANDATORY: verify the sprint result is COMPLETE (do not trust `hasNextPage`)

**Root cause of the LPP-64669 miss (2026-07-02):** the sprint query returned a
truncated page of 52 issues but set `pageInfo.hasNextPage=false`, so the pipeline
believed it had the whole board and silently dropped issues that genuinely matched
the filter (an In-Queue customer LPP). A single page's `hasNextPage` is NOT
trustworthy — the MCP has returned `false` on an incomplete page.

Two required steps on **every** run:

1. **Get the filter's true total first.** Run the sprint JQL once with
   `maxResults: 1` and `computeIssueCount: true` and record the total (`X`). If
   the MCP does not return a numeric total, page the filter yourself via
   `endCursor`/`nextPageToken` from `maxResults:1` until the cursor is exhausted
   and count the keys — that count is `X`.
2. **Page the real query until the cursor is exhausted.** Do not stop at the
   first page regardless of its `hasNextPage` value. Keep issuing the query with
   the returned `endCursor`/`nextPageToken` until there is no cursor, and pass
   **every** page to the assembler as a separate `--sprint-file`. Then pass
   `--expected-count X`. The assembler hard-fails unless the number of unique
   issues loaded equals `X`.

#### Collecting the results (large results are NORMAL)

The sprint query result is large (~1 MB with a full sprint) and **will not be returned inline**. The MCP saves it to a tool-result file and returns a message like *"result exceeds maximum allowed tokens. Output has been saved to /var/folders/.../tool-results/mcp-...-searchJiraIssuesUsingJql-<timestamp>.txt"*. **This is expected, not an error.** Never parse the truncated inline text and never treat the saved-to-file message as a failure.

For each of the three queries, capture its result as a file path:

- **Saved to file:** note the filename (the basename, e.g. `mcp-...-searchJiraIssuesUsingJql-1781081975826.txt`). The host path in the message is not reachable from bash; the same file is available inside the sandbox. Locate it with:
  ```bash
  find /sessions/*/mnt/.claude/projects -name '<basename>' -type f
  ```
- **Returned inline** (small results, e.g. SEV BPRs): save the raw JSON verbatim to a temp file in `/tmp/` (e.g. `/tmp/bpr_result.json`) using the Write tool or a bash heredoc.

#### Build and validate `jira_data.json` (hard stop on bad data)

Never assemble `jira_data.json` by hand. Run the assembler, which both builds the file and enforces all data-quality checks:

```bash
python3 SKILL_DIR/assemble_jira_data.py \
    --sprint-file <sprint result file> [--sprint-file <page 2> ...] \
    --sev-file <sev result file> \
    --bpr-file <bpr result file> \
    --expected-count <X: the filter total from the computeIssueCount step> \
    --out WORK_DIR/jira_data.json
```

The script validates: sprint issue count ≥ 20; **unique issues loaded == `--expected-count` (completeness guard — the primary defense against a truncated page falsely marked `hasNextPage=false`, the LPP-64669 bug)**; sprint and SEV results are not identical (crossed-response detection); ≥ 15 non-empty summaries; ≥ 10 issues with `customfield_10020`; and `hasNextPage` false on every supplied page (if a page reports `hasNextPage=true` it prints the `nextPageToken` to fetch — pass extra pages as additional `--sprint-file` arguments). It derives `sev_keys`, `sev_zero_day_keys` (label `zero-day-vulnerability`), and `sev_bpr_keys` itself. **Always pass `--expected-count`;** if omitted, the script prints a loud warning that completeness could not be verified.

**If the assembler exits non-zero:** show its ❌ message to the user verbatim and stop. With user approval, retry the failing MCP query **once** (sequentially), re-run the assembler, and if it fails again stop entirely and recommend a fresh session. Do **not** attempt manual data reconstruction or alternative data paths (no chunking, no TSV extraction, no browser-JS fetching of Jira data, no Confluence relay tricks) — a reconstructed dataset produces a worse report than no report, and these workarounds have burned hours in past sessions.

### Open Pull Requests

Scrape `https://github.com/liferay-headless/liferay-portal/pulls?q=is:pr+is:open+draft:false` via Chrome MCP.

For each listed PR, open its page and confirm the green **"Open"** badge is present (discard Closed/Merged). Collect per PR: number, title, **author** (the GitHub login of the PR sender — required for cross-team detection, rule 3, and for the assignee-ownership check below), opening date (YYYY-MM-DD), linked Jira key (pattern `LPD-NNNN` or `LPP-NNNN` from title or branch), reviewers (ignore the `liferay-headless` and `gemini-code-assist[bot]` bots — treat bot-only as no reviewer) with each reviewer's status (pending / approved / changes_requested), and **assignees** (the GitHub logins in the PR sidebar's "Assignees" field — read the same sidebar as Reviewers; use the full-page text scrape, not a DOM/JS query, since the sidebar has previously been misread by JS selectors that instead matched a keyboard-shortcuts overlay). The unauthenticated `api.github.com` is rate-limited to 60/hr — prefer scraping the authenticated PR pages over API calls.

Set `parent_key` and `lpp_fix_key` to `null` in the initial scrape — they get filled in by the mandatory resolution step below, done by Claude, before the data is considered ready to build from.

**PR parent resolution — mandatory, do this yourself, every run (2026-07-29 clarification):** build `sprint_keys` from the Jira sprint issues. For any PR whose `jira_key` is not in `sprint_keys`, call `getJiraIssue` (fields: `parent`, `issuetype`) and set `parent_key` to the parent's key if it's in `sprint_keys`. Run these lookups in parallel. If a PR has no parseable Jira key, flag it in chat and skip it.

`headless_daily_report.py` *also* has its own live-lookup fallback for this (`merge_prs()` calls `jira_get_issue` directly over HTTPS when it sees an unresolved PR), which can make it look like this step is optional — **it is not.** That fallback needs `ATLASSIAN_TOKEN`, and direct HTTPS from a Claude sandbox to `liferay.atlassian.net` is proxy-blocked in every environment seen so far (see the Publish section below), so the fallback fails silently for every single PR, every time, in practice. On 2026-07-29 this step was skipped ("the script resolves them" was taken at face value), and three PRs that were genuinely subtasks of in-sprint stories (e.g. LPD-96499's own subtasks) were published as standalone rows — caught only because the report's actual owner reviewed it line by line against what she knew was true. Do the `getJiraIssue` resolution yourself before ever calling `assemble`-adjacent build steps; don't rely on the script noticing it needs to.

### Slack Needs Owner (Chrome MCP — no Slack connector available for this org)

There is no Slack connector for this workspace, so this reuses the same Chrome-scraping approach as Open Pull Requests. **All judgment calls (window, roster matching, dismiss/re-flag logic) live in `assemble_slack_data.py` — Claude's job here is purely mechanical scraping.** Run this by default on every run. Only skip it if Chrome MCP is genuinely unavailable, or the user has explicitly said to skip it for this run — and if you do skip it, say so plainly before the approval gate, not just as a footnote afterward (2026-07-15: a silently-skipped run missed a real unanswered thread until a team meeting caught it).

Channel: `#t-dxp-headless` (`https://liferay.slack.com/archives/C5E1CRLJY`).

1. **Scan.** Navigate to the channel (do **not** open any thread first — scrape the plain channel view). Run `get_page_text` and save the output verbatim to a text file (e.g. `/tmp/slack_channel.txt`). Then run:
   ```bash
   python3 SKILL_DIR/assemble_slack_data.py scan \
       --channel-text /tmp/slack_channel.txt \
       --window-days 7 \
       --out /tmp/slack_candidates.json
   ```
   This prints how many candidate `[Title]` threads it found and how many need their thread opened (`reply_count > 0`) vs. have zero replies already.

2. **Open each candidate that needs it.** For every entry in `slack_candidates.json` with `reply_count > 0`: find that message's timestamp link on the page (its `href` is the permalink — e.g. `.../archives/C5E1CRLJY/p1783505623537369`), open the thread ("View thread"), and run `get_page_text` again. **If clicking "View thread" / the reply-count button doesn't visibly change the panel (a real failure mode seen 2026-07-31 — repeated clicks on the correct element produced identical `get_page_text` output every time), don't keep re-clicking blindly: navigate directly to the deep-link URL instead — `https://app.slack.com/client/<TEAM_ID>/<CHANNEL_ID>/thread/<CHANNEL_ID>-<ts>` where `<ts>` is the permalink's `p<digits>` converted to `<digits[:-6]>.<digits[-6:]>` (e.g. `p1785243005783069` → `1785243005.783069`) — then wait and re-run `get_page_text`.** For entries with `reply_count == 0`, you only need the permalink — do not bother opening the thread (there is nothing to read). Append one record per candidate to a single JSON array file, e.g. `/tmp/slack_details.json`:
   ```json
   [{"title": "<exact title from candidates.json>", "permalink": "<href>", "raw_thread_text": "<get_page_text output, or omit/null for zero-reply threads>"}]
   ```
   Every candidate must get a record — the classify step hard-fails if one is missing rather than silently under-reporting.

   ⚠️ **`raw_thread_text` must be the verbatim, unmodified `get_page_text` output for that thread panel — never a paraphrase, summary, or condensed rewrite.** `assemble_slack_data.py`'s `_extract_reply_authors()` identifies who replied by pattern-matching *exact* lines as they appear in Slack's own rendering: a `"N replies"` divider line, followed by pairs of `<Name>` / `<Weekday> at <H:MM> <AM|PM>` lines. A summarized or reformatted version of the thread (e.g. `"Alice: replied that..."`) will not match those patterns, so `_extract_reply_authors()` silently returns zero authors — every thread with a paraphrased `raw_thread_text` is then misclassified as unanswered even when team members clearly replied. This caused exactly that failure on 2026-07-10 (two answered threads were wrongly reported as unanswered). Save each thread's `get_page_text` result to a file and copy its contents through unedited — do not retype, translate, or "clean up" the text before putting it in `slack_details.json`. If a thread is long enough that `get_page_text` only shows part of it at a time, scroll the thread panel and capture each viewport, then concatenate the verbatim snippets in chronological order (overlapping content is fine — better duplicated than missing) rather than summarizing what you saw.

3. **Classify.** Run:
   ```bash
   python3 SKILL_DIR/assemble_slack_data.py classify \
       --candidates /tmp/slack_candidates.json \
       --details /tmp/slack_details.json \
       --sprint-context WORK_DIR/context_scratch.md \
       --out WORK_DIR/slack_data.json
   ```
   This checks each thread's reply authors against `Team Slack Names`, applies any existing `dismiss` overrides, sorts unanswered threads oldest-first, writes `slack_data.json`, and updates the `Slack Thread Snapshot` section of `WORK_DIR/context_scratch.md` in place — synced back to the shared Confluence context page in Workflow → 3.1, same as the other caches. Pass `WORK_DIR/slack_data.json` to `headless_daily_report.py` via `--slack-data-file`. If this prints `⚠ No '## Team Slack Names' section found` or `⚠ Team roster is empty` on a context page that should have a populated roster, the section is genuinely missing or malformed (not just a blank-line formatting quirk, fixed in 2.1.1) — inspect `context_scratch.md` directly before trusting the output.

**Dismissing a thread** (handled outside Slack, never got an in-thread reply): tell Claude which one, and run:
```bash
python3 SKILL_DIR/assemble_slack_data.py dismiss \
    --title-contains "<distinctive part of the title>" \
    --sprint-context WORK_DIR/context_scratch.md
```
It stays hidden until that thread's reply count changes again.

### Test Section (static — no data collection)

**2026-07-09 change (per Nóra):** the Test section no longer runs a live Testray
scrape or Jira bug-count fetch on every run. It used to require: a Chrome MCP
screenshot of two Testray builds ("Investigation"/"Acceptance" Failed counts)
plus a browser-JS fetch of three Jira filter counts (`all_bugs`, `fp4_fp5`,
`no_fp`), combined into `testing_panel.json` and passed to the script via
`--testing-panel-file`. **All of that is gone.** `--no-testing-panel` and
`--testing-panel-file` no longer exist as CLI flags.

The regression/testing data now lives on its own page — **"Headless Testray
Regression Tracking"** (space `ENGHEADLESS`, page id `5096669324`,
<https://liferay.atlassian.net/wiki/spaces/ENGHEADLESS/pages/5096669324/Headless+Testray+Regression+Tracking>)
— maintained independently of this report by whoever owns the Testray
regression tracking process. The Daily Actions Report's Test section is just
a Confluence **Include Page** macro transcluding that page by title (both
pages live in `ENGHEADLESS`, so no space qualifier is needed). Every daily
publish shows whatever is current on that page automatically — there is
nothing to fetch, screenshot, or pass to the script for this section on any
run.

If the regression tracking page is ever renamed or moved to another space,
update `TEST_REGRESSION_PAGE_TITLE` (and `TEST_REGRESSION_PAGE_URL`, used
only for the local HTML preview link) in `headless_daily_report.py` to match.

## Expected Output

### Data Files

Two JSON files written to `WORK_DIR` before the script runs. Regenerate both on every run — never reuse stale files from a previous run.

**`jira_data.json`** — always generated by `assemble_jira_data.py`, never hand-crafted:
```json
{
  "sprint_issues": [ ...raw issue objects from sprint query... ],
  "sev_keys": [...],
  "sev_zero_day_keys": [...],
  "sev_bpr_keys": [...],
  "changelogs": { "LPD-12345": [ ...history dicts... ], ... }
}
```
`changelogs` is added automatically when `--changelog-file` is passed to `assemble_jira_data.py` (see Workflow → step 1a). It should be present on every normal run — it is not something you skip by default.

**`pr_data.json`** — JSON array, one object per open PR:
```json
{
  "pr_number": 3811,
  "title": "LPD-89688 ...",
  "author": "dannielraposo",
  "created_at": "2026-05-25",
  "jira_key": "LPD-89688",
  "parent_key": null,
  "lpp_fix_key": null,
  "reviewers": [{"name": "jaimelr10", "status": "changes_requested"}],
  "assignees": ["jaimelr10"],
  "url": "https://github.com/liferay-headless/liferay-portal/pull/3811",
  "draft": false
}
```
`reviewers` is a list (a PR can have more than one human reviewer requested) — bots are already filtered out per the collection rule above. `assignees` is a list of GitHub logins from the PR's "Assignees" sidebar field; it feeds the ownership rule below and is independent of `reviewers` (a PR can have an assignee with no reviewer, or vice versa).

There is no `testing_panel.json` any more (removed 2026-07-09) — the Test section is static, see "Test Section" above.

**`slack_data.json`** — optional third file, always generated by `assemble_slack_data.py classify`, never hand-crafted. JSON array, one object per unanswered thread, already sorted oldest-first:
```json
[{"permalink": "https://liferay.slack.com/archives/C5E1CRLJY/p1783505623537369", "title": "Translation of problem messages", "author": "Alberto Chaparro", "created_date": "2026-07-09", "age_days": 1, "reply_count": 5}]
```
Omit `--slack-data-file` entirely if Slack scraping was skipped this run — the report renders fine without it.

### HTML Preview

Run `headless_daily_report.py` from `SKILL_DIR` **without** `--publish`, passing the data files from `WORK_DIR` (`--jira-data-file`, `--pr-data-file`, and `--slack-data-file` if collected). After it completes, report: section row counts, excluded count, the per-section PR counts (PRs routed to the top of 2b. Assigned and 2a. Needs Owner), how many unanswered Slack threads are pinned above them, link to the generated HTML file, and any warnings or changelog fetch failures.

**Open PRs routing:** There is no separate Pick Up Next PR table. Open PRs route into a Section 2 table and sort to the top, ahead of issue rows, based on whether the PR has an **owner**: a human reviewer, OR a human GitHub assignee other than the PR's own author. (Self-assignment — the author assigning the PR to themselves — is the default/trivial case on GitHub and does not count as someone else having picked it up; an assignee only counts when it's a *different* person from the author.) PR with an owner → top of 2b. Assigned (longest-open first); PR with no owner at all (no reviewer and no non-author assignee) → top of 2a. Needs Owner (longest-open first). PRs with no parseable Jira key are flagged in chat and skipped.

> **2026-07-08 follow-up:** the displayed section numbers were swapped to match the render order set earlier that day (Needs Owner renders first, Assigned second) — "2a." now labels Needs Owner and "2b." now labels Assigned. This is a label change only; nothing about routing logic or content moved.

> **2026-07-08 fix:** this rule used to look only at `reviewer` and missed PRs that had a real assignee but no reviewer requested yet (they were wrongly parked in 2b). See `CHANGELOG-fixes-2026-07-08.md` for the full story and the exact `has_owner` logic in `fetch_open_prs()` / the standalone-PR routing block in `headless_daily_report.py`.

**Section 1 (In Progress) visibility gate — an issue can be structurally eligible and still not appear:** being in an in-progress status for LPD/LPP is necessary but not sufficient. `evaluate_triggers()` also requires at least one *actionable* trigger — a status change, an assignee change, a new comment since the last snapshot, a PR needing action, or a staleness/age threshold crossed — or the issue is silently dropped from Section 1 (deliberately, to keep the section from being 40 rows of "nothing changed"). This is by design, but it has a known gap pattern: an issue with **no fresh event** (no new comment, no status/assignee change) is invisible even if it has been sitting for weeks, unless age itself is wired up as a trigger for that project.

- **LPD** has always had an age-based trigger (Trigger 7): `LPD_ORANGE_THRESHOLD` / `LPD_RED_THRESHOLD` (by t-shirt size) — days since creation alone is enough to surface a long-running LPD even with no other activity.
- **LPP did not have this until 2026-07-08.** `LPP-64236` (40 days old, in analysis, no trigger otherwise since its only comment landed the same day as a snapshot) was silently gated out of Section 1 despite being exactly the kind of stale, long-lived item that needs visibility. Fixed by adding **Trigger 7b**: any LPP older than `LPP_ORANGE_THRESHOLD` (10 days) or `LPP_RED_THRESHOLD` (19 days) now surfaces with `"{N}d in progress — check for blockers"`, mirroring LPD's Trigger 7. See `CHANGELOG-fixes-2026-07-08.md`.
- **If a future report seems to be missing a long-lived issue that "should obviously be there":** check whether its project has an age-based trigger at all before assuming the exclusion or tier logic is at fault — a missing age trigger is easy to miss because the issue looks correctly *classified*, just invisible.

**PTR ownership rule (Rule 6b in `should_exclude()`) — 2026-07-13 fix:** a PTR is kept if EITHER its `customfield_10001` (Team) field names a Headless team, OR its assignee is a known Headless team member (checked against `ctx.account_ids`, the `Account IDs` roster on the shared context page — see Shared Context Storage — this roster already includes the generic "PT User Headless" placeholder account, so no separate special-case is needed for it). Previously the rule required the Team field alone, which is frequently blank — on 2026-07-13, PTR-8977 and PTR-8970 (assigned to Beni Herrero Lorenzo) and PTR-8999 (PT User Headless) were all wrongly excluded as "Non-Headless PTR" purely because Team was empty, the same class of staleness bug as the 2026-07-10 `adolfopa` GitHub-roster incident above. A PTR already in "Answered" status is always excluded regardless of ownership (belt-and-suspenders on top of the sprint JQL's own `status not in (...,Answered)` filter). **If the roster (`Account IDs`) is stale** — a PTR assigned to a real team member still gets excluded — add them to `Account IDs` on the shared context Confluence page rather than accepting the exclusion at face value, same remediation as the GitHub-login case.

**PTR "Days in Progress" — 2026-07-13:** unlike LPD/LPP/BPR, a PTR's day count is always `today − issue["created"]` (see `get_first_active_date()`'s PTR branch) — "days open, from open until Answered." No changelog scan is needed or attempted. Because Rule 6b excludes "Answered" PTRs before this is ever computed, a PTR reaching the Days column is by definition still open.

**LPD "Days in Progress" now has two distinct meanings depending on current status — 2026-07-13 fix:** while status is "in development"/"in progress", the number is unchanged — total days since development began (most-recent transition into either status). For any OTHER LPD Section-1 status (escalated, in product review, ready for product review, in review — e.g. LPD-97411 on 2026-07-13), the number instead means **days in that current status specifically** (most-recent transition into the current status itself), and the cell/trigger text is labeled to match (e.g. `"3d in review"`, not `"3d in progress"` carried over from the development phase). This also fixes a documentation gap: the changelog pre-fetch step (1a above) previously only listed "In Development/In Progress" as LPD candidates, so any LPD sitting in In Review (like LPD-97411) silently missed its pre-fetch and fell back to the proxy-blocked live HTTPS fetch, landing on "(days unknown — changelog unavailable)". Pre-fetch is now required for all six LPD Section-1 statuses.

**Deduplication rules (June 2026 — no PR appears twice):**

1. **PR shown under an In Progress issue is not repeated in Pick Up Next.** If a PR is attached to a Section 1 (In Progress) issue *and actually renders there* (it emits Trigger-5 action text), it is suppressed from Pick Up Next. The comment under the issue row is enough. Never suppress a PR that isn't actually displayed under its issue, or it vanishes entirely.

   **2026-07-29 fix (per Nóra) — approved PRs are no longer the exception.** Through 2026-07-28, an *approved* PR emitted no Trigger-5 text at all (nothing to action on the issue side, by the reasoning that there's nothing left to do), so it never rendered under its issue and therefore always fell through to Pick Up Next 2b as a standalone-looking "Approved — ready to merge" row — even when it was plainly a subtask of a Section 1 story (e.g. PR#4055, approved, attached to LPD-98293, still showed up disconnected from that row). The report's owner considers "approved and ready to merge" exactly the kind of status update that belongs next to the story it's part of, not a reason to hide the connection. `_evaluate_pr_trigger()` now emits `"Approved — ready to merge — {suffix}"` for an approved+attached PR same as the other statuses, which both makes it appear under the issue row **and** — as a direct consequence of rule 1 above — suppresses it from Pick Up Next like every other attached PR. An approved PR only reaches Pick Up Next now if it has no attaching issue at all (genuinely standalone).

2. **LPD that fixes an in-scope LPP is shown only on the LPP line.** When an in-scope LPP has an "is fixed by" issuelink to an in-scope LPD (or a PR carries `lpp_fix_key`), the LPD is suppressed as its own row; any PR(s) it has are re-homed under the LPP row and the LPP renders "Fix: LPD-XXXX". The LPD does not get a separate line. **2026-07-08 fix:** this used to only suppress the LPD when it already had an attached PR, so an LPD linked to an LPP with no PR of its own rendered as a duplicate (its own row *and* the LPP's "Fix:" text). The suppression is now unconditional — any in-scope LPD linked to an in-scope LPP is suppressed regardless of whether it has a PR.

3. **Cross-team PR (unplanned work from another team) appears only as a flagged Pick Up Next row.** Team ownership is decided by the **PR author's GitHub login** checked against the `Team GitHub Logins` roster on the shared context page (see Shared Context Storage) — NOT by the issue's sprint label (all teams share the same iteration labels). A PR whose author is not on the roster is pinned to the **top of 2a. Needs Owner** as a standalone row flagged "⚠️ Cross-team review request from {author}", regardless of whether it has a reviewer. Its linked LPD is kept out of In Progress by the existing non-Headless exclusion (which keys off the sprint field starting with `HL`).

   **2026-07-10 incident:** Adolfo Pérez (`adolfopa`) was present in `Team Slack Names` and actively assigned to in-scope Headless work, but missing from `Team GitHub Logins` — his PR was wrongly flagged "⚠️ Cross-team review request from adolfopa". Before trusting a cross-team flag, cross-check the author against `Team Slack Names` and the sprint issues' assignees; if they clearly belong to the team, the roster is stale — add them to `Team GitHub Logins` rather than accepting the flag at face value. `Adolfo Pérez: adolfopa` has been added to the roster.

Every suppression (rules 1 and 2) is logged in the Excluded list for audit.

**Slack Needs Owner rows sit above everything else in 2a. Needs Owner** (above even cross-team PRs), sorted oldest-first among themselves — an unanswered public-channel question is the most visible kind of dropped ball. This routing is entirely inside `headless_daily_report.py` (`--slack-data-file`); nothing about PR/issue routing changes when Slack rows are present or absent.

**Subtask→parent resolution:** the sprint query fetches the `subtasks` field so a PR linked to a subtask of an in-sprint issue resolves to that parent **offline** (no live Jira call), ensuring rule 1 fires reliably. Claude should still pre-resolve `parent_key` in `pr_data.json` during data collection as the primary path.

### Confluence Page (after approval only)

After the user reviews the HTML and explicitly approves, re-run the script with `--publish`. The published page must have: full-width tables, issue cells as smart links / inline cards, priority cells as coloured status badges, assignee cells as @mentions, and the Test section rendered as a Confluence Include Page macro (never a table or bullet list). The shared context page (via `WORK_DIR/context_scratch.md`, synced back per Workflow → 3.1) must be updated with today's State Snapshot date.

## Workflow

### 0. Sync Shared Context from Confluence (v2.0.0+ — do this first, every run)

1. `getConfluencePage(context_page_id)` (see Shared Context Storage above for the ID, and the one-time bootstrap if it's not set up yet).
2. Write the page's content verbatim to `WORK_DIR/context_scratch.md`.
3. Use that path everywhere this doc says `WORK_DIR/context_scratch.md` — `--sprint-context-file` for `headless_daily_report.py`, `--sprint-context` for `assemble_slack_data.py`.

If the fetch fails (page missing, MCP unavailable), stop and tell the user — do not silently fall back to a local `project_current_sprint.md` copy from a previous run, since that's exactly the staleness problem this change fixes.

### 1. Fetch and Build

Run the three Jira MCP queries **sequentially** (see Jira Sprint Data above). Then, **before** building `jira_data.json`, pre-fetch changelogs (step 1a below) for the issues that will need them. Then build `jira_data.json` with `assemble_jira_data.py`. PR scraping and Slack scraping (step 1b below) are both independent of the MCP queries and of each other — they may overlap freely. Write the JSON files (`jira_data.json`, `pr_data.json`, and `slack_data.json` if collected) to `WORK_DIR`. Run the script without `--publish`.

**Before any of this, in a Cowork/sandboxed session:** pass `--output-dir WORK_DIR` (see "Read-only skill mounts" in Configuration above) to every `headless_daily_report.py` call in this section and the ones that follow. Skipping this means the HTML-preview run at the end of this section will fail with a read-only filesystem error after all the data collection is already done.

#### 1a. Pre-fetch changelogs via the Atlassian MCP (required, not optional)

**Do this on every run — do not skip it and fall back to letting `headless_daily_report.py` fetch changelogs itself.** The script's own direct-HTTPS fallback (`jira_get_issue(expand="changelog")`) is routinely blocked by the sandbox's proxy, which is exactly what caused missing "Days in Progress" values in past runs (rows silently fell back to just the status name, or — after the 2026-07-08 fix — show `"(days unknown — changelog unavailable)"`). Fetching via the MCP here avoids that failure mode entirely.

1. From the sprint issues just loaded, identify the **Section-1 candidates**: every LPD, LPP, BPR, and PTR issue in an in-progress-like status — these are the issues whose "Days in Progress" cell depends on `get_first_active_date()`. Use the exact status sets the script itself uses (`SECTION1_STATUSES` in `headless_daily_report.py`), not an abbreviated version — under-listing this caused a real miss on 2026-07-13 (LPD-97411, status "In Review", fell through the gap because this list only mentioned "In Development/In Progress"):
   - **LPD**: in progress, in development, escalated, in product review, ready for product review, in review — all six, not just the first two. (2026-07-13: LPD issues past development now track "days in current status" — e.g. "3d in review" — rather than days since development started; see `get_first_active_date()`'s LPD branch. The changelog is needed either way, so pre-fetch for all six statuses regardless.)
   - **LPP**: any status past In Queue.
   - **BPR**: Original Fix Committed or later.
   - **PTR** (2026-07-13): any non-Answered status kept by Rule 6b (see "Deduplication rules" below) — though in practice PTR's "days open" always falls back to `issue["created"]`, so pre-fetching its changelog isn't required for the Days cell; only fetch it if some other feature needs PTR history.
2. For each candidate, call `getJiraIssue` with `expand: "changelog"` via the Atlassian MCP and collect `changelog.histories` into a dict keyed by issue key: `{"LPD-12345": [...histories...], ...}`.
3. Write that dict to a JSON file in `/tmp/` (e.g. `/tmp/changelogs.json`). **If `/tmp/` already has a file at that name owned by another user (seen in some sandboxes — a stale, unrelated file causes a `PermissionError` on overwrite), write to a writable path inside `WORK_DIR` instead and use that path in the next step; don't fight for `/tmp/` specifically.**
4. Pass it to the assembler with `--changelog-file /tmp/changelogs.json` (or the `WORK_DIR` path if you redirected per the note above) — it gets merged into `jira_data.json`'s `changelogs` field automatically (see Data Files below).

If an individual `getJiraIssue` call fails for a given issue, skip just that one (log it) and continue — do not abort the whole pre-fetch. A handful of individual failures is fine; the script's HTTPS fallback and the 2026-07-08 fetch-failure labeling still cover any gaps.

**Temp files:** Any intermediate files created during this step (chunks, payloads, etc.) must be written to `/tmp/` — never to `SKILL_DIR` or `WORK_DIR` — **except** where the `/tmp/` permission note just above applies.

#### 1b. Slack Needs Owner (run by default — Chrome MCP only — see "Slack Needs Owner" under Input above)

Scan → open each candidate thread that needs it → classify. This runs on every report by default. Only skip it (omit `--slack-data-file`) if Chrome MCP isn't available, or the user has explicitly said to skip it for this run — and flag that decision to the user before the approval gate, not only in the post-publish summary (2026-07-15 incident: a silent skip missed a real unanswered thread).

### 2. Approval Gate

Present the HTML link and a **data quality summary** to the user before asking for approval. The summary must include:

- Sprint issues count (e.g. "47 sprint issues loaded")
- How many have a non-empty Topic/summary (e.g. "47/47 have summaries ✅" or "0/47 have summaries ❌")
- How many have a t-shirt size in `customfield_10804` (e.g. "12/47 have t-shirt size")
- Section counts: In Progress (N), Assigned (N — including PRs with a human reviewer at the top), Needs Owner (N — including no-reviewer PRs and unanswered Slack threads at the top), Excluded (N)
- Any fields that were null/missing across the board (flag these explicitly)

If any data quality issue is present (empty summaries, missing sprint field, missing t-shirt sizes for most issues), warn the user **before** they open the HTML:
> ⚠️ Data quality issues detected: [list them]. The report may have empty Topics, wrong Days in Queue, or incorrect issue inclusion. Consider retrying in a fresh session for a clean run.

Ask them to open the file in their browser and confirm it looks correct before publishing. **Do not proceed to step 3 without explicit approval.**

⚠️ **Token budget check:** Before asking for approval, count the approximate number of tool calls made so far in this session. If it exceeds 40, warn the user explicitly:

> "⚠️ This session has made many tool calls and may be near its token limit. You can safely stop here — when `--publish` runs it writes `adf_output.json`, `publish_adf_loader.js`, `publish_snippet.js`, and `publish_<sprint>_console.js` to your project folder, and the browser publish (section 3) can be done at any time. Do you want to continue or start a fresh session for the publish step?"

Let the user decide. Do not proceed to step 3 unless the user explicitly confirms.

### 3. Publish (in the user's authenticated browser)

Direct HTTPS from the sandbox to `liferay.atlassian.net` is always proxy-blocked (ProxyError 403), so the script never publishes over the network. Publishing happens in the user's authenticated browser, which bypasses the proxy. Run the script with `--publish --sprint-context-file WORK_DIR/context_scratch.md`. It does **not** attempt a network PUT — it writes four files to `SKILL_DIR` (or, per the read-only-mount workaround above, to whatever writable copy of the skill folder you ran the script from):

- `adf_output.json` — the validated ADF document. **This is the file the browser uploads** (it can be 150KB+).
- `publish_adf_loader.js` — a tiny snippet (~250 bytes) that creates a hidden file input `#__adf_input` on the page.
- `publish_snippet.js` — a small snippet (~1.4KB) that reads the uploaded ADF and PUTs it with `?notifyWatchers=false`.
- `publish_<sprint>_console.js` — the self-contained manual-paste fallback (embeds the ADF inline, so it is large).

#### 3a. Automatic path (preferred — no DevTools, no manual paste)

This is the default path whenever Chrome MCP is connected. The large ADF travels by **file upload**, so it never passes through Claude's context — which is what previously forced the manual paste (the self-contained `.js` was too large to inject). Steps:

1. Open the page in the user's browser: `https://liferay.atlassian.net/wiki/spaces/ENGHEADLESS/pages/<actions_report_page_id>` (confirm the user is authenticated).
2. Run the contents of `publish_adf_loader.js` via `javascript_tool` (creates the hidden `#__adf_input`).
3. Locate `#__adf_input` with `find`, then use the Chrome **`file_upload`** tool to upload `adf_output.json` into it. **If `find` fails to locate the hidden input (seen 2026-07-31 — `find` and `read_page filter="all"` both returned empty results on a large/complex page), fall back to `read_page` with `filter="all"` and a shallow `depth` (e.g. `depth: 2`) instead of the default — this reliably surfaces the hidden `<input type="file">` as a `button [ref_N] type="file"` entry even when the unrestricted call times out or comes back empty.**
4. Run the contents of `publish_snippet.js` via `javascript_tool`.
5. Confirm the result is `{ status: 200, ok: true, newVersion: N }`. **If the `javascript_tool` call itself returns an empty `{}` instead of the expected object (seen 2026-07-31 — the async IIFE's return value didn't come through), don't treat that as failure: check `read_console_messages` (pattern `"PUBLISH RESULT"`) for the logged result, and/or independently re-fetch `GET /wiki/rest/api/content/<page_id>?expand=version` and confirm the version number and `version.when` timestamp advanced to just now.**

Publishing the report to Confluence is publishing content on the user's behalf — only do it after the user has reviewed the HTML and approved (the Approval Gate in step 2).

#### 3b. Manual fallback (only if Chrome MCP is unavailable)

1. Open the page: `https://liferay.atlassian.net/wiki/spaces/ENGHEADLESS/pages/<actions_report_page_id>`
2. Open DevTools Console (Mac: Cmd+Option+J · Win/Linux: Ctrl+Shift+J)
3. If prompted, type `allow pasting` and press Enter
4. Paste the entire contents of `publish_<sprint>_console.js`, then press Enter.
5. The console prints `=== PUBLISH RESULT === { status: 200, ok: true, newVersion: N }`.

Verify the result against the checklist in **Expected Output → Confluence Page**.

⛔ Do not use the `updateConfluencePage` MCP tool — it does not support `?notifyWatchers=false` and silently drops full-width ADF table layout. The browser (file-upload + snippet, or console paste) is the working transport.

**On any failure:** Stop immediately. Report the exact error message and step to the user. Do not attempt silent recovery, retries, or workarounds without explicit instruction. If the run produces a Python traceback rather than the publish files, report the error message and function name and stop.

#### 3.1. After the browser publish succeeds

Only after the publish returns HTTP 200:

1. Re-run `headless_daily_report.py` with the same data files plus `--confirm-publish --sprint-context-file WORK_DIR/context_scratch.md`. This updates `WORK_DIR/context_scratch.md` in place: State Snapshot date → today, issue statuses → current Jira state, and `latest_skill_version` → this copy's `SKILL_VERSION`.
2. Read the updated `WORK_DIR/context_scratch.md` and call `updateConfluencePage(context_page_id, content)` to push it to the shared context page (contentFormat markdown — this is a plain data page, not the ADF report, so the ⛔ restriction in Workflow → 3b doesn't apply here). **Before pushing, do a quick sanity check for a duplicate `## Section Name` heading anywhere in the file (a defense-in-depth check — the 2.1.1 parser fix above should prevent this, but if a heading ever appears twice, keep only the most recent occurrence before pushing).**
