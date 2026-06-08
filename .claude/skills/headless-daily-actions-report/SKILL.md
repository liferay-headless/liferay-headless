---

allowed-tools: [Bash, Read, Write, mcp__373e0a15-d392-4d06-83a8-e087f4fce44f__searchJiraIssuesUsingJql, mcp__373e0a15-d392-4d06-83a8-e087f4fce44f__getJiraIssue, mcp__373e0a15-d392-4d06-83a8-e087f4fce44f__getConfluencePage, mcp__Claude_in_Chrome__navigate, mcp__Claude_in_Chrome__get_page_text, mcp__Claude_in_Chrome__javascript_tool, mcp__Claude_in_Chrome__computer]
description: Generates and publishes the Headless team’s Daily Actions Report. Use this skill whenever the user asks to run, generate, build, or publish the daily actions report, the headless report, or mentions headless_daily_report.py.
name: headless-daily-actions-report

---

# Headless Daily Actions Report

Fetch fresh data from Jira, GitHub, and Testray; build an HTML preview; get approval; then publish to Confluence.

## Configuration

After installing this skill, set these two paths to match the installer’s machine:

- **`SKILL_DIR`** — the folder where this skill was installed (contains `headless_daily_report.py`)
- **`WORK_DIR`** — the folder where scratch files (`jira_data.json`, `pr_data.json`, `testing_panel.json`) will be written during a run (can be the same as `SKILL_DIR`)

The script reads Atlassian and GitHub credentials from a `.env` file in `SKILL_DIR`. Create it if it doesn’t exist:

```
ATLASSIAN_EMAIL=your@email.com
ATLASSIAN_TOKEN=your_atlassian_api_token
GITHUB_TOKEN=your_github_token
```

## Preconditions

- `SKILL_DIR/headless_daily_report.py` exists
- `SKILL_DIR/headless-daily-actions-report/project_current_sprint.md` exists and has a current Sprint Metadata section
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

Read only the **Sprint Metadata** section of `SKILL_DIR/headless-daily-actions-report/project_current_sprint.md` (sprint label, start/end dates, `actions_report_page_id`, `report_page_title`). Fail fast if the file is missing or the section is absent.

### Jira Sprint Data

Three parallel MCP queries via `searchJiraIssuesUsingJql`:

- **Sprint issues** — JQL: `filter=54796 AND status not in (Closed,Completed,Resolved,Answered)`, maxResults 100, fields: `key, summary, status, assignee, labels, issuetype, priority, project, updated, created, duedate, comment, customfield_10804, customfield_10168, parent, customfield_10001, customfield_10020, issuelinks`
- **SEV bugs** — JQL: `project=LPD AND issuetype=Bug AND "Cross Cutting Properties[Checkboxes]" = "Security Vulnerability" AND status not in (closed)`
- **SEV BPRs** — JQL: `filter=15069 AND status not in (closed)`

Derive from the results:
- `sev_keys`: all keys from SEV bugs
- `sev_zero_day_keys`: SEV bug keys that carry the label `zero-day-vulnerability`
- `sev_bpr_keys`: all keys from SEV BPRs

### Open Pull Requests

Scrape `https://github.com/liferay-headless/liferay-portal/pulls?q=is:pr+is:open+draft:false` via Chrome MCP.

For each listed PR, open its page and confirm the green **"Open"** badge is present (discard Closed/Merged). Collect per PR: number, title, author, opening date (YYYY-MM-DD), linked Jira key (pattern `LPD-NNNN` or `LPP-NNNN` from title or branch), reviewer (ignore the `liferay-headless` bot — treat bot-only as no reviewer), and reviewer status (pending / approved / changes_requested).

Set `parent_key` and `lpp_fix_key` to `null` — the script resolves them.

**PR parent resolution:** build `sprint_keys` from the Jira sprint issues. For any PR whose `jira_key` is not in `sprint_keys`, call `getJiraIssue` (fields: `parent`, `issuetype`) and set `parent_key` to the parent’s key if one exists. Run these lookups in parallel. If a PR has no parseable Jira key, flag it in chat and skip it.

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

**`jira_data.json`**
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
  "reviewer": "jaimelr10",
  "reviewer_status": "changes_requested",
  "url": "https://github.com/liferay-headless/liferay-portal/pull/3811",
  "draft": false
}
```

**`testing_panel.json`**
```json
{"investigation": 101, "acceptance": 18, "all_bugs": 186, "fp4_fp5": 2, "no_fp": 12}
```

### HTML Preview

Run `headless_daily_report.py` from `SKILL_DIR` **without** `--publish`, passing the three data files from `WORK_DIR`. After it completes, report: section row counts, excluded count, standalone PR count, link to the generated HTML file, and any warnings or changelog fetch failures.

### Confluence Page (after approval only)

After the user reviews the HTML and explicitly approves, re-run the script with `--publish`. The published page must have: full-width tables, issue cells as smart links / inline cards, priority cells as coloured status badges, assignee cells as @mentions, and the Tests section rendered as a bullet list (not a table). `project_current_sprint.md` must be updated with today’s State Snapshot date.

## Workflow

### 1. Fetch and Build

Fetch all inputs in parallel where possible (Jira queries, PR scraping, Testray, Jira JS counts are independent). Write the three JSON files to `WORK_DIR`. Run the script without `--publish`.

**Temp files:** Any intermediate files created during this step (chunks, payloads, etc.) must be written to `/tmp/` — never to `SKILL_DIR` or `WORK_DIR`.

### 2. Approval Gate

Present the HTML link and run summary to the user. Ask them to open the file in their browser and confirm it looks correct before publishing. **Do not proceed to step 3 without explicit approval.**

⚠️ **Token budget check:** Before asking for approval, count the approximate number of tool calls made so far in this session. If it exceeds 40, warn the user explicitly:

> "⚠️ This session has made many tool calls and may be near its token limit. If publishing fails mid-way, recovery may not be possible in this session. You can safely stop here — `adf_output.json` will be saved to your project folder when `--publish` runs, and the fallback publish (section 3.1) can be run in a fresh session. Do you want to continue or start a fresh session for the publish step?"

Let the user decide. Do not proceed to step 3 unless the user explicitly confirms.

### 3. Publish

Run the script with `--publish`. The script saves `adf_output.json` to `SKILL_DIR` before attempting the network PUT — this file is the fallback source if the call fails.

Verify the result against the checklist in **Expected Output → Confluence Page**.

**On any failure:** Stop immediately. Report the exact error message and step number to the user. Do not attempt silent recovery, retries, or workarounds without explicit instruction.

#### 3.1. Publish Fallback (ProxyError or network failure only)

If the script’s publish step fails with a network error (ProxyError, ConnectionError, timeout):

⛔ Do not use the `updateConfluencePage` MCP tool — it does not support `?notifyWatchers=false` and silently drops full-width ADF table layout.

✅ Instead, publish via `javascript_tool` from a `liferay.atlassian.net` Chrome tab using the exact script below.

**Preparation:**
1. Read `SKILL_DIR/adf_output.json` via bash — it was saved by the script before the failed PUT.
2. Fetch the current page version via `getConfluencePage` MCP.
3. Fill in the four constants and run as a single `javascript_tool` call.

```javascript
// Run this in javascript_tool from a liferay.atlassian.net Chrome tab.

const PAGE_ID     = "<actions_report_page_id>";   // from project_current_sprint.md
const PAGE_TITLE  = "<confluence_page_title>";     // from SprintContext
const NEW_VERSION = <current_version + 1>;         // fetched via getConfluencePage MCP
const ADF_JSON    = <contents of adf_output.json as a JS object literal>;

const resp = await fetch(
  `/wiki/rest/api/content/${PAGE_ID}?notifyWatchers=false`,
  {
    method: "PUT",
    headers: { "Content-Type": "application/json", "X-Atlassian-Token": "no-check" },
    body: JSON.stringify({
      type: "page",
      title: PAGE_TITLE,
      version: { number: NEW_VERSION, minorEdit: true },
      body: {
        atlas_doc_format: {
          value: JSON.stringify(ADF_JSON),
          representation: "atlas_doc_format"
        }
      }
    })
  }
);
const result = await resp.json();
return { status: resp.status, version: result?.version?.number, ok: resp.ok };
```

**To inject `ADF_JSON`:** read `adf_output.json` via bash, then pass the parsed content as the JS object literal. Do **not** split into chunks or write any intermediate files to `SKILL_DIR`.

After a successful JS publish (HTTP 200), manually update `project_current_sprint.md`: State Snapshot date → today, issue statuses → current Jira state, Testing Panel Baseline → today’s counts.

If the failure is a traceback rather than a network error, report the error message and function name to the user and stop. Do not re-read the script.
