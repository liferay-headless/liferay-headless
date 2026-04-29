---

argument-hint: "[confluence-page-url]"
description: Run a remote retrospective backed by a Confluence page. Loads the page, detects its phase (collect, vote, discuss), and directs the user to the next action — collect entries, cluster and prioritize them, gather votes, or present the discussion agenda.
name: retro
allowed-tools:
  - mcp__claude_ai_Atlassian__*

---

# Retro

Drive a team retrospective through a single Confluence page.

## Roles

- **Host.** The caller who creates the page. Recorded in `# Host`. Only the host writes the body and triggers phase transitions.
- **Participant.** Anyone else running `/retro <url>`. Posts a footer comment for entries or ballots. Never modifies the body.

The host is also a participant: they post their own entries and ballot as comments alongside everyone else.

## Workflow

### 1. Resolve the Page

Accept a page URL from `${ARGUMENTS}`. When none is supplied, the caller becomes the host: create a page with title `Retro <YYYY-MM-DD>` and the body below, where `<host>` is the caller's `name` from `atlassianUserInfo` and `<accountId>` is the caller's `account_id`. Read the page URL from the create response, then update the body to replace `<page-url>` with it. Report the URL and tell the caller to share it so each team member can run `claude "/retro <page-url>"`.

````markdown
To participate, run the following in your terminal:

```
sh -c "$(curl -sSL https://raw.githubusercontent.com/liferay-headless/liferay-headless/main/scripts/skills_install.sh)"
claude mcp add --transport http Atlassian https://mcp.atlassian.com/v1/mcp/authv2
claude "/retro <page-url>"
```

# Status

Collect

# Host

<host> (`<accountId>`)
````

### 2. Detect Role

Resolve the caller via `atlassianUserInfo`. Read `# Host` from the body. The caller is the **host** iff their `account_id` matches the parenthesized id under `# Host`. Otherwise they are a **participant**.

### 3. Run the Phase

Read the `Status` line under `# Status` and run the matching phase for the caller's role. Only the host can advance the phase, and only with explicit confirmation. After each phase action, wait for the caller's next message, refetch the page via `getConfluencePage`, and re-run this step.

#### 1. Collect

Raw thoughts are collected from the team. Each thought batch is one footer comment on the page.

**All callers (host and participants).** Prompt the caller for thoughts one at a time. Tell them: "Send each thought as a separate message; reply `next` when you're done." Append each reply to an in-memory list as one bullet, verbatim. When the caller replies `next`, post **one** footer comment via `createConfluenceFooterComment` containing every accumulated bullet in order:

```
retro:entry

- Pair programming on the auth refactor caught a ton of edge cases early.
- Standup runs over by ten minutes most days.
```

Wording is preserved verbatim. Identity is captured by Confluence as the comment's `createdBy` — never write a name into the comment body.

After posting, tell the caller their entries are recorded and to send any message to check progress. The host may reply `close` to close collection.

**Host (close).** When the host asks to close collection, do all of the following in one body update:

1. Fetch every footer comment via `getConfluencePageFooterComments`. Filter to comments whose body begins with `retro:entry`. Each bulleted line under that header is one entry; the participant is the comment's `createdBy.displayName`.

1. Cluster the entries, then build the `# Analysis` section:

    1. Group near-duplicate or thematically related entries into clusters.
    1. Tag each cluster as **Went Well** (prefix `A`) or **Did Not Go Well** (prefix `B`) and assign a stable sequential ID per prefix (`A1`, `A2`, ..., `B1`, `B2`, ...). IDs must not change once published — they anchor voting and ranking.
    1. Record the cluster's **Frequency**: distinct participants who raised it (count by comment author, not by bullet).
    1. Score each cluster on **Severity** (1 to 3) based on language intensity and stated impact.

    The `# Analysis` section format:

    ```markdown
    # Analysis

    ## Went Well

    1. **A1 — Faster CI**: 1 participant, severity 2.
       - Summary: CI changes delivered measurable speedups.

    ## Did Not Go Well

    1. **B1 — Standup Overruns**: 1 participant, severity 2.
       - Summary: Daily standup consistently runs long.
    ```

    Ignore caller identity in the output — analysis is about themes, not people.

1. Refetch the page via `getConfluencePage` to capture the freshest body, then write a new body: keep `# Host`, set `# Status` to `Vote`, append `# Analysis`. Then continue to the Vote phase.

#### 2. Vote

Voting is open. Each ballot is one footer comment.

**All callers (host and participants).** Walk the caller through every cluster from `# Analysis` in ID order (`A1`, `A2`, ..., `B1`, ...). For each, present:

- The cluster ID and theme.
- The one-line summary.

Prompt for an integer between 1 and 10 — "how much do you want to discuss this in the meeting" (1 = skip, 10 = must discuss). Reject anything outside that range and ask again. Collect every rating before posting — partial ballots are not allowed.

Post one footer comment via `createConfluenceFooterComment`:

```
retro:vote

- A1: 6
- B1: 8
```

After posting, tell the caller their vote is recorded and to send any message to check progress. The host may reply `close` to close voting.

**Host (close).** When the host asks to close voting:

1. Fetch every footer comment, filter to `retro:vote`. If a participant (by `createdBy.accountId`) posted more than one ballot, ignore all of theirs — voting is one-shot.

1. Sum each cluster's ratings. Rank by:
    1. Rating sum, descending.
    1. `Frequency × Severity`, descending.
    1. Cluster ID, ascending.

1. Cap at the top three. Build the `# Agenda` section as a ranked list with average rating in brackets and a discussion prompt:

    ```markdown
    # Agenda

    1. **B1 — Standup Overruns** (avg 7.0) — What format keeps standup at fifteen minutes?

    1. **A1 — Faster CI** (avg 6.5) — What's the next bottleneck to attack?
    ```

1. Refetch the page, then write a new body: keep `# Host` and `# Analysis`, set `# Status` to `Discuss`, append `# Agenda`. Then continue to the Discuss phase.

#### 3. Discuss

The agenda is published and the meeting is ready. Take no action — the page is read-only by convention once `Status` is `Discuss`.
