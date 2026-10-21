---
name: "headless-daily-board-beta"
description: "BETA of the Headless Daily Actions Report with a new output: a tabbed board (progress bars, numbered tabs 1a/1b/1c/2a/2b, milestone status, tests) instead of the Confluence report page. Runs on its own (same data collection and same shared context page as the daily actions report). Use only when the user asks for the board beta / headless-daily-board-beta."
---

# Headless Daily Board — BETA (v0.17.4-beta)

> **What this skill is:** the full Headless Daily Actions Report pipeline — data collection, files, the shared
> context page (run memory: Sprint Metadata, rosters, Changelog Cache, State Snapshot, PR Snapshot, Slack Thread
> Snapshot), filtering and sorting rules — copied unchanged from `headless-daily-actions-report` v2.3.1, including its
> scripts, with a **different output**: the tabbed board built by `board.py`. It runs **on its own**.
>
> **Overrides for everything below:**
> - **Never publish to the Confluence report page.** Ignore every instruction about `--publish`, `publish_*.js`, the
>   ADF, file-upload/DevTools publishing and §3a/§3b. Steps 2–3 at the end replace them.
> - **Iteration is detected from Jira, not edited by hand** (Step 1, iteration check).
> - **Publishing = writing the board file into the Drive-synced folder, only after explicit approval** (Step 3) — the Google Site shows the newest one.
> - **The run memory is saved automatically right after the board is delivered** (Step 2), before the approval
>   gate — never wait for the publish or the approval to save it. (The old skill's memory page went stale from 2026-09-24 because that final
>   save was skipped.)
> - **AVD metrics are stored, not re-typed (v0.17.2):** section 3 always shows the last known AVD numbers from the
>   shared context page with "Number not changed since <date>", and every run asks Nóra whether there are new ones (Step 1c).
> - **Blockers are shown on the row (v0.17.3):** every issue with an open "Is blocked by" link in Jira gets a
>   "🔒 Blocked by KEY summary (status)" note in Other updates, and a bare "Start" action becomes "Wait — blocked".
>   When the blocker is done the note turns into "✅ Unblocked — … can start". Comes from the `issuelinks` already in
>   jira_data.json — no extra calls. A blocker added to Jira after the morning fetch only shows on the next run
>   (or re-fetch that one issue and put it first in `--sprint-file`).
> - **Live status (v0.17.0):** on the Google Site the board refreshes Jira statuses and PR states when it opens, via `liveStatus()` in `Live.gs` (ships with this skill; installed once in the Apps Script project next to Code.gs). Nothing to do per run.
> - **Oldest first inside each priority (v0.17.4):** inside the same priority tier, rows that have been in our queue
>   longest come first (most days first) — 1a/1c, 2a Needs Owner and 2b Assigned alike (e.g. SEV tickets 6d → 3d → 1d).
>   LPP rows in Pick Up Next still sort by heat score first, then oldest first. Built into `headless_daily_report.py`
>   (`_sort_section1`, `_sort_section2`) — nothing to do per run.
> Everything else (Step 0 context sync, Step 1 collection, 1a/1b, guardrails, budget checkpoints) applies as written.


**Skill Version:** 2.3.1 — 2026-09-10 (see `CHANGELOG.md` for what changed at each version; the many dated `CHANGELOG-fixes-*.md` files hold the detailed forensic history behind each fix)

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

**⚠️ Read-only skill mounts (Cowork / sandboxed sessions) — known issue, 2026-07-31, not yet code-fixed.**
`headless_daily_report.py` defaults `OUTPUT_DIR` to its own folder
(`Path(__file__).parent`, i.e. `SKILL_DIR`) — every output file it writes
(`daily_actions_report_<date>.html`, `adf_output.json`,
`publish_adf_loader.js`, `publish_snippet.js`, `publish_<sprint>_console.js`)
goes there. In a Cowork session the skill folder is a **read-only mounted
cache**, so both the plain preview run and `--publish` fail immediately with
`OSError: [Errno 30] Read-only file system`. **Workaround (do this first, every
time, in any session where the skill folder isn't known to be writable):**
copy the whole skill folder (all `.py` and `.md` files) into a writable
scratch directory and run every script (`headless_daily_report.py`,
`assemble_jira_data.py`, `assemble_slack_data.py`) from that copy instead of
the mounted path — the code is unmodified, it just needs a writable
`__file__.parent`. The real fix is an `--output-dir` CLI flag (not yet
applied — see `CHANGELOG-fixes-2026-07-31.md` for the exact diff); until
that lands, treat the copy-first step as a mandatory part of Configuration,
not an occasional workaround.

## Token Efficiency (read before running — added 2.1.7, 2026-08-26)

A 2026-08-26 run of this skill consumed roughly a full session's token budget by itself (previously it used about half). A post-run analysis of that session's transcript found the cost was concentrated in a handful of specific, fixable patterns — not in the underlying data collection, which is already reasonably tight. Follow these rules on every run:

1. **Never inject a large payload into a browser tab via `javascript_tool`, encoded or not.** The only reason to reach for `javascript_tool` with a big string is the §3a/§3b publish script, and doing this the wrong way was the single largest cost in the 2026-08-26 run — over 30% of that session's tokens, for zero result. What happened: after `file_upload` failed as expected (see the 2026-08-14 addendum below §3a), instead of going straight to §3b, base64-encoding the ~96KB console script and pushing it in 9 chunks via `javascript_tool` was attempted. Every chunk had to be `Read` back into Claude's own context first (since the file is one giant line), and the very first chunk push was then rejected outright by a content-safety filter that specifically blocks base64-looking data — so nothing was transferred and the tokens spent reading and re-encoding those chunks bought nothing. **The fix is procedural, not technical: there is no working chunked-injection transport for a payload this size, encoded or plain-text. Don't attempt one.** If `file_upload` fails (§3a), the very next step is always §3b, unmodified: hand `publish_<sprint>_console.js` to the user (e.g. via `SendUserFile`) and ask them to paste it into DevTools themselves. §3b is written as a **manual, human-typed** fallback for exactly this reason — a human pasting text into their own DevTools console has no context-size limit, which is precisely what an automated `javascript_tool` call does not have. Treat "Chrome MCP is available" and "the automatic publish path works" as two different facts — the first does not imply the second when the payload is this large.
2. **Batch every `ToolSearch` call.** Load every Chrome MCP tool (and any other deferred tool) you expect to need in the run in one `ToolSearch` call at the very start, using the comma-separated `select:` form. The 2026-08-26 run made 7 separate `ToolSearch` calls scattered across the session instead of 1-2 — each one re-reads the full accumulated context at whatever size it had grown to by that point, so late, scattered tool-loading is far more expensive than it looks from the call count alone.
3. **Prefer text-based Chrome tools over `computer`.** `find`, `get_page_text`, and `read_page` read the page as text; `computer` drives the page via simulated clicks/screenshots and costs substantially more per call (each call can carry image tokens, and it typically takes several calls to do what one `get_page_text` does). Use `computer` only when a page genuinely cannot be read or acted on as text (e.g. no stable selector or link exists for the action). In the Slack scraping step in particular (see below), prefer navigating directly to a thread's deep-link URL over clicking "View thread" — the skill already documents the deep-link format as a *fallback* for when clicking fails silently; use it as the **primary** method instead, since it's both cheaper and more reliable than click-and-hope.
4. **Keep `TaskUpdate` calls coarse.** Update task status at natural milestones (a whole workflow step done), not after every sub-action within a step — each update is cheap on its own but the count adds up over a long run.

None of the above changes what data is collected or how the report is built — they only change *how* Claude drives the tools to get there. If a future run's token cost still looks high after these are followed, get the actual breakdown (transcript + subagent `.jsonl` files) before guessing at a new cause — see the 2026-08-26 analysis in `CHANGELOG-fixes-2026-08-26-token-efficiency.md` for the method.

## Run Budget Guardrails (added 2.3.0, revised 2.3.1 same day with confirmed incident findings — read before running)

**Why this exists:** the only budget check that existed through 2.2.0 was a single, self-counted "have I made more than ~40 tool calls?" estimate, placed right before the Approval Gate (Workflow → 2) — i.e. *after* the entire expensive data-collection phase (Workflow → 1/1a/1b) has already run to completion. Every documented token-cost incident (2026-08-25's 44+ minute stopped run, 2026-08-26's whole-session run, and a 2026-09-10 run that burned ~2 hours and exhausted its session with **no report produced at all**) blew its budget *during* collection, not after — so the one checkpoint that existed could never have caught any of them before the damage was done. This section adds real checkpoints during the expensive phase itself, not just one at the end, and a way to leave usable partial work behind if a run does have to stop.

**2026-09-10 incident — confirmed root cause (transcript reviewed after this section was first drafted).** The failed run's own transcript is now available, and the actual cause was simpler than either hypothesis first floated below (the untested PR-staleness logic, or a subagent losing PR-Snapshot context) — the run never got far enough to reach GitHub PR scraping or the staleness check at all. It stalled entirely inside step 1a (Jira changelog+comment pre-fetch): instead of delegating that fetch to a subagent as Workflow → 1a already recommended, Claude called `getJiraIssue(expand=changelog)` directly from the main thread, once per candidate issue, and let each full response — changelog histories, comment bodies, author objects, avatar URLs, timestamps — land straight in the conversation. This happened for 14-15 of the ~60 candidates before the pattern was caught — only because the user asked why the run was taking so long, not because any guardrail caught it — and every one of those responses stayed in context, getting reprocessed on every subsequent turn. None of that inline-fetched data was ever written to disk, so it was wasted outright: a full re-fetch was needed to actually persist anything. A rate limit then stalled the recovery attempt further, pushing total elapsed time well past the user's 30-minute deadline.

Why the existing instruction didn't prevent this: Workflow → 1a's delegation guidance (2026-08-14 addendum) said to fetch these calls at real concurrency, "**ideally** via a delegated subagent" — a recommendation, not a hard requirement. That gap is closed below (see the new ⛔ MANDATORY rule in Workflow → 1a and the matching hard-ceiling bullet here). The checkpoint/persistence machinery in the rest of this section (token tracking, phase breakdowns, resume-from-partial-output) is still worth having as defense-in-depth, but none of it would have caught this specific failure by itself, because the failure was Claude choosing not to delegate at all — not a delegated subagent running long. The fix has to sit at the point of that choice, not only in monitoring its cost afterward.

**Use the actual token signal when you have it.** Some sessions (Cowork in particular) periodically surface a system reminder of the literal form `<total_tokens>N tokens left</total_tokens>`. When one has appeared anywhere in this session's context, treat the most recent one as authoritative and note its value at every checkpoint below, alongside the tool-call count. Compute the delta between checkpoints (tokens consumed by that phase) and use it to project whether the *next* phase — historically the most expensive one is the concurrent step-1 subagent dispatch — is likely to exhaust the remaining budget before the run reaches a usable state (a built HTML preview). If no such reminder has appeared yet this session, fall back to the tool-call-count heuristic alone (as before 2.3.0) — but still apply it at every checkpoint below, not only once before approval.

**Checkpoint schedule — record `{tool_call_count, total_tokens if known, wall-clock elapsed}` at each of these points, and compare against the historical baselines named:**

1. **After Workflow → 0 (context sync) completes.** This is your baseline. Sync-in is historically cheap (a handful of calls) — if it isn't, something is already wrong (e.g. the context page fetch is retrying) and it's worth a sanity check before spending anything on collection.
2. **Immediately before dispatching the three Workflow → 1 subagents (1a changelog/comment pre-fetch, GitHub PR scraping, Slack scraping).** This is the last cheap point to stop at. If checkpoint 1's numbers already look unusually high for this stage, say so to the user before committing to the expensive concurrent phase rather than after.
3. **Immediately when all three subagents have returned (or been confirmed complete via their output files — see the redispatch rule below).** This phase alone has historically accounted for roughly half of a full run's cost (~23% GitHub+Slack per the 2026-08-26 postmortem, more when something goes wrong — e.g. the 2026-08-25 incident where the same ~44-issue changelog fetch was redone three times end-to-end, costing roughly a quarter of that run's total budget by itself). **If the delta since checkpoint 2 alone exceeds roughly a third of the total budget available at checkpoint 2** (by token count if known, or by a tool-call count that's clearly disproportionate — e.g. well over 150-200 calls across the three subagents combined for a normal ~15-25 PR / ~10-20 Slack candidate sprint), stop before calling `assemble_jira_data.py` or building the HTML. Tell the user plainly which of the three phases looks like the outlier (compare each subagent's own reported turn/tool-call count — GitHub PR scraping and Slack scraping have historically run 90-110 turns each; a phase running noticeably longer than that with no obvious reason, like an unusually large PR count, is the one to call out) and ask whether to continue, narrow scope (e.g. skip Slack for this run with the user's explicit sign-off, per the existing rule under "Slack Needs Owner"), or stop and resume in a fresh session (see persistence rule below — nothing already fetched needs to be redone).
4. **Before Workflow → 2's existing Approval Gate check** (unchanged: warn if total tool calls exceed ~40) — but now report it as a **breakdown by phase** (sync / 1a / PR scraping / Slack scraping / assemble+build), not just a single total, so the user can see which phase actually drove the cost rather than just that a number crossed a threshold.
5. **Before attempting Workflow → 3a's automatic publish path.** This is the single worst historical offender by itself (the 2026-08-26 chunked-`javascript_tool` attempt burned ~30% of an entire session's budget for zero result before ever reaching §3b). Publishing can happen "at any time" once the data files exist (see the Approval Gate note in Workflow → 2), so if the budget already looks tight entering step 3, say so and offer to stop here — the ADF/snippet files are already written to disk and a fresh session (or the user's own DevTools paste, §3b) can finish the publish without repeating any data collection.

**Persist each phase's output the moment it's ready — don't hold it only in a subagent's return value or wait for all three Workflow → 1 phases to finish before writing anything to disk.** `pr_data.json` and `slack_data.json` (and the raw changelog/comment dicts from step 1a) should land in `WORK_DIR`/`/tmp/` as soon as their own collection step completes, exactly as the existing per-step instructions already describe — the point of calling it out here is that this is also what makes a stop-at-checkpoint-3 decision cheap: if the run stops there, nothing already fetched is wasted. **Before starting any of the three Workflow → 1 phases in a new run (or a resumed one), check `WORK_DIR` for an already-current (same-day) output file from that phase and skip re-collecting it if one exists and the user confirms it's still wanted** — the same "check for a completed subagent output before redoing the work by hand" principle that already applies to step 1a (Workflow → 1a, 2026-08-25) applies to all three phases, and now also across a stopped-and-resumed run, not just across a single run's redispatch confusion.

**Hard ceilings on every "keep going until done" loop — stop and report rather than loop indefinitely:**
- **Step 1a's per-issue `getJiraIssue(expand=changelog)` calls: zero direct calls from the main thread once the candidate count exceeds ~10.** This is the confirmed cause of the 2026-09-10 incident above, and it is now a hard rule, not a preference — see the matching ⛔ MANDATORY rule in Workflow → 1a. **If you notice you are about to make a second consecutive `getJiraIssue` call for this step from the main thread (not from within a dispatched subagent), stop immediately** — do not finish the rest of the batch inline first "since you're already partway through." Before switching to the subagent approach, write whatever you've already fetched inline to a file in `WORK_DIR`/`/tmp/` (reconstruct it from the conversation if the raw tool results are still there) so it isn't wasted, then delegate the remainder. Treat any repeat of this specific pattern as the first thing to check on a slow run, before any other hypothesis in this section.
- Sprint/SEV/BPR pagination: already self-limiting via `--expected-count` (the assembler hard-fails on a mismatch), but if a single query needs more than ~15 pages to satisfy its expected count, treat that as an anomaly worth flagging to the user rather than silently continuing to page — that's well outside every historical run's normal range (1-2 pages for SEV/BPR, 1 page for the sprint query since the 2026-08-25 `comment`-field fix).
- Slack thread scrolling (Input → Slack Needs Owner, step 2): cap at ~8 viewport captures per thread. If a thread still isn't fully captured after 8 scrolls, save what you have (partial-but-real beats a loop that never terminates) and flag that specific thread to the user rather than continuing to scroll it.
- Subagent turn counts: if a delegated subagent for any of the three Workflow → 1 phases is still running well past double its historical baseline (~200 turns) with no output yet, that's the checkpoint-3 trigger above — don't let it run indefinitely on the assumption it'll finish eventually.

**Rate limits: announce them, don't silently wait them out.** The 2026-09-10 incident's recovery attempt was further stalled by an MCP rate limit that blocked both remaining fetches for a stretch of time the user only learned about after the fact, well past their stated deadline. If a call comes back rate-limited, tell the user right away — what's limited and, if known, roughly when it resets — rather than silently retrying or waiting in the background. A user with a deadline needs to know a limit is the current blocker as soon as you know it, not after it's already cost significant time.

**The 2026-09-09 PR staleness check (see "Open Pull Requests" below) still needs its own trip-wire, even though it turned out not to be what caused the 2026-09-10 incident.** The 2026-09-10 run's transcript (see above) shows it never reached GitHub PR scraping at all, so this feature remains unverified on a live run — the concern below still applies whenever it finally is exercised end to end:
- **If a large majority of PRs (rule of thumb: more than half) come back "changed"/ambiguous** on a day when the `PR Snapshot` cache should already be populated from a prior run (i.e. this isn't the very first run since the feature shipped), that means the staleness comparison itself likely isn't working — GitHub's date-text formats, or the cache's `captured_date`/`updated_display` fields, aren't matching what the comparison logic expects. **Stop after confirming the pattern on the first handful of PRs, tell the user the staleness check looks broken rather than merely "cautious," and ask whether to fall back explicitly to deep-scraping every PR (the pre-2.2.0 behavior) for this run** — don't silently pay full per-PR cost while the run still claims to be using the cheaper cached path, and don't spend the run's whole budget re-attempting the comparison in different ways hoping it starts working.
- **When any of the three Workflow → 1 phases is delegated to a subagent, that subagent needs the relevant `PR Snapshot` cache content (or the path to `WORK_DIR/context_scratch.md`) explicitly included in its dispatch prompt.** The staleness-check instructions below assume the cache is "already loaded as part of the shared context at the start of every run" — true for the main thread after Workflow → 0, but **not automatically true for a freshly dispatched subagent**, which starts with no memory of this conversation. If the PR-scraping subagent isn't told where to find (or given the contents of) the cache, it will either silently skip the staleness check (falling back to deep-scraping everything — safe, just not the intended savings) or, worse, spend turns trying to locate a file it was never pointed at. Always pass the file path (and confirm `WORK_DIR/context_scratch.md` exists before dispatching) or the cache's JSON content directly in the subagent's prompt.

## Preconditions

- `SKILL_DIR/headless_daily_report.py` exists
- `SKILL_DIR/assemble_jira_data.py` exists (builds and validates `jira_data.json` from MCP result files)
- The shared context Confluence page (`context_page_id` — see **Shared Context Storage**) is reachable via the Atlassian MCP and has a current Sprint Metadata section, and a `Team GitHub Logins` JSON section (display name → GitHub login) used for cross-team PR detection (dedup rule 3). Source rosters from the team page: https://liferay.atlassian.net/wiki/spaces/ENGHEADLESS/overview — keep them in sync when the roster changes (anyone with edit access to that Confluence page can update rosters directly — no code/skill-file edit needed). If the section is missing/empty, cross-team detection silently does nothing. A local `SKILL_DIR/headless-daily-actions-report/project_current_sprint.md` template still ships with the skill purely as a **one-time bootstrap seed** for creating that page — see Shared Context Storage — it is not read at runtime once the shared page exists.

  **Roster completeness (recurring failure pattern, seen 2026-07-10 and again 2026-07-29):** a person can be added to one roster (say, `Team GitHub Logins`, because their PR needed cross-team-detection to work) without being added to the others (`Account IDs`, which several exclusion rules check assignee ownership against). The person then looks like a non-Headless outsider to any rule that only consults the roster they're missing from, even though they're clearly doing Headless work. If a Section 1 exclusion or a cross-team flag looks wrong for someone you know is on the team, check whether they're present in *all* the rosters they'd plausibly need to be in, not just the one that's already correct — and add them everywhere they're missing, not just the one place the current symptom points at.

  **Team ownership changes (an issue stops being Headless work):** this happens through normal churn — an issue gets reassigned to another team, or was only ever pulled in by a shared filter/iteration label it doesn't actually belong to. There's no automatic way to detect this for every project (LPD has a sprint-field/team/assignee ownership check; LPP does not). When a team member says an issue "isn't Headless anymore," the correct, permanent fix is to add the `headless-board-out` label directly on that Jira issue (`should_exclude()` Rule 1 excludes it unconditionally, for any project) rather than trying to patch it out of a single run's data — the label persists across every future run with no code change needed.

  **Epics and Initiatives are always excluded (Rule 2b, `should_exclude()`) — 2026-08-27, per Nóra.** This is a daily *action* report — Epics and Initiatives are containers of work, not actionable work items themselves, and having them appear as ordinary rows next to the individual issues underneath them is confusing/redundant. Found live: LPD-98772, LPD-86135, LPD-88573, and LPD-94243 (all issuetype "Epic") were appearing as ordinary Planned-tier rows in 1b. `should_exclude()` now excludes both `"Epic"` and `"Initiative"` issuetypes unconditionally, for any project, before any other classification runs — reason string `"{issuetype} — not an actionable work item"`, visible in the report's Excluded table like any other exclusion. This is a hard type-based exclusion with no roster/label override; if an Epic or Initiative genuinely needs to be tracked in the daily report, the individual actionable issue under it (not the Epic itself) is the right thing to add.
- `SKILL_DIR/.env` is optional (see Configuration above) — never block on it or prompt the user for credentials.
- Chrome MCP is available (required for GitHub PR scraping and, if enabled, Slack scraping)
- The Atlassian MCP is available (cloudId: `5d1aaa67-5d5e-4cca-b668-33b9742cfb4a`)
- `SKILL_DIR/assemble_slack_data.py` exists (turns Chrome-scraped Slack text into `slack_data.json` — see "Slack Needs Owner" below). There is no Slack connector for this org, so this whole section is a Chrome-scraping workaround — but it is **run by default, not optional-by-default**. **2026-07-15 incident:** a run silently skipped this step (reasonable-sounding at the time — it used to be framed as optional) and a new unanswered thread went completely unreported until a team meeting caught it. Only skip it if Chrome MCP is genuinely unavailable, or the user has explicitly said to skip it for this specific run — never skip it by default or to save time/tool-calls, and never skip it without calling it out to the user BEFORE the approval gate (not just noting it after the fact in a summary). The synced context scratch file (`WORK_DIR/context_scratch.md`, see Shared Context Storage) must have a `Team Slack Names` JSON section (display name → Slack display name) for reply matching to work — if it's missing, `assemble_slack_data.py` will warn and over-flag rather than silently under-report.

  **⚠️ `assemble_slack_data.py`'s parser is stricter than `headless_daily_report.py`'s — known issue, 2026-07-31, not yet code-fixed.** The 2026-07-29 fix that let `load_sprint_context()` tolerate a blank line between a `## Section Name` heading and its ` ```json ` fence was **not** applied to `assemble_slack_data.py`'s own, separately-implemented `_read_md_json_section()` — and since Confluence's markdown round-trip reliably reintroduces that blank line, `assemble_slack_data.py classify` will silently see an **empty `Team Slack Names` roster on every run**, misclassifying answered threads as unanswered (confirmed 2026-07-31: 19-reply and 5-reply threads with real team replies both came back "unanswered" until this was caught). **If you see `⚠ No '## Team Slack Names' section found` or `⚠ Team roster is empty` from `assemble_slack_data.py classify` on a context page that should already have a populated roster, treat it as a hard stop** — strip the blank line after every `## Section Name` heading in `context_scratch.md` (e.g. `re.sub(r'(^## .+\n)\n(```json)', r'\1\2', text, flags=re.MULTILINE)`) and re-run classify before trusting its output. See `CHANGELOG-fixes-2026-07-31.md` for the one-line regex fix this needs (identical in spirit to 2026-07-29's fix, just never propagated to this file).

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

**Note (2026-07-31):** this migration fixed the *cache/roster data* half of the read-only-mount problem. It did not fix the *script output files* (HTML preview, ADF, publish snippets), which still default to writing inside `SKILL_DIR` — see the "Read-only skill mounts" note in Configuration above for that half of the same class of problem.

**Permanent Context Page Policy** (mirrors the report page's policy above):

- `context_page_id` is set once and **never changes**. Bootstrapped 2026-07-29: `context_page_id: 5190975505` (space `ENGHEADLESS`, title "Headless Daily Report — Shared Context", <https://liferay.atlassian.net/wiki/spaces/ENGHEADLESS/pages/5190975505/Headless+Daily+Report+Shared+Context>). **This page already exists — do not re-bootstrap.** Only go through the bootstrap step below if this ID is ever blanked out again (e.g. a fresh install of this skill for a different team/space).
- The page body holds the *exact same* section structure `project_current_sprint.md` always used — `## Sprint Metadata` (key: value lines) followed by `## Section Name` headers each containing a fenced ` ```json ` block (Changelog Cache, State Snapshot, Account IDs, Designer Account IDs, Team GitHub Logins, PR Snapshot, Team Slack Names, Slack Thread Snapshot). This is deliberate — `headless_daily_report.py`'s `load_sprint_context()`/`save_sprint_context()` and `assemble_slack_data.py`'s `--sprint-context` parsing didn't need to change internally at all, only *where* that content is stored and how it gets there each run.
- **Bootstrap (one-time, only if `context_page_id` is still blank above):** read the shipped template at `SKILL_DIR/headless-daily-actions-report/project_current_sprint.md` (this ships purely as bootstrap seed content now — it is never read at runtime once the page exists) and call `createConfluencePage` with that content, space `ENGHEADLESS`, title as above. Record the returned page ID into this section of `SKILL.md` so every future run knows where to look. Tell the user you're doing this and why — creating new shared team infrastructure is worth a heads-up even though it's just a data page.
- Roster edits (new hire, someone leaves, a GitHub/Slack handle changes) can now be made by **any team member directly on the Confluence page** — no engineering change or skill-file edit required, unlike the old local-file approach.

**Every run, in order:**

1. **Sync in (Workflow → Step 0, before Step 1):** `getConfluencePage(context_page_id)`, write its content verbatim to `WORK_DIR/context_scratch.md`. **When writing this file, keep each `## Section Name` heading directly followed by its ` ```json ` fence with no blank line in between where you can help it** — `load_sprint_context()` now tolerates a blank line there (2026-07-29 fix, see CHANGELOG-fixes-2026-07-29.md) and will loudly error rather than silently loading empty rosters if the fences are missing entirely, but a tight, minimal format is still the safest target since Confluence's own markdown rendering on the read-back can reformat things you don't control. **`assemble_slack_data.py` does NOT tolerate the blank line yet (see the 2026-07-31 known issue in Preconditions above) — for that script the tight format isn't just "safest," it's currently required.** If you notice blank lines after re-fetching this page (Confluence's round-trip reliably adds them), strip them before calling `assemble_slack_data.py classify`.
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

- **Sprint issues** — JQL: `filter=54796 AND status not in (Closed,Completed,Resolved,Answered)`, maxResults 100, fields: `key, summary, status, assignee, labels, issuetype, priority, project, updated, created, duedate, customfield_10804, customfield_10168, parent, customfield_10001, customfield_10020, issuelinks, subtasks`. **Note `comment` is deliberately absent from this list as of 2026-08-25** — see the perf addendum below; it's fetched separately, per-issue, only for the subset that needs it.
- **SEV bugs** — JQL: `project=LPD AND issuetype=Bug AND "Cross Cutting Properties[Checkboxes]" = "Security Vulnerability" AND status not in (closed)`, fields: `key, summary, status, labels, issuelinks` (issuelinks is required — see BPR-linkage note below, not just default fields). **Paginate this one fully too** — do not assume one page is the whole result. Keep issuing it with `nextPageToken` until a page reports `hasNextPage: false`, exactly like the sprint query below. (2026-08-25: a run stopped after page 1 of this query, missing 6 of 21 real SEV bugs, until it was caught and the pagination finished as a follow-up. The field list here is small, so this rarely needs more than 2 pages, but "small usually means one page" is not the same guarantee as "always one page.")
- **SEV BPRs** — JQL: `filter=15069 AND status not in (closed)`. Same rule — paginate to exhaustion, don't assume a single page.
- **SEV BPR details (board beta v0.12.0, 2026-10-13 — mandatory, run right after the two SEV queries).** Save the sprint/SEV/BPR results to files, then run
  `python3 SKILL_DIR/assemble_jira_data.py --sprint-file <sprint page(s)> --sev-file <sev> --bpr-file <bpr> --plan-sev-bpr`.
  It prints ONE `searchJiraIssuesUsingJql` call (JQL `key in (...) AND statusCategory != Done AND status not in (Open, Scheduled, "Awaiting Original Fix")` + the field list) for the SEV BPRs that are not in the sprint result. Run it via the MCP (maxResults 100, page until `hasNextPage=false`), save the result to a file and pass it to the assembler with `--sev-bpr-detail-file` (repeatable for pages). If it prints "none needed", skip it.
  **Why:** `headless_daily_report.py` used to fetch these BPRs one by one over direct HTTPS, which always fails in the sandbox (no token, proxy-blocked) — 134 silent "Failed to fetch BPR" errors on 2026-10-13, and any active Headless SEV BPR outside the sprint filter would have been missing. The assembler now records every queried key as checked, and the report script skips the HTTPS fallback for them.
  **Scope:** the SEV bugs query covers every team's security bugs (63 on 2026-10-13, only 5 Headless), so the assembler now takes issuelink BPRs **only from SEV bugs that are in the Headless sprint result**, plus everything in `filter=15069`. Other teams' backports (e.g. Commerce's BPR-93181/93183 for LPD-106190) are not Headless work and must not be added.
  **Days column:** if the detail query returns a BPR in "In Progress", "Verification" or "Original Fix Committed", fetch its changelog with `getJiraIssue(expand="changelog", fields=["status"])` (main thread is fine for ≤ 10 issues) and add it to the `--changelog-file` dict before assembling.

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

**2026-08-14 addendum (SUPERSEDED 2026-08-25 — read the note below first) —
`maxResults` above ~5 can itself be untrustworthy, not just a single page's
`hasNextPage`.** A run requesting `maxResults:100` (or even `10`) with the
full field list above **including `comment`** got back only 5 issues with
`hasNextPage:false` **and** a nonzero `remainingCount` in the same response —
internally contradictory. At the time, dropping `comment` alone while
keeping `maxResults` high was tried and didn't fix it, so this was recorded
as a field-list-combined-size issue rather than a single-field one, and
`maxResults:5` (~16 sequential pages for a full sprint) became the
mandatory workaround.

**2026-08-25 correction — it WAS the `comment` field, full stop; the
2026-08-14 test just didn't isolate it correctly.** Comment threads on this
board can run to thousands of words (one issue's most recent comment alone
was a multi-page technical writeup) — that's what was blowing past the
per-page size limit, not the field list's overall shape. Re-tested live on
2026-08-25 with `comment` fully removed from the fields array (every other
field unchanged) and `maxResults:100`: **a single call returned all 78
sprint issues, correct and complete, `hasNextPage:false`, no contradiction.**
The 2026-08-14 attempt to drop `comment` apparently didn't actually remove
it cleanly, or was retested against a different symptom — either way,
today's result is directly reproducible and is now the standard approach.

**What changed as a result:** the bulk sprint query above no longer requests
`comment` at all, and defaults to `maxResults:100` (a single call for any
sprint under ~100 issues; if `--expected-count` from the computeIssueCount
step exceeds 100, page as before, but each page now holds up to 100 issues
instead of 5). Comments are instead fetched **per-issue**, bundled into the
*same* `getJiraIssue(expand="changelog")` call already made for the
Section-1-eligible candidate subset in step 1a below (add `"comment"` to
that call's `fields` — no extra round-trip), and merged back into
`jira_data.json` via `assemble_jira_data.py --comment-file` (see step 1a and
"Build and validate `jira_data.json`" below). This is safe because comment
data is only ever read by trigger-evaluation code for issues in an
in-progress-like status (see "Section 1 visibility gate" below) — exactly
the same issue set the changelog pre-fetch already targets — so nothing is
lost by not fetching comments for the ~20 issues that don't need them.

**If you ever see the old `maxResults:100` failure mode recur** (a page
short of `hasNextPage:false` with a nonzero `remainingCount`, or any other
internally-contradictory pagination result) even with `comment` removed,
that's new information — don't silently fall back to `maxResults:5` without
noting it in the run's data-quality summary, since the fix above assumes
the 2026-08-25 test result still holds. See `CHANGELOG-fixes-2026-08-14.md`
(§1, historical) and `CHANGELOG-fixes-2026-08-25.md` (§6, the correction and
re-test) for the full writeup.

#### Collecting the results (large results are NORMAL)

Since `comment` was dropped from the sprint query (2026-08-25), this is now typically a single call — but the response is still large enough (~500-600 KB for a full sprint, even without comments) that it usually will not come back inline; the same save-to-file handling below still applies, just to 1-2 calls instead of ~16.

The sprint query result is large (~1 MB with a full sprint) and **will not be returned inline**. The MCP saves it to a tool-result file and returns a message like *"result exceeds maximum allowed tokens. Output has been saved to /var/folders/.../tool-results/mcp-...-searchJiraIssuesUsingJql-<timestamp>.txt"*. **This is expected, not an error.** Never parse the truncated inline text and never treat the saved-to-file message as a failure.

For each of the three queries, capture its result as a file path:

- **Saved to file:** note the filename (the basename, e.g. `mcp-...-searchJiraIssuesUsingJql-1781081975826.txt`). The host path in the message is not reachable from bash; the same file is available inside the sandbox — but **locate and inspect it with the Glob and Read tools, never with Bash.** (Fixed 2026-08-19 — see `CHANGELOG-fixes-2026-08-19.md` §2: the previous `bash find ... | cp ... | python3 -c ...` sequence used here, once per page, was the actual driver behind "too many approval prompts" during a run — every distinct Bash invocation needs a fresh user approval because its content (the basename, the timestamp) is different every single time, while Glob and Read are pre-approved read-only tools that never prompt. An 11-page sprint fetch used to mean up to 11 separate approval clicks just for this step; it's now zero.)
  1. **Locate:** call the Glob tool with `pattern: "**/<basename>"` and no fixed `path` (or `path: "/sessions"` if that root exists in this environment) — `**` matches the unpredictable `mnt/.claude/projects/...` segment regardless of the exact session directory, so you don't need to know or guess it.
  2. **Inspect:** call the Read tool directly on the path Glob returned to check `hasNextPage`, `nextPageToken`/`endCursor`, and the issue keys/count before deciding whether to fetch another page. Do not shell out to `cat`, `head`, or `python3 -c` for this — Read already returns the text.
  3. **Use directly, don't copy:** pass the path Glob found straight to `assemble_jira_data.py --sprint-file <path>` (repeat the flag once per page). There is no need to `mkdir`/`cp` it into `WORK_DIR` first — the assembler can read it from wherever it already lives; copying was never required, it was just a side effect of not having a locate step that worked without Bash.
- **Returned inline** (small results, e.g. SEV BPRs): save the raw JSON verbatim to a temp file in `/tmp/` (e.g. `/tmp/bpr_result.json`) using the Write tool (not a bash heredoc — same reasoning as above: Write doesn't prompt, a bash heredoc does).

#### Build and validate `jira_data.json` (hard stop on bad data)

Never assemble `jira_data.json` by hand. Run the assembler, which both builds the file and enforces all data-quality checks:

```bash
python3 SKILL_DIR/assemble_jira_data.py \
    --sprint-file <sprint result file> [--sprint-file <page 2> ...] \
    --sev-file <sev result file> \
    --bpr-file <bpr result file> \
    --expected-count <X: the filter total from the computeIssueCount step> \
    --changelog-file <path from step 1a> \
    --comment-file <path from step 1a> \
    --sev-bpr-detail-file <SEV BPR detail result file> \
    --out WORK_DIR/jira_data.json
```

`--changelog-file` and `--comment-file` are both optional but should be present on every normal run (step 1a produces both from the same per-issue fetch — see below). `--comment-file` merges each candidate's comment data into the matching `sprint_issues[*].fields.comment`, since the bulk sprint fetch above no longer requests `comment` at all (2026-08-25 perf fix).

The script validates: sprint issue count ≥ 20; **unique issues loaded == `--expected-count` (completeness guard — the primary defense against a truncated page falsely marked `hasNextPage=false`, the LPP-64669 bug)**; sprint and SEV results are not identical (crossed-response detection); ≥ 15 non-empty summaries; ≥ 10 issues with `customfield_10020`; and `hasNextPage` false on the **last** supplied `--sprint-file` (pages before the last are expected to have `hasNextPage=true` — that's what makes them non-final; if the last page still reports `hasNextPage=true` the script prints the `nextPageToken` to fetch — pass it as one more `--sprint-file` argument). **(Fixed 2026-08-19 — see `CHANGELOG-fixes-2026-08-19.md`: this check used to fire on every supplied page, not just the last, which made the documented multi-page pagination workflow below impossible to satisfy.)** It derives `sev_keys`, `sev_zero_day_keys` (label `zero-day-vulnerability`), and `sev_bpr_keys` itself. **Always pass `--expected-count`;** if omitted, the script prints a loud warning that completeness could not be verified.

**If the assembler exits non-zero:** show its ❌ message to the user verbatim and stop. With user approval, retry the failing MCP query **once** (sequentially), re-run the assembler, and if it fails again stop entirely and recommend a fresh session. Do **not** attempt manual data reconstruction or alternative data paths (no chunking, no TSV extraction, no browser-JS fetching of Jira data, no Confluence relay tricks) — a reconstructed dataset produces a worse report than no report, and these workarounds have burned hours in past sessions.

### Open Pull Requests

Scrape `https://github.com/liferay-headless/liferay-portal/pulls?q=is:pr+is:open+draft:false` via Chrome MCP. This list page already shows an **"Updated X ago"** string per row — capture it verbatim as `updated_display` for every PR while you're there. It costs nothing extra (you're already loading this page) and it's the key to the staleness check below.

**⚠️ Staleness check — added 2026-09-09, do this before opening any PR's full page (per Nóra/Carlos, PR#4181/LPD-101664 accuracy bug).** Read the `PR Snapshot` section of `context_scratch.md` (already loaded as part of the shared context at the start of every run). For each PR number present in that cache, compare its cached `updated_display` + `captured_date` against the fresh `updated_display` you just read from the list page:
- Convert both to an approximate absolute date (today's date, or the cache's `captured_date`, minus the number of days/hours the text names — e.g. cached `"11 days ago"` captured on `captured_date: 2026-09-07` implies the PR last changed around 2026-08-27). If GitHub's freshly-displayed update implies a **later** date than that → the PR changed since last run.
- If a PR is **not** in the cache at all (new PR, or the cache predates this feature) → always treat it as changed.
- If the comparison is ambiguous for any reason (GitHub switches to an absolute "Updated on Mon DD" format for older PRs, the text doesn't parse cleanly, etc.) → default to treating it as changed. Accuracy wins over savings whenever unsure.

**For PRs that did NOT change:** skip opening the full page entirely. Carry the cached `reviewer`, `reviewer_status`, `assignees`, and `latest_comment_flag` straight into that PR's `pr_data.json` entry unchanged, alongside the title/number/URL you already have from the list page. This is the actual savings — on a quiet day most of the 10-20 open PRs fall in this bucket and only the handful that actually moved get a page load.

**For PRs that DID change (or are new):** open the full page exactly as before. Confirm the green **"Open"** badge is present (discard Closed/Merged). Collect per PR: number, title, **author** (the GitHub login of the PR sender — required for cross-team detection, rule 3, and for the assignee-ownership check below), opening date (YYYY-MM-DD), linked Jira key (pattern `LPD-NNNN` or `LPP-NNNN` from title or branch), reviewers (ignore the `liferay-headless` and `gemini-code-assist[bot]` bots — treat bot-only as no reviewer) with each reviewer's status (pending / approved / changes_requested), and **assignees** (the GitHub logins in the PR sidebar's "Assignees" field — read the same sidebar as Reviewers; use the full-page text scrape, not a DOM/JS query, since the sidebar has previously been misread by JS selectors that instead matched a keyboard-shortcuts overlay). The unauthenticated `api.github.com` is rate-limited to 60/hr — prefer scraping the authenticated PR pages over API calls.

**Latest-comment read — added 2026-09-09, only for PRs you're already deep-scraping under the rule above.** The same full-page text scrape that gets you reviewers/assignees also shows the timeline, including the most recent comment(s) — reading them costs no extra page load. Set `latest_comment_flag` to a short (under ~15 words) plain-English note **only** when the latest comment states something the structured reviewer/assignee fields above don't already capture — e.g. "no need to review this for now, more changes coming" when the formal review request hasn't been withdrawn, or a stated hold/blocker. Leave it `null`/omitted otherwise — most PRs won't need it, and it is not a substitute for reading assignees/reviewers correctly. This is what makes a comment-only handoff (like Carlos's on PR#4181) visible without reading every PR's comments every day: only the PRs that already needed a fresh page open (because something structural changed, or a new PR) get their comments read at all.

**⚠️ 2026-08-25 — the field list above is exhaustive, not a starting point, with the one exception just named.** Do not pull the PR description, commit history, or CI/status-check comments — none of that is used anywhere downstream. On 2026-08-25, several PRs in a run were scraped as full pages (description, commits, CI comments included) before this was caught partway through and switched to targeted extraction for the rest — the first few PRs alone were a meaningful share of that run's token cost. Extract only the named fields (now including the latest-comment glance above, and only for PRs being deep-scraped), starting from the very first PR in the list, every run.

**Untested idea, not yet adopted (2026-08-26) — a GitHub API/connector path, if one becomes available, would likely be cheaper than per-PR page scraping.** This step's per-PR-page-open pattern (navigate + locate + extract per PR) is already fairly close to minimal for browser scraping, but it's still one full page load per PR — for a 14-PR sprint that's roughly 3× as many Chrome MCP calls as PRs. A single GitHub API/GraphQL call (or a connected GitHub MCP connector, if the org ever adds one) could return title/author/reviewers/assignees/draft-status for every open PR in one round trip. A 2026-08-26 check found this sandbox's direct network access to `api.github.com` is proxy-gated per-repository (`liferay-headless/liferay-portal` returned "GitHub access to this repository is not enabled for this session" without an explicit grant) — so this is not a drop-in fix and needs verifying in the actual scheduled-run environment (not just an ad-hoc session) before relying on it. Don't attempt an API path on your own initiative if it isn't already wired up here; note the idea to the user instead.

Set `parent_key` and `lpp_fix_key` to `null` in the initial scrape — they get filled in by the mandatory resolution step below, done by Claude, before the data is considered ready to build from.

**PR parent resolution — mandatory, do this yourself, every run (2026-07-29 clarification):** build `sprint_keys` from the Jira sprint issues. For any PR whose `jira_key` is not in `sprint_keys`, call `getJiraIssue` (fields: `parent`, `issuetype`, `summary`, `status`) and set `parent_key` to the parent's key if it's in `sprint_keys`. **Board beta v0.15.0:** for every PR that stays standalone (no `parent_key`), also write its Jira issue to `WORK_DIR/pr_jira.json` as `{"LPD-1": {"summary": "…", "status": "In Review", "statusCategory": "indeterminate"}}` — `board.py` shows it under the PR title on the PR row. Missing file = PR rows show the title and a Jira link without status. Run these lookups in parallel. If a PR has no parseable Jira key, flag it in chat and skip it.

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

2. **Open each candidate that needs it.** For every entry in `slack_candidates.json` with `reply_count > 0`: find that message's timestamp link on the page (its `href` is the permalink — e.g. `.../archives/C5E1CRLJY/p1783505623537369`) and navigate directly to the deep-link URL — `https://app.slack.com/client/<TEAM_ID>/<CHANNEL_ID>/thread/<CHANNEL_ID>-<ts>` where `<ts>` is the permalink's `p<digits>` converted to `<digits[:-6]>.<digits[-6:]>` (e.g. `p1785243005783069` → `1785243005.783069`) — then run `get_page_text`. **(2026-08-26: use direct navigation as the primary method, not just a fallback.** It was originally documented only as a fallback for when clicking "View thread" silently failed to update the panel (2026-07-31), but it is also cheaper and more deterministic than click-and-verify — a `navigate` + `get_page_text` pair, versus locating the clickable element with `find`/`computer`, clicking it, and then re-reading. Clicking through the UI is still a valid fallback if the deep-link format ever stops resolving.) For entries with `reply_count == 0`, you only need the permalink — do not bother opening the thread (there is nothing to read). Append one record per candidate to a single JSON array file, e.g. `/tmp/slack_details.json`:
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
   This checks each thread's reply authors against `Team Slack Names`, applies any existing `dismiss` overrides, sorts unanswered threads oldest-first, writes `slack_data.json`, and updates the `Slack Thread Snapshot` section of `WORK_DIR/context_scratch.md` in place — synced back to the shared Confluence context page in Workflow → 3.1, same as the other caches. Pass `WORK_DIR/slack_data.json` to `headless_daily_report.py` via `--slack-data-file`. **See the 2026-07-31 known issue above (Preconditions): if this prints `⚠ No '## Team Slack Names' section found` or `⚠ Team roster is empty` on a context page that should have a populated roster, that is a parser bug, not an actually-empty roster — strip blank lines from `context_scratch.md` and re-run before trusting the output.**

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
`changelogs` is added automatically when `--changelog-file` is passed to `assemble_jira_data.py` (see Workflow → step 1a). It should be present on every normal run — it is not something you skip by default. Similarly, `--comment-file` (also from step 1a) merges each candidate's comment data directly into its `sprint_issues[*].fields.comment` — it does not add a new top-level key, since `comment` belongs on the issue itself, not in a separate lookup table.

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
  "draft": false,
  "updated_display": "2 days ago",
  "latest_comment_flag": null
}
```
`reviewers` is a list (a PR can have more than one human reviewer requested) — bots are already filtered out per the collection rule above. `assignees` is a list of GitHub logins from the PR's "Assignees" sidebar field; it feeds the ownership rule below and is independent of `reviewers` (a PR can have an assignee with no reviewer, or vice versa).

`updated_display` (2026-09-09) — the verbatim "Updated ..." text from the PR list page, captured for every PR regardless of whether it was deep-scraped this run (for PRs that weren't, it's still the fresh value from the list page — only the reviewer/assignee/comment fields get carried forward from cache). `latest_comment_flag` (2026-09-09) — `null` for almost every PR; only set (per the staleness-check section above) on a deep-scraped PR whose latest comment reveals something the structured fields don't already show.

There is no `testing_panel.json` any more (removed 2026-07-09) — the Test section is static, see "Test Section" above.

**`slack_data.json`** — optional third file, always generated by `assemble_slack_data.py classify`, never hand-crafted. JSON array, one object per unanswered thread, already sorted oldest-first:
```json
[{"permalink": "https://liferay.slack.com/archives/C5E1CRLJY/p1783505623537369", "title": "Translation of problem messages", "author": "Alberto Chaparro", "created_date": "2026-07-09", "age_days": 1, "reply_count": 5}]
```
Omit `--slack-data-file` entirely if Slack scraping was skipped this run — the report renders fine without it.

### HTML Preview

Run `headless_daily_report.py` from `SKILL_DIR` **without** `--publish`, passing the data files from `WORK_DIR` (`--jira-data-file`, `--pr-data-file`, and `--slack-data-file` if collected). After it completes, report: section row counts (1a, 1b, 2a, 2b), excluded count, the per-section PR counts (PRs routed to the top of 2b. Assigned and 2a. Needs Owner), how many unanswered Slack threads are pinned above them, link to the generated HTML file, and any warnings or changelog fetch failures.

**Section 1 split into 1a/1b — 2026-08-26 (per Nóra).** "In Progress" is no longer a single table; it's two:

- **1a. Needs Attention** — everything that used to be Section 1, MINUS the carve-out below. Sort order is completely unchanged (tier ascending, then days per the existing per-tier rule — see `_sort_section1()`).
- **1b. In Progress not in the Iteration** (renamed 2026-08-27 from "Long Time Ago", per Nóra) — a new carve-out: **Planned** LPD work (tier Expedite "2" / Focus "12" / Regular "13") that is in an in-progress status but whose parsed sprint field (`sprint_name`, from `customfield_10020`) does **not** exactly match the currently active sprint (`ctx.sprint_field`, e.g. `HL26M3|DEV#18|Aug24-Sep04`). This is planned work that's still technically in progress but has fallen out of the sprint it was supposed to land in. Sort order here is flat — no tier grouping at all — ordered purely by days-in-progress descending (longest-running first, see `_sort_section1b()`).

  **2026-08-27 fix (per Nóra) — `sprint_name` parsing was picking the wrong array entry.** `customfield_10020` is an array of every sprint an issue has ever been in, and it is **not reliably chronological** — Jira can and does return the currently-active sprint anywhere in the array, not just last (confirmed live: LPD-96499's array was `[DEV#14(closed), DEV#18(active), DEV#17(closed), DEV#16(closed), DEV#15(closed)]` — the active sprint was 2nd, not last). The parser used to take `sprint_list[-1]` unconditionally, which silently misrouted ~20 in-sprint Planned issues from 1a into 1b whenever their *last* array entry happened to be an older closed sprint even though the active sprint was also present earlier in the array (e.g. LPD-96499/96693/96723/97697/94248/99738/100250/100251/100252/100296/100985/101182). Fixed: `parse_issue()` now prefers the array entry whose own `state` is `"active"`; it only falls back to the last entry (previous behavior) when no entry is marked active at all. **If a Planned, actively-worked issue is showing up in 1b when it should obviously be in 1a (or vice versa), check its raw `customfield_10020` array for an `"active"`-state entry before assuming the sprint field itself is stale or wrong.**

Everything that is NOT a Planned-tier LPD issue (all Unplanned tiers — SEV, BPR, PTR, LPP, release blockers — across any project) always lands in 1a; the active-sprint check only ever applies to Planned LPD work, since the sprint field isn't a meaningful signal for Unplanned issues in the first place. The match against `ctx.sprint_field` is **exact string equality** — an issue in an old closed sprint, or with a blank/missing sprint field, routes to 1b, not 1a. This is intentionally stricter than the unrelated Rule 5 non-Headless exclusion check in `should_exclude()`, which only tests `sprint_name.startswith("HL")` (i.e. "ever assigned to *any* Headless sprint, current or past") — that check decides whether the issue is Headless-owned at all; the 1a/1b split decides whether Planned work is current or stale, a different question entirely. It is also unrelated to the newer Rule 5b (v2.1.8, above) — Rule 5b is an *exclusion* rule keyed off the same `headless_sprint` flag but gating whether a non-sprint LPD appears in the report at all; the 1a/1b split only decides, for issues that already passed exclusion, which In Progress sub-table they render in.

Internally `route_issue()` now returns `"1a"` / `"1b"` (not a bare `"1"`); `report_data` carries separate `section1a` / `section1b` lists. **"1a"/"1b" are deliberately unrelated to the "2a"/"2b" codes** used internally for Pick Up Next (which are themselves already display-swapped, see the 2026-07-08 fix noted above) — this naming was chosen specifically to avoid colliding with that existing pair. Both the ADF publisher and the HTML preview render one h2 "🔴 In Progress" followed by two h3 subheadings ("1a. Needs Attention" / "1b. In Progress not in the Iteration"), each with its own table (or an empty-state paragraph). All other rules — exclusions, PR dedup/routing, Slack routing, Section 2 (Pick Up Next) — are unaffected by this split.

**Open PRs routing:** There is no separate Pick Up Next PR table. Open PRs route into a Section 2 table and sort to the top, ahead of issue rows, based on whether the PR has an **owner**: a human reviewer, OR a human GitHub assignee other than the PR's own author. (Self-assignment — the author assigning the PR to themselves — is the default/trivial case on GitHub and does not count as someone else having picked it up; an assignee only counts when it's a *different* person from the author.) PR with an owner → top of 2b. Assigned (longest-open first); PR with no owner at all (no reviewer and no non-author assignee) → top of 2a. Needs Owner (longest-open first). PRs with no parseable Jira key are flagged in chat and skipped.

> **2026-07-08 follow-up:** the displayed section numbers were swapped to match the render order set earlier that day (Needs Owner renders first, Assigned second) — "2a." now labels Needs Owner and "2b." now labels Assigned. This is a label change only; nothing about routing logic or content moved.

> **2026-07-08 fix:** this rule used to look only at `reviewer` and missed PRs that had a real assignee but no reviewer requested yet (they were wrongly parked in 2b). See `CHANGELOG-fixes-2026-07-08.md` for the full story and the exact `has_owner` logic in `fetch_open_prs()` / the standalone-PR routing block in `headless_daily_report.py`.

**Section 1 (In Progress) visibility gate — an issue can be structurally eligible and still not appear:** being in an in-progress status for LPD/LPP is necessary but not sufficient. `evaluate_triggers()` also requires at least one *actionable* trigger — a status change, an assignee change, a new comment since the last snapshot, a PR needing action, or a staleness/age threshold crossed — or the issue is silently dropped from Section 1 (deliberately, to keep the section from being 40 rows of "nothing changed"). This is by design, but it has a known gap pattern: an issue with **no fresh event** (no new comment, no status/assignee change) is invisible even if it has been sitting for weeks, unless age itself is wired up as a trigger for that project.

- **LPD** has always had an age-based trigger (Trigger 7): `LPD_ORANGE_THRESHOLD` / `LPD_RED_THRESHOLD` (by t-shirt size) — days since creation alone is enough to surface a long-running LPD even with no other activity.
- **LPP did not have this until 2026-07-08.** `LPP-64236` (40 days old, in analysis, no trigger otherwise since its only comment landed the same day as a snapshot) was silently gated out of Section 1 despite being exactly the kind of stale, long-lived item that needs visibility. Fixed by adding **Trigger 7b**: any LPP older than `LPP_ORANGE_THRESHOLD` (10 days) or `LPP_RED_THRESHOLD` (19 days) now surfaces with `"{N}d in progress — check for blockers"`, mirroring LPD's Trigger 7. See `CHANGELOG-fixes-2026-07-08.md`.
- **If a future report seems to be missing a long-lived issue that "should obviously be there":** check whether its project has an age-based trigger at all before assuming the exclusion or tier logic is at fault — a missing age trigger is easy to miss because the issue looks correctly *classified*, just invisible.

**2026-08-27 fix (per Nóra) — the trigger gate no longer applies to 1a at all.** Before this fix, `"1a"`-routed issues were still subject to the same trigger requirement as everything else, and it was dropping issues that are supposed to be unconditionally visible per the 1a/1b rule — e.g. LPD-103525 and LPD-101274 (both Planned-tier, in progress, in the currently active sprint) had no recent trigger and were silently skipped from Section 1 entirely, which is a stricter and more surprising failure than merely landing in the "wrong" 1a/1b bucket. Per Nóra's explicit choice, `_gate_exempt` now also includes `section == "1a"` — i.e. every Unplanned issue and every Planned-in-active-sprint issue always shows in 1a, trigger or not, with a default `"No new activity — review manually"` Action cell when no other trigger text fires. **1b keeps the trigger requirement** (that's deliberate — it's the "stale carryover" bucket, and showing all of it unconditionally would make it balloon). If a Planned/active-sprint issue is still missing from 1a, the trigger gate is no longer a possible explanation — look at routing (see the `customfield_10020` fix above) or exclusion instead.

**LPD sprint-membership status gate (Rule 5b in `should_exclude()`) — 2026-08-26, per Nóra.** The sprint filter (`filter=54796`) was widened on 2026-08-26 to surface more issues, and the existing Rule 5 ownership check (headless team / headless sprint / headless assignee — see Preconditions above) alone was not enough to keep the report to what the team actually wants under "Planned work": Rule 5 kept every LPD owned by a Headless team/assignee at *any* status, including pre-development ones (Open, Ready for Development, Ready for Refinement, In Design, Ready for Research, In Refinement — `SECTION2_STATUSES["LPD"]`), the moment the wider filter started returning them. Rule 5b adds a second gate, checked only for LPD issues that already survived Rule 5:

- An LPD **in the current Headless sprint** (`sprint_field`/`sprint_name` starts with `HL` — `headless_sprint` True) is unaffected — it's planned work for this iteration and is kept at any status, exactly as before.
- An LPD that is **not** in the current Headless sprint, and only survived Rule 5 via team/assignee ownership (`headless_sprint` False), is now also gated on status: kept only if it's already at or past "in progress" — i.e. its status is in `SECTION1_STATUSES["LPD"]` (in progress, in development, escalated, in product review, ready for product review, in review). Anything still in a pre-development status is excluded with reason `"Non-sprint LPD not yet in progress"`.
- SEV bugs/BPRs bypass Rule 5 (and therefore Rule 5b) entirely, same as before — this only affects ordinary LPD "planned work" rows.

This only touches LPD. "Unplanned work" (LPP) and PTR/BPR are unaffected — LPP has no sprint-field ownership check at all (see the "Team ownership changes" note in Preconditions), and PTR/BPR are gated purely by their own rules (6b, 7) which don't reference `sprint_field`. If a widened filter later needs the same treatment for another project, add an equivalent rule there rather than broadening Rule 5b's `project == "LPD"` guard — the projects have different meanings of "planned" (see the project's own Sprint Field vs backlog semantics).

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

> **Iteration check (beta, mandatory):** as soon as `assemble_jira_data.py` has written `WORK_DIR/jira_data.json`
> and **before** the first `headless_daily_report.py` run, execute
> `python3 board.py --sync-sprint --context-file WORK_DIR/context_scratch.md --jira-data-file WORK_DIR/jira_data.json`.
> It reads the active `HL…` sprint from the fetched issues and, if it differs, updates `sprint_label`, `sprint_field`,
> `label_dev`, `label_dis`, `start_date`, `end_date` in the Sprint Metadata. Quote its one-line result in the run summary.

Run the three Jira MCP queries **sequentially** (see Jira Sprint Data above) — this part cannot be parallelized (documented crossed-response risk). As soon as the sprint query's issue list is in hand (you don't need SEV bugs/BPRs yet, and you don't need `assemble_jira_data.py` to have run — step 1a only needs each candidate's key/status/project, which the raw sprint result already has), **three independent steps can run concurrently**: step 1a (changelog + comment pre-fetch), step 1b GitHub PR scraping, and step 1b Slack scraping. None of the three depends on the others' output. **Recommended: dispatch all three as separate delegated subagents in one batch** rather than doing them one after another — this is one of the largest available time savings in the whole run, since 1a alone has historically taken several minutes and there's no reason PR/Slack scraping has to wait behind it. Only build `jira_data.json` with `assemble_jira_data.py` after both the SEV bugs/BPRs queries (run sequentially after the sprint query, per above) and step 1a have finished. Write the JSON files (`jira_data.json`, `pr_data.json`, and `slack_data.json` if collected) to `WORK_DIR`. Run the script without `--publish`.

**When delegating any of these three to a subagent, state the completion condition explicitly and unambiguously** (e.g. "keep paging until hasNextPage is false — do not stop after the first page even if it looks complete") — an ambiguous instruction has caused a subagent to stop after one page of a two-page query in the past, costing a follow-up round-trip to finish it. **Also include, in every such dispatch: the relevant cache/context content the subagent needs (see the PR-staleness trip-wire in Run Budget Guardrails above — a subagent starts with none of this conversation's context), and record checkpoint 2 from Run Budget Guardrails immediately before sending all three.** When they've all returned, record checkpoint 3 and apply its stop/continue rule before moving on to assemble/build.

**Before any of this, in a Cowork/sandboxed session:** apply the "Read-only skill mounts" workaround from Configuration above — copy the skill folder to a writable scratch directory and run every script from there. Skipping this step means the HTML-preview run at the end of this section will fail with a read-only filesystem error after all the data collection is already done.

#### 1a. Pre-fetch changelogs AND comments via the Atlassian MCP (required, not optional)

**Do this on every run — do not skip it and fall back to letting `headless_daily_report.py` fetch changelogs itself.** The script's own direct-HTTPS fallback (`jira_get_issue(expand="changelog")`) is routinely blocked by the sandbox's proxy, which is exactly what caused missing "Days in Progress" values in past runs (rows silently fell back to just the status name, or — after the 2026-07-08 fix — show "(days unknown — changelog unavailable)"). Fetching via the MCP here avoids that failure mode entirely.

**2026-08-25 perf fix — this step now also carries the `comment` field, for the same set of issues, in the same call.** Since the bulk sprint query above no longer fetches `comment` (it was the reason that query needed ~16 sequential `maxResults:5` pages), each candidate's comment data has to come from somewhere — and this per-issue fetch was already happening for changelogs, so it costs nothing extra to add `"comment"` to the same call's `fields`. Build TWO dicts from the same set of `getJiraIssue` responses: `{key: [...changelog.histories...]}` and `{key: {...fields.comment...}}` (i.e. the raw `{"comments": [...]}` object). Write them to two separate files and pass them as `--changelog-file` and `--comment-file` respectively (see "Build and validate `jira_data.json`" above).

1. From the sprint issues just loaded, identify the **Section-1 candidates**: every LPD, LPP, BPR, and PTR issue in an in-progress-like status — these are the issues whose "Days in Progress" cell depends on `get_first_active_date()`. Use the exact status sets the script itself uses (`SECTION1_STATUSES` in `headless_daily_report.py`), not an abbreviated version — under-listing this caused a real miss on 2026-07-13 (LPD-97411, status "In Review", fell through the gap because this list only mentioned "In Development/In Progress"):
   - **LPD**: in progress, in development, escalated, in product review, ready for product review, in review — all six, not just the first two. (2026-07-13: LPD issues past development now track "days in current status" — e.g. "3d in review" — rather than days since development started; see `get_first_active_date()`'s LPD branch. The changelog is needed either way, so pre-fetch for all six statuses regardless.)
   - **LPP**: any status past In Queue.
   - **BPR**: Original Fix Committed or later.
   - **PTR** (2026-07-13): any non-Answered status kept by Rule 6b (see "Deduplication rules" below) — though in practice PTR's "days open" always falls back to `issue["created"]`, so pre-fetching its changelog isn't required for the Days cell; only fetch it if some other feature needs PTR history.
2. For each candidate, call `getJiraIssue` with `expand: "changelog"` and `fields: [..., "comment"]` (add `comment` to whatever field list you're already using for this call) via the Atlassian MCP. From each response, collect `changelog.histories` into one dict keyed by issue key (`{"LPD-12345": [...histories...], ...}`) and `fields.comment` into a second dict keyed the same way (`{"LPD-12345": {"comments": [...]}, ...}`).
3. Write both dicts to JSON files in `/tmp/` (e.g. `/tmp/changelogs.json`, `/tmp/comments.json`). **If `/tmp/` already has a file at that name owned by another user (seen in some sandboxes — a stale, unrelated file causes a `PermissionError` on overwrite), write to a writable path inside `WORK_DIR` instead and use that path in the next step; don't fight for `/tmp/` specifically.**
4. Pass them to the assembler with `--changelog-file /tmp/changelogs.json --comment-file /tmp/comments.json` (or the `WORK_DIR` paths if you redirected per the note above) — they get merged into `jira_data.json`'s `changelogs` field and each candidate's `sprint_issues[*].fields.comment` respectively (see Data Files below).

If an individual `getJiraIssue` call fails for a given issue, skip just that one (log it) and continue — do not abort the whole pre-fetch. A handful of individual failures is fine; the script's HTTPS fallback and the 2026-07-08 fetch-failure labeling still cover any gaps.

**2026-08-14 addendum — issue these calls at real concurrency, not "a handful at a time."** Unlike the three sprint/SEV/BPR JQL queries above (which have a documented, confirmed crossed-response risk when run in parallel), each `getJiraIssue` call here targets a distinct issue key with no shared pagination state — there is no known crossed-response risk for this step. A run that fetched dozens of candidates a few at a time made this one of the largest wall-clock contributors in the session. Fan these out at meaningfully higher concurrency, ideally via a delegated subagent that returns only the consolidated `{key: [...histories...]}` dict — this keeps the per-issue changelog payloads out of the main thread's context as well as speeding up the step. See `CHANGELOG-fixes-2026-08-14.md` (§2).

**⛔ MANDATORY, 2026-09-10 (confirmed incident, not a hypothetical) — delegate this step to a subagent whenever there are more than ~10 candidates; never loop `getJiraIssue(expand=changelog)` calls in the main thread.** The guidance immediately above ("ideally via a delegated subagent") was only a recommendation, and on 2026-09-10 a run fetched 14-15 of ~60 candidates' full payloads — changelog histories, comment bodies, author objects, avatars, timestamps — directly into the main conversation before the pattern was caught (only because the user asked why the run was taking so long), burning a large share of a session on data that was never even written to disk, so it had to be re-fetched anyway. This is now a hard rule, not a preference:
- Dispatch a subagent for this step whenever the candidate count exceeds ~10. Instruct it explicitly to return only the consolidated `{key: [...histories...]}` / `{key: {...comment...}}` dicts (written to files it creates itself) — never the raw per-issue API responses.
- **If you catch yourself about to make a second consecutive `getJiraIssue(expand=changelog)` call from the main thread for this step, stop immediately.** Don't finish fetching the rest inline "since you're already partway through" — that reasoning is exactly what let the 2026-09-10 run get to issue 14-15 before stopping.
- Before switching to the subagent, write whatever you've already fetched inline to a file in `WORK_DIR`/`/tmp/` (reconstruct it from the conversation if the raw tool results are still available) so it isn't wasted — then delegate only the remaining candidates.

**⚠️ MANDATORY, 2026-08-25 — before redoing this step by hand, check for a completed subagent output first.** If a delegated subagent call for this step shows as rejected, cancelled, or interrupted in the visible chat, that is **not proof the subagent actually stopped** — a subagent that was already dispatched can keep running in the background to completion regardless of what the chat transcript appears to show. On 2026-08-25 this happened twice in one run: two separate delegated attempts both looked rejected, so the changelog/sprint fetch was redone a third time by hand — meaning the same ~44-issue fetch ran three times end to end, which alone accounted for roughly a quarter of that run's total token cost. **Before falling back to a manual re-fetch of this step (or any other delegated step), check `WORK_DIR` and the session's subagent output/transcript locations for a file that already contains the result.** Only redo the work by hand if no completed output exists.

**Temp files:** Any intermediate files created during this step (chunks, payloads, etc.) must be written to `/tmp/` — never to `SKILL_DIR` or `WORK_DIR` — **except** where the `/tmp/` permission note just above applies.

#### 1b. Slack Needs Owner (run by default — Chrome MCP only — see "Slack Needs Owner" under Input above)

Scan → open each candidate thread that needs it → classify. This runs on every report by default. Only skip it (omit `--slack-data-file`) if Chrome MCP isn't available, or the user has explicitly said to skip it for this run — and flag that decision to the user before the approval gate, not only in the post-publish summary (2026-07-15 incident: a silent skip missed a real unanswered thread).

#### 1c. Board data + build (beta output — after the HTML preview from Step 1 exists)

All configuration, the exact calls and the layout rules live in `board.py` (see its header). Never expand
changelogs here; no subagent needed (~5 + 3×epics small calls). Budget checkpoint before starting.

1. `python3 board.py --plan` → run calls A–C in parallel; then `python3 board.py --plan --epic-keys <keys from A>`
   → run D–E in parallel. If `--plan` reports more than 25 epics, stop and ask.
2. Write `WORK_DIR/epics.json` exactly in the format `--plan` prints, and the Testray page body to
   `WORK_DIR/testray.html`.
   **AVD metrics (section 3) — stored, never "?" (2026-10-16, per Nóra).** The four AVD numbers live in the
   `## AVD Metrics` section of the shared context page (synced into `WORK_DIR/context_scratch.md` in Step 0), e.g.
   `{"story": {"value": 45, "since": "2026-10-16"}, "epic": {"value": 119, "since": "2026-10-16"}, "handoff": {"value": 72.7, "since": "2026-10-16"}, "wip": {"value": 13, "since": "2026-10-16"}, "last_reviewed": "2026-10-16"}`
   (`since` = the date that number last changed; goals are fixed in the board: story 15d, epic 65d, handoff 24d, WIP ≤ 18).
   - **Ask on every run, before building:** show Nóra the stored numbers with their dates and ask with AskUserQuestion
     whether there are new AVD numbers (options: "No change — keep these" / "Yes — I'll paste the new numbers").
     If the run is unattended, don't block: use the stored numbers and put the question in the run summary instead.
   - **New numbers:** update only the metrics whose value changed, and set their `since` to today. Unchanged metrics keep
     their old `since`. Set `last_reviewed` to today either way. Never read the AVD site yourself.
   - **Write `WORK_DIR/avd.json` on every run** from the stored section:
     `{"story": {"value": 45, "basis": "Number not changed since 2026-10-16"}, "epic": {...}, "handoff": {...}, "wip": {...}}`
     (the `basis` text is what the tile shows under the number; optional `outliers` as in the board.py header).
     Only if the section is missing or empty, leave the tiles as "?" and tell Nóra.
   - The `## AVD Metrics` section is saved back to the shared page with the rest of the run memory in Step 2 —
     `--confirm-publish` passes unknown sections through unchanged, so edit it in `WORK_DIR/context_scratch.md` before that step.
3. `python3 board.py --build --work-dir WORK_DIR --report-html <the daily_actions_report_<date>.html written in Step 1> --jira-data-file WORK_DIR/jira_data.json`
   (`WORK_DIR/context_scratch.md` is picked up automatically: its Account IDs + Team GitHub Logins feed the Assign
   buttons, which only work on the Google Site — the Apps Script there updates Jira and GitHub.)
   It validates epics.json, builds `board_<date>.html`, runs the count check against the preview (prints OK or
   MISMATCH) and copies the board to `/mnt/user-data/outputs/`. Report MISMATCH or schema problems; never hand-edit the HTML.

### 2. Deliver the board, save the run memory, then ask for approval

1. Send `/mnt/user-data/outputs/board_<date>.html` with SendUserFile. **Keep the returned `fileUuid`** (needed in Step 3).
2. **Immediately** (no approval needed — nothing becomes visible to the team) re-run `headless_daily_report.py` with the
   same data files plus `--confirm-publish --sprint-context-file WORK_DIR/context_scratch.md` (updates only the local file:
   State Snapshot date → today, statuses, caches, `latest_skill_version`; it publishes nothing).
3. Read the updated `WORK_DIR/context_scratch.md` and call `updateConfluencePage(context_page_id, content)`
   (contentFormat markdown) — the shared context page 5190975505. Confirm the call succeeded; if it fails, say so
   clearly (the next run would otherwise compare against stale data).
4. Run summary for the user — the data quality summary below, the board tab counts (1a, 1b, 1c, folded, 2a, 2b), the
   count-check result, the iteration-check line, the AVD numbers used (with "not changed since" dates, and the
   "any new AVD numbers?" question if it could not be asked earlier) and "memory saved ✅ / ❌".
5. **⛔ Approval gate:** ask "Publish this board to the Google Site?" and **stop**. Do not go to Step 3 without an explicit yes.
   If the user asks for changes or reports a problem, see Step 4. (Token budget checkpoint 4 from Run Budget Guardrails applies here.)

**Data quality summary (from the old approval gate):**
- Sprint issues count (e.g. "47 sprint issues loaded")
- How many have a non-empty Topic/summary (e.g. "47/47 have summaries ✅" or "0/47 have summaries ❌")
- How many have a t-shirt size in `customfield_10804` (e.g. "12/47 have t-shirt size")
- Section counts: In Progress — 1a. Needs Attention (N), In Progress — 1b. In Progress not in the Iteration (N), Assigned (N — including PRs with a human reviewer at the top), Needs Owner (N — including no-reviewer PRs and unanswered Slack threads at the top), Excluded (N)
- Any fields that were null/missing across the board (flag these explicitly)

If any data quality issue is present (empty summaries, missing sprint field, missing t-shirt sizes for most issues), warn the user **before** they open the HTML:
> ⚠️ Data quality issues detected: [list them]. The report may have empty Topics, wrong Days in Queue, or incorrect issue inclusion. Consider retrying in a fresh session for a clean run.


### 3. Publish to the Google Site (only after the user's explicit approval)

Write the board into the Drive-synced folder on Nóra's Mac with `device_commit_files`, using the **`fileUuid` from
Step 2.1** (not `stagedPath` — a same-day re-run can otherwise commit a stale copy), `force: true` →
`devicePath: /Users/nori/Library/CloudStorage/GoogleDrive-nora.szel@liferay.com/My Drive/Headless/Headless Daily Board/board_<date>.html`.
Google Drive for desktop syncs it; the site https://sites.google.com/liferay.com/headless-daily/home (Apps Script web app
showing the newest `board_*.html` in that folder) updates within about a minute. Confirm in one line: "site updated ✅".
If the device is not reachable or the folder is not connected, say so and ask Nóra to drag the file into that Drive folder.

### 4. If the user reports a problem with the board

The memory is already saved (Step 2), the site is only updated after approval (Step 3). If the data was wrong (e.g. a fetch failed), fix the cause and rerun the skill —
the rerun overwrites the memory with corrected data. Never hand-edit the board HTML.
