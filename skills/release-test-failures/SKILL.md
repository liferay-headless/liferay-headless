---

allowed-tools: [Bash, Glob, Grep, Read, Skill, Write]
argument-hint: '<investigationKey>'
description: Triage a release test failure investigation from a "New Test Failures" Epic and report the verdict to the owning team.
name: release-test-failures

---

# Triage a Release Test Failure

Every release produces an Epic whose summary contains `New Test Failures` (e.g. `U154 New Test Failures`). Each child is an investigation Task, labeled `release-test-failure`, for one failing test or a cluster of tests sharing an error. Decide whether the failure is a product bug, a test that needs fixing, environment noise, or something already tracked, then report it to the team that owns it.

This skill investigates and reports. It does not fix anything — the follow-up ticket it creates is picked up by the owning team, through the `test-fix` skill or by hand.

## Preconditions

- `${JIRA_API_USER}` and `${JIRA_API_TOKEN}` are set. Every Jira call follows [`../../rules/jira-rest-api.md`](../../rules/jira-rest-api.md).
- `${TESTRAY_CLIENT_ID}` and `${TESTRAY_CLIENT_SECRET}` are set, as required by portal's `.claude/skills/test-fix/references/testray.md`.
- `gsutil` is authenticated with a Liferay Google account. When a download returns `403` or `gcloud auth list` shows no credentialed account, stop and ask the user to run `! gcloud auth login`.

## Input

`${ARGUMENTS}` is an LPD key (`LPD-108485`) or its browse URL.

## Expected Output

### Verdict

One of:

- `Bug` — the product behaves incorrectly.
- `Duplicate` — an existing Bug or test-fix ticket already covers this failure (see **Look for an Existing Follow-up**).
- `No action` — the failure comes from the environment and not from the product or the test (crashed shard, `Failed prior to running test`, infrastructure timeout), and the test passes on the next builds.
- `Test-fix` — the test is wrong: an outdated assertion, a timing assumption, a missing wait, or test data that collides.

The skill never states whether a failure is a release blocker. That is the decision of the owning team's product owner.

### Follow-up

The URL of the Bug or Task created in **Report**, or of the existing ticket for `Duplicate`. None for `No action`.

### Investigation

The final status and resolution of the investigation Task.

## Workflow

### Validate the Investigation

1. Fetch the issue with `summary`, `description`, `parent`, `labels`, `components`, and `issuelinks`. Proceed only when the parent's summary contains `New Test Failures` or the issue carries the `release-test-failure` label. Otherwise, abort and say why.

1. Extract the release name from the summary (e.g. `7.4.13-U154` from `Investigate dataMasks failing in 7.4.13-U154 with ...`).

1. Extract every Testray case result URL (`.../case-result/<caseResultId>`) from the description's ADF. A single investigation can cluster several tests; investigate each case result, and group them under one verdict only when they share a root cause.

### Gather the Failure Data

For each case result, fetch the failure data by following portal's `.claude/skills/test-fix/references/testray.md` (`name`, `type`, `errorTrace`, `buildSha`, `lastPassSha`, `firstFailSha`).

Then list the case's recent results across all routines (`r_caseToCaseResult_c_caseId eq '<caseId>'`, `sort=dateCreated:desc`) and resolve each result's build name. Record:

- Whether it failed in the previous release build, i.e. is it new in this release.
- Whether the test fails on master team routines (`[master] ci:test:<team>`, `EE Development Acceptance (master)`) or only on release builds.

A test that only fails on release builds usually points to something that differs between master CI and release bundles: feature flag defaults, a fresh database, the database vendor, or modules that are not shipped.

### Look for an Existing Follow-up

Search Jira for tickets naming the test (`summary ~ "<test-name>" OR text ~ "<test-name>"`), including earlier investigations under previous `New Test Failures` Epics and tickets labeled `claude-test-fix`.

The verdict is `Duplicate` **only** when a follow-up Bug or test-fix Task already exists — either naming the test directly or linked to an earlier investigation — and it still covers this failure:

- **Resolved** → apply the rule from `test-fix` **Claim the Failure**: find its fix commit and run `git merge-base --is-ancestor <fixSha> <buildSha>`. When the fix is not in `<buildSha>`, the release was built before the fix and the ticket covers it. When the fix is already in `<buildSha>`, the test still failed with the fix, so it does not cover this failure.
- **Unresolved** → it covers this failure.

An earlier investigation **without** a Bug or test-fix follow-up is not a duplicate. Continue the workflow, and in **Report** also link that earlier investigation to the new follow-up.

When the verdict is `Duplicate`, skip to **Confirm With the User**.

### Read the CI Artifacts

Download and read the failing shard's artifacts by following [`references/ci-artifacts.md`](references/ci-artifacts.md). The goal is a timeline that places the failure next to the server's activity — for example, a request returning `404` before the batch import that registers its endpoint has finished.

Read the test source and the code it exercises next to the timeline. Name the mechanism with file paths and line numbers; do not stop at the symptom.

### Collect the Feature Flags

List every feature flag the test toggles (Playwright `featureFlagsTest` fixture, Poshi `portal-ext.properties`, Java `@FeatureFlag`/`FeatureFlags` setup) and every flag that gates the failing code. For each one, read `portal-impl/src/portal.properties` and record:

- The default value (`feature.flag.<KEY>`).
- The key (`LPD-63311`).
- The type (`feature.flag.<KEY>.type`: `release`, `dev`, `beta`, or `deprecation`).

Release bundles start with every flag at its default, while long-lived master bundles often have them on already. A test that enables a flag at runtime may hit code paths, such as deferred initialization, that master CI never exercises.

### Classify

Pick the verdict. Adapting a test (`Test-fix`) to a behavior change is valid only when the commit that changed the behavior documents the change in its subject, linked Jira ticket, or pull request body — the same rule `test-fix` applies. Without that documentation, the test's assertion is correct and the verdict is `Bug`.

For a `Bug`, identify the culprit commit between `lastPassSha` and `firstFailSha` and the component that owns the culprit code (the culprit's LPD ticket component, or `.github/CODEOWNERS`). The Bug is a **clear regression** when the test passed on an earlier build and the culprit changed the behavior without documenting it.

### Reproduce Locally

Only for `Bug` and `Test-fix`. Reproduce on master to confirm the verdict and to learn whether master is affected too:

1. Write down the setup that mirrors the CI run: a fresh database when the failure depends on first-time initialization, the feature flag defaults from **Collect the Feature Flags**, and any flag the test toggles left to the test itself.

1. Hand the user the exact command and let them run it — builds, deploys, and runtime tests are slow and must run where the user can watch them.

1. Record whether it reproduced.

When it does not reproduce but the CI artifacts already prove the mechanism (for example, a timing race that only loses on slower CI nodes), keep the verdict and say so in the comment. When it does not reproduce and the artifacts are inconclusive, reconsider `No action`.

### Confirm With the User

Show the user the verdict, the evidence, the drafted follow-up ticket, and the investigation comment. Write nothing to Jira until the user confirms.

### Report

#### Bug

Invoke the `jira-bug` skill with:

- **Affects Version** — the release's Jira version (e.g. `7.4.13 DXP U154` for `7.4.13-U154`; look it up among the LPD project versions). Add `Master` when the bug reproduced on master.
- **Bug Type** (`customfield_10240`) — `Regression Bug` for a clear regression, otherwise `Default`. A regression bug is usually treated as a blocker, but the product owner decides.
- **Component** — the owner of the culprit code.
- **Description** — the failing test, the trace excerpt, the evidence timeline, the culprit commit (short SHA and subject), the steps to reproduce derived from the test, and a **Feature Flags** section listing each flag's key, type, and default, or stating that the code is not behind a feature flag.
- **Summary** — the wrong behavior, not the test name.

#### Test-Fix

Invoke the `jira-task` skill with:

- **Component** — the investigation's component.
- **Description** — the root cause, the evidence timeline, the proposed fix with file paths, and the command that verifies it.
- **Summary** — what the test must do differently (e.g. `Wait for the MCP object endpoints after enabling LPD-63311 in Playwright`).

#### Both

- Leave the assignee empty. Jira then assigns the component lead, which routes the ticket to the owning team.
- Link the follow-up to the investigation with **Relates**, and to any earlier investigation found in **Look for an Existing Follow-up**.

#### Duplicate

Link the investigation to the existing follow-up with **Duplicate**.

#### Comment and Close

1. Comment on the investigation with the verdict, the evidence timeline, the feature flags, and the follow-up key. For a `Bug`, state that the owning team's product owner decides whether it blocks the release. For `No action`, state the evidence that it is environmental.

1. Fetch the investigation's transitions, pick the one named `Closed`, and fetch its fields with `expand=transitions.fields` — the resolution is required. Close with:

	| Verdict | Resolution |
	| --- | --- |
	| `Bug` | `Completed` |
	| `Duplicate` | `Duplicate` |
	| `No action` | `Discarded` |
	| `Test-fix` | `Completed` |

1. Fetch the investigation and the follow-up again to confirm the comment, the link, and the final status.