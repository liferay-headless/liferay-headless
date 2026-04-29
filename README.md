### Welcome to Liferay's Headless Team 👋

Pull requests for code affecting headless infrastructure / data integration / staging components are welcome to [liferay-headless/liferay-portal](https://github.com/liferay-headless/liferay-portal). See [PULL_REQUESTS.md](PULL_REQUESTS.md) for our PR guidelines and review workflow.

### Scripts

- **Install Claude Code skills**:

    ```bash
    curl -sSL -H "Accept: application/vnd.github.v3.raw" "https://api.github.com/repos/liferay-headless/liferay-headless/contents/scripts/skills_install.sh?ref=main" | sh
    ```

- **Uninstall Claude Code skills**:

    ```bash
    curl -sSL -H "Accept: application/vnd.github.v3.raw" "https://api.github.com/repos/liferay-headless/liferay-headless/contents/scripts/skills_uninstall.sh?ref=main" | sh
    ```

- **Launch liferay.com locally**:

    ```bash
    curl -sSL -H "Accept: application/vnd.github.v3.raw" "https://api.github.com/repos/liferay-headless/liferay-headless/contents/scripts/liferay.com.sh?ref=main" | bash
    ```
