# Execution guide

## Identity (every Stocks MCP call)

`agent_id: "claude-code-scheduled"` (or `"claude-code"` when the run is interactive);
`model_id`: the exact model ID if the runtime states it, otherwise `"unknown"`;
`prompt_version: "trade-suggestions-v2"`.
If the Stocks MCP tools are missing from the session, the whole Stocks section is unavailable. Record
"MCP not connected", point to the setup on the website's `/connect` page, and continue with any work
that doesn't depend on it. Never print or save the API key.

## Tool map

| Step | Source | Calls and fields |
|---|---|---|
| 1 time | local | `venv/bin/python -c` using `stocks_service.sessions`: `is_session`, `next_session`, `session_bounds`; last completed session = the latest session whose close is ≤ now |
| 1 state | files | `reports/trade-suggestions/pointers.json`, latest `<date>/evidence.json` |
| 1 holdings | Stocks | `list_accounts()`, then `get_account(id)` and `list_transactions(id, cursor=…)` for every account, all pages |
| 1 watch lists | Stocks | `get_watchlist()`; a brokerage watch list only if a connector exposes one (otherwise record it as unavailable) |
| 2 tools | Stocks | read the session's MCP tool list and the server instructions; record any tool that was added or removed |
| 2 outlook | Stocks | `get_outlook(min_grade="insufficient", limit=200)`, both sides; keep `asof`, `run_id`, `placeable_until`, `cash_return_6m`, `cost_profile` |
| 2 paper | Stocks | for `paper-agent`: `get_account`, `list_orders`, `list_transactions`, `get_performance` (its default pairing is the matching baseline) |
| 2 detail | Stocks | `get_prediction(symbol)` for the strongest long, the strongest short, each proposed order and each material rejection |
| 3 sync | Plaid (if available) + Stocks | `get_account` (real), then `upload_holdings`, then `get_account` again |
| 6 research | QuanterLab (if connected), service API | list saved configs, results and active jobs before launching anything |
| 7 submit | Stocks | `get_account`, `list_orders`, then `place_paper_order(account_id="paper-agent", …)`, then `list_orders` |

## Server facts to verify each run (don't assume them)

- **Time exit:** the execution policy is `exec_daily_v1`, with `timeout_sessions = 126` counted from the
  fill session. The exit executes at the open of the 127th session after the fill. Compute it as
  `sessions.nth_session_after(fill_session, 127)`, where `fill_session = sessions.next_session(asof)`.
  Compare it with fill + 6 calendar months (`paper_limits.add_calendar_months`). The MCP has no
  close-position tool, so the agent cannot shorten this exit.
  - Observed 2026-11-22: a fill on 2026-11-23 times out on 2027-05-27, four days past six months.
    Fills in some later windows land inside six months.
- **Sizing:** risk and cost profile values sit behind the account's `risk_profile` and the outlook
  `cost_profile`. When the server rejects an order as `qty X exceeds the risk limit of N (…)`, N is the
  server limit.
- **Order rules:** an order is refused after `placeable_until`, when the symbol already has an open order
  or position, or before the account has been processed through the outlook session.

## Evidence (per run)

Directory: `reports/trade-suggestions/<pacific-date>/` (gitignored; it contains holdings).
- `report.md`: the readable full details, which is the link in the delivery.
- `evidence.json`, with these fields:

```json
{
  "workflow_version": "2.0.0", "policy_baseline": "2026-11-21-paper-v2", "prompt_version": "trade-suggestions-v2",
  "run": {"started_utc": "", "ended_utc": "", "pacific_date": "", "last_completed_session": "", "next_session": ""},
  "sources": [{"name": "", "call": "", "args": {}, "retrieved_start_utc": "", "retrieved_end_utc": "",
               "ok": true, "error": null, "ids": {}}],
  "instruments": [{"symbol": "", "role": "holding|watch|comparator|cash", "supported": true, "last_close": null,
                   "close_asof": null}],
  "outlook": {"asof": "", "run_id": "", "placeable_until": "", "rows": []},
  "data_checks": {"revisions": [], "quarantined": [], "coverage_gaps": []},
  "scored": [{"forecast_id": "", "due": "", "outcome": null, "status": "scored|not_due|unavailable"}],
  "forecasts": {"next_session": [], "six_month": [], "native_126_sessions": []},
  "research": {"algorithm_jobs": [{"system": "", "job_id": "", "status": "queued|running|completed|failed",
                                   "hypothesis": "", "rule": "", "data_cutoff": "", "cost_model": "",
                                   "baseline": "", "window": "", "result": null}]},
  "paper": {"candidates": [{"symbol": "", "side": "", "grade": "", "hypothesis": "", "sizing_input": {},
                            "sizing_output": {}, "decision": "submitted|rejected|skipped", "reason": "",
                            "idempotency_key": "", "order_id": null, "status": null}],
            "performance": {}, "baseline_comparison": {}},
  "decisions": {"broad_allocation": {}, "tactical_real": {}, "paper_experiment": {}},
  "pointers_updated": [], "improvements": {"proposed_diff": null, "pr": null, "installed": false}
}
```

Copy values exactly as served, together with their identifiers and timestamps. `null` means unknown,
and the report says why.

## Pointers

`reports/trade-suggestions/pointers.json` holds `{portfolio, entry, six_month, paper, usefulness}`. Each
one has a `date` and a `path` to the evidence that last fully covered that section. Update a pointer
only after `evidence.json` is written and re-read, and only for sections whose coverage was complete.

## Same-outlook reruns (hourly schedules)

If the outlook `run_id` matches the last run's and no paper order changed status, append one line to
`reports/trade-suggestions/log.md` and stop. Run the full sequence when anything changed.

## Checks before delivery

1. Every number in `report.md` traces to a `sources` entry from this run.
2. Every row in both directions is present, including unavailable and negative rows. Rankings use central
   net estimates.
3. Each experiment carries the PAPER EXPERIMENT label. No real-account order language appears.
4. Every submitted order was read back. Accepted orders aren't reported as filled.
5. At most two new positions have been placed for this decision, across reruns.
6. Pointers advanced only for fully covered sections.
7. `venv/bin/python -m pytest -q tests/unit/test_paper_limits.py tests/service/test_trade_suggestions_skill.py`
   passes. This needs the test MongoDB only for the second file; if it is down, record that.
