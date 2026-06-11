# Delivery Axis

The core IC-output axis: how much of the member's own work they shipped end-to-end.

## Lens

The member's **own delivered work** — the `work_item` nodes they actually **produced** (`role` = author / co-author / driver), **not** the ones they only reviewed (`role` = reviewer → PR-Reviews axis). Features built, internal bugs fixed, tasks completed, shipped/closed/backported. **Exclude customer-facing support** (LPP axis — don't double-count hotfixes/customer bugs/backports), test work (Testing), and investigation (Discovery); Delivery is about *landing the change*. Weight end-to-end ownership (designed, built, tested, merged, upgrade path handled) and reliable closure; discount filed-but-not-driven tickets and idle long-span tickets.

## Scale — score (absolute, 0–100)

The **score** measures the absolute, org-wide magnitude of the member's shipped output — independent of role. **100 = the most prolific, fully-owned delivery period imaginable for *any* engineer**; it drives the radar geometry. The node's **grade is separate and role-relative** (`rating-calibration.md`) — judged against what's expected of *this* member's role, **not** read off the score band.

- **0–39** — Minimal landed output: mostly tickets filed-but-not-driven, long-idle tickets, or changes that stalled before merge; at most a few trivial fixes shipped.
- **40–69** — Steady end-to-end delivery: their own internal bug fixes, small-to-medium features, and routine tasks merged and closed reliably — but scope stays mostly within single tickets, with few multi-ticket arcs and nothing the rest of the team depends on.
- **70–89** — High volume of substantial work shipped end-to-end: multi-ticket feature arcs designed, built, tested, merged with the upgrade/backport path handled, plus consistently reliable closure and hard or critical-path tickets. (~40 cleanly-shipped tickets across domains sits here.)
- **90–100** — Exceptional, compounding output: everything above sustained at rare volume, **and** the delivered work becomes a foundation others build on — a reusable module / scaffold / pattern engineers extend, or a whole workstream unblocked. 100 is the ceiling; output this large and this load-bearing is rare.

### Output Nodes

```json
{
  "id": "axis:delivery",
  "type": "radar_axis",
  "label": "Delivery",
  "score": 84,          // 0–100, absolute org-wide magnitude (see Scale); drives the radar
  "grade": "exceeds",   // role-relative tier (rating-calibration.md) — judged separately from the score
  "text": "one-line rationale citing the work"
}
```
