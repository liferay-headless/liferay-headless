# Discovery Axis

The depth of the member's investigation and root-cause work.

## Lens

Investigation and exploration. The **core unit is the Spike** — `work_item` nodes whose `issuetype` is `Spike` (the type the collector stamps onto every ticket). A spike *is* discovery work: time-boxed investigation, design exploration, or a research question, where the deliverable is the finding, not a patch. Weight how many spikes the member owned and how deep each went.

Beyond spikes, the same investigative signal shows up as root-cause analysis, framework-level debugging, and performance research — much of it living in `jira_comment` evidence (stack traces, "the error is…", framework analysis) rather than diffs, on tickets of any type. Count that too, but a `Spike` is the cleanest, strongest signal. Weight the **depth of the analysis, not the size of the resulting patch**. Pull extra context with `querying.md` if needed.

> The exact Jira type string is whatever the collector captured on the node — if this org names it something other than `Spike`, match that string.

## Scale — score (absolute, 0–100)

The **score** measures the absolute, org-wide magnitude of the member's investigative work — independent of role. **100 = the deepest, most consequential body of investigation imaginable for *any* engineer**; it drives the radar geometry. The node's **grade is separate and role-relative** (`rating-calibration.md`) — judged against what's expected of *this* member's role, **not** read off the score band.

- **0–39** — Little investigation: takes tickets at face value; no root-cause work or exploration visible.
- **40–69** — Solid debugging on their own work: root-causes the bugs they're assigned and traces failures to a real cause before fixing.
- **70–89** — Deep, repeated framework-level investigation: cracks hard root causes others were stuck on, runs spikes and performance research, debugs across subsystem boundaries — the analysis, not the patch, is the contribution.
- **90–100** — Investigation that redirects the team: root causes or performance findings that reshape design decisions or unblock whole efforts; the analysis others rely on to know what to build. 100 is the ceiling.

### Output Nodes

```json
{
  "id": "axis:discovery",
  "type": "radar_axis",
  "label": "Discovery",
  "score": 74,          // 0–100, absolute org-wide magnitude (see Scale); drives the radar
  "grade": "meets",     // role-relative tier (rating-calibration.md) — judged separately from the score
  "text": "one-line rationale citing the investigation"
}
```
