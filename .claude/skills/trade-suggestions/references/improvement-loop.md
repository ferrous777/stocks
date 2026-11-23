# Improvement loop (every run, before delivery)

1. **Look back.** List procedural errors this run actually showed: a wrong field, a missed page, a
   misread unit, a check that should have caught something, a step that wasted calls. Only real
   observations count, never hypotheticals.
2. **Classify each one.**
   - *Procedure fix* (allowed without approval): clearer steps, a corrected tool mapping, a new check, or
     a regression test.
   - *Policy change* (needs the user's explicit instruction): authority, caps, schedules, numeric policy,
     strategy adoption, or turning research into orders. Write it up as a question in the report. Don't
     apply it.
3. **Make the fix outside the main checkout.**
   ```
   git worktree add ../stocks-skill-fix -b skills/trade-suggestions-<date> origin/main
   ```
   Edit the skill, add a regression case to `tests/unit/test_paper_limits.py` or
   `tests/service/test_trade_suggestions_skill.py`, bump the workflow version and `prompt_version`, and
   run both test files.
4. **Save.**
   - Commit, push, and open a PR with `gh pr create --reviewer @copilot`, following the repo's PR rules.
   - The skill counts as **installed** only once it is merged to `main` and the checkout the schedule
     runs from has it. Until then, the report says "proposed in PR #N, not installed".
   - Remove the worktree afterwards.
5. **On failure,** put the full proposed diff in `evidence.json` under `improvements.proposed_diff` and
   report the failure. Never claim success.

Keep accounts, holdings, raw daily evidence and credentials out of skill files. Skill files hold durable
evidence links and reusable lessons only. Don't hold the verdict back for refactoring that isn't needed.
