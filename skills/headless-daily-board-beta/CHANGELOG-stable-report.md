# Changelog — headless-daily-actions-report

Version numbers were introduced in **2.0.0** (2026-07-28). Everything before
that shipped without a version string, so the entries below map each dated
fix — already documented in detail in the individual `CHANGELOG-fixes-*.md`
files — onto an informal version number, oldest first. Going forward, bump
`SKILL_VERSION` (set at the top of `headless_daily_report.py`,
`assemble_jira_data.py`, and `assemble_slack_data.py`) and add an entry here
on every change, however small. The dated files remain in the skill folder
for the full forensic detail (root cause, symptom, exact fix) behind each
entry — this file is the fast "what changed and when" index.

## 2.3.1 — 2026-09-10 (run-budget guardrails — confirmed incident fix)

Per Nóra: a run on 2026-09-10 ran ~2 hours and burned the whole session's
token budget with no report produced at all. First analyzed without
transcript access (wrongly suspected v2.2.0's PR-staleness feature); Nóra
then supplied the actual transcript, which showed the run never reached
GitHub PR scraping at all — it stalled in Workflow → 1a, where Claude
fetched Jira changelog/comment data for 14-15 of ~60 candidates one issue at
a time from the main thread instead of delegating to a subagent (previously
only a soft "ideally" recommendation), then lost more time to a rate limit
during recovery that wasn't announced promptly. See
`CHANGELOG-fixes-2026-09-10-run-budget-guardrails.md` for the full writeup,
including the superseded first-pass hypothesis.

- **Workflow → 1a, now a hard rule:** delegate the changelog+comment
  pre-fetch to a subagent once candidates exceed ~10; a "stop on second
  consecutive main-thread `getJiraIssue(expand=changelog)` call" self-check,
  plus a salvage-to-disk step before switching over.
- **New "Run Budget Guardrails" section:** a 5-checkpoint schedule across
  the whole run (context sync → subagent dispatch → subagent return, with a
  stop-and-report rule past ~1/3 of budget → Approval Gate → §3a publish
  attempt), using the Cowork `<total_tokens>N tokens left</total_tokens>`
  signal when present, tool-call counting otherwise.
- **Persistence rule generalized** from step-1a-only to all three
  Workflow → 1 phases, and across resumed sessions.
- **New rate-limit rule:** announce it immediately rather than silently
  waiting it out.
- Hard numeric ceilings added for every other previously-unbounded "keep
  going until done" loop (pagination, Slack scrolling, subagent turns).
- The v2.2.0 PR-staleness trip-wire and subagent-context-passing
  precautions from the first-pass hypothesis are kept as still-valid
  defense-in-depth, reframed as untested-on-a-live-run rather than as the
  cause of this incident.

`SKILL_VERSION` → 2.3.1 in all three `.py` files, for consistency (no
Python behavior change this round — same pattern as 2.1.7).

**Not yet verified against a live run.**

## 2.2.0 — 2026-09-09 (accuracy + cost feature — PR staleness check)

Per Nóra/Carlos: PR#4181/LPD-101664 sat showing "Waiting for review from ccorreagg (13d)" for two days after Carlos had already commented "no need to review this for now" and reassigned the PR to Petteri — because the report only ever reads structured GitHub reviewer/assignee fields, and Carlos's reassignment was a GitHub Assignees change the report never re-scraped, while his comment was never read at all. A full comment-check on all 10-20 open PRs every day was explicitly ruled out as too token/time expensive. See `CHANGELOG-fixes-2026-09-09-pr-staleness.md` for the full writeup.

- **New staleness check (SKILL.md, data-collection step only — no script logic):** the GitHub PR list page's "Updated X ago" text (already scraped every run, zero extra cost) is compared against a per-PR `updated_display`/`captured_date` now stored in the `PR Snapshot` cache. Only PRs whose list-page "Updated" text implies a change since the cached date get a full page open; everything else carries forward its cached reviewer/reviewer_status/assignees/latest_comment_flag. New PRs, or anything ambiguous to compare, always get the full open — savings never come at the cost of a silent miss.
- **New `latest_comment_flag` (SKILL.md + `_evaluate_pr_trigger`/`_evaluate_standalone_pr_trigger`):** for PRs that *are* deep-scraped under the rule above, Claude also glances at the same page's most recent comment (free — same page load) and sets a short plain-English flag only when it states something the structured fields don't already show. Rendered as its own `💬 ...` line in the Action column, additive to (not replacing) the structural read.
- **Bug fix, independent of the above — `_evaluate_pr_trigger()`/`_evaluate_standalone_pr_trigger()`:** previously never looked at `assignees` at all when building the Action text for a PR attached to an issue, so even a same-day fresh re-scrape picking up a GitHub assignee change (like Carlos → Petteri) wouldn't have changed the displayed text — it only ever branched on `reviewer`/`reviewer_status`. A human assignee (not the PR's own author) now leads the text as "Reassigned to {name} — review still pending from {reviewer} ({N}d)" whenever the review request isn't already APPROVED. This alone would have caught PR#4181's reassignment even without any of the staleness/comment-reading work above.
- **`PR Snapshot` cache schema (`update_caches`, `load_sprint_context`/`save_sprint_context` unchanged — already generic dict passthrough):** each PR entry is now `{status, reviewer, reviewer_status, assignees, updated_display, latest_comment_flag, captured_date}` instead of the bare string `"open"`. The cache was previously write-only (used only for an HTML-preview PR count) — this is the first time it's read back by anything.
- SKILL_VERSION bumped to 2.2.0 in `headless_daily_report.py`.

## 2.1.11 — 2026-08-27 (rename)

Per Nóra: Section 1b's heading is renamed from **"Long Time Ago"** to **"In Progress not in the Iteration"** — same bucket, same routing logic, display text only. Updated in `adf_heading(...)` (ADF publisher) and the HTML preview's `<h3>`, plus every docstring/comment/log line that referenced the old name in `headless_daily_report.py`, and the corresponding mentions in `SKILL.md`. `route_issue()`'s `"1b"` return value and `report_data["section1b"]` are internal identifiers, unaffected. See `CHANGELOG-fixes-2026-08-27.md` §5.

## 2.1.10 — 2026-08-27 (bug fix + feature)

Three fixes to the 1a/1b split shipped in 2.1.9, per Nóra's feedback the following day. See `CHANGELOG-fixes-2026-08-27.md` for the full forensic writeup.

- **Bug fix:** `parse_issue()`'s `sprint_name` used to take `customfield_10020[-1]` (the array's last entry) as "the current sprint," assuming the array is chronological. It isn't — Jira can return the active sprint anywhere in the array. This silently misrouted ~20 in-sprint Planned issues from 1a into 1b. Now prefers the entry whose own `state == "active"`, falling back to the last entry only when nothing is marked active.
- **Bug fix:** the Section-1 trigger gate (`evaluate_triggers()`) was dropping 1a-eligible issues (Planned+active-sprint, e.g. LPD-103525, LPD-101274) entirely when they had no fresh trigger event. Per Nóra ("Remove gate only for 1a"), `_gate_exempt` now also covers `section == "1a"` — Unplanned and Planned+active-sprint issues always show; 1b still requires a trigger.
- **New Rule 2b in `should_exclude()`:** Epic and Initiative issuetypes are now excluded unconditionally, for any project — this is an action report, not a container-of-work report. Four Epics (LPD-98772, LPD-86135, LPD-88573, LPD-94243) had been appearing as ordinary rows.
- Also investigated (not a code issue): a Confluence *edit-mode* rendering of Section 1 as one merged table turned out to be a stale, never-published editor draft, not a problem with the published page or the ADF this skill generates. See CHANGELOG-fixes-2026-08-27.md §4.

## 2.1.9 — 2026-08-26 (feature)

Per Nóra: Section 1 ("In Progress") is now split into two sub-buckets
instead of one flat table.

- **New `1a. Needs Attention`** — everything that used to be Section 1,
  minus the carve-out below. Sort order (tier ascending, then per-tier days
  rule) is completely unchanged — `_sort_section1()` was not touched.
- **New `1b. Long Time Ago`** — Planned LPD work (tier Expedite "2" / Focus
  "12" / Regular "13") that's in an in-progress status but whose parsed
  sprint field no longer exactly matches the currently active sprint
  (`ctx.sprint_field`). A blank/missing sprint field or an old closed
  sprint's name both route here, not to 1a. Flat sort, no tier grouping —
  purely days-in-progress descending (new `_sort_section1b()`).
- Unplanned work (SEV, BPR, PTR, LPP, release blockers — any project) is
  never subject to the active-sprint check and always lands in 1a; the
  split only ever applies to Planned LPD issues, since the sprint field
  isn't a meaningful signal for Unplanned work.
- `route_issue()` now takes a `ctx` parameter and returns `"1a"`/`"1b"`
  instead of a bare `"1"`. Chosen naming deliberately avoids colliding with
  the existing (already display-swapped) `"2a"`/`"2b"` Pick Up Next codes.
- `report_data` now carries `section1a`/`section1b` instead of `section1`;
  `build_adf_document()` and `generate_html_preview()` both render one h2
  "🔴 In Progress" followed by two h3 subheadings, each with its own table.
- Unrelated to, and layered cleanly on top of, the v2.1.8 Rule 5b exclusion
  gate above — Rule 5b decides whether a non-sprint LPD is *excluded*
  entirely; this split decides, for issues that already passed exclusion,
  which In Progress sub-table they render in.
- All other rules (exclusions, PR dedup/routing, Slack routing, Section 2)
  are unchanged.
- Verified via a synthetic routing/sort test (12 mock issues covering
  Planned/Unplanned × matched/mismatched/blank sprint field, LPP visibility,
  BPR, PTR, and both new sort functions), plus `py_compile` and the full
  `--test-exclusions` suite (all 13 tests, including v2.1.8's Rule 5b test)
  on all three scripts. **Not yet verified through a full live end-to-end
  run** (same caveat as 2.1.6/2.1.8 below — this has not been exercised
  against real Jira sprint data yet).

## 2.1.8 — 2026-08-26 (report scope)

Nóra widened the sprint filter (`filter=54796`) to catch more issues, and asked for the report itself to filter more so the wider net doesn't turn into a wall of noise in "Planned work" (LPD). See `CHANGELOG-fixes-2026-08-26-lpd-scope.md` for the full writeup. Short version:

- **New Rule 5b in `should_exclude()` (`headless_daily_report.py`):** an LPD issue that is not in the current Headless sprint (`sprint_field` doesn't start with `HL`) and only survived the existing Rule 5 ownership check via team/assignee is now also gated on status — kept only if it's already at or past "in progress" (`SECTION1_STATUSES["LPD"]`). Pre-development statuses (Open, Ready for Development, Ready for Refinement, In Design, Ready for Research, In Refinement) are excluded for that group. An LPD genuinely in the current HL sprint is unaffected — kept at any status, same as always. SEV bugs/BPRs still bypass Rule 5 (and therefore 5b) entirely.
- **Scope: LPD ("Planned work") only.** LPP ("Unplanned work"), PTR, and BPR are unchanged — none of them use a `sprint_field`-based ownership check, so Rule 5b's `project == "LPD"` guard doesn't touch them.
- Added `test_exclusion_lpd_status_gate()` covering all six pre-development statuses (excluded), all six Section-1 statuses (kept), an in-sprint backlog-status issue (kept regardless), and the SEV bypass (kept). All 13 exclusion tests pass (`python3 headless_daily_report.py --test-exclusions`).

## 2.1.7 — 2026-08-26 (perf)

A 2026-08-26 run used roughly a full session's token budget on its own (previously about half a session) for what should be routine, repeatable work. Post-run analysis of the session transcript (main thread + all delegated subagents) found the cost concentrated in a few specific, fixable behaviors, not in the underlying data collection. See `CHANGELOG-fixes-2026-08-26-token-efficiency.md` for the full breakdown and method. Short version:

- **New "Token Efficiency" section added near the top of SKILL.md** — four standing rules (no chunked/encoded payload injection via `javascript_tool`; batch `ToolSearch` calls; prefer text-based Chrome tools over `computer`; keep `TaskUpdate` calls coarse) that apply to every run, not just the publish step.
- **§3a/§3b publish step: closed off the single largest cost in the 2026-08-26 run.** Once `file_upload` fails (already expected/documented since 2026-08-14), the only correct next step is §3b's manual DevTools paste — a human pastes the text themselves, which is what makes it work regardless of script size. The 2026-08-26 run instead spent ~30% of its total tokens trying to push the ~96KB console script into the page via `javascript_tool`, base64-encoded and chunked — every chunk had to be read into Claude's own context first, and the transfer was then blocked outright by a content-safety filter on the first chunk. Nothing was gained; the step still had to fall back to the manual paste anyway. SKILL.md now says explicitly: don't attempt this, of any encoding, ever.
- **Slack Needs Owner: the deep-link thread URL is now the primary method for opening a candidate thread**, not just the documented fallback for when clicking "View thread" silently fails (2026-07-31). It's a `navigate` + `get_page_text` pair versus locate-click-verify, and was one of two Chrome-scraping subagents that were the second-largest cost in the 2026-08-26 run (the Slack subagent leaned heavily on the more expensive `computer` tool).
- **Open Pull Requests: noted (not yet adopted) that a GitHub API/connector path could replace per-PR page scraping** if one becomes reliably available in the scheduled-run environment — flagged as an untested idea, since a direct check on 2026-08-26 found this sandbox's network access to the repo is proxy-gated per-repository and needs a real grant before it could work.

## 2.1.6 — 2026-08-25 (perf)

A live run on 2026-08-25 was stopped by Nóra after 44 minutes with no
report yet produced — she asked for a concrete plan (and the actual skill
fix) to make the next run fast, not just correct. Root-caused and fixed the
same day. See `CHANGELOG-fixes-2026-08-25.md` §6 for the full writeup.
Short version:

- **The bulk sprint query no longer fetches `comment`.** This was the
  actual cause of the `maxResults:5` / ~16-sequential-page workaround from
  the 2.1.x/2026-08-14 era (see CHANGELOG-fixes-2026-08-14.md §1) — comment
  threads on this board can run to thousands of words, which blew past the
  MCP's per-page size limit at any page size above ~5. The 2026-08-14 test
  that tried dropping `comment` and concluded it "didn't fix it" was
  re-tested live on 2026-08-25 and, with `comment` actually removed, a
  single `maxResults:100` call reliably returns the full 78-issue sprint.
  The bulk fetch is now 1 call instead of ~16.
- **Comments moved to the per-issue candidate fetch** (step 1a, the same
  call that already fetches changelogs for Section-1-eligible issues) —
  costs nothing extra since it's the same call, and covers the only issues
  that ever read comment data downstream (trigger evaluation only runs on
  in-progress-like issues).
- **`assemble_jira_data.py` gained a `--comment-file` flag**, mirroring the
  existing `--changelog-file` pattern, to merge per-issue comment data back
  into `sprint_issues[*].fields.comment`.
- **Step 1a (changelog+comment pre-fetch), GitHub PR scraping, and Slack
  scraping can now run concurrently** once the sprint issue list is fetched
  — none of the three depends on the others' output, and none needs
  `assemble_jira_data.py` to have run first. Previously documented as
  happening one after another.
- Tightened the SEV bugs/BPR query instructions to explicitly require
  paginating to exhaustion — a 2026-08-25 run stopped after page 1 of the
  SEV bugs query and missed 6 of 21 real issues until a follow-up caught it.
- SKILL_VERSION bumped to 2.1.6 across all three scripts.

## 2.1.5 — 2026-08-25

The 2026-08-24 run published a report with a real Headless customer issue
(LPP-65271) missing entirely and three other-team issues (LPP-65328,
BPR-92226, BPR-91747) wrongly included, and separately took 1.5 hours and
far more tokens than expected. See `CHANGELOG-fixes-2026-08-25.md` for the
full writeup. Short version:

- **LPP-65271 was dropped from the whole report, not just Section 1** —
  caused by (a) a same-day date-string comparison bug in the "new comment"
  trigger check (`>` instead of `>=`), and (b) the Section-1 "no trigger →
  drop" gate having no carve-out for LPP the way PTR already has one. Both
  fixed — see §1.
- **LPP "Pending" now gets the identical hide-then-resurface-after-5-days
  treatment as "Solution Proposed"** (per Nóra) — previously only Solution
  Proposed had a dedicated gate for this; Pending relied on the same buggy
  generic gate by coincidence. See §2.
- **LPP-65328, BPR-92226, BPR-91747 wrongly counted as Headless work** —
  `should_exclude()` had a real team-ownership check for LPD and PTR but
  never one for LPP or BPR, so any other team's issue that happened to match
  the shared cross-team sprint filter passed straight through. Added a
  narrow, safe ownership check based on the "PT User `<Team>`" placeholder
  assignee pattern. See §3.
- Stale sprint metadata (`DEV#17` instead of the actual active `DEV#18`)
  refreshed in the shared context page. See §4.
- **Two process rules added to cut run time/token cost** — (1) check
  `WORK_DIR`/subagent output for already-completed work before redoing a
  step by hand, since a delegated call that looks rejected in the chat may
  have finished in the background anyway; (2) the PR-scraping field list is
  exhaustive, not a starting point — no full-page scrapes, from the first
  PR onward. Doc-only, no `.py` logic touched by this part. See §5.
- SKILL_VERSION bumped to 2.1.5 across all three scripts for tracking
  (§1–§3 changed `headless_daily_report.py`'s logic; §5 is docs-only).

## 2.1.3 — 2026-08-19

Nóra reported noticeably more Cowork approval prompts during recent runs
than expected, and that testing the 2.1.2 fix below did not reduce them —
correctly, since it was a different bug. See `CHANGELOG-fixes-2026-08-19.md`
§2 for the full writeup. Short version:

- **The per-page "locate the MCP's saved-to-file result" step used `bash
  find` + `cp` + `python3 -c`, once per paginated page.** Every such Bash
  call has different content (a different timestamped filename each time),
  so it can never be "always allowed" — Cowork prompts fresh every time.
  At the `maxResults:5` page size made mandatory in 2.1.1, a full sprint
  fetch is ~11 pages, so this one documented step alone produced up to ~11
  approval clicks per run — almost certainly the actual driver behind "more
  approvals than expected the last few days," since 2.1.1 is what pushed
  page count from 1-2 up to ~11 as a side effect. Fixed by locating the file
  with the **Glob** tool and reading it with the **Read** tool instead of
  Bash — both are pre-approved, no-confirmation tools — and by passing the
  located path straight to the assembler instead of copying it first (the
  copy step was never actually required). Doc-only change; no `.py` logic
  touched.
- SKILL_VERSION bumped to 2.1.3 across all three scripts for tracking.

## 2.1.2 — 2026-08-19

`assemble_jira_data.py` was rejecting every correctly-paginated sprint fetch
— see `CHANGELOG-fixes-2026-08-19.md` for the full writeup. Short version:

- **The `hasNextPage` completeness check applied to every supplied
  `--sprint-file`, not just the last one.** Pages 1..N-1 of any multi-page
  traversal always have `hasNextPage=true` by definition, so the documented
  pagination workflow (page until exhausted at `maxResults:5`, pass every
  page separately) could never pass the check — every run since the
  2026-08-14 fix made `maxResults:5` mandatory was affected. Fixed so only
  the last supplied `--sprint-file` is required to have `hasNextPage=false`;
  the independent `--expected-count` check still guards completeness.
- SKILL_VERSION re-synced to 2.1.2 across all three scripts (had drifted to
  2.1.1 / 2.0.0 / 2.0.0).

## 2.1.1 — 2026-08-14

A full run succeeded end-to-end but took ~1.5 hours and burned about half of
Nóra's session token budget; she asked for a breakdown of what drove that
cost. All three findings are efficiency/process gaps, not report-correctness
bugs — see `CHANGELOG-fixes-2026-08-14.md` for the full writeup. No `.py`
code changed; this is a doc-only release (SKILL_VERSION bumped for tracking,
per "add an entry however small").

- **Jira sprint query: `maxResults:5` is the known-safe page size, not
  `100`.** `maxResults:100` (or even `10`) with the documented field list
  returned only 5 issues with a self-contradictory `hasNextPage:false` +
  nonzero `remainingCount` — a worse variant of the already-documented
  LPP-64669 `hasNextPage` bug. Dropping `comment` didn't fix it either.
  `maxResults:5` reliably returns correct pagination; budget ~10-12
  sequential pages and delegate the paging to a subagent to keep the raw
  payloads out of the main thread's context.
- **Changelog pre-fetch (step 1a) can run at much higher concurrency.**
  Unlike the sprint/SEV/BPR queries, per-issue `getJiraIssue` changelog
  calls have no known crossed-response risk and were being issued only a
  handful at a time — a large chunk of the run's wall-clock time. Documented
  as safe to fan out at real concurrency, ideally via a delegated subagent.
- **`file_upload` reliably rejects Claude-authored files in Cowork/sandboxed
  sessions.** Go straight to the § 3b console-paste fallback rather than
  retrying `file_upload` or trying alternate paths. Also documented: never
  leave a placeholder in the fallback script before substituting the real
  ADF payload — a placeholder slip this run silently returned `{}` and
  doubled the cost of an already context-heavy step.

## 2.1.0 — 2026-07-29

The first real run against the new 2.0.0 shared-context storage, and it
surfaced a fragile parser plus a couple of process gaps. See
`CHANGELOG-fixes-2026-07-29.md` for the full six-part writeup; short version:

- **Parser hardening.** `load_sprint_context()`'s section regex only matched
  a heading immediately followed by its ` ```json ` fence — a blank line in
  between (which Confluence's own markdown round-trip introduces routinely)
  made every roster and cache silently parse as empty, with no error. Now
  tolerates blank lines, and raises loudly if fences are present but nothing
  parsed. This was the root cause behind three of the four review rounds
  today, so it's the highest-value fix in this release.
- **Approved-PR routing changed (behavior change, per Nóra).** An approved
  PR attached to a rendering Section 1 issue now shows under that issue's
  Action column instead of always appearing separately in Pick Up Next.
- **Process, not code:** PR→parent resolution and roster completeness both
  turned out to be "the script/data will handle it" assumptions that don't
  hold up in practice — documented explicitly in SKILL.md as mandatory
  Claude-side steps rather than left implicit.
- `context_page_id` for the ENGHEADLESS shared context page is now recorded
  directly in SKILL.md (5190975505) — the one-time bootstrap is done.

## 2.0.0 — 2026-07-28

**Shared context storage.** Sprint Metadata, both rosters, and the four
run-to-run caches (Changelog Cache, State Snapshot, PR Snapshot, Slack Thread
Snapshot) moved from a local `project_current_sprint.md` file inside the
skill's own install — which only the machine that installed the skill could
see or update — onto a single shared Confluence page that every teammate's
session reads and writes via the Atlassian MCP. Triggered by two real
failures on 2026-07-28: a teammate covering during PTO would only ever see
whatever cache happened to be on their own machine, and a sandboxed/read-only
session could build a correct report but silently fail to persist the cache
update anywhere. See SKILL.md § Shared Context Storage for the full design,
the one-time bootstrap, and the permanent context page policy.

- `headless_daily_report.py`: new `--sprint-context-file` flag overriding the
  previously-hardcoded local path (defaults to the old path, so the script
  still runs standalone without the flag); `SprintContext` gained
  `latest_skill_version`; `save_sprint_context()` now also patches that key
  into the Sprint Metadata block.
- `assemble_slack_data.py`: no code change needed — `--sprint-context` was
  already a CLI flag; just point it at the synced scratch copy instead of
  the local skill file.
- `assemble_jira_data.py`: unaffected by the context-storage change (it
  never read `project_current_sprint.md`).

**Versioning.** All three scripts now carry a `SKILL_VERSION` constant,
printed at the start of every run. `headless_daily_report.py` compares its
own version against `latest_skill_version` on the shared context page (see
above) and prints a loud, non-blocking console warning if it's behind
whatever last successfully published — so "is everyone on the latest
version?" is answerable by reading one Confluence page instead of asking
around. `SKILL.md` now carries a `Skill Version` line and a matching
`version:` field in its frontmatter.

## Pre-versioning history (informal version numbers)

| Ver (informal) | Date | Summary | Detail |
|---|---|---|---|
| 1.1.0 | 2026-07-02 | Sprint-query completeness guard — a truncated MCP page falsely marked `hasNextPage=false` silently dropped LPP-64669; added the `--expected-count` completeness check in `assemble_jira_data.py`. | `CHANGELOG-fixes-2026-07-02.md` |
| 1.2.0 | 2026-07-06 | Section tables now carry explicit `colwidth` so Confluence stops resetting Nóra's manually-tuned column widths on every publish. | `CHANGELOG-fixes-2026-07-06.md` |
| 1.3.0 | 2026-07-08 | Three-part fix day: added the LPP age trigger (7b) so long-running LPPs like LPP-64236 stop falling through Section 1's visibility gate; two follow-up fixes same day; testing-panel delta bug. | `CHANGELOG-fixes-2026-07-08.md` |
| 1.4.0 | 2026-07-09 | Test section became a static Confluence Include Page macro — removed the live Testray scrape and Jira bug-count fetch entirely. | `CHANGELOG-fixes-2026-07-09.md` |
| 1.5.0 | 2026-07-09 | New feature: unanswered `#t-dxp-headless` Slack questions surface at the top of Needs Owner, via Chrome-scraping (no Slack connector available for this org). | `CHANGELOG-fixes-2026-07-09-slack-needs-owner.md` |
| 1.6.0 | 2026-07-10 | Fixed a false "cross-team" flag on a genuine Headless PR — the author was missing from the `Team GitHub Logins` roster, not actually a wrong exclusion rule. | `CHANGELOG-fixes-2026-07-10.md` |
| 1.7.0 | 2026-07-13 | LPD "Days in Progress" now tracks days in the *current* status (not carried over from the development phase) for LPDs past development; plus two related fixes the same day. | `CHANGELOG-fixes-2026-07-13.md` |
| 1.8.0 | 2026-07-15 | Fixed a closed SEV bug appearing in the report from a stale re-used fetch, and BPR-linkage catching backport tickets the saved filter hadn't picked up yet; plus the Slack-scrape-skip incident that went unreported until a team meeting. | `CHANGELOG-fixes-2026-07-15.md` |
| 1.9.0 | 2026-07-08 to 2026-07-15 (various) | Everything else folded into the dated files above but not called out as its own headline item (minor exclusion-rule tightenings, PTR ownership rule, etc.) — see the dated files and SKILL.md's inline "2026-0X-XX fix" notes throughout the Workflow/Deduplication sections. | various |

## Format going forward

```
## X.Y.Z - YYYY-MM-DD
One-paragraph summary of what changed and why (symptom -> root cause -> fix,
same spirit as the dated CHANGELOG-fixes-*.md files). Bullet the concrete
code/doc changes if there's more than one.
```

Bump the patch version (`X.Y.Z+1`) for a bug fix, minor (`X.Y+1.0`) for a new
feature or non-breaking behavior change, major (`X+1.0.0`) for anything that
changes the on-disk data format or breaks compatibility with an older copy of
the skill (like this 2.0.0 release does for the context-storage location).
