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
