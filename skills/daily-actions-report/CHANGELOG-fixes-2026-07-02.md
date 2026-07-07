# Skill fixes — 2026-07-02

## Sprint-query completeness guard (LPP-64669 root cause)

**Symptom:** LPP-64669 (an In-Queue Customer Issue, assignee PT User Headless,
matching board filter 54796) was missing from the 2026-07-02 report, even though
two near-identical LPPs created within the same day (LPP-64653, LPP-64657) were
included.

**Root cause:** The `searchJiraIssuesUsingJql` MCP returned a **truncated first
page of 52 issues** for the sprint query but set `pageInfo.hasNextPage=false`.
The pipeline trusted that flag, treated 52 as the complete board, and never paged
further. LPP-64669 lived outside the returned 52, so it never entered
`jira_data.json` — it was never excluded by any rule; it simply was never loaded.
This is a **data-completeness failure at the query layer**, not a classification
or exclusion bug. It can silently drop *any* issue, not just LPPs.

**Fix:**
- `assemble_jira_data.py`: added `--expected-count N`. The number of unique
  sprint issues loaded must equal `N` (the filter's true total from a
  `computeIssueCount=true` call) or the build **hard-fails** with a clear message.
  If `--expected-count` is omitted, it prints a loud warning that completeness
  could not be verified. Trusting a single page's `hasNextPage` is no longer the
  guard.
- `SKILL.md`: new **MANDATORY** step before assembly — (1) fetch the filter total
  via `computeIssueCount=true`, (2) page the real query via `endCursor` until the
  cursor is exhausted (do not stop at the first page regardless of `hasNextPage`),
  pass every page as a separate `--sprint-file`, and always pass `--expected-count`.

**Verification:** unit-tested the guard — mismatch → exit 1 with the LPP-64669
message; exact match → passes with "completeness verified"; missing arg → passes
but warns. No change to any downstream report logic.
