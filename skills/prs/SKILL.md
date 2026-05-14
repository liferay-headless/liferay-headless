---

argument-hint: '[weeks] [list-weeks]'
description: Reports on the pull request throughput of the team.
name: prs

---

# Pull Requests

Produce a weekly view of pull-request activity in `liferay-headless/liferay-portal`. The output has two parts in this order:

1. An ASCII bar chart of PRs opened per week for the last `<weeks>` weeks.
1. A nested Markdown list of every PR opened in each of the last `<list-weeks>` weeks, with link and brief description.

## Input

### Weeks

Number of weeks to chart. First positional in `${ARGUMENTS}`. Defaults to `20`.

### List Weeks

Number of trailing weeks to enumerate as a nested list. Second positional in `${ARGUMENTS}`. Defaults to `4`. Must not exceed `<weeks>`.

## Procedure

Use **natural ISO weeks** (Monday 00:00 UTC → next Monday 00:00 UTC). The current bucket is the ISO week containing today (partial, still in progress). The bucket before it is the previous Mon→Mon window, and so on for `<weeks>` total buckets. Bucket boundaries are calendar-aligned, not relative to today.

1. **Fetch** every PR with `createdAt >= <since>` from `liferay-headless/liferay-portal` via the GitHub CLI:

	```bash
	gh pr list \
		--repo liferay-headless/liferay-portal \
		--state all \
		--search "created:>=<since>" \
		--limit 2000 \
		--json number,createdAt,title,author,url
	```

	`<since>` is the Monday (UTC) that starts the oldest bucket, formatted as `YYYY-MM-DD`. Compute it as `monday_of_this_week - (<weeks> - 1) * 7d`, where `monday_of_this_week` is the most recent Monday ≤ today (UTC). `--state all` is mandatory — open and closed PRs both count.

1. **Bucket** each PR by `createdAt` into one of `<weeks>` half-open windows `[Monday, next Monday)`. The newest bucket is the ISO week containing today and may be partial.

1. **Render the chart**, oldest → newest, in a fenced block with this exact shape:

	````
	```
	PRs to liferay-headless/liferay-portal — last <weeks> weeks (week starting)
	Total: <sum>   Max: <max>/wk

	YYYY-MM-DD  ████████████████████████████████████████ <count>
	...
	```
	````

	- Label is the bucket's Monday (`YYYY-MM-DD`).
	- Bar length is `round(count / max * 40)` cells of `█`.
	- Pad the bar field to 40 cells with trailing spaces so the count column lines up.
	- The newest bucket may be a partial week (Monday → today). Render it with the same scaling; do not normalize.

1. **Render the list** for the most recent `<list-weeks>` buckets, oldest → newest, as a top-level nested Markdown list:

	```markdown
	- **Week YYYY-MM-DD – YYYY-MM-DD** (<n> PRs)
	  - [#<num>](<url>) — <brief>
	  ...
	```

	- Outer label spans the bucket's Monday (inclusive) and the following Sunday (inclusive: `Monday + 6d`).
	- Inner items are sorted by `createdAt` ascending.
	- `<brief>` is the PR title with leading `LPD-NNNNN` ticket chains and leading separators (`|`, `:`, `-`) stripped, then trimmed. Preserve the rest verbatim — do not paraphrase or shorten.

## Output

Print both blocks to the conversation as the assistant's final reply, chart first, then list. Do not write to a file. Do not append a summary after.
