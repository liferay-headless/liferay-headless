
# Skill fixes — 2026-07-29

The first real run against the new (2.0.0) shared-Confluence-context storage.
Four rounds of back-and-forth with Nóra were needed before the report was
right — this file documents why, so the same class of bug doesn't cost
another four rounds next time. Most of today's pain was a one-time bootstrap
cost (see fix #1); the rest are process/roster gaps that will recur
occasionally no matter what, and are documented so they're fast to diagnose.

## 1. Blank line between a heading and its ```json fence silently emptied every roster and cache

**Symptom:** a SEV bug in "In Review" (LPD-99438) was wrongly excluded as
"non-Headless assignee," and two LPP issues with real, recent comments
(LPP-64904, LPP-64948) never got a Section 1 trigger despite the data
clearly supporting one. Both looked like classification bugs at first.

**Root cause:** `load_sprint_context()`'s section-parsing regex was
`r"^## ([^\n]+)\n```json\n(.*?)```"` — it required the ` ```json ` fence on
the line *immediately* after the heading, no blank line permitted. The
shared context page is round-tripped through Confluence
(`getConfluencePage` → write scratch file → ... → `updateConfluencePage`),
and Confluence's own markdown handling adds a blank line after headings as a
matter of course. The very first time that content came back through the
round trip, every `## Section Name` block failed to match, so
`json_sections` came back completely empty — every roster (Account IDs,
Team GitHub Logins, ...) and every cache (State Snapshot, Changelog Cache,
...) silently became `{}`. No exception was raised anywhere; the run
finished and produced what looked like a normal report with some wrong
exclusions in it.

This is the exact same failure shape as several past incidents (2026-07-10's
`adolfopa` gap, 2026-07-13's PTR Team-field gap) — trusting a single,
sometimes-empty signal — except here *every* roster and cache was the
"sometimes-empty signal," all at once, from one formatting quirk.

**Fix:**
- The regex now matches `\n+` (one or more newlines) between the heading and
  the fence instead of a literal single `\n`, so a blank line no longer
  breaks anything.
- Added a defense-in-depth check right after the parsing loop: if the raw
  text clearly contains ` ```json ` fences but zero sections were parsed,
  `load_sprint_context()` now raises instead of silently continuing with
  empty rosters. This is meant to catch the *next* format surprise loudly,
  since blank lines won't be the last thing that trips this parser up.
- SKILL.md's Shared Context Storage section now records the bootstrapped
  `context_page_id` (5190975505) directly, so no future run re-bootstraps
  by mistake, and adds a mandatory post-sync sanity check (verify
  `account_ids`/`team_github_logins`/`state_snapshot` are non-empty) before
  building anything — this alone would have caught today's bug on the first
  run instead of the third round of user-reported symptoms.

## 2. PR→parent resolution was skipped, not just failing quietly

**Symptom:** several PRs that were genuine subtasks of in-sprint stories
(e.g. three subtasks of LPD-96499) were published as standalone rows instead
of appearing under their parent story's Action column.

**Root cause:** this one wasn't a script bug — it was a process gap. The
Jira-side and GitHub-side data collection were split across two parallel
subagents this run, and the GitHub-side agent was told to leave `parent_key`
null "since the script resolves it." `merge_prs()` does have a live-lookup
fallback for exactly this (`jira_get_issue` over HTTPS), but direct HTTPS
from a Claude sandbox to `liferay.atlassian.net` is proxy-blocked in every
environment seen so far — so that fallback fails for every PR, silently,
every time, in this kind of session. Nothing in the run output flagged this
as a problem; it just produced standalone PRs that looked plausible.

**Fix:** SKILL.md's "PR parent resolution" section now states explicitly
that this is a mandatory step Claude performs itself (via `getJiraIssue`,
in parallel, for every PR whose `jira_key` isn't already in `sprint_keys`)
before treating PR data as ready to build from — not a "the script handles
it" assumption. The script's own fallback is left in place for standalone/
offline use, but the skill instructions no longer imply it's a substitute
for doing the resolution up front.

## 3. Roster gaps: present in one roster, missing from another

**Symptom:** LPD-75919 (In Review, assigned to Adolfo Pérez) was wrongly
excluded as a non-Headless reviewer.

**Root cause:** Adolfo Pérez had been added to `Team GitHub Logins` on
2026-07-09 (to fix a cross-team false-positive on his PRs) but never added
to `Account IDs` — a different roster, checked by a different rule (LPD
Rule 3, the In-Review ownership check). Same root cause class as the
2026-07-10 incident, just a different roster pair.

**Fix:** added Adolfo Pérez to `Account IDs`. Also added a general note to
SKILL.md's preconditions: when an exclusion looks wrong for someone clearly
on the team, check *all* the rosters they should be in, not just the one
the current symptom points at — a person can easily be complete in one and
missing from another.

## 4. Sprint composition drifted during a long review session

**Symptom:** LPD-42559 had a PR (#4065) that stayed standalone even after
fix #2 above, because the issue itself wasn't in the pulled sprint data at
all.

**Root cause:** roughly an hour elapsed between the initial Jira sprint
fetch and the final several rebuild/review cycles (normal for a session with
several rounds of user feedback). LPD-42559 was confirmed live to have
`customfield_10001` = "Headless Product Team" and to be in the active
sprint — it most likely got added to the sprint after the original fetch.
This isn't really fixable by a process change (sprint boards change
in real time); it's a reminder that a long review cycle can leave the data
slightly behind reality, and a quick live spot-check on a reported
discrepancy is cheaper than assuming the pipeline is wrong.

**Fix (this run only):** fetched the issue live and spliced it into
`jira_data.json` directly rather than re-running the full three-query Jira
pipeline for one issue. No code change — this is a documented judgment call
for future sessions facing the same situation, not a new automated step.

## 5. Team ownership drift with no signal to catch it

**Symptom:** LPP-64968 kept appearing in the report after it had stopped
being Headless-owned; nothing in the data indicated a change (its Team
field and Sprint field were both already blank, and its assignee wasn't
ever a Headless account).

**Root cause:** LPD has a "non-Headless" ownership check (`should_exclude()`
Rule 5, keyed off Team/sprint-field/assignee); LPP does not. There isn't a
generic, reliable machine signal for "this issue quietly stopped being ours"
across every project — it surfaces when a human notices.

**Fix:** used the existing `headless-board-out` label (Rule 1, applies to
any project) directly on the Jira issue, which is the durable, correct
remedy — it persists across every future run with no data patch needed.
Documented this explicitly in SKILL.md's preconditions section as the
standard response whenever a team member flags "X isn't Headless anymore."

## 6. Approved-and-attached PRs always routed to Pick Up Next, hiding the connection to their story

**Symptom (business rule, not a bug):** PR#4055, approved, attached to
LPD-98293 (a Section 1 story), still rendered as a disconnected-looking row
in Pick Up Next rather than next to LPD-98293's own row.

**Root cause:** `_evaluate_pr_trigger()` deliberately emitted no Trigger-5
text for an approved PR ("nothing to action on the issue side"), and dedup
rule 1 only suppresses a PR from Pick Up Next when the issue actually
renders it. No text meant no suppression, regardless of the PR's real
attachment. This was working as designed — the design was just wrong for
what the report's owner actually wants: "approved and ready to merge" is
still a status update that belongs with its story.

**Fix:** `_evaluate_pr_trigger()` now emits
`"Approved — ready to merge — {suffix}"` for an approved PR attached to a
rendering issue, same as every other reviewer status. This both surfaces it
under the issue row and, via the existing dedup rule 1, suppresses it from
Pick Up Next. An approved PR only reaches Pick Up Next now if it truly has
no attaching issue.

## Files touched
- `headless_daily_report.py`: `load_sprint_context()` (regex + defense-in-depth
  check), `_evaluate_pr_trigger()` (approved-PR branch), `SKILL_VERSION` bump
  to 2.1.0.
- `SKILL.md`: filled in bootstrapped `context_page_id`; added mandatory
  post-sync sanity check; strengthened "PR parent resolution" to an explicit
  mandatory Claude-side step; added roster-completeness and team-ownership-
  drift guidance; rewrote dedup rule 1's approved-PR exception.
- No changes needed to `assemble_jira_data.py` or `assemble_slack_data.py`.
