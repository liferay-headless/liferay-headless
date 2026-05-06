---

argument-hint: '<user> <period>'
description: Produce an executive-grade performance review for a single team member.
name: performance-review

---

# Performance Review

Generate a short, executive-grade markdown review of one team member for one review period (one of three per year — delivered in January, May, or September, each covering the preceding four months), grounded in Jira, GitHub, and git evidence pulled directly from those systems.

## Input

### Team Member

The person under review. Comes from `${ARGUMENTS}`. If the identifier is missing, ambiguous, or cannot be matched to exactly one member, ask the caller — do not guess.

### Period

A review period named after the month in which the review is delivered, in the form `yyyy-jan`, `yyyy-may`, or `yyyy-sep` (e.g. `2026-may`). Comes from `${ARGUMENTS}`. Each review covers the preceding four months:

- `yyyy-may` → from `yyyy-01-01` (inclusive) to `yyyy-05-01` (exclusive) — covers Jan–Apr.
- `yyyy-sep` → from `yyyy-05-01` to `yyyy-09-01` — covers May–Aug.
- `yyyy-jan` → from `(yyyy-1)-09-01` to `yyyy-01-01` — covers Sep–Dec of the previous year.

If absent, default to the current period — pick the most recent of the three delivery months that is on or before today and use that year. If malformed, ask the caller — do not guess.

## Expected Output

### Review Markdown

A single markdown review printed directly to the conversation as the assistant's final reply. Do not write it to a file.

The review draws on four sources of evidence, all pulled from GitHub and Jira via `gh` and `curl` against the REST APIs.

The commit search and the PR search are independent queries against a fixed list of Liferay-related repositories — neither depends on the other's output. The repo list:

- `liferay/liferay-portal`
- `liferay/liferay-portal-ee`
- `liferay-headless/liferay-portal`
- `liferay-headless/liferay-headless`
- `liferay-headless/github-actions`
- `4lejandrito/cliferay`
- The user's personal fork (`<gh-handle>/liferay-portal`, if it exists)

1. **Commits** — Every commit authored by the user during the period, discovered with `gh search commits --author <login> --author-date <since>..<until>` scoped to the repo list via repeated `--repo <owner>/<name>` flags (or one call per repo). Extract ticket keys from each commit message. This is the most relevant piece of work. 
1. **GitHub comments and reviews** — Comments and reviews the user left on any GitHub issue or pull request during the period. Start here, then also fetch the content of the comments:

    ```bash
    gh api "search/issues?q=commenter:<login>+updated:<since>..<until>&per_page=100" --paginate --jq '.items[] | "\(.updated_at)\t\(.html_url)\t\(.title)"' | sort -r
    ```
1. **Pull requests** — Every pull request authored by the user with activity in the period (opened, updated, merged, or closed), discovered with `gh search prs --author <login> --updated <since>..<until>` scoped to the same repo list via `--repo` flags. Capture title, target branch, state, merge status, source repository, and any linked Jira key — pay particular attention to PRs closed without merging or stalled at review, since those carry growth signal that commits alone do not show.
1. **Jira comments** — Every Jira comment authored by the user during the period, on any ticket. Capture the comment `id` alongside its body and parent issue key — Jira's REST API does not return a browser URL for comments, so the deep-link must be constructed. The comments themselves are the evidence (root-cause framing, design pushback, scope challenges, status updates) — never the assignee field.

Every assertion in the output must trace to a commit, PR, GitHub issue/PR comment or review, or Jira comment — never speculate about effort, intent, or attitude, and **never claim ownership of a ticket from the assignee field**. Render links using the data the API hands back; never expose bare SHAs, PR numbers, or comment ids:

Take **time-to-complete** into consideration when shaping the review — a multi-month arc and a one-day fix are not equivalent achievements, and a ticket that has sat open for the full period is a stronger growth signal than one that briefly stalled. Derive each ticket's span from when the user actually started the work (the earlier of the first associated commit or PR) to when the work ended (the Jira `resolutiondate` for closed tickets, or the merge/close timestamp of the last associated PR, or the last associated commit otherwise).

The output is short and executive — what a director reads in under a minute. Use this structure exactly:

````markdown
# <Display Name> — <Period label, e.g. "May 2026 review (Jan–Apr)">

_Period: <since> – <until>_
_Role: <resolved role from the team roster>_

## Headline

**Rating: <Meets expectations | Exceeds expectations | Exceeds expectations and enables others to exceed>.** <Overall rating based on the achievements and growth opportunities.>

<One sentence summarizing the user's performance during the period.>

<Number of commits, PRs, comments, and reviews authored during the period, as well as the number of Jira tickets with comments from the user.>

## Achievements

<Each `###` subsection IS one achievement; its bullets are the evidence for that achievement. Derive the achievements from the evidence. Order the achievements from highest to lowest rating.>

### <Achievement name>

**Rating: <Meets expectations | Exceeds expectations | Exceeds expectations and enables others to exceed>.** <One short sentence explaining why. Apply a high bar in general.>

<One-sentence statement of the value the person delivered.>

- [<TICKET-KEY, commit, PR, GitHub issue/PR comment or review, or Jira comment link>](<url>) — <evidence, in a few words>

## Growth

<Each `###` subsection IS one growth opportunity; its bullets are the evidence for that opportunity. Derive the opportunities from the evidence. Order the opportunities from lowest to highest rating. If no growth signal is present in the data, write a single subsection with the descriptor _"None evident given the data."_ and no bullets.>

### <Growth opportunity name>

**Rating: <Below expectations | Meets expectations>.** <One short sentence explaining why.>

<One-sentence statement of what the person could improve on.>

- [<TICKET-KEY, commit, PR, GitHub issue/PR comment or review, or Jira comment link>](<url>) — <evidence, in a few words>
````

Every body bullet is a single line of the form `<link> — <evidence>`, where `<link>` is a Markdown link to a ticket, PR, commit, GitHub issue/PR comment or review, or specific Jira comment and `<evidence>` is a terse phrase pointing to the concrete artifact behavior (root cause framed, backport landed, PR closed unmerged, ticket stalled, design pushback in review). When the evidence is a comment or review, link directly to the comment so a reader can read the actual analysis in one click — not the parent ticket or PR. No multi-sentence prose inside bullets; no bullets without a link.

Achievements are grounded in concrete evidence: commits, PRs, substantive Jira comments, and substantive GitHub issue/PR comments and reviews. Commits and PRs show shipped code; Jira comments can carry equal weight — especially on customer-facing tickets (LPP and similar) where root-cause analysis, reproduction, and triage often happen entirely in comments before a small patch lands or before the ticket is handed off; GitHub comments and PR reviews carry weight when they shape design, catch real bugs, or unblock peers — review participation is part of the role for senior+ engineers and a legitimate basis for an achievement.

## Rating calibration

### Associate Software Engineer

- **Below expectations.** Slips routine tickets despite mentorship; landed code regresses in review; needs hand-holding for ordinary work.
- **Meets expectations.** Closes assigned bug tickets and small technical tasks with normal review feedback; absorbs guidance and applies it.
- **Exceeds expectations.** Ships modest features independently; picks up adjacent issues without prompting; raises code quality bar for own work.
- **Exceeds + enables others.** Authors reusable docs, fixtures, or onboarding artifacts the next associate inherits — rare at this level.

### Mid Software Engineer

- **Below expectations.** Routine domain work needs senior rescue; commitments slip without flagging; customer bugs sit untouched.
- **Meets expectations.** Owns features and customer bug fixes end-to-end within an established domain; backports cleanly; gives review feedback.
- **Exceeds expectations.** Drives multi-ticket arcs; shapes design within the domain; takes on customer-blocking or critical-priority work.
- **Exceeds + enables others.** Builds shared tooling, conventions, or mentorship that lifts the team's mid-level cohort and reduces senior load.

### Senior Software Engineer

- **Below expectations.** Stays at mid-level scope; avoids cross-cutting work; defers architecture calls to others.
- **Meets expectations.** Owns major features end-to-end; debugs hard issues independently; makes sound architecture calls in their domain.
- **Exceeds expectations.** Leads multi-team initiatives; runs firefights; shapes technical direction across the domain; mentors mids.
- **Exceeds + enables others.** Builds APIs/platforms other teams adopt; sets reusable patterns; raises the bar for the senior cohort.

### Staff Software Engineer

- **Below expectations.** Operates at senior scope without broadening influence; doesn't shape decisions outside immediate team.
- **Meets expectations.** Drives multi-product initiatives; owns hardest problems; shapes cross-team architecture; influences other senior+ engineers.
- **Exceeds expectations.** Defines engineering strategy for product areas; lands platform-level wins visible across the org.
- **Exceeds + enables others.** Builds capabilities other Staff engineers and teams compound on; sets cross-org standards; force-multiplies the engineering function.

### Team Lead

- **Below expectations.** Personal IC work without team uplift; team blocked, unbalanced, or unclear on priorities.
- **Meets expectations.** Ships personal work AND unblocks the team; runs planning, reviews, and quality; closes the loop on commitments.
- **Exceeds expectations.** Drives team-wide outcomes; owns product quality and roadmap execution; absorbs firefighting without dropping plan work.
- **Exceeds + enables others.** Builds capabilities other Liferay teams adopt; force-multiplies the engineering org beyond the team's headcount.