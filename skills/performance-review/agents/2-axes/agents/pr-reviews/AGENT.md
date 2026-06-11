# PR Reviews Axis

The quality and reach of the member's peer reviews.

## Lens

The reviews the member left on **other people's** work — the `work_item` nodes where `role` = reviewer, and their `comment` / `review:<state>` / `review_comment` evidence (the actual feedback). Reward design-shaping feedback, bug catches, and unblocking peers over tactical nits ("not sorted", "please check my comments"); volume matters, substance more. Pull extra context with `querying.md` if needed.

## Scale — score (absolute, 0–100)

The **score** measures the absolute, org-wide magnitude of the member's peer-review contribution — independent of role. **100 = the most impactful body of peer review imaginable for *any* engineer**; it drives the radar geometry. The node's **grade is separate and role-relative** (`rating-calibration.md`) — judged against what's expected of *this* member's role, **not** read off the score band.

- **0–39** — Barely reviews others' work: a few rubber-stamp approvals or tactical nits, no real engagement with peers' changes.
- **40–69** — Regular, useful reviews: a steady volume of approvals and comments that catch real issues on peers' work, but mostly tactical (correctness nits, style, "please check X").
- **70–89** — High-volume, substantive review: consistently catches real bugs, shapes design, and unblocks peers across many PRs; feedback others act on.
- **90–100** — Review as a force-multiplier: depth and reach that raises the team's bar — design-level guidance, mentoring through review, catching architectural problems early; the kind of reviewing others learn from. 100 is the ceiling.

### Output Nodes

```json
{
  "id": "axis:pr_reviews",
  "type": "radar_axis",
  "label": "PR Reviews",
  "score": 74,          // 0–100, absolute org-wide magnitude (see Scale); drives the radar
  "grade": "meets",     // role-relative tier (rating-calibration.md) — judged separately from the score
  "text": "one-line rationale citing the reviews"
}
```
