# Connecting an AI agent (MCP)

The website's **Connect** page (`/connect`) has copy-paste setup for Claude Code, JSON-configured clients, the Claude API MCP connector, the Python MCP SDK and a curl check, all pointing at the server you are viewing, plus the live tool list.

The service exposes an MCP server for an external AI decision-maker:
- **Endpoint:** `https://stocks-production-8666a97e.up.railway.app/mcp`. It uses streamable HTTP and is stateless.
- **Auth:** `Authorization: Bearer <one of STOCKS_API_KEYS>`.
- **Scope:** orders are placed on **paper accounts only**. Real accounts can be read, and their holdings uploaded for tracking, but never traded.

## Tools

Every tool takes three identity arguments, and every call is logged to `agent_decisions` exactly as sent:
- `agent_id`: a fixed name for the app, e.g. `chatgpt`.
- `model_id`: the exact model identifier, but only if the app's runtime provides it. Otherwise send `unknown`. Never guess it, and never infer it from `agent_id`.
- `prompt_version`: e.g. `v1`.

Example: `{"agent_id": "chatgpt", "model_id": "unknown", "prompt_version": "v1"}`. Most results include `links`: absolute URLs of the website page or chart view that shows the same data.

| Tool | What it does |
|---|---|
| `get_prediction` | Detailed view of one watched ticker: outlook rows for both sides, every strategy's decision, ATR levels with time-to-target odds, recent returns, 52-week range, calendar-year returns, chart links. |
| `get_outlook` | Latest six-month outlook rows: plan, grade, expected return and percentiles, `placeable_until`, and the cost profile (`cost_profile` key and `cost` values) it was built with. At most 200 rows, no paging. |
| `get_watchlist` | Watched symbols (and removed ones) with their last close. |
| `add_to_watchlist` | **Confirmed.** Checks the ticker at Yahoo, adds it and loads its daily history. |
| `remove_from_watchlist` | **Confirmed.** Stops tracking a ticker and keeps its history. Refused while paper orders or positions need its prices. |
| `list_accounts` | Real accounts (cash, equity, latest snapshot, open breaks) and every paper account (return, equity, activity), best return first. |
| `get_account` | Paper: equity, cash, free buying power, reservations, positions, and the account's own `cost` and `risk_limits` values (null if the profile is missing). Real: holdings at the latest close, cash, snapshot, breaks. |
| `get_performance` | Paper: return, max drawdown, closed-order stats, equity points, and the paired comparison with its baseline (with the influence gate). |
| `list_orders` | Paper orders and their status. |
| `list_transactions` | Fills and ledger entries of any account, newest first, paged with `cursor`. |
| `upload_holdings` | Applied immediately, with no confirmation. Uploads a real account's `positions[{symbol, qty, avg_cost?, institution_price?, institution_price_as_of?, institution_value?}]`, plus whatever the source actually provides: `cash` (core cash only; omit if unknown, which is never treated as zero), `available_to_withdraw`, `as_of` (the institution's timestamp; omit if unknown), `retrieved_at`, `source`, and `account_name` to create the account. See *Uploading from Plaid* below. |
| `place_paper_order` | DAY limit order for the next session from an outlook row. Needs `idempotency_key` and `rationale`. Rejected after `placeable_until`, above the risk limits, or when the symbol already has an open order or position. |
| `cancel_order` | Cancel an open order before its session opens. |
| `get_links` | The page catalog, plus links for a symbol (with an optional chart view: `chart_range`, `from_year` or `compare_years`), an account, or an outlook side. |

**Confirmed** tools (the watch-list changes) change data in two steps:
1. Called without `confirm_token`, they only preview the change and return a single-use token. The token is bound to those exact arguments and is valid for 15 minutes.
2. The agent shows the preview to the user. After the user agrees, it repeats the call with the token.

## Setup

1. Create a risk profile (`POST /api/v1/risk-profiles`) and two paper accounts with the same starting cash and profiles:
   - one for the agent (`policy: "agent"`);
   - one baseline (`policy: "baseline_v1@1"`).
2. Point the agent at `/mcp` with a bearer API key. Run it after each daily outlook, which is built after the close by the tick, and before the next open.
3. Compare the two with `GET /api/v1/paper/compare?agent=<id>&baseline=<id>`.

The agent stays **shadow-only**: it never affects real-account output. That holds until, over at least 126 shared sessions and 30 closed orders, the paired daily-return difference has a 95% CI lower bound above 0 and the agent's drawdown is no worse than the baseline's.

## Uploading from Plaid (e.g. Fidelity)

| Plaid field | Send as | Notes |
|---|---|---|
| `holdings[].quantity`, `security.ticker_symbol` | `positions[].qty`, `.symbol` | |
| `holdings[].cost_basis / quantity` | `positions[].avg_cost` | Required on the first upload only. |
| `holdings[].institution_price`, `institution_price_as_of`, `institution_value` | the same names on each position | Stored for reference. Omit the timestamp if Plaid has none. |
| `balances.available` | `available_to_withdraw` | Cash available to withdraw. It is **not** core cash. |
| `balances.current` | (do not send as cash) | This is total account value. |
| core cash (only if separately identified) | `cash` | Otherwise omit `cash`: it stays unknown, never zero. |
| the time of your Plaid request | `retrieved_at` | |
| an institution timestamp, if Plaid gives one | `as_of` | Omit it if unknown. Reconciliation then uses `retrieved_at`. |

How the service handles these uploads:
- **Unknown cash.** While cash is unknown, holdings are still reconciled and valued, but equity is reported as incomplete (`valuation.missing`). An earlier cash figure is shown as `last_reported_cash` (historical), never as current cash. The first upload that does report core cash establishes it.
- **Delayed trades.** A recorded fill from the last few days that Plaid has not reflected yet makes the difference `pending`, not `open`. It resolves itself once a later upload includes the trade.
