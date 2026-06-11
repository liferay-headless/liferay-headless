# Speed Axis

How fast the member's commits land — computed, not judged.

## Lens

The `commit` nodes carry `authored` and `committed` timestamps in their payload; Speed is a single computed metric over them.

## Scale — score (absolute, computed)

The **score** is computed directly from the commit timestamps, so it is inherently absolute and org-wide — no role weighting. **100 = commits that land instantly** (see anchors). It drives the radar geometry. The node's **grade is separate and role-relative** (`rating-calibration.md`) — judged against what's expected of *this* member's role, **not** read off the score.

For each `commit` node, time-to-land = `committed − authored` (parse both offset-aware so the merger's timezone cancels; floor at 0 for clock skew). Take the **median** across the period (median resists long-PR skew). Score on a simple linear scale, with the median **deflated by the member's `fte`** (capacity, from the roster):

```
speed = clamp(0, 100, 100 − (median_hours × fte) × 50/168)
```

Anchors (at `fte = 1.0`): 0 h → 100, one week (168 h) → 50, two weeks (336 h) → 0; reference points 1 day ≈ 93, 3 days ≈ 79. The median lands the score; the clamp floors slow medians at 0. Run a throwaway script for the calc and delete it after.

**Why `fte` is here** (Speed is the one score that moves with capacity). The `100`-anchor is *instant* — fixed regardless of hours worked — so capacity must not scale the whole score, only the **delay**. A part-timer's off-days stretch the wall-clock `committed − authored`, mechanically inflating the median through no fault of responsiveness; deflating the median by `fte` discounts only that delay (`100 − fte × (100 − raw_score)`). For a full-timer `fte = 1.0` and nothing changes. This is an **upper-bound** correction — it assumes the whole latency is the author waiting, when most of it is review queue and CI that capacity doesn't touch — so say in the node `text` that the corrected score is the generous end of the range.

**Ground in every commit.** The score is a median over the member's *whole* commit set, so the provenance must cover that whole set: `axis:speed` carries **one outgoing edge to every `commit` node in the period** — not a hand-picked sample. Each edge's `why` states **that commit's own time-to-land** (e.g. `6 h to land`, `2.3 d to land`, `<1 h to land`). Findings (tail, fast exceptions) may additionally ground in their own commit subsets, but they do **not** substitute for the axis node's full coverage. `validate` enforces this: if `axis:speed` exists, any `commit` node it does not link to is an error. Build the edge list in the same throwaway script that computes the median (you already have every commit's time-to-land there).

### Output Nodes

```json
{
  "id": "axis:speed",
  "type": "radar_axis",
  "label": "Speed",
  "score": 59,          // 0–100, absolute; from the formula above; drives the radar
  "grade": "meets",     // role-relative tier (rating-calibration.md) — judged separately from the score
  "text": "states the median, e.g. median 2.9 d across 158 commits"
}
```
