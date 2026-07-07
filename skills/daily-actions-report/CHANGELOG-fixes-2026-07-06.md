# Skill fixes — 2026-07-06

## Section tables now use the manually-tuned Confluence column widths

**Symptom:** the report script rendered section tables (In Progress, 2a.
Assigned, 2b. Needs Owner) with evenly auto-sized columns. Nóra had manually
resized the columns on the live Confluence page for readability, but every
new publish reset them back to the default even split.

**Root cause:** `adf_table_cell` never set a `colwidth` attribute, so
Confluence had no per-column width to preserve and fell back to auto-sizing
on every publish.

**Fix:**
- `headless_daily_report.py`: added a `SECTION_COLWIDTHS` constant
  (`[130, 135, 630, 185, 230, 490]`, px, for Priority / Topic / Issue /
  Assignee / Days / Action) read directly off the live page's ADF
  (`colwidth` per cell, table `width: 1800`).
- `adf_table_cell()` now accepts an optional `colwidth` param and all cell
  builders (`build_priority_cell`, `build_topic_cell`, `build_issue_cell`,
  `build_pr_cell`, `build_assignee_cell`, `build_days_cell`,
  `build_action_cell`) and `_build_header_row` / `_build_data_row` pass the
  matching width through. `adf_table()` also sets `"width": 1800` on the
  table node.
- `generate_html_preview` / `_html_section_table`: added a matching
  `<colgroup>` with the same proportions (as percentages) plus
  `table-layout: fixed` and word-wrap CSS, so the local HTML preview now
  shows the same layout that will be published.

**Verification:** compiled the script, generated a sample section table, and
confirmed the ADF cell `attrs.colwidth` values and table `attrs.width`
exactly match what was read from the live Confluence page. Confirmed the
HTML preview's `<colgroup>` percentages are proportional to the same widths.
