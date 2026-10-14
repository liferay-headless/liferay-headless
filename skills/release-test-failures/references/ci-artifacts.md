# Read the CI Artifacts of a Testray Case Result

Download the artifacts of the shard that ran a failing case result and build a timeline from them.

## Locate the Shard

Fetch the case result (`/o/c/caseresults/<caseResultId>`). Its `attachments` field is a JSON string listing the shard's files, for example:

```
https://storage.cloud.google.com/testray-results/2026-10/test-1-41/test-portal-release/51/playwright-js-tomcat101-postgresql163/193/0/liferay-log.txt.gz?authuser=0
```

Drop the query string and replace `https://storage.cloud.google.com/` with `gs://` to get the object path. The shard prefix is everything up to the last `/`. List it:

```bash
gsutil ls -r "gs://testray-results/<path>/<shard>/"
```

Typical contents:

- `docker-logs/` — database container logs.
- `jenkins-console.txt.gz` — the runner's console, with the test order and the failure output.
- `liferay-log.txt.gz` — the portal log for the whole shard.
- `playwright-report/` — the HTML report.
- `test-results/<test>/` and `test-results/<test>-retry1/` — per-attempt Playwright output: `trace.zip`, `error-context.md.gz`, and screenshots.

Download into a new, empty directory under the scratchpad. Some objects carry a `.gz` name but are stored decompressed; check with `file` before running `gunzip`.

```bash
gsutil -q cp "gs://testray-results/<path>/<shard>/liferay-log.txt.gz" "<dir>/"
```

## Read the Console

Find the runner command and the per-test markers. In the Playwright progress line, `×` is a failed attempt, `F` a test that failed after its retries, and `·` a pass. A test that fails on every attempt while the rest of the shard passes points to something specific to that test or its position (for example, the first test after a feature flag toggle), not to a broken shard.

## Read a Playwright Trace

Unzip `trace.zip`. The `*.network` files are JSON lines; each `resource-snapshot` entry carries the request's wall-clock start time and response status:

```bash
jq -r 'select(.type=="resource-snapshot") | [.snapshot.startedDateTime, .snapshot.request.method, .snapshot.request.url, .snapshot.response.status] | @tsv' <dir>/*.network
```

Filter the URLs for the failing endpoint and for the feature flag calls (`/o/com-liferay-feature-flag-web/set-enabled`). `test.trace` holds the test steps and the final `error` entry.

## Read the Liferay Log

The log's timestamps are in the time zone set by `user.timezone` in the JVM arguments, printed in the first line; Playwright timestamps are UTC. Align them before comparing.

Search around the failure time for exceptions, for `BatchEngineUnitProcessorImpl` deploy lines, and for anything the failing endpoint or module logs. A deferred batch unit for a feature flag runs on a `default-*` executor thread right after the flag is enabled; its `Successfully deployed batch engine file` line marks when its object definitions exist.

## Build the Timeline

Merge the events into one table, in UTC, with the source of each line:

| Time (UTC) | Event | Source |
| --- | --- | --- |
| 20:59:19.020 | `set-enabled` LPD-63311 | trace `0-trace.network` |
| 20:59:21.247 | `POST /o/data-masks/` → 404 | trace `1-trace.network` |
| 20:59:32.541 | data-mask `02-object-definition` deployed | `liferay-log.txt` |

The table goes into the investigation comment and the follow-up ticket as-is.