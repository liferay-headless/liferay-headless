### Welcome to Liferay's Headless Team 👋

Pull requests for code affecting headless infrastructure / data integration / staging components are welcome to [liferay-headless/liferay-portal](https://github.com/liferay-headless/liferay-portal). See [PULL_REQUESTS.md](PULL_REQUESTS.md) for our PR guidelines and review workflow.

### Claude Code plugin

This repo ships the `liferay-headless` Claude Code plugin.

To install:

```bash
claude plugin marketplace add liferay-headless/liferay-headless
claude plugin install liferay-headless@liferay-headless
```

To update:

```bash
claude plugin update liferay-headless@liferay-headless
```

To uninstall:

```bash
claude plugin marketplace remove liferay-headless
```

#### Testing local changes

To try out unreleased changes, install the plugin from your local clone instead of GitHub. `cd` to the `liferay-headless` repo and then run:

```bash
claude plugin marketplace add ./
claude plugin install liferay-headless@liferay-headless
```

### Scripts

- **Launch liferay.com locally**:

    ```bash
    curl -sSL -H "Accept: application/vnd.github.v3.raw" "https://api.github.com/repos/liferay-headless/liferay-headless/contents/scripts/liferay.com.sh?ref=main" | bash
    ```
