# Testing Axis

How much the member strengthened the test suite.

## Lens

Test work: tests added, flaky-test elimination, coverage, and reusable test infrastructure. Weigh work-items themed `testing`/`reliability`, commits/PRs whose `text` is about tests, flakiness, baselines, Playwright/integration specs, and any reusable test helper others inherit. Weight reach over volume — a pattern that removes a *class* of flaky failures, or fixtures the whole team reuses, beats a pile of one-off assertions. Pull extra context with `querying.md` if the graph is too thin to judge.

## Scale — score (absolute, 0–100)

The **score** measures the absolute, org-wide magnitude of the member's test contribution — independent of role. **100 = the most impactful testing contribution imaginable for *any* engineer**; it drives the radar geometry. The node's **grade is separate and role-relative** (`rating-calibration.md`) — judged against what's expected of *this* member's role, **not** read off the score band.

- **0–39** — Little test contribution: tests only where review strictly demanded them, or none; no attention to flakiness or coverage gaps.
- **40–69** — Solid test hygiene on their own work: ships tests alongside their features/fixes, covers the change's main paths, fixes the occasional flaky test — but stays scoped to their own changes and adds nothing others reuse.
- **70–89** — Substantial, deliberate test work beyond their own changes: meaningful coverage added across a subsystem, flaky tests eliminated, integration/Playwright specs that harden an area and measurably raise suite reliability.
- **90–100** — Compounding test infrastructure: reusable tooling / fixtures / conventions the team inherits, or a pattern that removes a whole *class* of flaky failures. The work lifts everyone's tests, not just their own. 100 is the ceiling; contributions this load-bearing are rare.

### Output Nodes

```json
{
  "id": "axis:testing",
  "type": "radar_axis",
  "label": "Testing",
  "score": 82,          // 0–100, absolute org-wide magnitude (see Scale); drives the radar
  "grade": "exceeds",   // role-relative tier (rating-calibration.md) — judged separately from the score
  "text": "one-line rationale citing the work"
}
```
