# Skill fixes — 2026-07-08

## 1. LPP issues missed the Section 1 age trigger (LPP-64236 gap)

**Symptom:** `LPP-64236` — 40 days old, status "in analysis", clearly a
long-running item — was completely absent from the In Progress section of
the 2026-07-07 report. Nóra had to ask twice: first "why is this missing?",
then, correctly intuiting the real issue, "but it's a long-lasting one, it's
in progress for a while, right? It should be in the list."

**Root cause:** `evaluate_triggers()` only surfaces a Section-1-eligible
issue if it finds at least one *actionable* trigger (status/assignee change,
new comment since the last snapshot, PR needing action, or an age threshold
crossed). LPP-64236's only recent comment landed the same day as the last
snapshot, so it produced no "new comment" trigger, and — unlike LPD — **LPP
had no age-based trigger at all.** LPD issues get one automatically via
Trigger 7 (`LPD_ORANGE_THRESHOLD` / `LPD_RED_THRESHOLD`, by t-shirt size),
but that logic was never mirrored for LPP. So a stale LPP with no fresh
event was invisible even though the Days column would have shown it as
40 days old and red — the age data existed, it just wasn't wired into the
trigger gate.

**Fix:** added **Trigger 7b** in `evaluate_triggers()`, directly after the
existing LPD Trigger 7 block: for any `project == "LPP"` issue, compute days
since `created` (the same calculation the Days column already uses) and
compare against `LPP_ORANGE_THRESHOLD` (10) / `LPP_RED_THRESHOLD` (19). If
either is crossed, emit `"{N}d in progress — check for blockers"` as an
actionable trigger — mirroring LPD's behavior exactly. Age alone is now
sufficient to keep a stale LPP visible in Section 1, independent of whether
anything else changed on it.

**Verification:** re-ran the report end to end with this fix in place —
Section 1 grew from 9 to 10 rows, and LPP-64236 appeared with the expected
"40d in progress 🔴" / "40d in progress — check for blockers" text.

**Why this matters going forward:** this is a project-specific gap, not a
generic bug — the same class of miss could recur for BPR or PTR if either
project ever needs an age-based trigger and doesn't have one yet. If a
future report is missing an issue that "should obviously be there" because
it's been sitting for a long time, check whether its project has an
age-based trigger in `evaluate_triggers()` before assuming the exclusion or
tier logic is at fault.

## 2. Standalone PR routing (2a vs 2b) missed real owners with no reviewer yet

**Symptom:** the 2026-07-07 report parked several PRs in "2b. Needs Owner"
even though they had a real person attached via GitHub's Assignees field
(e.g. #3997 and #3995, both assigned to magjed4289) — just no reviewer
requested yet. Nóra's initial framing was "all of the PRs have an assignee,
move them all to 2a," but the correct permanent rule (confirmed with her)
is narrower: a PR only counts as "owned" if it has a human reviewer, **or**
a human GitHub assignee who is not the PR's own author. Self-assignment on
one's own PR is the default/trivial GitHub behavior and isn't a real
ownership signal — e.g. PR #3959 was assigned only to its own author
(GaborKomaromi) with no reviewer, and correctly belongs in 2b.

**Root cause:** the standalone-PR section-routing block and
`fetch_open_prs()` only ever looked at `reviewer` (singular, first human
reviewer) to decide 2a vs 2b. The GitHub "Assignees" field was never
collected or considered at all.

**Fix:**
- `fetch_open_prs()`: after parsing reviewers, now also parses `assignees`
  from the raw PR data (`pr.get("assignees")`, falling back to a single
  `assignee` field), filters out bots (`_BOT_NAMES`) and the PR's own
  author, and computes `has_owner = bool(reviewer) or bool(human_assignees)`.
  Both `assignees` and `has_owner` are added to the enriched PR dict.
- Standalone-PR routing block: now routes on `has_owner` instead of
  `bool(reviewer)` — PRs with an owner (reviewer or non-author assignee) go
  to 2a, everything else goes to 2b.
- `_evaluate_standalone_pr_trigger()`: when there's no reviewer but there
  are assignees, now renders `"Assigned to {names} — no reviewer yet ({N}d)"`
  instead of the old blanket `"No reviewer assigned"`, so the action text
  reflects the real state.
- `pr_data.json` schema: `reviewer`/`reviewer_status` (singular) replaced
  with `reviewers` (a list of `{"name", "status"}` — a PR can have more than
  one requested reviewer) and a new `assignees` field (list of GitHub
  logins). See `SKILL.md` → Expected Output → Data Files for the updated
  schema.

**Verification:** regenerated the report with corrected `pr_data.json` —
#3959 (self-assigned only, no reviewer) correctly moved to 2b with "No
reviewer assigned"; #3997 and #3995 (assigned to magjed4289, no reviewer)
correctly stayed/moved to 2a with "Assigned to magjed4289 — no reviewer yet
(4d)".

**Note on the 2026-07-07 hardcoded BPR override:** that same session also
added a temporary `MANUAL_PLANNED_REGULAR_BPR_KEYS` override to force 11
newly-added BPR tickets into Section 2b. This was purely a same-day
workaround because Nóra added those BPRs to the sprint *after* that day's
Jira data pull, so the standard sprint filter didn't see them yet. It is
**not** a permanent rule and has been removed from this version — on any
normal run, newly-sprint-added BPRs are picked up automatically by the main
Jira sprint filter on the next fetch.
