### Welcome to Liferay's Headless Team 👋

Pull requests for code affecting headless infrastructure / data integration / staging components are welcome to [liferay-headless/liferay-portal](https://github.com/liferay-headless/liferay-portal).

Please make sure you answer the following questions in the PR's description:
1. What is being changed?
2. Why is it being changed?
3. How can we test the changes?

### Our pull request review workflow:
1. First **make sure that the PR is ready for review**, use a draft PR if you just need to launch some tests before starting a review process.
2. You should **review your changes before sending them**. This way you’ll be making sure the code is as refined as possible before someone starts reviewing it. **Good commit messages are very important** for allowing others to understand the changes made.
3. Some of the **main expectations of a Pull request are**:
	+ The solution should **make technical sense**.
	+ The **title of the PR is descriptive enough**.
	+ The **name of the branch must contain the LPD of the subtask/bug**.
	+ The **PR contains the link to the Jira ticket**.
	+ The **PR contains a description if it is needed to understand the technical context**.
	+ **The commit history should be “clean”**. If the main approach changes, the PR should be as refined according to the final approach as possible.
	+ The **code is clean and well-structured**.
	+ **There are enough tests according to the changes**. These test changes shouldn’t be mixed with other code changes for simplifying the possible hotfixing process.
	+ The **changes don’t break any already existing functionality**. This should be covered by proper testing and check of test executions.
4. Once the PR is already created, you should **run all necessary tests and analyze the failures**. You should analyse if a special test suite needs to be executed to make sure all the possible failures are taken into account.
5. The **PR should get assigned a “main” reviewer**. This figure has some expectations associated including:
	+ As a general rule, he/she **should download, compile, deploy and test the PR**. This includes both executing the tests that were created through the code changes as well as testing the fix/functionality.
	+ This person **is encouraged to find ways of improving the PR** by simplifying it, making it more efficient or any change that will bring value to the code.
	+ This person **has the right to push changes to the branch** of mainly two different natures:
		* **Changes that fundamentally change the approach of the PR**. These kinds of changes are expected to be explained to the PR creator and agreed upon before pushing them.
		* **Changes that simplify or improve the already existing codebase**. Good commit messages are key for allowing the PR creator to understand and learn from them.
	+ This person **can also add comments, questions or ask for code changes in the PR**.
	+ If the changes needed are too deep, **responsibility of the task/PR can get transferred to the main reviewer**, although in most cases the code will still be the creator’s responsibility.
6. **Extra reviewers can get assigned to the PR for redundancy**. These can comment or remain silent.
7. The **PR creator will stop working on the code until the main reviewer finishes the code check**. For proper tracking please use the Github assignees section.
8. As soon as the test execution finishes, **you should check possible failures related to the changes made**. As the creator of the PR this responsibility lies mainly in your shoulders.
9. **Once the review is finished** and agreed upon as well as the test failure checks, **the PR is ready to be forwarded**.
