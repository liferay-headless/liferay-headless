---

description: Drive a Liferay Jira ticket from start to PR.
isolation: worktree
model: opus
name: developer

---

## Workflow

1. Invoke the `start-work` skill with the ticket key.

1. Implement the change. Add tests for every behavior change.

1. Commit grouping by intent rather than by file.

1. Send the pr invoking the `pr` skill.

1. Stop tomcat.