"""MCP server for the external AI decision-maker (plan §10, §D), mounted at ``/mcp``.

Streamable HTTP (stateless, JSON responses) with the official ``mcp`` SDK. Authentication is a
bearer token equal to one of the service's API keys. Every tool requires ``agent_id``, ``model_id``
and ``prompt_version``; every call is logged to ``agent_decisions`` (what was asked, what the agent
saw, what it did). The tools can only act on **paper** accounts; real accounts are refused.
"""

from __future__ import annotations

import datetime as dt
import hmac
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pymongo.database import Database

INSTRUCTIONS = """Paper-trading tools for a six-month stock outlook.
Each session's outlook is built after the close; orders for the next session must be placed before
its open (see placeable_until). Orders are DAY limit orders at the outlook row's entry limit with the
row's stop and target; exits are simulated with the same rules as the research. Only paper accounts.
Always pass your agent_id, model_id and prompt_version; place_paper_order needs an idempotency_key and
a rationale. Grades: A = validated strategy, B = calibrated but not validated, C = the symbol's own
history (base rate), insufficient = no estimate."""


class _Auth:
    """ASGI wrapper: Authorization: Bearer <API key> (constant-time compare)."""

    def __init__(self, app, keys: list[str]):
        self.app, self.keys = app, [k.encode() for k in keys]

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            auth = headers.get(b"authorization", b"")
            token = auth[7:].strip() if auth[:7].lower() == b"bearer " else b""
            if not any(hmac.compare_digest(token, k) for k in self.keys):
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json"),
                                        (b"www-authenticate", b"Bearer")]})
                await send({"type": "http.response.body", "body": b'{"detail":"missing or invalid bearer token"}'})
                return
        await self.app(scope, receive, send)


class McpPath:
    """Serve ``/mcp`` itself (no 307 to ``/mcp/``): some MCP clients do not follow redirects on POST."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path") == "/mcp":
            scope = {**scope, "path": "/mcp/", "raw_path": b"/mcp/"}
        await self.app(scope, receive, send)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _clean(x: Any) -> Any:
    """JSON-safe copy (ObjectIds and datetimes to strings)."""
    from bson import ObjectId
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items() if k != "_id"} | ({"id": str(x["_id"])} if "_id" in x else {})
    if isinstance(x, list):
        return [_clean(v) for v in x]
    if isinstance(x, ObjectId):
        return str(x)
    if isinstance(x, (dt.datetime, dt.date)):
        return x.isoformat()
    return x


def build_mcp(get_db) -> FastMCP:
    mcp = FastMCP("stocks-paper", instructions=INSTRUCTIONS, stateless_http=True, json_response=True,
                  streamable_http_path="/",
                  transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))

    def log(tool: str, ident: dict, args: dict, result: dict, *, account_id: str | None = None) -> None:
        db: Database = get_db()
        db.agent_decisions.insert_one({"ts": _now(), "tool": tool, "account_id": account_id, **ident,
                                       "args": args, "result": result})

    def audited(tool: str, idn: dict, args: dict, fn):
        """Run ``fn()``; every outcome, including validation errors and refusals, is logged with the
        caller's identity before the result or error is returned (identity itself is checked first)."""
        try:
            res, summary = fn()
        except Exception as e:
            log(tool, idn, args, {"error": f"{type(e).__name__}: {e}"}, account_id=args.get("account_id"))
            raise
        log(tool, idn, args, summary, account_id=args.get("account_id"))
        return res

    def ident(agent_id, model_id, prompt_version) -> dict:
        d = {"agent_id": agent_id, "model_id": model_id, "prompt_version": prompt_version}
        if not all(d.values()):
            raise ValueError("agent_id, model_id and prompt_version are required")
        return d

    def paper(db: Database, account_id: str) -> dict:
        acc = db.accounts.find_one({"_id": account_id})
        if acc is None:
            raise ValueError(f"account {account_id} not found")
        if acc.get("kind") != "paper":
            raise ValueError(f"{account_id} is a real account; MCP tools only act on paper accounts")
        return acc

    @mcp.tool()
    def get_outlook(agent_id: str, model_id: str, prompt_version: str, side: str | None = None,
                    min_grade: str = "C", limit: int = 50) -> dict:
        """Latest six-month outlook rows (best expected return first), with each row's plan and grade."""
        from .outlook.build import GRADE_ORDER, latest_outlook
        idn = ident(agent_id, model_id, prompt_version)

        def run():
            o = latest_outlook(get_db())
            if o is None:
                raise ValueError("no outlook yet")
            rows = [r for r in o["rows"] if (side is None or r["side"] == side)
                    and GRADE_ORDER[r["grade"]] <= GRADE_ORDER.get(min_grade, 3)][: max(1, min(limit, 200))]
            keep = ("symbol", "side", "grade", "source", "plan", "exp_return_6m", "exp_excess_6m", "p10_return_6m",
                    "p90_return_6m", "signals", "reasons")
            res = _clean({"asof": o["asof"], "run_id": o["run_id"], "placeable_until": o.get("placeable_until"),
                          "cash_return_6m": o["cash_return_6m"], "cost_profile": o["cost_profile"],
                          "rows": [{k: r.get(k) for k in keep} for r in rows]})
            return res, {"observation": res}   # exactly what the agent received, incl. the outlook run id

        return audited("get_outlook", idn, {"side": side, "min_grade": min_grade, "limit": limit}, run)

    @mcp.tool()
    def get_account(agent_id: str, model_id: str, prompt_version: str, account_id: str) -> dict:
        """Paper account summary: equity, cash, free buying power, reserved cash, positions by market value."""
        from .paper.broker import account_book
        idn = ident(agent_id, model_id, prompt_version)

        def run():
            db = get_db()
            acc = paper(db, account_id)
            _, info = account_book(db, acc, _now())
            res = _clean({"account_id": account_id, "starting_cash": acc["starting_cash"],
                          "risk_profile": acc["risk_profile"], "last_session_executed": acc["last_session_executed"],
                          "stalled": acc.get("stalled"), **info})
            return res, {"observation": res}

        return audited("get_account", idn, {"account_id": account_id}, run)

    @mcp.tool()
    def list_orders(agent_id: str, model_id: str, prompt_version: str, account_id: str,
                    status: str | None = None) -> dict:
        """Orders of a paper account (open, filled, closed, not_filled, cancelled)."""
        idn = ident(agent_id, model_id, prompt_version)

        def run():
            db = get_db()
            paper(db, account_id)
            q = {"account_id": account_id, **({"status": status} if status else {})}
            orders = _clean(list(db.orders.find(q).sort("placed_at", -1).limit(200)))
            return {"orders": orders}, {"order_ids": [x["id"] for x in orders]}

        return audited("list_orders", idn, {"account_id": account_id, "status": status}, run)

    @mcp.tool()
    def place_paper_order(agent_id: str, model_id: str, prompt_version: str, account_id: str, symbol: str,
                          side: str, qty: int, idempotency_key: str, rationale: str) -> dict:
        """Place a DAY limit order for the next session from the latest outlook row (paper only).

        Uses the row's entry limit, stop and target. Rejected after the row's placeable_until, above the
        account's risk limits, or when the symbol already has an open order or position."""
        from .accounts.service import AccountError, NotFound
        from .paper.broker import place_order
        idn = ident(agent_id, model_id, prompt_version)
        args = {"account_id": account_id, "symbol": symbol, "side": side, "qty": qty,
                "idempotency_key": idempotency_key, "rationale": rationale}

        def run():
            if len(rationale.strip()) < 3 or len(idempotency_key) < 8:
                raise ValueError("a rationale and an idempotency_key of at least 8 characters are required")
            db = get_db()
            paper(db, account_id)
            try:
                res = place_order(db, account_id, symbol=symbol, side=side, qty=qty,
                                  idempotency_key=idempotency_key, decided_by={**idn, "rationale": rationale},
                                  now=_now())
            except (AccountError, NotFound) as e:
                return {"rejected": str(e)}, {"rejected": str(e)}
            o = res["order"]
            return (_clean({**o, "replayed": res["replayed"]}),
                    {"order_id": str(o["_id"]), "replayed": res["replayed"], "outlook_asof": o["outlook_asof"]})

        return audited("place_paper_order", idn, args, run)

    @mcp.tool()
    def cancel_order(agent_id: str, model_id: str, prompt_version: str, account_id: str, order_id: str) -> dict:
        """Cancel an open paper order before its session opens."""
        from .accounts.service import AccountError, NotFound
        from .paper.broker import cancel_order as _cancel
        idn = ident(agent_id, model_id, prompt_version)

        def run():
            db = get_db()
            paper(db, account_id)
            try:
                o = _cancel(db, account_id, order_id, now=_now())
            except (AccountError, NotFound) as e:
                return {"rejected": str(e)}, {"rejected": str(e)}
            return _clean(o), {"status": o["status"]}

        return audited("cancel_order", idn, {"account_id": account_id, "order_id": order_id}, run)

    @mcp.tool()
    def get_performance(agent_id: str, model_id: str, prompt_version: str, account_id: str,
                        baseline_account: str | None = None) -> dict:
        """Equity curve summary, and (with baseline_account) the paired comparison and influence gate."""
        from .paper.report import compare
        idn = ident(agent_id, model_id, prompt_version)

        def run():
            db = get_db()
            paper(db, account_id)
            curve = list(db.equity_curve.find({"account_id": account_id}).sort("session", 1))
            res = {"account_id": account_id, "sessions": len(curve),
                   "equity": [{"session": e["session"], "equity": e["equity"]} for e in curve[-30:]]}
            if baseline_account:
                paper(db, baseline_account)
                res["comparison"] = compare(db, account_id, baseline_account)
            return _clean(res), {"sessions": len(curve)}

        return audited("get_performance", idn, {"account_id": account_id, "baseline_account": baseline_account}, run)

    return mcp
