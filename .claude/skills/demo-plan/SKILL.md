---

description: Build the weekly Headless team demo plan by picking a current and a fallback ticket per member from Jira and producing a Slack-ready announcement.
name: demo-plan

---

# Demo Plan

Each Monday the daily is replaced by a team demo. Every team member shows the work they currently own (or, if it is too early, the most recent piece they wrapped up). This skill produces the weekly announcement: it queries each member's open and recently closed Jira tickets and emits a Slack-ready message that the host can paste into the team channel.

## Input

### Per-Member Lookup

For every team member, run two Jira searches in parallel:

1. **Current WIP** — `assignee = <accountId> AND project = LPD AND statusCategory = "In Progress" ORDER BY updated DESC`, top 5 results.
1. **Recently closed** — `assignee = <accountId> AND project = LPD AND statusCategory = Done ORDER BY resolved DESC`, top 3 results.

Pull the `summary`, `status`, `issuetype`, `updated`, and `resolutiondate` fields. Wrap account IDs that contain `:` in double quotes inside the query.

## Expected Output

A Slack-ready message copied to the clipboard. Do not post it from the skill — the host owns the announcement. After copying, tell the caller that the clipboard holds the message and that they need to convert each `@handle` into a real Slack mention before sending.

The message has this exact shape:

```
• @<slack-handle>
    ◦ Current: https://liferay.atlassian.net/browse/LPD-XXXXX — <summary>
    ◦ Fallback: https://liferay.atlassian.net/browse/LPD-YYYYY — <summary>
```

Every member gets the same two-line block — no exceptions, no alternate labels.

- **Outer bullet** (`•`): one per member, in roster order. `<slack-handle>` is the exact value from the Member Roster table for that member's `accountId` — never derive it from the Jira display name.
- **`Current:` line**: the parent Story/Task/Bug with the most recent `updated` timestamp from the **Current WIP** query. Skip Technical Task subtasks unless they're the only signal of progress, in which case use the parent Story's URL with the subtask's summary. Deprioritize Investigate / Poshi / flaky-test tickets — surface them only when nothing more substantive is open. If the member has zero In Progress tickets, pull `Current:` from the **Recently closed** query (most recent `resolved`).
- **`Fallback:` line**: the next-most-recent parent Story/Task/Bug from the **Recently closed** query, skipping Technical Task duplicates and the ticket already used on the `Current:` line. Recently closed feature work outranks old test fixes.
- **Links**: hardcode the plain ticket URL (`https://liferay.atlassian.net/browse/LPD-XXXXX`), one per inner bullet. No wrapping syntax — no `<url|label>`, no Markdown `[label](url)`, no angle brackets, no trailing label after the URL. Slack auto-links the bare URL on its own; adding a label produces a duplicated `LPD-XXXXX|LPD-XXXXX` href. Do not embed extra ticket links inside the summary either.
- **Summary**: a paraphrase of the Jira `summary`, capped at 10 words. Strip ticket prefixes/labels (`[ACCEPTANCE]`, `TEST FIX |`, `Technical Task |`, `[POSHI]`, etc.) and any leading `Investigate`/`Fix` boilerplate before counting. No trailing punctuation, no embedded ticket links.
