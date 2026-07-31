# Daily Actions Report — Setup Guide (Headless Team)

This lets anyone on the Headless team run the Daily Actions Report — not just
Nóra. Useful for PTO cover, but also just for spreading ownership. Work
through this once per person/machine; after that, running it is just "run the
daily actions report" in Claude.

**Updated 2026-07-31 (v2.1.1):** this guide previously described a
local-file config scheme that predates the Confluence-based Shared Context
Storage migration (v2.0.0, 2026-07-28). Rosters and caches now live on a
single shared Confluence page, not a file inside the skill folder — see
"Shared config: Confluence, not a local file" below. If you set this up
before 2026-07-28, re-read that section; the old steps no longer apply.

---

## Prerequisites

Each person who wants to run this needs, on their own machine/account:

- Claude (desktop app or Cowork) with two connections active:
- **Atlassian MCP**, connected to `liferay.atlassian.net` (cloudId
`5d1aaa67-5d5e-4cca-b668-33b9742cfb4a`) — used for all Jira reads and,
during publish, the Confluence report page.
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
`slack_data.json`, and — as of v2.0.0 — `context_scratch.md`, the synced
copy of the shared Confluence context page) get written — can be the
same folder as `SKILL_DIR`.

**If your session's `SKILL_DIR` is read-only** (e.g. a sandboxed Claude/
Cowork session where the skill folder is a mounted, read-only cache — you'll
see an `OSError: [Errno 30] Read-only file system` if you hit this), pass
`--output-dir` pointing `headless_daily_report.py`'s output (the HTML
preview, `adf_output.json`, publish snippets) at a writable folder instead.
This flag was added in v2.1.1 specifically for this case — see
`CHANGELOG-fixes-2026-07-31.md` for the full story. There's nothing to edit
in the scripts for any of this — just tell Claude the paths (or let it use
`SKILL_DIR` for both `SKILL_DIR`/`WORK_DIR`, plus `--output-dir` if needed)
the first time you run it.

3. **`.env` — optional, usually skip it.** `SKILL_DIR/.env` only feeds a
fallback Jira changelog fetch that's normally never needed (see
`SKILL.md` → Configuration) and is routinely proxy-blocked anyway. Don't
ask around for tokens to fill it in — a missing `.env` should never block
a run. Only create one if you specifically want that fallback path:
```
ATLASSIAN_EMAIL=your@email.com
ATLASSIAN_TOKEN=your_atlassian_api_token
```

4. **Shared config: Confluence, not a local file.** As of v2.0.0
(2026-07-28), Sprint Metadata, both rosters (Account IDs, Designer Account
IDs, Team GitHub Logins, Team Slack Names), and the four run-to-run caches
(Changelog Cache, State Snapshot, PR Snapshot, Slack Thread Snapshot) live
on a single **permanent Confluence page** — `context_page_id: 5190975505`
(space `ENGHEADLESS`, "Headless Daily Report — Shared Context"), not in a
file inside this folder. There is nothing to install or commit for this —
every run reads that page fresh via the Atlassian MCP at the start
(`getConfluencePage`) and writes it back after publish
(`updateConfluencePage`). See `SKILL.md` → Shared Context Storage for the
full detail; in short:
- **Roster changes** (new hire, someone leaves, a GitHub/Slack handle
changes) — edit the Confluence page directly. Any team member with edit
access can do this; it needs no code change and no PR to this repo. This
replaces the old "edit `project_current_sprint.md` and land the fix"
step — don't do that anymore, that file no longer exists.
- **Caches** (Changelog/State/PR/Slack Snapshot) — the script maintains
these itself after each publish; you don't need to touch them.
- The nested `daily-actions-report/project_current_sprint.md` file some
older setups may still have on disk is now **bootstrap seed content
only** — it's what the Confluence page was originally created from, and
is never read at runtime once that page exists (it already does; don't
re-bootstrap it).

---

## Running it

Open Claude and say something like "run the daily actions report." Claude
follows `SKILL.md`'s workflow (Step 0 syncs the shared Confluence context
in, then the three steps below, then syncs it back out):

1. **Fetch and build** — pulls Jira (via Atlassian MCP), scrapes open PRs and
(by default) the `#t-dxp-headless` Slack channel (via Chrome MCP), and
builds a local HTML preview. This step doesn't touch the report page on
Confluence (it does read the shared context page, per Step 0 above).
2. **Approval gate** — Claude shows you the HTML preview and a data-quality
summary. Open the file, sanity-check it, and only then approve publishing.
Don't skip this even if you're in a hurry — it's the only check between a
bad data pull and a page the whole team sees.
3. **Publish** — the *report page* update happens in *your* logged-in
browser (direct API calls to Confluence are always proxy-blocked from
Claude's sandbox for that page's ADF/full-width-table requirements — see
`SKILL.md` Section 3b). Confirm the page updated (HTTP 200) before walking
away. The *shared context page*, by contrast, is a plain markdown/JSON
dump with none of those requirements, so syncing it back out **does** use
the `updateConfluencePage` MCP tool directly, right after the report page
publish succeeds — this is expected and correct, not a shortcut.

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
- **`assemble_slack_data.py` warns `No '## Team Slack Names' section found` /
`Team roster is empty` on a page that should already have a populated
roster** — this was a real bug (see `CHANGELOG-fixes-2026-07-31.md`, fix
#1) fixed in v2.1.1; if you're still on an older copy, treat this warning
as a hard stop, not a proceed-anyway condition.
- **`OSError: [Errno 30] Read-only file system` writing the HTML
preview/ADF/publish snippets** — the skill folder is mounted read-only in
this session; pass `--output-dir` at a writable path (see step 2 above and
`CHANGELOG-fixes-2026-07-31.md`, fix #2).
- **Jira MCP returns fewer than 20 issues, or two queries return identical
data** — known MCP caching issue. Start a fresh Claude session and retry.
- **Confluence *report page* publish fails (ProxyError/ConnectionError)** —
expected from the sandbox; publishing that page must go through the
browser path in `SKILL.md` Section 3, never the `updateConfluencePage` MCP
tool. (The separate *shared context page* sync-out is the one place
`updateConfluencePage` is correct — see "Running it" step 3 above.)
- **Still stuck** — ask in the team channel rather than improvising a new
workaround; several past incidents (documented in the CHANGELOG files) came
from well-intentioned one-off fixes that didn't match the permanent rules.
