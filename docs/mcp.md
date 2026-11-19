# Connecting an AI agent (MCP)

The website's **Connect** page (`/connect`) has copy-paste setup for Claude Code, JSON-configured clients, the Claude API MCP connector, the Python MCP SDK and a curl check, all pointing at the server you are viewing, plus the live tool list.

The service exposes an MCP server for an external AI decision-maker:
- **Endpoint:** `https://stocks-production-8666a97e.up.railway.app/mcp`. It uses streamable HTTP and is stateless.
- **Auth:** `Authorization: Bearer <one of STOCKS_API_KEYS>`.
- **Scope:** orders are placed on **paper accounts only**. Real accounts can be read, and their holdings uploaded for tracking, but never traded.

## Tools

Every tool takes `agent_id`, `model_id` and `prompt_version`, and every call is logged to `agent_decisions`. Most results include `links`: absolute URLs of the website page or chart view that shows the same data.

| Tool | What it does |
|---|---|
| `get_prediction` | Detailed view of one watched ticker: outlook rows for both sides, every strategy's decision, ATR levels with time-to-target odds, recent returns, 52-week range, calendar-year returns, chart links. |
| `get_outlook` | Latest six-month outlook rows: plan, grade, expected return and percentiles, and `placeable_until`. |
| `get_watchlist` | Watched symbols (and removed ones) with their last close. |
| `add_to_watchlist` | **Confirmed.** Checks the ticker at Yahoo, adds it and loads its daily history. |
| `remove_from_watchlist` | **Confirmed.** Stops tracking a ticker and keeps its history. Refused while paper orders or positions need its prices. |
| `list_accounts` | Real accounts (cash, equity, latest snapshot, open breaks) and every paper account (return, equity, activity), best return first. |
| `get_account` | Paper: equity, cash, free buying power, reservations, positions. Real: holdings at the latest close, cash, snapshot, breaks. |
| `get_performance` | Paper: return, max drawdown, closed-order stats, equity points, and the paired comparison with its baseline (with the influence gate). |
| `list_orders` | Paper orders and their status. |
| `list_transactions` | Fills and ledger entries of any account, newest first, paged with `cursor`. |
| `upload_holdings` | **Confirmed.** Uploads a real account's holdings: `as_of`, `cash`, `positions[{symbol, qty, avg_cost}]`, and `account_name` to create the account. The first upload is the opening balance. Later uploads are reconciled, and any differences become breaks, never trades. |
| `place_paper_order` | DAY limit order for the next session from an outlook row. Needs `idempotency_key` and `rationale`. Rejected after `placeable_until`, above the risk limits, or when the symbol already has an open order or position. |
| `cancel_order` | Cancel an open order before its session opens. |
| `get_links` | The page catalog, plus links for a symbol (with an optional chart view: `chart_range`, `from_year` or `compare_years`), an account, or an outlook side. |

**Confirmed** tools change data in two steps:
1. Called without `confirm_token`, they only preview the change and return a single-use token. The token is bound to those exact arguments and is valid for 15 minutes.
2. The agent shows the preview to the user. After the user agrees, it repeats the call with the token.

## Setup

1. Create a risk profile (`POST /api/v1/risk-profiles`) and two paper accounts with the same starting cash and profiles:
   - one for the agent (`policy: "agent"`);
   - one baseline (`policy: "baseline_v1@1"`).
2. Point the agent at `/mcp` with a bearer API key. Run it after each daily outlook, which is built after the close by the tick, and before the next open.
3. Compare the two with `GET /api/v1/paper/compare?agent=<id>&baseline=<id>`.

The agent stays **shadow-only**: it never affects real-account output. That holds until, over at least 126 shared sessions and 30 closed orders, the paired daily-return difference has a 95% CI lower bound above 0 and the agent's drawdown is no worse than the baseline's.
