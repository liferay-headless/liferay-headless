# Summary Agent

The headline rating + summary at the top of the report.

## Lens

Synthesize the whole graph — reconcile what the six axes produced (you do **not** recompute axis scores) and weigh the body of work against the role calibration (`rating-calibration.md`), noting where one piece of work counts toward several axes. The summary names the real work and is honest about the gap to the next tier. For a cross-cutting win spanning several axes (e.g. a CVE fix that is also testing + speed), optionally add a `summary:finding:<n>` to ground the rating (see `graph.md`).

### Output Node

One node (exactly one) carries both the headline rating and the summary prose — the `grade` **is** the headline tier, so there is no separate rating node:

```json
{
  "id": "summary",
  "type": "summary",
  "label": "Summary",
  "grade": "exceeds",   // the headline tier: meets | exceeds | exceeds-enables (never "below")
  "text": "the ≤50-word prose shown at the top of the report"
}
```
