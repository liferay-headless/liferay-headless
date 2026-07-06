---

allowed-tools: [Bash, Edit, Glob, Grep, Read, Skill, Write]
argument-hint: '<caseResultId | routineName | testName | testrayBuildUrl>'
description: Resolve a single Liferay test failure end-to-end.
name: test-fix

---

# Fix a Test Failure

This skill is the **liferay-portal `test-fix` skill** plus the headless-team customizations below. It is run from within the liferay-portal repo; read the canonical skill from the repo root and follow it end-to-end:

- Skill: `.claude/skills/test-fix/SKILL.md`
- Its reference: `.claude/skills/test-fix/references/testray.md`

Apply the overrides in this file wherever they touch the canonical procedure; everything the canonical skill says that is not overridden here still holds.

## Customizations

### Additional input — Routine Name

In addition to the canonical inputs (case result ID, test name, Testray build URL), accept a **routine name**: when `${ARGUMENTS}` matches `ci:test:<team>` or `[master] ci:test:<team>`, resolve it to a case result ID with the procedure below, then feed that ID into the canonical workflow exactly like any other. The procedure finds the latest build of that team routine on the master project and returns the first unclaimed failed case result on the build.

#### Resolve a Routine Name to a Case Result ID

Run the canonical **Authentication** step from portal's `.claude/skills/test-fix/references/testray.md` first, then:

1. Normalize the input by stripping a leading `[master] ` when present. The result is the canonical routine name (e.g. `ci:test:headless`), to which `[master]` is reapplied when querying.

1. Resolve the routine ID on the master project (`35392`). When zero matches, abort:

	```bash
	curl \
		--data-urlencode "filter=name eq '[master] <routineName>' and r_routineToProjects_c_projectId eq '35392'" \
		--data-urlencode "pageSize=1" \
		--get \
		--header "Accept: application/json" \
		--header "Authorization: Bearer ${ACCESS_TOKEN}" \
		--silent \
		--url "https://testray.liferay.com/o/c/routines"
	```

1. Resolve the latest build for that routine. When no build exists, abort:

	```bash
	curl \
		--data-urlencode "filter=r_routineToBuilds_c_routineId eq '<routineId>'" \
		--data-urlencode "pageSize=1" \
		--data-urlencode "sort=dateCreated:desc" \
		--get \
		--header "Accept: application/json" \
		--header "Authorization: Bearer ${ACCESS_TOKEN}" \
		--silent \
		--url "https://testray.liferay.com/o/c/builds"
	```

1. Continue with the resulting `<buildId>` through the **Resolve a Build URL to a Case Result ID** section of portal's `.claude/skills/test-fix/references/testray.md`, treating `<teamIds>` as empty (the routine itself is already the team scope).

### Additional step — Confluence-backed lock in Claim the Failure

The headless team runs `test-fix` agents concurrently, so **Claim the Failure** needs a fence around the ticket-creation window. Before the canonical first step (the Jira duplicate-ticket check), insert this step:

1. Acquire a Confluence-backed lock that fences the critical section where two agents could race to create the Jira ticket. Create a page titled `<test-name>` under the [Test Fix Claims folder](https://liferay.atlassian.net/wiki/spaces/ENGHEADLESS/folder/4939415561). Confluence enforces unique titles within a space, so page creation is the atomic primitive — only one creation succeeds. The Jira ticket is the durable claim; the lock only protects the window leading to its creation. Drive the page create and delete through the Confluence Cloud REST API with `curl` (same auth as [`../../rules/jira-rest-api.md`](../../rules/jira-rest-api.md)), never through the Atlassian MCP.

	- **Creation succeeds** → lock acquired. You are responsible for releasing it (deleting the page) — either after creating the ticket, or after deciding to skip the candidate.
	- **Creation fails with a duplicate-title error** → the test is already claimed by another agent. Skip this candidate.
