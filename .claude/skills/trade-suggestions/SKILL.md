---
name: trade-suggestions
description: Scheduled (daily or hourly) run that connects to the stocks MCP server, reads the latest six-month outlook and the user's accounts, and writes a dated trade-suggestion report. Optionally places paper orders on the agent's paper account. Use for "run trade suggestions", scheduled suggestion tasks, or when asked what to buy/short today.
---

# Trade suggestions (scheduled)

Adapted for this repo from the operational doctrine in
[agiprolabs/claude-trading-skills](https://github.com/agiprolabs/claude-trading-skills)
(`prediction-market-live-ops`, `risk-management`, `position-sizing`, `trade-journal`). Those
skills are mostly about crypto. Only the parts that fit this service are kept: evidence-gated
stages, freshness gates, a halt switch, server-owned sizing, and an append-only record of each
decision.

Read `AGENTS.md` first. Its rules override everything here. Never fabricate a number. Every figure in
the report must come from a tool result in this run. If something required is missing, the
report says so and stops.

## Arguments

- *(none)*: **suggest** mode. Read only and write the report. Nothing on the server changes.
- `paper`: **suggest** mode plus paper orders on `paper-agent` (simulated money only). This builds
  the agent's track record against `paper-baseline` for the shadow gate in `docs/mcp.md`.

Real accounts are never traded. The MCP server refuses it anyway.

## Cadence

The outlook is built once per trading day by the `jobs-tick` cron, after the close
(`*/15 12-23 * * 1-5` UTC). Orders are placeable until the next session's open
(`placeable_until`).
- **Daily** (recommended): weekdays at 3:30 PM PT (about 2.5 h after the close, well before
  the next open).
- **Hourly**: allowed but adds nothing. Step 2 ends the run early when the outlook has not
  changed. Use it only if you also want open paper orders re-checked.

## Step 0: Preflight

1. The MCP server must be connected (`stocks`, endpoint
   `https://stocks-production-8666a97e.up.railway.app/mcp`, bearer API key). If no stocks MCP
   tools are available, write a report saying "MCP not connected" with the setup command from
   the website's `/connect` page and stop.
2. Identity on **every** call:
   `agent_id: "claude-code-scheduled"`,
   `model_id`: your exact model ID if your runtime states it, else `"unknown"`,
   `prompt_version: "trade-suggestions-v1"`. Bump the version whenever this file changes, so the
   server's `agent_decisions` log can tell prompt versions apart.
3. Halt switch: if `reports/trade-suggestions/HALT` exists, run suggest mode only (no paper
   orders) and quote the file's contents in the report.

## Step 1: Gather (read-only tools)

1. `get_outlook(side=null, min_grade="C", limit=200)`. Record `asof`, `run_id` and
   `placeable_until`.
2. `list_accounts()`.
3. For each real account: `get_account`. Note `valuation.missing`, unknown cash and `open_breaks`.
4. `get_account("paper-agent")`, `get_performance("paper-agent")` and
   `list_orders("paper-agent", status="open")`.

If any of these fails, the report records the exact error and the run stops. No partial guesses.

## Step 2: Freshness gates

- **Same outlook as last run**: if the newest file in `reports/trade-suggestions/` has the same
  `run_id`, append one line, `<timestamp> no new outlook (run_id …)`, to `log.md` there and stop.
  This keeps hourly runs cheap.
- **Window closed**: if now ≥ `placeable_until`, write the report but mark every suggestion
  **"window closed, informational only"**, and place no paper orders.
- **Stale data**: if `asof` is more than one trading session old, say so at the top of the
  report. It means the tick may be failing; link `/ops`.

## Step 3: Pick candidates

Grades come from the server, and the report must label every row by its grade:
- **A** (`validated: true`): a validated strategy signal. Only these may be called *suggestions*.
- **B**: calibrated but unvalidated. Label it **research**.
- **C**: this ticker's own base rate. Label it **research, base rate only**.
- **insufficient**: skip it.

As of 2026-11, no strategy passes the gate, so expect zero A rows. In that case, say plainly at
the top: "No validated signals today; everything below is research." Do not soften it or
present research as a recommendation.

Selection:
1. Longs: the top 5 `side=long` rows with a `plan`, by `exp_return_6m`. Shorts: the top 5
   `side=short` rows the same way. Skip any row whose `p10_return_6m` is missing.
2. Call `get_prediction(symbol)` for each one and use its strategy decisions, umpire votes,
   P(win) and ATR time-to-target odds in the reasoning.
3. **Holdings review**: for every symbol held in a real or paper account, report its current
   long and short rows. Flag a held long whose short row grades higher, or whose `p10` is below
   the cash return (`cash_return_6m`).
4. Mark each candidate that already has an open order or position in `paper-agent` (the server
   would refuse another one).

## Step 4: Sizing (owned by the server, not by you)

- Do **not** compute share counts for real accounts. The service's risk profile
  (`risk_per_trade`, heat, cluster, ADV limits) owns sizing. Show the plan instead: entry
  limit, stop, target, `risk_pct` and `reward_pct`. Link the account page for the sized ticket.
- If a real account's cash is unknown (`valuation.missing`), say that equity-based numbers for it
  are unavailable. Never treat unknown cash as zero.

## Step 5: Paper orders (only with the `paper` argument, no HALT, window open)

For each grade A row (or, if the user explicitly approved research-grade paper trading in
this repo's memory, the selected B rows):
1. `idempotency_key = "<asof>-<symbol>-<side>"`. A re-run on the same outlook replays the order
   and never duplicates it.
2. Call `place_paper_order(account_id="paper-agent", qty=<large request>, ...)` with a rationale
   that cites the grade, `exp_return_6m`, p10/p90 and the deciding signals.
3. If it is rejected with `qty X exceeds the risk limit of N (...)`, retry once with qty N and the
   same key (nothing was inserted). Record any other rejection verbatim. Do not work around it.
4. Never cancel orders except one placed this run in error. Report open orders from earlier runs
   as they are.

## Step 6: Report

Write `reports/trade-suggestions/<asof>.md` (overwrite on a re-run for the same `asof`). Use
this structure, filled only with values from this run's tool results:

```
# Trade suggestions — outlook <asof> (run <run_id>)
Generated <now UTC> · mode <suggest|paper> · placeable until <placeable_until> · prompt trade-suggestions-v1
<banner: validated-signal status / window closed / stale data / HALT>

## Suggestions (grade A)            ← or "None today"
| Symbol | Side | Grade | Entry | Stop | Target | Exp 6m | p10 / p90 | Why | Link |

## Research (grades B/C)
(same table)

## Your holdings
per account: symbol, qty, current long/short rows, flag if any

## Paper account (paper-agent)
equity, return, drawdown, vs baseline (influence gate status), orders placed/rejected this run

## Data issues
anything missing, unknown cash, open breaks, errors
```

Then append one line to `reports/trade-suggestions/log.md`:
`<now UTC> | asof <asof> | run <run_id> | A:<n> B:<n> C:<n> | paper orders placed:<n> rejected:<n>`.

End the run with a 3–5 line summary: the banner, the top items and the report path. If
anything needs the user (a watch-list add, a holdings upload, a failing tick), say so. Never
confirm a watch-list change yourself, since no user is present in a scheduled run.
