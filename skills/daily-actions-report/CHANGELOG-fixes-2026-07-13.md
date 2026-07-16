# Skill fixes — 2026-07-13

Three fixes from today's run, requested by Nóra after reviewing the 2026-07-13
report.

## 1. LPD "Days in Progress" conflated two different phases

**Symptom:** LPD-97411 (status "In Review") showed "5d in progress" — but
that number was actually "days since development started," carried over
from before it moved into review. Nóra wanted a genuinely different number:
days in the *current* status (e.g. "3 days In Review"), not a relabeled
development-phase count.

**Root cause:** `get_first_active_date()`'s LPD branch only ever searched
the changelog for transitions TO `"in development"`/`"in progress"`
(`_LPD_ACTIVE_STATUSES`), regardless of the issue's actual current status.
For an LPD sitting in "In Review", "Escalated", "In Product Review", or
"Ready for Product Review", this produced a number anchored to when
development began, not to when the current phase began — a stale metric
wearing the wrong label.

Compounding this: SKILL.md's changelog pre-fetch instructions (step 1a) only
listed "In Development/In Progress" as LPD candidates, so LPD-97411 wasn't
pre-fetched at all — it fell back to the script's own live-HTTPS fetch,
which is proxy-blocked in the Claude sandbox, landing on
"(days unknown — changelog unavailable)" instead of even the wrong number.

**Fix:**
- `get_first_active_date()`: when status is `"in development"`/`"in
  progress"`, behavior is unchanged. For any OTHER LPD Section-1 status, it
  now searches for the most-recent transition INTO the issue's *own current
  status* instead, with a permitted fallback to `issue["created"]` if no
  such transition is found (the issue may have been created directly into
  that status, or arrived via a bulk/automation transition with no simple
  `status` changelog item).
- Cache invalidation: added a new branch so LPD issues outside
  development/in-progress **always** recompute from the changelog rather
  than trusting a cached date — a stale "in progress" date left over from a
  previous phase must never be mislabeled as this phase's entry date.
- `compute_days_active_cell()`: now checks the issue's current status. In
  development/in progress → unchanged `"{N}d in progress"`. Any other active
  LPD status → `"{N}d {status}"` (e.g. `"3d in review"`, `"2d escalated"`).
- Trigger 7 (`evaluate_triggers()`): the "check for blockers" trigger text
  previously hardcoded "in development" regardless of actual status — now
  labeled to match the current phase the same way, so a long-stalled
  in-review issue doesn't get misreported as stalled-in-development.
- SKILL.md step 1a: the LPD candidate list now names all six
  `SECTION1_STATUSES["LPD"]` values, not just the first two, so this gap
  can't quietly reopen.

**Why this matters going forward:** any time a project's changelog pre-fetch
candidate list in SKILL.md is narrower than the actual `SECTION1_STATUSES`
set the script uses, issues in the uncovered statuses will silently miss
pre-fetch and fall back to a fetch method that's routinely blocked in this
sandbox. Keep the two in sync.

## 2. PTRs excluded solely because a single Jira field was blank

**Symptom:** none of the 4 PTRs pulled in by the sprint filter appeared in
the report, even though 3 of them (PTR-8977, PTR-8970 — assigned to Beni
Herrero Lorenzo; PTR-8999 — assigned to PT User Headless) were clearly
Headless team work.

**Root cause:** Rule 6b (`should_exclude()`) only kept a PTR if
`customfield_10001` (Team) named a Headless team. That field was blank on
all 4 PTRs pulled in — it's evidently not reliably populated for PTRs the
way it sometimes is for LPD. This is the same class of bug as the
2026-07-10 `adolfopa` GitHub-roster incident: trusting one often-empty field
as the sole ownership signal.

**Fix:** Rule 6b now keeps a PTR if EITHER the Team field names Headless OR
its assignee is a known Headless team member — checked against
`ctx.account_ids` (the `Account IDs` roster in `project_current_sprint.md`,
which already includes the "PT User Headless" placeholder account, so no
extra special-case was needed for it). PTR-9007 (assigned to Ana Buchmann,
not on the roster) remains correctly excluded — this wasn't a blanket
"show all PTRs" change, just a fallback for when Team is blank.

**Also added:** an explicit `status == "answered"` exclusion inside Rule 6b
itself, on top of the sprint JQL's own `status not in (...,Answered)`
filter — belt-and-suspenders per Nóra's request that Answered PTRs never
appear, even if the upstream filter ever changes.

## 3. PTR "Days in Progress" was never computed at all

**Symptom:** even manually-included PTRs showed "(days unknown — changelog
unavailable)" — `get_first_active_date()` had no PTR branch (only LPD, LPP,
BPR), so it always fell through to the "unknown project" case.

**Fix:** added a PTR branch to `get_first_active_date()`: always
`issue["created"][:10]` — "days open, from open until Answered," per
Nóra's framing. No changelog scan needed; since Rule 6b (fix #2 above)
already excludes Answered PTRs before this is ever called, any PTR reaching
the Days column is by definition still open. Also added an explicit PTR
branch in `compute_days_active_cell()` (functionally identical to the
generic fallback it used to hit, but now self-documenting) that renders
`"{N}d in progress"`.

## Files touched
- `headless_daily_report.py`: `get_first_active_date()`, `compute_days_active_cell()`, `evaluate_triggers()` (Trigger 7), `should_exclude()` (Rule 6b).
- `SKILL.md`: step 1a candidate list, new documentation under the Section 1 visibility gate.
