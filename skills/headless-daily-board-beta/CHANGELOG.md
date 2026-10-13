# Changelog — headless-daily-board-beta

## 0.17.1-beta (2026-10-13)
- Live status never stays on "loading…": after 30 s the header says "Live status not answering"; a Jira- or GitHub-only failure is shown in the header ("Jira not reachable" / "GitHub not reachable").
- Live.gs install note: paste into a Script file (not HTML), save, run testLiveStatus with Live.gs open (the function dropdown lists the open file's functions), then deploy a New version.

## 0.17.0-beta (2026-10-13)
- Live status on the Google Site: when the board opens inside the Apps Script web app it calls `liveStatus({keys, prs})` (new `Live.gs`, read-only, 5-minute script cache) and updates every Jira status chip (issue rows, standalone-PR Jira lines, Milestone status epics) and adds a live state chip after every PR link (merged / closed / draft / approved / changes requested / review required). Changed statuses get a marker with the run-time status in the tooltip; rows whose issue is now Done are dimmed. Header line shows "Live status · HH:MM · N changed since the run". Outside the web app, or if Live.gs isn't installed, the board shows the run-time values ("Live status unavailable").
- Board content (tabs, cycle time, actions) stays as of the run.

## 0.16.0-beta (2026-10-13)
- Assign picker = the TEAM list in board.py (15 people + PT User Headless, confirmed by Nóra 2026-10-13), not the whole "Account IDs" roster from the context page (that roster is wider on purpose — it drives ownership/exclusion rules — and put non-team people like Eric Yan, Chris Kian, Akhash Ramprakash, Dániel Pintér, Selena Aungst, Victor Galan in the picker while leaving PT User Headless out). Jira account IDs come from Account IDs + Designer Account IDs; GitHub logins from Team GitHub Logins with notes in brackets stripped from the names (Adolfo Pérez's login was never matched before).
- "Request review" pickers (2a PR rows) list only people with a GitHub login.
- `--build` warns if a TEAM name has no Jira account ID in the context file.

## 0.15.0-beta (2026-10-13)
- Standalone PR rows (no Jira issue of their own on the board) show the PR title (from pr_data.json, leading Jira key stripped) plus a "Jira: KEY · summary ↗" line with the linked issue's status chip. `board.py --build` picks up WORK_DIR/pr_data.json (or `--pr-data-file`) and WORK_DIR/pr_jira.json automatically.
- SKILL.md: the PR parent-resolution getJiraIssue call also fetches summary + status, and standalone PRs' issues are saved to WORK_DIR/pr_jira.json.

## 0.14.0-beta (2026-10-13)
- Every issue row shows its current Jira status as a chip next to the key (grey = to do, blue = in progress, green = done), taken from jira_data.json — no extra Jira calls. PR-only and Slack rows have no Jira issue, so no chip.
- Issue info from jira_data.json is now merged across all places an issue appears (top level, as a parent, in issuelinks) instead of the last sparse reference overwriting it; this also restores a lost epic link (LPD-109497 → LPD-108235 on 2026-10-13).

## 0.13.0-beta (2026-10-13)
- Theme switch (System / Light / Dark) in the board header. Each viewer's choice is saved in their own browser (localStorage, wrapped in try/catch — if the Google Sites frame blocks storage, the switch still works for the visit and falls back to System). A small head script applies the saved theme before the page paints.
- Dark-mode fixes: table row borders and the "—" placeholder now use theme colours (were fixed light-mode values); `color-scheme` set so native controls (Assign picker) match the theme. Jira issue-type and priority label colours unchanged.

## 0.12.0-beta (2026-10-13)
- SEV BPRs outside the sprint filter are fetched in one MCP query (`assemble_jira_data.py --plan-sev-bpr` prints it; result passed with `--sev-bpr-detail-file`) instead of per-issue direct HTTPS from `headless_daily_report.py`, which always failed in the sandbox (134 silent fetch errors on 2026-10-13). Queried keys are stored as `sev_bpr_checked_keys` in jira_data.json and the report script skips the HTTPS fallback for them.
- Issuelink BPRs are taken only from SEV bugs that are in the Headless sprint result (the SEV query covers every team's security bugs); filter=15069 is still used as is. Prevents other teams' backports (e.g. Commerce BPR-93181/93183) from appearing once the fetch works.
- SKILL.md: new mandatory "SEV BPR details" step after the SEV queries; assembler command shows `--sev-bpr-detail-file`.

## 0.11.0-beta (2026-10-09)
- Assign buttons wired for the Apps Script (Code.gs v2): issue rows set the Jira assignee and add the person as assignee on linked PRs; PR rows in 2a request a GitHub review. Roster (names → Jira account IDs, GitHub logins) comes from the context file. No Jira comment is added.
- AVD tiles: numbers are provided manually by Nóra in the run request.

## 0.10.0-beta (2026-10-07)
- Approval gate restored before publishing: Step 2 delivers the board in chat and saves the run memory automatically, then asks "Publish this board to the Google Site?"; Step 3 (Drive folder → site) runs only after an explicit yes.

## 0.9.1-beta (2026-10-07)
- Removed the "BETA · private preview" banner; added an "open full width ↗" link (web app URL) in the board header.
- Step 2 commits the board with the SendUserFile fileUuid + force (stagedPath re-used a stale copy in testing).
- Google Site: header removed, embed made taller.

## 0.9.0-beta (2026-10-07)
- Google Sites publishing: Step 2 writes board_<date>.html into the Drive-synced folder "My Drive/Headless/Headless Daily Board" via device_commit_files; the Apps Script web app (embedded on https://sites.google.com/liferay.com/headless-daily/home) shows the newest board file.

## 0.8.0-beta (2026-10-07)
- Run memory is saved to the shared context page automatically right after the board is delivered (no approval/publish gate). Fixes the cause of the page being stale since 2026-09-24.
- Iteration auto-detect: `board.py --sync-sprint` updates Sprint Metadata from the active HL sprint in jira_data.json before the preview run.

## 0.7.0-beta (2026-10-07)
- Back to the shared context page (Confluence 5190975505) for the run memory, exactly like the daily actions report: Step 0 reads it, Step 3 saves it after approval. The project-doc memory from 0.6.0 is removed. Still no report-page publishing.

## 0.6.0-beta (2026-10-07)
- Run memory no longer uses Confluence: Step 0 reads and Step 3 saves the memory file (same format as project_current_sprint.md) as the Claude Project doc claude/headless-board-memory.md. Nothing is written to Confluence.

## 0.5.0-beta (2026-10-07)
- Standalone: the skill now contains the full daily actions report pipeline (headless_daily_report.py, assemble_jira_data.py, assemble_slack_data.py, bootstrap assets, and the v2.3.1 SKILL.md collection steps, copied unchanged). It fetches its own data, writes the same files and caches, and saves the run memory to the shared context page after approval. Output = the board; no Confluence report publishing.

## 0.4.0-beta (2026-10-07)
- Moved configuration, the exact Jira/Confluence call list (`--plan`), input discovery (`--find-inputs`), epics.json validation, the stable-report count check and copying to outputs into board.py. SKILL.md reduced to safety rules, budget gate and 4 steps.

## 0.3.0-beta (2026-10-07)
- Epic T-shirt size (customfield_10804): Size column in Milestone status; Milestone bar weighted by size in person-months (XL = 1 month/person per roadmap).

## 0.2.0-beta (2026-10-07)
- Tabs numbered 1a, 1b, 1c, 2a, 2b, 3, 4 (1c moved after 1b).
- 1a = all unplanned + planned with PR action; 1c = other planned with high cycle time, sorted Story/Task/other/Spike then cycle time desc; remaining planned rows in a folded box.
- Topic links to the parent epic (jira_data parent, fallback: epic name match).
- Jira issue-type colours.

## 0.1.0-beta (2026-10-06)
First beta. Reads the stable report preview (read-only), adds tabs, iteration/milestone bars, Milestone status (Headless Team field, sorted by cycle time), Tests snapshot. AVD tiles are placeholders until the AVD data source is connected. Google Sites publishing and Assign (Apps Script) not set up yet.
