# Skill change — 2026-07-09

## 1. Test section is now static (Testray live scrape removed)

**Requested by Nóra:** cancel the daily Testray run and the Jira-bug-count
fetch behind the Test section, and instead render that section as a static
Confluence "Include Page" macro pointing at another page, matching the
manual edit Nóra made to the live page earlier that day
(<https://liferay.atlassian.net/wiki/spaces/ENGHEADLESS/pages/4899110937/Headless+Team+Daily+Actions+Report>).

**What used to happen (removed):** every run scraped two Testray builds via
Chrome MCP screenshot (`[master] ci:test:headless` "Investigation" and
`EE Development Acceptance (master)` "Acceptance", both Failed counts from
the "Total test cases" chart), plus a browser-JS fetch of three Jira filter
counts (`all_bugs` filter 15065, `fp4_fp5` filter 45383, `no_fp` filter
45384). The five counts were combined into `testing_panel.json`, diffed
against a persisted "Testing Panel Baseline" in `project_current_sprint.md`
to show deltas, and rendered as a bold-paragraph + 5-item bullet list.

**What replaced it:** the Test section now transcludes a dedicated page —
**"Headless Testray Regression Tracking"** (space `ENGHEADLESS`, page id
`5096669324`) — via Confluence's Include Page macro. That page is maintained
independently of this report. The ADF node is a top-level `extension` block
(`extensionKey: "include"`, `extensionType:
"com.atlassian.confluence.macro.core"`, `macroParams: {"": {"value":
"Headless Testray Regression Tracking"}}`) — confirmed byte-for-byte against
the ADF Nóra's manual edit actually produced on the live page (fetched via
`getConfluencePage` with `contentFormat: "adf"` before writing this).

**Code changes in `headless_daily_report.py`:**
- Added `adf_extension()` (generic Confluence macro/extension ADF node
  builder) and `adf_include_page_macro(page_title)` (Include Page specific).
- Added `TEST_REGRESSION_PAGE_TITLE` / `TEST_REGRESSION_PAGE_URL` constants
  and `_build_test_section()`, which replaces `_build_testing_section()`.
- Removed entirely: `_TESTING_FILTERS`, `_format_delta()`,
  `_build_testing_panel_bullet()`, `_build_testing_section()`,
  `_html_testing_panel()`, `_build_testing_panel_data()`, the
  `testing_baseline` field on `SprintContext`, the "Testing Panel Baseline"
  read/write in `load_sprint_context()` / `save_sprint_context()`, the
  "Testing baseline" block in `update_caches()`, the INCOMPLETE-banner logic
  in `generate_html_preview()`, and the `--no-testing-panel` /
  `--testing-panel-file` CLI flags.
- `report_data` no longer has a `testing_panel` key.
- HTML preview shows a static note linking to the source page instead of
  live counts (a local HTML file can't render a Confluence macro).

**Docs updated:** `SKILL.md` ("Testing Panel" section replaced with "Test
Section (static — no data collection)"; removed Chrome `computer` tool from
`allowed-tools` since screenshotting was its only use in this skill;
`WORK_DIR` / Data Files sections now describe two JSON files instead of
three). `reference_tests_section.md` rewritten from a Testray baseline
reference into a pointer at the new static approach.
`project_current_sprint.md`'s "Testing Panel Baseline" JSON section was
deleted — nothing reads or writes it any more.

**Verification:** `py_compile` on the edited script; a standalone harness
built a minimal `SprintContext` + empty `report_data`, ran
`build_adf_document()` + `validate_adf()`, and asserted the resulting
`extension` node matches the real page's ADF exactly (extensionKey,
extensionType, macroParams value); `generate_html_preview()` ran and
produced a preview mentioning "Include Page" and the target page title, with
no `testing_panel` residue; `--test-exclusions` (pre-existing unit tests,
unrelated to this change) still passes; `--help` no longer lists
`--no-testing-panel` / `--testing-panel-file`.

**If the regression page is ever renamed or moved to a different space:**
update `TEST_REGRESSION_PAGE_TITLE` (and `TEST_REGRESSION_PAGE_URL`) in
`headless_daily_report.py`. A bare-title Include Page reference only
resolves within the same space as the page it's published to (ENGHEADLESS)
— see the docstring on `adf_include_page_macro()` if it ever needs a
space-qualified form.
