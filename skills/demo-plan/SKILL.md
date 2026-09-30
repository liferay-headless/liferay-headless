---

description: Build the weekly Headless team demo plan by ranking the team's most critical tickets from Jira and recent pull requests and producing a Slack-ready announcement of the top 10 with their authors.
name: demo-plan

---

# Demo Plan

Each Monday the daily is replaced by a team demo. This skill produces the weekly announcement — the ten most critical tickets the team has worked on, each with the member(s) who will show it: it queries each member's open and recently closed Jira tickets, plus the pull requests they have open or sent during the last week, and emits a Slack-ready message that the host can paste into the team channel.

## References

Before running, read both files — they are the source of truth for who is on the team and how to call Jira:

- `../../rules/team.md` — member roster (Jira account IDs, Slack handles, GitHub handles). The Per-Member Lookup below iterates this table; the Slack handle on each outer bullet comes verbatim from this file, and the GitHub handle is the PR author to search for.
- `../../rules/jira-rest-api.md` — how to authenticate `curl` against the Jira Cloud REST API. All Jira queries below go through `curl`, never through the Atlassian MCP.

## Input

### Per-Member Lookup

For every team member, run two Jira searches in parallel:

1. **Current WIP** — `assignee = <accountId> AND project = LPD AND statusCategory = "In Progress" ORDER BY updated DESC`, top 5 results.
1. **Recently closed** — `assignee = <accountId> AND project = LPD AND statusCategory = Done ORDER BY resolved DESC`, top 3 results.

Pull the `summary`, `status`, `issuetype`, `priority`, `labels`, `updated`, `resolutiondate`, and `parent` fields. Wrap account IDs that contain `:` in double quotes inside the query.

In parallel with the Jira searches, fetch the member's **Recent PRs** with the GitHub CLI — every PR they authored in `liferay-headless/liferay-portal` that is still open with activity during the last 7 days, or was created during the last 7 days:

```bash
gh search prs --author <github-handle> \
	--repo liferay-headless/liferay-portal \
	--state open --updated ">=<today - 7d>" --json number,title,state,createdAt,updatedAt,url --limit 50

gh search prs --author <github-handle> \
	--repo liferay-headless/liferay-portal \
	--created ">=<today - 7d>" --json number,title,state,createdAt,updatedAt,url --limit 50
```

Merge both result sets and drop duplicates. Parse the `LPD-NNNNN` keys from each PR title (a title may carry several). Resolve every key that the Jira searches did not already return with a direct `GET /rest/api/3/issue/<key>?fields=summary,status,issuetype,priority,labels,updated,resolutiondate,parent`, and map Technical Task keys to their parent Story/Task/Bug (fetch the parent too — its `priority` and `labels` drive the criticality). The ticket may be assigned to someone else in Jira — the PR still counts as the author's work. Ignore PRs whose title carries no `LPD-` key.

Then tell **merged** PRs from **in-flight** ones. Fork PRs never show as merged — the CI bot closes them when it forwards them to `brianchandotcom/liferay-portal`. For every closed fork PR, find the forwarded PR link in its comments (`gh api repos/liferay-headless/liferay-portal/issues/<n>/comments`, scanning every comment for `brianchandotcom/liferay-portal/pull/<N>`), then read Brian's comments on it (`gh api repos/brianchandotcom/liferay-portal/issues/<N>/comments`, author `brianchandotcom`). A comment starting with `Merged.` means the PR is **merged**. Anything else — an open PR, a closed PR Brian sent back, or one never forwarded — is **in flight**.

## Expected Output

A Slack-ready message copied to the clipboard. Do not post it from the skill — the host owns the announcement. After copying, tell the caller that the clipboard holds the message and that they need to convert each `@handle` into a real Slack mention before sending.

Build it in two steps. First pick a `Current` and a `Fallback` candidate ticket for every member (rules below). Then pool all candidates, merge duplicates — a ticket picked for several members is one line crediting all of them — and emit only the **top 10** tickets, one per line, in this exact shape:

```
• [<criticality>] <@<slack-handle>[, @<slack-handle>]> — https://liferay.atlassian.net/browse/LPD-XXXXX — <summary>
```

- **Order**: every `***` ticket first, then `**`, then `*`. Within a tier, **merged** tickets come before **in-flight** ones: a ticket is merged when at least one of the credited members' Recent PRs on it is merged and none is still in flight; a ticket backed by no PR counts as in flight. Within each of those groups, the ticket with the most recent activity wins — the newest `updatedAt` among the credited members' Recent PRs on it, or the Jira `updated` timestamp when no PR backs it.
- **Alignment**: pad with trailing spaces so every column starts at the same position on every line — `[**]` and `[*]` are padded to the width of `[***]`, and each `<authors>` field and each URL is padded to the width of the longest one in the message, so the ` — ` separators, URLs, and summaries line up.
- **Author**: right after the criticality, wrapped in a single pair of angle brackets, the `<slack-handle>` of each credited member, in roster order and comma-separated (`<@Daniel Raposo, @boton>`). It is the exact value from the Member Roster table for that member's `accountId` — never derive it from the Jira display name.
- **Criticality**: `***`, `**`, or `*`, judged from the ticket on the line (the parent, never a Technical Task) — read its `summary`, `labels`, `priority`, and the titles of the PRs behind it. Take the first tier that matches:
	- `***` — the change touches an API exposed to customers (REST, GraphQL, batch, MCP tools, or the generators behind them such as REST Builder) or changes the UI; or it introduces — or prevents — a major (breaking) change in any API, such as renamed operations, removed or changed parameters, or `compatibilityVersion` gating; or it reshapes a framework in a significant way; or it belongs to a company top initiative (a label matching `*_Top_*`, e.g. `26_Top_PCE`, `27_Top_MCP_Enhacements`).
	- `**` — the ticket's Jira `priority` is Blocker, Critical, or High; or it is any other important change (a customer-facing bug fix, a security fix, a notable performance improvement).
	- `*` — changes you judge less relevant: test fixes, Poshi or Playwright migrations, test suites, and internal tooling.
- **No Epics**: never pick an Epic as a candidate — it is a container whose real work lives in its children, which their own authors already surface. Skip Epics everywhere, including a PR whose only `LPD-` key is an Epic. A member left with nothing but Epics contributes no candidate.
- **`Current` candidate**: the parent Story/Task/Bug with the most recent PR activity from the **Recent PRs** — an open PR outranks one already closed, then the newest `createdAt` wins. The Investigate / Poshi / flaky-test deprioritization below applies to PR-backed tickets too. PRs are the strongest signal of demoable work, and they surface tickets the Jira assignee field misses. When the member has no Recent PRs, take the parent Story/Task/Bug with the most recent `updated` timestamp from the **Current WIP** query. Skip Technical Task subtasks unless they're the only signal of progress, in which case use the parent Story's URL with the subtask's summary. Deprioritize Investigate / Poshi / flaky-test tickets — surface them only when nothing more substantive is open. If the member has zero In Progress tickets, pull the `Current` candidate from the **Recently closed** query (most recent `resolved`).
- **`Fallback` candidate**: the next PR-backed ticket from the **Recent PRs**, in the same order; when none is left, the next-most-recent parent Story/Task/Bug from the **Recently closed** query, skipping Technical Task duplicates and the ticket already used as the `Current` candidate. Recently closed feature work outranks old test fixes.
- **Links**: hardcode the plain ticket URL (`https://liferay.atlassian.net/browse/LPD-XXXXX`), one per line. No wrapping syntax around the URL — no `<url|label>`, no Markdown `[label](url)`, no angle brackets, no trailing label after the URL. Slack auto-links the bare URL on its own; adding a label produces a duplicated `LPD-XXXXX|LPD-XXXXX` href. Do not embed extra ticket links inside the summary either.
- **Summary**: a paraphrase of the Jira `summary`, capped at 10 words. Strip ticket prefixes/labels (`[ACCEPTANCE]`, `TEST FIX |`, `Technical Task |`, `[POSHI]`, etc.) and any leading `Investigate`/`Fix` boilerplate before counting. No trailing punctuation, no embedded ticket links.
