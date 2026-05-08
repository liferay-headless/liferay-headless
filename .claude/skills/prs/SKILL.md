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

Anchor the buckets at **today (UTC)**. The most recent bucket is `[today - 7d, today)`, the one before it is `[today - 14d, today - 7d)`, and so on. Bucket boundaries are date-based, not ISO-week-aligned, so "the last N weeks" stays stable regardless of weekday.

1. **Fetch** every PR with `createdAt >= today - <weeks> * 7d` from `liferay-headless/liferay-portal` via the GitHub CLI:

	```bash
	gh pr list \
		--repo liferay-headless/liferay-portal \
		--state all \
		--search "created:>=<since>" \
		--limit 2000 \
		--json number,createdAt,title,author,url
	```

	`<since>` is `today - <weeks> * 7d` formatted as `YYYY-MM-DD`. `--state all` is mandatory — open and closed PRs both count.

1. **Bucket** each PR by `createdAt` into one of `<weeks>` half-open windows `[start, end)` ending at today. PRs created on today fall outside the trailing window and are dropped.

1. **Render the chart**, oldest → newest, in a fenced block with this exact shape:

	````
	```
	PRs to liferay-headless/liferay-portal — last <weeks> weeks (week starting)
	Total: <sum>   Max: <max>/wk

	YYYY-MM-DD  ████████████████████████████████████████ <count>
	...
	```
	````

	- Label is the bucket's start date (`YYYY-MM-DD`).
	- Bar length is `round(count / max * 40)` cells of `█`.
	- Pad the bar field to 40 cells with trailing spaces so the count column lines up.

1. **Render the list** for the most recent `<list-weeks>` buckets, oldest → newest, as a top-level nested Markdown list:

	```markdown
	- **Week YYYY-MM-DD – YYYY-MM-DD** (<n> PRs)
	  - [#<num>](<url>) — <brief>
	  ...
	```

	- Outer label spans the bucket's start date (inclusive) and end date (inclusive: `end - 1d`).
	- Inner items are sorted by `createdAt` ascending.
	- `<brief>` is the PR title with leading `LPD-NNNNN` ticket chains and leading separators (`|`, `:`, `-`) stripped, then trimmed. Preserve the rest verbatim — do not paraphrase or shorten.

## Output

Print both blocks to the conversation as the assistant's final reply, chart first, then list. Do not write to a file. Do not append a summary after.
