# Daily Actions Report — Setup Guide (Headless Team)

This lets anyone on the Headless team run the Daily Actions Report — not just
Nóra. Useful for PTO cover, but also just for spreading ownership. Work
through this once per person/machine; after that, running it is just "run the
daily actions report" in Claude.

---

## Prerequisites

Each person who wants to run this needs, on their own machine/account:

- Claude (desktop app or Cowork) with two connections active:
  - **Atlassian MCP**, connected to `liferay.atlassian.net` (cloudId
    `5d1aaa67-5d5e-4cca-b668-33b9742cfb4a`) — used for all Jira reads and,
    during publish, the Confluence page.
  - **Chrome MCP**, with the person **logged into their own accounts** for:
    - `github.com` (read access to `liferay-headless/liferay-portal`) — PRs
      are scraped from the authenticated PR pages, no GitHub token needed.
    - `liferay.atlassian.net` — required for the publish step (Section 3),
      since the actual page update happens via the runner's own authenticated
      browser session, not an API call.
    - `liferay.slack.com` — for the Slack Needs Owner scrape of
      `#t-dxp-headless` (there's no Slack connector for this org, so this is
      Chrome-scraped like GitHub).
- Python 3.10+ with `requests` installed (`pip install requests --break-system-packages`).

No GitHub token, Slack token, or Atlassian API token is required to run a
normal report — everything above goes through the runner's own logged-in
sessions. `.env` (see below) is optional and only used as a rarely-needed
fallback.

---

## One-time setup per person

1. **Install the skill.** Get this whole `daily-actions-report` folder onto
   your machine (all files listed in `SKILL.md`'s Preconditions must live
   together in one folder).

2. **Set `SKILL_DIR` and `WORK_DIR`.** These are referenced throughout
   `SKILL.md` — they aren't hardcoded in the scripts. When you (or Claude, on
   your behalf) run the skill:
   - `SKILL_DIR` = wherever you put this folder (contains
     `headless_daily_report.py`).
   - `WORK_DIR` = wherever scratch files (`jira_data.json`, `pr_data.json`,
     `slack_data.json`) get written — can be the same folder as `SKILL_DIR`.
   There's nothing to edit in the scripts for this — just tell Claude these
   two paths (or let it use `SKILL_DIR` for both) the first time you run it.

3. **`.env` — optional, usually skip it.** `SKILL_DIR/.env` only feeds a
   fallback Jira changelog fetch that's normally never needed (see
   `SKILL.md` → Configuration) and is routinely proxy-blocked anyway. Don't
   ask around for tokens to fill it in — a missing `.env` should never block
   a run. Only create one if you specifically want that fallback path:
   ```
   ATLASSIAN_EMAIL=your@email.com
   ATLASSIAN_TOKEN=your_atlassian_api_token
   ```

4. **Check the shared roster is current.** This skill uses one shared
   config/state file for the whole team —
   `SKILL_DIR/daily-actions-report/project_current_sprint.md`. It's committed
   alongside the code (this PR includes the current version), so you don't
   need to create it — just know it exists and what's in it:
   - **Sprint Metadata** — current sprint label/dates and the permanent
     Confluence page ID. Never edit `actions_report_page_id` or
     `report_page_title`.
   - **Team GitHub Logins**, **Team Slack Names**, **Account IDs** — rosters
     used for cross-team PR detection and Slack reply matching. If you
     notice these are stale (e.g. a teammate's GitHub handle is missing),
     update the file and land the fix — it's better than the report silently
     misclassifying someone's work.
   - **Changelog Cache / State Snapshot / PR Snapshot / Slack Thread
     Snapshot** — the script maintains these itself after each publish. You
     don't need to touch them.

---

## Running it

Open Claude and say something like "run the daily actions report." Claude
follows `SKILL.md`'s three-step workflow:

1. **Fetch and build** — pulls Jira (via Atlassian MCP), scrapes open PRs and
   (by default) the `#t-dxp-headless` Slack channel (via Chrome MCP), and
   builds a local HTML preview. This step doesn't touch Confluence.
2. **Approval gate** — Claude shows you the HTML preview and a data-quality
   summary. Open the file, sanity-check it, and only then approve publishing.
   Don't skip this even if you're in a hurry — it's the only check between a
   bad data pull and a page the whole team sees.
3. **Publish** — happens in *your* logged-in browser (direct API calls to
   Confluence are always proxy-blocked from Claude's sandbox). Confirm the
   page updated (HTTP 200) before walking away.

Whoever runs it needs to be logged into Confluence, GitHub, and Slack as
**themselves** for steps 1 and 3 — there's no shared service account.

---

## If something breaks

`SKILL.md` documents known failure modes and fixes in detail (see the
`CHANGELOG-fixes-*.md` files for the history of specific bugs and why each
rule exists). A few quick pointers:

- **Assembler script (`assemble_jira_data.py` / `assemble_slack_data.py`)
  exits non-zero** — read its ❌ message, it tells you exactly what's wrong.
  Don't try to hand-build the JSON files as a workaround; a bad reconstructed
  dataset is worse than no report.
- **Jira MCP returns fewer than 20 issues, or two queries return identical
  data** — known MCP caching issue. Start a fresh Claude session and retry.
- **Confluence publish fails (ProxyError/ConnectionError)** — expected from
  the sandbox; publishing must go through the browser path in `SKILL.md`
  Section 3, never the `updateConfluencePage` MCP tool.
- **Still stuck** — ask in the team channel rather than improvising a new
  workaround; several past incidents (documented in the CHANGELOG files) came
  from well-intentioned one-off fixes that didn't match the permanent rules.
