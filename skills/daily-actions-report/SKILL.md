---

allowed-tools: [Bash, Read, Write, mcp__373e0a15-d392-4d06-83a8-e087f4fce44f__searchJiraIssuesUsingJql, mcp__373e0a15-d392-4d06-83a8-e087f4fce44f__getJiraIssue, mcp__373e0a15-d392-4d06-83a8-e087f4fce44f__getConfluencePage, mcp__Claude_in_Chrome__navigate, mcp__Claude_in_Chrome__get_page_text, mcp__Claude_in_Chrome__javascript_tool, mcp__Claude_in_Chrome__computer]
description: Generates and publishes the Headless team's Daily Actions Report. Use this skill whenever the user asks to run, generate, build, or publish the daily actions report, the headless report, or mentions headless_daily_report.py.
name: daily-actions-report

---

# Headless Daily Actions Report

Fetch fresh data from Jira, GitHub, and Testray; build an HTML preview; get approval; then publish to Confluence.

## Configuration

After installing this skill, set these two paths to match the installer's machine:

- **`SKILL_DIR`** — the folder where this skill was installed (contains `headless_daily_report.py`)
- **`WORK_DIR`** — the folder where scratch files (`jira_data.json`, `pr_data.json`, `testing_panel.json`) will be written during a run (can be the same as `SKILL_DIR`)

The script reads Atlassian and GitHub credentials from a `.env` file in `SKILL_DIR`. Create it if it doesn't exist:

```
ATLASSIAN_EMAIL=your@email.com
ATLASSIAN_TOKEN=your_atlassian_api_token
GITHUB_TOKEN=your_github_token
```

## Preconditions

- `SKILL_DIR/headless_daily_report.py` exists
- `SKILL_DIR/assemble_jira_data.py` exists (builds and validates `jira_data.json` from MCP result files)
- `SKILL_DIR/daily-actions-report/project_current_sprint.md` exists and has a current Sprint Metadata section, and a `Team GitHub Logins` JSON section (display name → GitHub login) used for cross-team PR detection (dedup rule 3). Source it from the team page: https://liferay.atlassian.net/wiki/spaces/ENGHEADLESS/overview — keep it in sync when the roster changes. If the section is missing/empty, cross-team detection silently does nothing.
- `SKILL_DIR/.env` exists with valid `ATLASSIAN_EMAIL`, `ATLASSIAN_TOKEN`, and `GITHUB_TOKEN`
- Chrome MCP is available (required for GitHub PR scraping and Testray screenshots)
- The Atlassian MCP is available (cloudId: `5d1aaa67-5d5e-4cca-b668-33b9742cfb4a`)

## Permanent Page Policy

**The Daily Actions Report uses a single permanent Confluence page — forever.**

- `actions_report_page_id` is set once and **never changes**, not even when rolling to a new sprint or a new release cycle.
- `report_page_title` is the fixed Confluence page title. It also never changes.
- Every daily run PUTs fresh content to this same page. The page header, sprint label, dates, and remaining days are all updated in the content body — but the page ID and title stay constant.
- When rolling to a new sprint (e.g. DEV#12 → DEV#13), update only: `sprint_label`, `sprint_field`, `label_dev`, `label_dis`, `start_date`, `end_date`, and the State Snapshot / Testing Panel Baseline / PR Snapshot sections. **Do not touch `actions_report_page_id` or `report_page_title`.**
- Confluence version history is unlimited — every past daily run is preserved and browsable via the page history.

## Input

### Sprint Metadata

Read only the **Sprint Metadata** section of `SKILL_DIR/daily-actions-report/project_current_sprint.md` (sprint label, start/end dates, `actions_report_page_id`, `report_page_title`). Fail fast if the file is missing or the section is absent.

**`sprint_field` vs `sprint_label` — do not confuse them.** `sprint_label` (e.g. `26M2|DEV#13|Jun15-Jun26`) is the shared iteration label used by **every** product team — it is for display only (report header/filename) and must never be used to identify Headless work. `sprint_field` is the real Jira Sprint value (`customfield_10020`) and **must start with `HL`** (e.g. `HL26M2|DEV#13|Jun15-Jun26`); it is the only reliable signal of Headless team ownership. The loader now **requires** `sprint_field` and **fails loudly** if it is missing or does not start with `HL` (no silent fallback to the label). When rolling sprints, update both — and make sure `sprint_field` keeps its `HL` prefix.

### Jira Sprint Data

Three MCP queries via `searchJiraIssuesUsingJql` — **run them SEQUENTIALLY, never in parallel.** Parallel Jira MCP calls have returned crossed/duplicated responses (two different queries answered with the same cached payload), which produced a wrong report two days in a row in June 2026.

- **Sprint issues** — JQL: `filter=54796 AND status not in (Closed,Completed,Resolved,Answered)`, maxResults 100, fields: `key, summary, status, assignee, labels, issuetype, priority, project, updated, created, duedate, comment, customfield_10804, customfield_10168, parent, customfield_10001, customfield_10020, issuelinks`
- **SEV bugs** — JQL: `project=LPD AND issuetype=Bug AND "Cross Cutting Properties[Checkboxes]" = "Security Vulnerability" AND status not in (closed)`
- **SEV BPRs** — JQL: `filter=15069 AND status not in (closed)`

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

Set `parent_key` and `lpp_fix_key` to `null` — the script resolves them.

**PR parent resolution:** build `sprint_keys` from the Jira sprint issues. For any PR whose `jira_key` is not in `sprint_keys`, call `getJiraIssue` (fields: `parent`, `issuetype`) and set `parent_key` to the parent's key if one exists. Run these lookups in parallel. If a PR has no parseable Jira key, flag it in chat and skip it.

### Testing Panel

**Testray (via Chrome MCP + screenshot):**

- **Investigation count:** latest build matching `[master] ci:test:headless` at `https://testray.liferay.com/web/testray#/project/35392/routines/994140` → screenshot the "Total test cases" chart → record the FAILED (red) count.
- **Acceptance count:** latest build matching `EE Development Acceptance (master)` on the same page, with the Headless team filter applied (`testrayTeamIds=[45740]`) → same chart → FAILED count.

**Jira bug counts (browser JS only — never use the Atlassian MCP for these):**

The MCP uses its own credentials and returns wrong totals for these filters. Run the following as a `javascript_tool` call from any `liferay.atlassian.net` Chrome tab and collect the three counts:

- Filter `15065` → `all_bugs`
- Filter `45383` → `fp4_fp5`
- Filter `45384` → `no_fp`

Paginate using `nextPageToken` until `isLast` is true (max 50 pages per filter). If the JS call fails entirely, use `null` — the script will render N/A.

## Expected Output

### Data Files

Three JSON files written to `WORK_DIR` before the script runs. Regenerate all three on every run — never reuse stale files from a previous run.

**`jira_data.json`** — always generated by `assemble_jira_data.py`, never hand-crafted:
```json
{
  "sprint_issues": [ ...raw issue objects from sprint query... ],
  "sev_keys": [...],
  "sev_zero_day_keys": [...],
  "sev_bpr_keys": [...]
}
```

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

**`testing_panel.json`**
```json
{"investigation": 101, "acceptance": 18, "all_bugs": 186, "fp4_fp5": 2, "no_fp": 12}
```

### HTML Preview

Run `headless_daily_report.py` from `SKILL_DIR` **without** `--publish`, passing the three data files from `WORK_DIR`. After it completes, report: section row counts, excluded count, the per-section PR counts (PRs routed to the top of 2a. Assigned and 2b. Needs Owner), link to the generated HTML file, and any warnings or changelog fetch failures.

**Open PRs routing:** There is no separate Pick Up Next PR table. Open PRs route into a Section 2 table and sort to the top, ahead of issue rows, based on whether the PR has an **owner**: a human reviewer, OR a human GitHub assignee other than the PR's own author. (Self-assignment — the author assigning the PR to themselves — is the default/trivial case on GitHub and does not count as someone else having picked it up; an assignee only counts when it's a *different* person from the author.) PR with an owner → top of 2a. Assigned (longest-open first); PR with no owner at all (no reviewer and no non-author assignee) → top of 2b. Needs Owner (longest-open first). PRs with no parseable Jira key are flagged in chat and skipped.

> **2026-07-08 fix:** this rule used to look only at `reviewer` and missed PRs that had a real assignee but no reviewer requested yet (they were wrongly parked in 2b). See `CHANGELOG-fixes-2026-07-08.md` for the full story and the exact `has_owner` logic in `fetch_open_prs()` / the standalone-PR routing block in `headless_daily_report.py`.

**Section 1 (In Progress) visibility gate — an issue can be structurally eligible and still not appear:** being in an in-progress status for LPD/LPP is necessary but not sufficient. `evaluate_triggers()` also requires at least one *actionable* trigger — a status change, an assignee change, a new comment since the last snapshot, a PR needing action, or a staleness/age threshold crossed — or the issue is silently dropped from Section 1 (deliberately, to keep the section from being 40 rows of "nothing changed"). This is by design, but it has a known gap pattern: an issue with **no fresh event** (no new comment, no status/assignee change) is invisible even if it has been sitting for weeks, unless age itself is wired up as a trigger for that project.

- **LPD** has always had an age-based trigger (Trigger 7): `LPD_ORANGE_THRESHOLD` / `LPD_RED_THRESHOLD` (by t-shirt size) — days since creation alone is enough to surface a long-running LPD even with no other activity.
- **LPP did not have this until 2026-07-08.** `LPP-64236` (40 days old, in analysis, no trigger otherwise since its only comment landed the same day as a snapshot) was silently gated out of Section 1 despite being exactly the kind of stale, long-lived item that needs visibility. Fixed by adding **Trigger 7b**: any LPP older than `LPP_ORANGE_THRESHOLD` (10 days) or `LPP_RED_THRESHOLD` (19 days) now surfaces with `"{N}d in progress — check for blockers"`, mirroring LPD's Trigger 7. See `CHANGELOG-fixes-2026-07-08.md`.
- **If a future report seems to be missing a long-lived issue that "should obviously be there":** check whether its project has an age-based trigger at all before assuming the exclusion or tier logic is at fault — a missing age trigger is easy to miss because the issue looks correctly *classified*, just invisible.

**Deduplication rules (June 2026 — no PR appears twice):**

1. **PR shown under an In Progress issue is not repeated in Pick Up Next.** If a PR is attached to a Section 1 (In Progress) issue *and actually renders there* (it emits Trigger-5 action text — i.e. it is awaiting review, has changes requested, or has no reviewer), it is suppressed from Pick Up Next. The comment under the issue row is enough. **Exception:** an *approved* PR emits no Trigger-5 text (nothing to action on the issue side), so it does NOT render under the issue — such a PR therefore still appears in Pick Up Next 2a as "Approved — ready to merge". Never suppress a PR that isn't actually displayed under its issue, or it vanishes entirely.

2. **LPD that fixes an in-scope LPP is shown only on the LPP line.** When an in-scope LPP has an "is fixed by" issuelink to an in-scope LPD (or a PR carries `lpp_fix_key`), the LPD is suppressed as its own row; its PR(s) are re-homed under the LPP row and the LPP renders "Fix: LPD-XXXX". The LPD does not get a separate line.

3. **Cross-team PR (unplanned work from another team) appears only as a flagged Pick Up Next row.** Team ownership is decided by the **PR author's GitHub login** checked against the `Team GitHub Logins` roster in `project_current_sprint.md` — NOT by the issue's sprint label (all teams share the same iteration labels). A PR whose author is not on the roster is pinned to the **top of 2b. Needs Owner** as a standalone row flagged "⚠️ Cross-team review request from {author}", regardless of whether it has a reviewer. Its linked LPD is kept out of In Progress by the existing non-Headless exclusion (which keys off the sprint field starting with `HL`).

Every suppression (rules 1 and 2) is logged in the Excluded list for audit.

**Subtask→parent resolution:** the sprint query fetches the `subtasks` field so a PR linked to a subtask of an in-sprint issue resolves to that parent **offline** (no live Jira call), ensuring rule 1 fires reliably. Claude should still pre-resolve `parent_key` in `pr_data.json` during data collection as the primary path.

### Confluence Page (after approval only)

After the user reviews the HTML and explicitly approves, re-run the script with `--publish`. The published page must have: full-width tables, issue cells as smart links / inline cards, priority cells as coloured status badges, assignee cells as @mentions, and the Tests section rendered as a bullet list (not a table). `project_current_sprint.md` must be updated with today's State Snapshot date.

## Workflow

### 1. Fetch and Build

Run the three Jira MCP queries **sequentially** (see Jira Sprint Data above), then build `jira_data.json` with `assemble_jira_data.py`. PR scraping, Testray, and the Jira JS counts are independent of each other and of the MCP queries — those may overlap freely. Write the three JSON files to `WORK_DIR`. Run the script without `--publish`.

**Temp files:** Any intermediate files created during this step (chunks, payloads, etc.) must be written to `/tmp/` — never to `SKILL_DIR` or `WORK_DIR`.

### 2. Approval Gate

Present the HTML link and a **data quality summary** to the user before asking for approval. The summary must include:

- Sprint issues count (e.g. "47 sprint issues loaded")
- How many have a non-empty Topic/summary (e.g. "47/47 have summaries ✅" or "0/47 have summaries ❌")
- How many have a t-shirt size in `customfield_10804` (e.g. "12/47 have t-shirt size")
- Section counts: In Progress (N), Assigned (N — including PRs with a human reviewer at the top), Needs Owner (N — including no-reviewer PRs at the top), Excluded (N)
- Any fields that were null/missing across the board (flag these explicitly)

If any data quality issue is present (empty summaries, missing sprint field, missing t-shirt sizes for most issues), warn the user **before** they open the HTML:
> ⚠️ Data quality issues detected: [list them]. The report may have empty Topics, wrong Days in Queue, or incorrect issue inclusion. Consider retrying in a fresh session for a clean run.

Ask them to open the file in their browser and confirm it looks correct before publishing. **Do not proceed to step 3 without explicit approval.**

⚠️ **Token budget check:** Before asking for approval, count the approximate number of tool calls made so far in this session. If it exceeds 40, warn the user explicitly:

> "⚠️ This session has made many tool calls and may be near its token limit. You can safely stop here — when `--publish` runs it writes `adf_output.json`, `publish_adf_loader.js`, `publish_snippet.js`, and `publish_<sprint>_console.js` to your project folder, and the browser publish (section 3) can be done at any time. Do you want to continue or start a fresh session for the publish step?"

Let the user decide. Do not proceed to step 3 unless the user explicitly confirms.

### 3. Publish (in the user's authenticated browser)

Direct HTTPS from the sandbox to `liferay.atlassian.net` is always proxy-blocked (ProxyError 403), so the script never publishes over the network. Publishing happens in the user's authenticated browser, which bypasses the proxy. Run the script with `--publish`. It does **not** attempt a network PUT — it writes four files to `SKILL_DIR`:

- `adf_output.json` — the validated ADF document. **This is the file the browser uploads** (it can be 150KB+).
- `publish_adf_loader.js` — a tiny snippet (~250 bytes) that creates a hidden file input `#__adf_input` on the page.
- `publish_snippet.js` — a small snippet (~1.4KB) that reads the uploaded ADF and PUTs it with `?notifyWatchers=false`.
- `publish_<sprint>_console.js` — the self-contained manual-paste fallback (embeds the ADF inline, so it is large).

#### 3a. Automatic path (preferred — no DevTools, no manual paste)

This is the default path whenever Chrome MCP is connected. The large ADF travels by **file upload**, so it never passes through Claude's context — which is what previously forced the manual paste (the self-contained `.js` was too large to inject). Steps:

1. Open the page in the user's browser: `https://liferay.atlassian.net/wiki/spaces/ENGHEADLESS/pages/<actions_report_page_id>` (confirm the user is authenticated).
2. Run the contents of `publish_adf_loader.js` via `javascript_tool` (creates the hidden `#__adf_input`).
3. Locate `#__adf_input` with `find`, then use the Chrome **`file_upload`** tool to upload `adf_output.json` into it.
4. Run the contents of `publish_snippet.js` via `javascript_tool`.
5. Confirm the result is `{ status: 200, ok: true, newVersion: N }`.

Publishing the report to Confluence is publishing content on the user's behalf — only do it after the user has reviewed the HTML and approved (the Approval Gate in step 2).

#### 3b. Manual fallback (only if Chrome MCP is unavailable)

1. Open the page: `https://liferay.atlassian.net/wiki/spaces/ENGHEADLESS/pages/<actions_report_page_id>`
2. Open DevTools Console (Mac: Cmd+Option+J · Win/Linux: Ctrl+Shift+J).
3. If prompted, type `allow pasting` and press Enter.
4. Paste the entire contents of `publish_<sprint>_console.js`, then press Enter.
5. The console prints `=== PUBLISH RESULT === { status: 200, ok: true, newVersion: N }`.

Verify the result against the checklist in **Expected Output → Confluence Page**.

⛔ Do not use the `updateConfluencePage` MCP tool — it does not support `?notifyWatchers=false` and silently drops full-width ADF table layout. The browser (file-upload + snippet, or console paste) is the working transport.

**On any failure:** Stop immediately. Report the exact error message and step to the user. Do not attempt silent recovery, retries, or workarounds without explicit instruction. If the run produces a Python traceback rather than the publish files, report the error message and function name and stop.

#### 3.1. After the browser publish succeeds

Only after the publish returns HTTP 200, update `project_current_sprint.md`: State Snapshot date → today, issue statuses → current Jira state, Testing Panel Baseline → today's counts. Do **not** update these caches before the browser publish succeeds — `--publish` only generates the files; it does not change the page.
