# Fixes — 2026-07-15

## Incident 1: Closed SEV bug (LPD-97411) shown in report; its 2 BPRs missing

**Reported by Nóra after a team meeting**, one publish cycle after the
2026-07-15 daily run.

**Root cause (two compounding issues):**

1. LPD-97411 (a SEV bug) closed partway through the session, between an
   early fetch of the SEV bugs query and the final `assemble_jira_data.py`
   build. A *fresher* re-fetch taken later in the same session had already
   correctly dropped it (JQL: `status not in (closed)`), but the build used
   the earlier, stale fetch instead — reused deliberately to stay
   "consistent" with an already-approved HTML preview. The closed bug was
   therefore published as still active.
2. LPD-97411's two backport tickets (BPR-91107, BPR-91108) didn't exist yet
   when the SEV BPRs query (`filter=15069`) was run — they're auto-created
   by the Branch Manager once the fix is committed, which can lag behind the
   SEV bug's own status change. The saved filter had no way to surface them
   yet, so they never made it into `sev_bpr_keys` at all.

**Fixes:**

- SKILL.md: added a mandatory rule to re-fetch SEV bugs/BPRs as the *last*
  step before building `jira_data.json`, immediately before publish — never
  reuse an earlier-session fetch, even if it changes numbers already shown
  to the user in a preview.
- SKILL.md: SEV bugs JQL now explicitly requests the `issuelinks` field.
- `assemble_jira_data.py`: now unions `sev_bpr_keys` with any `BPR-*` issue
  found in each SEV bug's own `issuelinks`, not just the `filter=15069`
  result — this is a more reliable source of truth than the saved filter
  alone (validated 2026-07-15: this caught 4 additional legitimate SEV BPRs
  on a live re-test, beyond just the LPD-97411 case).
- `assemble_jira_data.py`: added a defense-in-depth filter that auto-drops
  any SEV issue whose status is closed/resolved/answered at build time
  (checks `statusCategory.key == "done"` or status name), as a safety net —
  not a substitute for re-fetching fresh, since the script can only see what
  a given input file claims, not what changed after it was saved.

## Incident 2: New Slack thread not surfaced in the report

**Reported by Nóra after the same team meeting.**

**Root cause:** the Slack Needs Owner step was silently skipped for the
2026-07-15 run. It was framed as "optional" in SKILL.md and treated as safe
to drop to save time/tool-calls; the skip was only noted after the fact in
the publish summary, not flagged to the user before the approval gate. Since
the step never ran, no thread — old or new — from `#t-dxp-headless` could
have been caught that day.

**Fix:**

- SKILL.md: Slack Needs Owner is now run by default on every report. It may
  only be skipped if Chrome MCP is genuinely unavailable, or the user has
  explicitly said to skip it for that specific run — and either way, the
  decision must be surfaced to the user *before* the approval gate, not
  buried in the post-publish summary.
