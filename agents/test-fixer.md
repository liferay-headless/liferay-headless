---

description: Resolve a single Liferay test failure end-to-end.
isolation: worktree
model: opus
name: test-fixer

---

## Workflow

1. Invoke the `/liferay-headless:test-fix` skill with the supplied input, or with `ci:test:headless` when none was supplied.

1. Stop tomcat.