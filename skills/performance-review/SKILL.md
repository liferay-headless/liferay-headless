---

argument-hint: '<user> <period>'
description: Produce an executive-grade performance review for a single team member.
name: performance-review

---

# Performance Review

Produce an executive-grade **HTML** review of one team member for one review period — delivered in January, May, or September, each covering the preceding four months — grounded in Jira, GitHub, and git evidence.

## References

- `../../rules/team.md` — roster. Resolve the caller's input to exactly one member; take the GitHub handle, Jira account ID, and role from here.
- `../../rules/jira-rest-api.md` — Jira auth (`JIRA_API_USER` / `JIRA_API_TOKEN`); never the Atlassian MCP.
- `graph.md` — the provenance graph every agent reads from and appends to (nodes, edges, id namespaces, the two write primitives).
- `rating-calibration.md` — role-indexed calibration used by the Group, Axes, and Summary agents.
- `querying.md` — how an agent pulls extra Jira/GitHub context, with guardrails.

## Inputs

Both come from `${ARGUMENTS}`. If either is missing, ambiguous, or malformed, ask the caller — do not guess.

- **Team member** — resolve against the roster to exactly one member → `handle`, `jira_account_id`, `role`, `fte`, display `name`.
- **Period** — `yyyy-jan` / `yyyy-may` / `yyyy-sep` (e.g. `2026-may`), resolved to the window and a delivery label (e.g. "May 2026"):
  - `yyyy-may` → `yyyy-01-01` … `yyyy-05-01` (Jan–Apr)
  - `yyyy-sep` → `yyyy-05-01` … `yyyy-09-01` (May–Aug)
  - `yyyy-jan` → `(yyyy-1)-09-01` … `yyyy-01-01` (Sep–Dec of the previous year)
  - If absent, default to the most recent of the three delivery months on or before today.

## Orchestration

Five agents build the review on the shared graph (see `graph.md`). Each is a **`general-purpose` subagent** with its own folder under `agents/` (an `AGENT.md` + any scripts); everything for a run lives in `output/<handle>/` and the scripts take `--dir output/<handle>`. The orchestrator only sequences them — it never loads an artifact's contents.

Below, `<dir>` = `output/<handle>`.

1. **Resolve inputs** (above) — the only values the orchestrator holds.
2. **Run the agents in order**, handing each its `AGENT.md` + `graph.md` + `<dir>` + the values it needs:
   Collect (`agents/0-collect/`, also `handle`/`jira_account_id`/`since`/`until`) → Group (`agents/1-group/`, `role` + `fte`) → Axes (`agents/2-axes/`, `role` + `fte`) → Summary (`agents/3-summary/`, `role` + `fte`) → Render (`agents/4-render/`, the person details).
   The grade-producing agents (Group, Axes, Summary) all take `fte` and apply the capacity-normalization rule in `rating-calibration.md` (grades scale to capacity; scores stay absolute). Confirm each agent's output exists before starting the next.
3. **Verify**: `./graph.py --dir <dir> validate` passes; report `<dir>/review.html` and the rating.
