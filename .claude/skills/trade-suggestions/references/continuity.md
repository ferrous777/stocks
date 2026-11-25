# Continuity (dated observations: never current facts)

Use these only to bootstrap missing pointers or to investigate a known failure. Re-verify everything.

## 2026-11-22 (skill v2.0.0 written; no run executed yet)

- The Stocks MCP was not connected in Claude Code (`claude mcp list` showed no servers). The endpoint and
  setup are on the website's `/connect` page.
- Paper accounts: `paper-agent` (policy agent) and `paper-baseline` (`baseline_v1@1`), $100k each, risk
  profile `default@1`, cost profile `market@1`. There is also one `paper-<strategy>-v<n>` account per
  strategy; these are not to be operated.
- No real (Fidelity) account existed yet. `upload_holdings` with `account_name` creates one.
- Research status: no strategy passed the validation gate, so expect zero Grade A rows. The short umpire
  helps; the long umpire does not.
- Time exit: under `exec_daily_v1` (126 sessions from fill), a fill on 2026-11-23 exits on 2027-05-27,
  past the six-calendar-month bound (2027-05-23). The MCP has no tool to close a position early.
- QuanterLab was listed in the plugin directory but not installed.
- `plaid_integration/` exists in the repo, but no Plaid credentials or extraction had been wired into
  this workflow.
- The XNYS calendar in the installed `exchange_calendars` ends on 2027-11-23. Session arithmetic past that
  date fails, and the failure must be reported, not worked around.
