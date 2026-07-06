---

argument-hint: "<team member>"
description: Given a Headless team member, pick the best-fit item for them to pick up from the Daily Actions Report's "2b. Needs Owner" queue — an unowned task, a PR to review, etc. — ranked by their domain history, current load, and seniority. Use when asked what someone should work on next, what to hand a team member, or to find a good fit from the Needs Owner queue.
name: next-task

---

# Next Task

The Daily Actions Report's **2b. Needs Owner** section is the team's unowned-work queue: Jira issues sitting on the placeholder assignee (**PT User Headless**) that need a real owner, plus open PRs with no reviewer. This skill answers `member → item`: given one team member, it returns the best item from that queue for them to pick up — the task to own, the PR to review, whatever fits them best — with a one-line rationale.

It is **suggestion-only**. It never assigns anyone in Jira, requests a PR reviewer, or mutates anything — it only recommends the best next item and explains why. Making the change is left to the user.

## Input

### The team member

The argument names the member (Slack handle, name, or GitHub handle). Resolve them against `../../rules/team.md` to their Jira account ID, GitHub handle, role, and FTE. If the argument is missing or ambiguous, ask which member.

### The Needs Owner queue

Fetch the report page (the `2b. Needs Owner` section is regenerated on every daily run) and parse its table:

```bash
curl -s --user "${JIRA_API_USER}:${JIRA_API_TOKEN}" -H "Accept: application/json" \
  "https://liferay.atlassian.net/wiki/api/v2/pages/4899110937?body-format=atlas_doc_format"
```

The body is ADF JSON under `body.atlas_doc_format.value` (a JSON string — parse it). Walk `content` to the `heading` whose text is `2b. Needs Owner`; the next `table` node is the queue. Columns are **Priority · Topic · Issue · Assignee · Days in Queue · Action**. Each data row is one of two kinds:

- **Issue needing an owner** — the Issue cell is an `inlineCard` linking `…/browse/LPD-…` (or `LPP-`/`BPR-`), the Assignee reads `PT User Headless`, and the Action is `Assign & start` / `Assign & investigate`. The priority tier is a `[…]` badge in the Topic cell: `[Expedite]`, `[High Release Blockers]`, `[High BPR]`, `[High LPP Customer Issues]`, `[Focus]`, etc.
- **PR needing a reviewer** — the Issue cell links a `…/pull/N`, the Assignee is the PR **author**'s GitHub handle, and the Action is `No reviewer assigned`. A PR is only a candidate if the member is **not** its author.

Do not trust the table's Topic text as the ticket summary — it is often the parent/epic name. Enrich each issue from Jira instead.

### Enrichment

For each queue item, in parallel:

```bash
curl -s --user "${JIRA_API_USER}:${JIRA_API_TOKEN}" -H "Accept: application/json" \
  "https://liferay.atlassian.net/rest/api/3/issue/<KEY>?fields=summary,components,labels,issuetype,priority,parent"
```

Keep `components` (e.g. `Data Integration > Export/Import`) — the primary domain signal — plus `issuetype`, `priority`, and `summary`. For a PR, resolve its touched area via its linked Jira key (`gh pr view N --repo liferay-headless/liferay-portal --json title,headRefName,body` → parse an `LPD-`/`LPP-` key from title or branch) and enrich that key. If no key is parseable, treat the PR as component-unknown.

## Best-fit evaluation

Score every queue item **for this member** and rank them. Three signals, in this order:

1. **Domain expertise (primary).** Does the item sit in an area this member actually works? For each item's component(s), check the member's recent depth there:

   ```
   jql = project in (LPD,LPP) AND component = "<component>" AND assignee = "<memberId>"
         AND resolved >= -180d ORDER BY resolved DESC        # fields=key; count them
   ```

   Also credit anything they're currently In Progress in that component. More recent depth in the component = stronger fit. Wrap account IDs containing `:` in double quotes.

2. **Load & capacity (gate).** Get the member's active work:

   ```
   jql = assignee = "<memberId>" AND project in (LPD,LPP) AND statusCategory = "In Progress"
   ```

   Normalize by their **FTE** (from the roster). If they're already heavily loaded — especially carrying an expedite/blocker — prefer a lighter pick (a PR review over a fresh task) or say plainly that they have no free capacity.

3. **Seniority fit (guardrail).** Match item weight to their role:
   - `[Expedite]`, `[High Release Blockers]`, `[High BPR]`, `[High LPP Customer Issues]`, SEV / zero-day → good fits for **Senior / Staff**; steer Associates away from these unless nothing else fits and they have real footing in the area.
   - Routine `[Focus]` / planned work → fine for **Mid / Associate**, especially to build breadth in an area they've started in.
   - PR reviews → good fits when the member is a peer-or-senior with history in the touched component.

Combine: expertise picks the item; capacity gates it (don't hand more to someone maxed out); seniority keeps high-stakes items with senior members and routine ones open to juniors. Skip the Product Owner if named (they don't take dev work); for the Team Lead, prefer coordination-light picks.

## Output

Lead with the member and their current load, then the recommendation:

> **@Meg Jedraszak** — 1 in progress (FTE 1.0), room to take one on.
>
> **Pick up:** https://liferay.atlassian.net/browse/LPD-95413 — *New process to verify resolved Missing References at Import time* (Task · `Data Integration > Export/Import` · Low)
> **Why:** her area — closed 4 issues in Export/Import in the last 90d; the ticket is routine `[Focus]` work that fits a Mid engineer.
> **Runner-up:** review PR #3959 (same area, and she's not the author).

- The recommended item is a bare ticket/PR URL plus its enriched summary, type, component, and priority tier.
- **Why** names the deciding signal — the component and recent count — plus the capacity/seniority reasoning when it mattered. If the best available pick rests only on load or seniority because the member has no domain history in anything queued, say so.
- If the queue has nothing that fits (empty queue, or every item is a poor match / they're at capacity), say that instead of forcing a pick.

This skill stops at the recommendation. It does **not** assign the issue in Jira or request the PR review — even if the user approves the pick. Leave the actual assignment to the user (they can do it in Jira, or ask for it explicitly outside this skill).
