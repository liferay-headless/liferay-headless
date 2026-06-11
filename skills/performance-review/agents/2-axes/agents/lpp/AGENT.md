# LPP (Support) Axis

The member's customer-facing support footprint.

## Lens

Customer-facing support: bug reproduction, root-cause for customer issues, triage, hotfixes, and release-branch backports. The strongest, most direct signal is the **`lpp_ticket` evidence nodes** — LPP-* issues from the customer-support project the member was assignee of, with activity in the window. Each carries `priority`, `status`, `resolutiondate`, and `linked_tickets` (the LPD/LRHC engineering issues it links to). Use that link to bridge a customer ticket to engineering work already in the graph: a `wi:LPD-…` the member owns that a `lpp_ticket` points to is customer-driven work, not internal bug-fixing — credit it here even though it also feeds Delivery. Also weigh work-items themed `support`/`customer`/`backport`, `created_ticket` bug nodes, `jira_comment` evidence mentioning customers/hotfixes, and backport PRs/tickets (BPR-*). A genuine customer hotfix backported to release lines is the strong signal; truly internal bug-fixing with no LPP/customer linkage is **not** LPP. Don't invent activity — little supporting evidence scores low. Pull extra context with `querying.md` if needed (e.g. an LPP ticket's full description or comment thread).

## Scale — score (absolute, 0–100)

The **score** measures the absolute, org-wide magnitude of the member's customer-facing support work — independent of role. **100 = the heaviest, most dependable support footprint imaginable for *any* engineer**; it drives the radar geometry. The node's **grade is separate and role-relative** (`rating-calibration.md`) — judged against what's expected of *this* member's role, **not** read off the score band.

- **0–39** — Little to no customer-facing work: at most one incidental triage; support isn't part of how they spend their time.
- **40–69** — Real but light support footprint: handles a few customer bugs end-to-end — reproduces, fixes, and backports them to release lines.
- **70–89** — Heavy, reliable support load: a steady stream of customer hotfixes root-caused and backported across release branches; a dependable owner for customer-blocking issues.
- **90–100** — Carries the team's customer-facing reliability: high volume of customer firefights resolved and backported, **and** makes others faster at support — runbooks, triage patterns, fixes that cut recurrence. 100 is the ceiling.

### Output Nodes

```json
{
  "id": "axis:lpp",
  "type": "radar_axis",
  "label": "LPP (Support)",
  "score": 32,          // 0–100, absolute org-wide magnitude (see Scale); drives the radar
  "grade": "meets",     // role-relative tier (rating-calibration.md) — judged separately from the score
  "text": "one-line rationale citing the support work"
}
```
