# Test Section (static)

**2026-07-09 (per Nóra):** the Daily Actions Report's Test section no longer
tracks a live Testray/Jira baseline. This file used to hold the "Testing
Panel Baseline" — a persisted `{investigation, acceptance, all_bugs, fp4_fp5,
no_fp}` count fetched fresh every run via a Testray screenshot (Chrome MCP)
and a browser-JS Jira filter fetch, then diffed against the previous run to
show deltas. That entire pipeline has been removed.

## What replaced it

The Test section is now a static Confluence **Include Page** macro that
transcludes a dedicated page:

- **Page title:** `Headless Testray Regression Tracking`
- **Space:** `ENGHEADLESS`
- **Page ID:** `5096669324`
- **URL:** <https://liferay.atlassian.net/wiki/spaces/ENGHEADLESS/pages/5096669324/Headless+Testray+Regression+Tracking>

That page is maintained independently (by whoever owns the Testray
regression-tracking process) and is out of scope for this skill. The Daily
Actions Report just needs to reference it by title on every publish — see
`TEST_REGRESSION_PAGE_TITLE` / `adf_include_page_macro()` /
`_build_test_section()` in `headless_daily_report.py`, and the "Test Section"
subsection of `SKILL.md`.

## Nothing to fetch

There is no counts file, no baseline, no delta, and no Chrome screenshot step
for this section any more. Do not resurrect `testing_panel.json`,
`--testing-panel-file`, `--no-testing-panel`, or a "Testing Panel Baseline"
section in `project_current_sprint.md` — none of it is read by the script.

## If the regression page moves or is renamed

Update `TEST_REGRESSION_PAGE_TITLE` (and `TEST_REGRESSION_PAGE_URL`, used only
for the local HTML preview link) in `headless_daily_report.py`. If it ever
moves to a different Confluence space than `ENGHEADLESS`, the Include Page
macro's bare-title parameter will stop resolving — `adf_include_page_macro()`
would need a space-qualified reference at that point (not currently
supported; extend it if this happens).
