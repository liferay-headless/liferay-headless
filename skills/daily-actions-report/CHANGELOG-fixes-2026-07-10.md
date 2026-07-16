# Skill change — 2026-07-10

## 1. Team GitHub Logins roster gap (false cross-team flag)

**What happened:** the 2026-07-10 run flagged PR #4011 (LPD-97594, authored
by `adolfopa`) as "⚠️ Cross-team review request from adolfopa" in Section
2a. Needs Owner. Nóra caught this: adolfopa is Adolfo Pérez, a genuine
Headless team member — present in `Team Slack Names`, and actively
assigned to in-scope Headless work (LPD-97594's assignee). He was simply
missing from the `Team GitHub Logins` roster, which is what dedup rule 3
(cross-team PR detection) actually keys off.

**Fix applied:** added `"Adolfo Pérez": "adolfopa"` to `Team GitHub Logins`
in `project_current_sprint.md`. Re-running the report with the corrected
roster routed PR #4011 to 2b. Assigned as expected, with no cross-team flag.

**Process note added to SKILL.md (dedup rule 3):** before trusting a
cross-team flag, cross-check the author against `Team Slack Names` and the
sprint issues' assignees — if they clearly belong to the team, the roster
is stale, not the PR.

## 2. Slack `raw_thread_text` must be verbatim, not paraphrased

**What happened:** during Slack Needs Owner scraping, two threads
("Problem convention in error responses" and "Translation of problem
messages") had genuine team-member replies (Alejandro Tardín, Beni Herrero
Lorenzo) visible on the page, but `assemble_slack_data.py classify` still
reported both as unanswered. Root cause: the `raw_thread_text` passed to
`slack_details.json` had been condensed into a paraphrased summary (e.g.
`"Alejandro Tardín: can you share your code snippet?"`) instead of the
literal `get_page_text` output. `_extract_reply_authors()` identifies reply
authors by matching the *exact* line-pair pattern Slack's own thread panel
renders — a `"N replies"` divider followed by `<Name>` / `<Weekday> at
<H:MM> <AM|PM>` line pairs. A paraphrase doesn't match those patterns, so
the author list comes back empty and every thread is misclassified as
unanswered regardless of what actually happened in the thread.

**Fix applied:** re-ran `classify` with the literal `get_page_text` dumps
for both threads (newlines, "N replies" divider, and name/timestamp lines
preserved exactly). Both were correctly reclassified as answered (0
unanswered) and dropped from the published report.

**Doc change:** added an explicit ⚠️ warning under "Slack Needs Owner" step
2 in SKILL.md: `raw_thread_text` must be the verbatim, unmodified
`get_page_text` output for that thread — never retyped, translated, or
"cleaned up" — because the classifier's author-detection is a literal
line-pattern match, not semantic parsing.
