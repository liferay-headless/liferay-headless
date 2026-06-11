# Brian Axis

How well the member's code holds up to Brian's review — the team's final quality gate.

## Lens

Every PR the team opens (in `liferay-headless/liferay-portal` or `liferay/liferay-portal`) is **forwarded to `brianchandotcom/liferay-portal`**, and a comment on the original PR carries the link to the forwarded one. Brian does **not** merge through GitHub — when a PR is good he leaves a positive comment and **rebases it onto master**; when it isn't, he sends it back. So Brian's response on the forwarded PR is the verdict on the member's code quality. This axis measures the **rejection rate**: how often Brian bounced the member's PRs versus accepting them clean.

## Method

The forward link and Brian's comments are **not** in the graph (the collector drops chatter on the member's own PRs), so fetch them live with `gh` (see `querying.md`):

1. Take the member's own `pull_request` nodes from the graph (their PRs this period).
2. For each, read its conversation comments — `gh api repos/<owner>/<repo>/issues/<n>/comments` — and scan **every** comment (regardless of author) for a `brianchandotcom/liferay-portal/pull/<N>` URL. The link may be the CI bot's "successfully forwarded to …" message **or** a bare URL the author posts after `ci:forward` — don't filter by author, or you'll miss forwards. (No such link anywhere → the PR was never forwarded; leave it out of the denominator.)
3. Pull Brian's responses on the forwarded PR — `gh api repos/brianchandotcom/liferay-portal/issues/<N>/comments` and `.../pulls/<N>/reviews` — filtering to author `brianchandotcom`.
4. Classify each forwarded PR:
   - **accepted** — Brian's comment is approving/neutral and he rebased it onto master (the positive-comment-then-rebase pattern), or he raised nothing substantive.
   - **rejected** — Brian asks for changes, points out a defect to fix, or otherwise sends it back rather than rebasing it in. A terse "rebase error" / "resend on top of #…" note where Brian does **not** merge **counts as a rejection** — he bounced it, regardless of the reason.

Rejection rate = rejected ÷ forwarded. Note the sample size in the `text` (a clean record over 3 PRs is weaker evidence than over 40).

> Confirm Brian's handle is `brianchandotcom`; if the org routes through a different account, match that login.

## Scale — score (absolute, 0–100)

The **score** is the inverse of Brian's rejection rate — absolute and org-wide. **100 = no rejections** (every forwarded PR accepted clean); it drives the radar geometry.

- **0–39** — Brian frequently sends PRs back (>~35% rejected): code regularly needs rework before it lands.
- **40–69** — A meaningful minority bounce (~15–35%): recurring, fixable issues Brian keeps flagging.
- **70–89** — Occasional rejection (~5–15%); the large majority sail through on the first pass.
- **90–100** — Brian accepts the member's PRs essentially as-is (≤~5% rejected). **100 = zero rejections** across a real volume of forwarded PRs.

## Scale — grade (role-relative)

Unlike most axes, this one has **no signal other than the rejection record**, so the grade is a role-calibrated reading of that *same* record — it will track the score, not diverge from it. A clean record is more expected the more senior the engineer, and a messy one is more damning; calibrate the bands to the member's role with that in mind:

- **below** — Brian bounces the member's PRs often enough that their code regularly needs rework before it lands (the 0–39 band; for a senior+, a sustained 40–69 record lands here too).
- **meets** — the normal, healthy record: the large majority sail through with the occasional bounce (≈ the 70–89 band).
- **exceeds** — a **near-spotless record across a real volume** of forwarded PRs: the member's code essentially always clears the team's final quality gate on the first pass (≈ the 90–100 band). A spotless record over a *thin* sample (a handful of PRs) is weaker evidence — say so in the `text` and don't over-credit it, but don't downgrade a genuinely clean record on real volume either.

**Do not** default a clean record to `meets` on the reasoning that "clean code is expected." Clearing the final gate near-flawlessly across real volume is, on its face, **above** the baseline — grade it `exceeds`.

## Grounding

Create **one verdict node per forwarded PR** in your own namespace (`brian:review:<n>`), carrying the **`url` of Brian's actual accept/reject comment** on the forwarded PR. Then:

- `axis:brian` grounds in each `brian:review:<n>` node — edge `why` = `accepted` / `rejected`.
- each `brian:review:<n>` grounds in the **original `pull_request` evidence** node (`ev:<pr-url>`) it came from — edge `why` = `the forwarded PR`.

So the drill-down reads axis → Brian's verdict comment → the original PR. If there are many PRs, you may additionally group them under `brian:finding:accepted` / `brian:finding:rejected` findings (each ≥2 review nodes), but the per-PR verdict nodes are the required grounding.

### Output Nodes

The axis (exactly one):

```json
{
  "id": "axis:brian",
  "type": "radar_axis",
  "label": "Brian",
  "score": 92,          // 0–100, absolute; 100 = no rejections (see Scale); drives the radar
  "grade": "exceeds",   // role-relative tier — read the rejection record off "Scale — grade" above
  "text": "states the rejection rate + sample, e.g. 1 rejection across 28 forwarded PRs"
}
```

One verdict node per forwarded PR:

```json
{
  "id": "brian:review:1",
  "type": "brian_review",
  "label": "<the PR title>",
  "url": "https://github.com/brianchandotcom/liferay-portal/pull/<N>#issuecomment-<id>",  // Brian's accept/reject comment
  "grade": "meets",     // accepted → meets (or exceeds if Brian praised it); rejected → below
  "text": "what Brian said, e.g. 'Rebased onto master, no changes requested' or 'Sent back: <reason>'"
}
```
