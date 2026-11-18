# Connecting an AI agent (MCP)

The website's **Connect** page (`/connect`) has copy-paste setup for Claude Code, JSON-configured clients, the Claude API MCP connector, the Python MCP SDK and a curl check, all pointing at the server you are viewing, plus the live tool list.

The service exposes an MCP server for an external AI decision-maker:
- **Endpoint:** `https://stocks-production-8666a97e.up.railway.app/mcp`. It uses streamable HTTP and is stateless.
- **Auth:** `Authorization: Bearer <one of STOCKS_API_KEYS>`.
- **Scope:** the tools act on **paper accounts only**. Real accounts are refused.

## Tools

Every tool takes `agent_id`, `model_id` and `prompt_version`, and every call is logged to `agent_decisions`.

| Tool | What it does |
|---|---|
| `get_outlook` | Latest six-month outlook rows: plan, grade, expected return and percentiles, and `placeable_until`. |
| `get_account` | Equity, cash, free buying power, reservations and positions of a paper account. |
| `list_orders` | Orders and their status. |
| `place_paper_order` | DAY limit order for the next session from an outlook row. Needs `idempotency_key` and `rationale`. Rejected after `placeable_until`, above the risk limits, or when the symbol already has an open order or position. |
| `cancel_order` | Cancel an open order before its session opens. |
| `get_performance` | Equity curve. With `baseline_account`, also the paired comparison and the influence gate. |

## Setup

1. Create a risk profile (`POST /api/v1/risk-profiles`) and two paper accounts with the same starting cash and profiles:
   - one for the agent (`policy: "agent"`);
   - one baseline (`policy: "baseline_v1@1"`).
2. Point the agent at `/mcp` with a bearer API key. Run it after each daily outlook, which is built after the close by the tick, and before the next open.
3. Compare the two with `GET /api/v1/paper/compare?agent=<id>&baseline=<id>`.

The agent stays **shadow-only**: it never affects real-account output. That holds until, over at least 126 shared sessions and 30 closed orders, the paired daily-return difference has a 95% CI lower bound above 0 and the agent's drawdown is no worse than the baseline's.
