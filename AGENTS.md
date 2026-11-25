# AGENTS.md

Repository rules for any coding agent or contributor working in this repo.

## Non-Negotiable Behavior Rules

1. Do not generate, present, or persist fake data.
2. Do not add fallback logic that fabricates values (for example: random numbers, synthetic placeholders, or guessed metrics) to make UI or APIs appear valid.
3. If required data is unavailable, fail explicitly with a clear error state and actionable message rather than inventing output.
4. Every function must return a deterministic, requirement-aligned value for valid inputs, and a clear/intentional error path for invalid or missing inputs.
5. Do not mark work as complete unless implementation behavior matches the stated requirements.
6. All changes must pass relevant tests before completion; run the narrowest impacted tests first, then broader suites as appropriate.

## Verification Standard

- Validate the exact behavior changed, not just syntax.
- Prefer executable checks over visual assumptions.
- If tests are missing for changed behavior, add them.
- If any required test fails, do not ship a workaround that hides failure.

## Pull Requests and Reported Status

1. Before acting on a workflow that has saved notes or memory (pull requests, reviews, deploys), read every note about it, including known failures.
2. A command that exits 0 is not proof it worked. Read the resulting state back before relying on it or reporting it.
3. Request Copilot's review in the same command that creates the pull request, every time: `gh pr create --reviewer @copilot ...`. Note the time just before the request. Then confirm it registered: the timeline must show a `review_requested` event for reviewer `Copilot` created at or after that time, and no later `review_request_removed` event for `Copilot`. `gh` succeeds even when GitHub silently drops the request, so an empty `requested_reviewers` list is not proof either way: it also empties once the review is submitted. An older request, a removed request, or a request for someone else does not count.

   ```sh
   gh api repos/{owner}/{repo}/issues/<number>/timeline --paginate --jq '.[] | select(.event == "review_requested" or .event == "review_request_removed" or .event == "copilot_work_started" or .event == "reviewed") | {event, at: (.created_at // .submitted_at), reviewer: (.requested_reviewer.login // .user.login), actor: .actor.login}'
   ```

   `copilot_work_started` and a `reviewed` event by `Copilot`, after the request, show the review is underway or done.

4. If it did not register, retry once, note the retry time, and read the timeline again against that time. If the retry registered, continue normally. Only if registration still cannot be confirmed, tell the user at once that there is no review and ask how to proceed. Never say you are waiting for something that was not confirmed to have started, and never start a wait that cannot end.
5. Merging to `main` deploys to production. Do not merge without a completed review whose comments are all fixed or answered and passing CI, unless the user says to merge that pull request without one.
6. If you reported something that turns out to be wrong, say so first in the next message, with what is actually true.
