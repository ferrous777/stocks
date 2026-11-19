"""MCP server for the external AI decision-maker (plan §10, §D), mounted at ``/mcp``.

Streamable HTTP (stateless, JSON responses) with the official ``mcp`` SDK. Authentication is a
bearer token equal to one of the service's API keys. Every tool requires ``agent_id``, ``model_id``
and ``prompt_version``; every call is logged to ``agent_decisions`` (what was asked, what the agent
saw, what it did). The tools can only act on **paper** accounts; real accounts are refused.
"""

from __future__ import annotations

import datetime as dt
import hmac
from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field
from pymongo.database import Database

INSTRUCTIONS = """Stocks service: a six-month stock outlook, simulated (paper) trading accounts, tracking of the
user's real brokerage accounts (e.g. Fidelity), and the watch list of tickers.

1. IDENTIFY YOURSELF ON EVERY CALL
Every tool requires these three arguments. They are logged exactly as sent.
  agent_id        A fixed name for your app, e.g. "chatgpt" or "claude-code".
  model_id        Your exact model identifier, but only if your runtime tells you what it is.
                  If it does not, send "unknown". Do not guess, and do not derive it from agent_id.
  prompt_version  "v1" unless the user gives you another version.
Example: {"agent_id": "chatgpt", "model_id": "unknown", "prompt_version": "v1"}

2. READING (safe, changes nothing)
  get_prediction    everything about one ticker: outlook, strategy signals, levels, recent returns
  get_outlook       the six-month outlook for every watched ticker, best expected return first
  get_watchlist     the tickers being tracked
  list_accounts     real accounts and all paper accounts (best return first)
  get_account       one account's cash and positions
  get_performance   a paper account's return, drawdown and comparison with the baseline
  list_orders       a paper account's orders
  list_transactions any account's fills and cash entries (page with next_cursor)
  get_links         website links, e.g. a chart with several calendar years overlaid
Most results include "links" to the website page showing the same data. Give the user these links
when seeing the chart or table would help.

3. UPLOADING HOLDINGS (no confirmation needed)
  upload_holdings   records a real account's current cash and positions as of a date. It is applied
                    immediately. The first upload is the opening balance (avg_cost required for every
                    position; pass account_name to create a new account); later uploads are compared
                    with the records and any difference is flagged for the user, never treated as a
                    trade. Report the result, including any differences, to the user.

4. WATCH-LIST CHANGES NEED THE USER'S YES: add_to_watchlist, remove_from_watchlist
  a. Call the tool WITHOUT confirm_token. Nothing changes; you get a preview and a confirm_token.
  b. Show the preview to the user and ask whether to go ahead.
  c. Only if the user clearly says yes, call the same tool again with the SAME arguments plus
     confirm_token. Never confirm on the user's behalf. Tokens are single-use and expire after
     15 minutes; if one is refused, start again at step a.

5. PAPER ORDERS (simulated money only; real accounts are never traded)
  place_paper_order  needs a unique idempotency_key (8+ characters; reusing it returns the same
                     order) and a short rationale. It buys or shorts at the outlook row's entry
                     limit, with that row's stop and target, for the next trading session only.
                     It is refused after the row's placeable_until time, above the account's risk
                     limits, or if the ticker already has an open order or position there.
  cancel_order       cancels an order before its session opens.

6. READING THE OUTLOOK
Grades: A = signal from a validated strategy; B = calibrated signal, strategy not validated;
C = this ticker's own history only (a base rate, not a forecast); insufficient = no estimate.
Only grade A rows (validated: true) come from a validated strategy; present every other row as
research, not as a recommendation."""


AgentId = Annotated[str, Field(description='Stable name of the calling client or agent, e.g. "chatgpt".')]
ModelId = Annotated[str, Field(description='Exact model identifier if your runtime metadata provides it; '
                                           'otherwise "unknown". Never guess or infer it from the agent name.')]
PromptVersion = Annotated[str, Field(description='Version of the instructions the agent runs under, e.g. "v1".')]


class Holding(BaseModel):
    """One position in an uploaded brokerage snapshot."""
    symbol: str = Field(description="ticker, e.g. NVDA")
    qty: float = Field(description="shares held (negative for a short)")
    avg_cost: float | None = Field(default=None, gt=0,
                                   description="average cost per share (> 0); required on the first upload")


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
    """JSON-safe copy (ObjectIds and datetimes to strings, ``_id`` to ``id``)."""
    from .mcp_ops import jsonable
    return jsonable(x)


def _site(ctx) -> str:
    """Public base URL of this deployment, from the MCP request (honouring the proxy's forwarded headers)."""
    req = getattr(getattr(ctx, "request_context", None), "request", None) if ctx is not None else None
    if req is None:
        raise ValueError("links need the HTTP request; not available on this transport")
    proto = (req.headers.get("x-forwarded-proto") or req.url.scheme).split(",")[0].strip()
    host = (req.headers.get("x-forwarded-host") or req.headers.get("host") or req.url.netloc).split(",")[0].strip()
    return f"{proto}://{host}"


def build_mcp(get_db, get_fetcher=None, get_settings=None) -> FastMCP:
    from . import mcp_ops
    from .web import links as L

    mcp = FastMCP("stocks-paper", instructions=INSTRUCTIONS, stateless_http=True, json_response=True,
                  streamable_http_path="/",
                  transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))

    def log(tool: str, ident: dict, args: dict, result: dict, *, account_id: str | None = None,
            duration_ms: float | None = None) -> None:
        db: Database = get_db()
        db.agent_decisions.insert_one({"ts": _now(), "tool": tool, "account_id": account_id, **ident,
                                       "args": args, "result": result, "duration_ms": duration_ms})

    def audited(tool: str, idn: dict, args: dict, fn):
        """Run ``fn()``; every outcome, including validation errors and refusals, is logged with the
        caller's identity before the result or error is returned (identity itself is checked first)."""
        import time
        t0 = time.perf_counter()
        try:
            res, summary = fn()
        except Exception as e:
            log(tool, idn, args, {"error": f"{type(e).__name__}: {e}"}, account_id=args.get("account_id"),
                duration_ms=(time.perf_counter() - t0) * 1000)
            raise
        log(tool, idn, args, summary, account_id=args.get("account_id"), duration_ms=(time.perf_counter() - t0) * 1000)
        return res

    def ident(agent_id, model_id, prompt_version) -> dict:
        d = {"agent_id": agent_id, "model_id": model_id, "prompt_version": prompt_version}
        if not all(isinstance(v, str) and v.strip() for v in d.values()):
            raise ValueError('agent_id, model_id and prompt_version are required (model_id: your exact model '
                             'identifier if your runtime provides it, otherwise "unknown")')
        return d

    def account(db: Database, account_id: str) -> dict:
        acc = db.accounts.find_one({"_id": account_id})
        if acc is None:
            raise ValueError(f"account {account_id} not found; list_accounts shows them")
        return acc

    def paper(db: Database, account_id: str) -> dict:
        acc = account(db, account_id)
        if acc.get("kind") != "paper":
            raise ValueError(f"{account_id} is a real account; this tool only acts on paper accounts")
        return acc

    def url(ctx, path: str) -> str:
        return L.absolute(_site(ctx), path)

    def confirmed(tool: str, idn: dict, args: dict, confirm_token: str | None, preview, apply):
        """Two-step change: without a token, preview + token; with it, apply exactly the previewed change."""
        db = get_db()

        def run():
            now = _now()
            if not confirm_token:
                p = preview(now)
                tok = mcp_ops.issue_token(db, tool, args, idn, now)
                res = {"status": "preview — nothing has changed yet", "preview": p, **tok}
                return res, {"preview": p, "token": tok["confirm_token"]}
            doc = mcp_ops.redeem_token(db, confirm_token, tool, args, now)
            try:
                out = apply(now)
            except Exception:
                mcp_ops.release_token(db, doc["_id"])
                raise
            return {"status": "done", **out}, {"applied": True, "token": doc["_id"]}

        return audited(tool, idn, {**args, "confirm_token": confirm_token}, run)

    def account_links(ctx, acc: dict) -> dict:
        return {"account": url(ctx, L.account(acc["_id"], acc.get("kind", "real")))}

    # --- outlook and predictions -----------------------------------------------------------------

    @mcp.tool()
    def get_outlook(agent_id: AgentId, model_id: ModelId, prompt_version: PromptVersion, ctx: Context, side: str | None = None,
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
                          "rows": [{**{k: r.get(k) for k in keep}, "link": url(ctx, L.symbol(r["symbol"]))} for r in rows],
                          "links": {"outlook": url(ctx, L.outlook(side if side in ("long", "short") else None))}})
            return res, {"observation": res}   # exactly what the agent received, incl. the outlook run id

        return audited("get_outlook", idn, {"side": side, "min_grade": min_grade, "limit": limit}, run)

    @mcp.tool()
    def get_prediction(agent_id: AgentId, model_id: ModelId, prompt_version: PromptVersion, symbol: str, ctx: Context) -> dict:
        """Detailed prediction for one watched ticker: its outlook rows for both sides (grade, entry/stop/target
        plan, expected six-month return with 10th/90th percentiles, P(win), outcome odds, base rate, umpire
        votes), today's decision of every strategy with reasons, ATR levels with time-to-target odds, recent
        returns, 52-week range and calendar-year returns, plus links to its chart. Tickers not on the watch
        list must be added first (add_to_watchlist)."""
        idn = ident(agent_id, model_id, prompt_version)

        def run():
            res = mcp_ops.prediction(get_db(), symbol)
            sym = res["symbol"]
            years = [y["year"] for y in res.get("calendar_years", [])][:3]
            res["links"] = {"chart": url(ctx, L.symbol(sym)), "chart_5y": url(ctx, L.symbol(sym, range="5Y")),
                            **({"compare_recent_years": url(ctx, L.symbol(sym, compare=years))} if years else {}),
                            "outlook": url(ctx, L.outlook())}
            res = _clean(res)
            return res, {"symbol": sym, "outlook_asof": (res.get("outlook") or {}).get("asof")}

        return audited("get_prediction", idn, {"symbol": symbol}, run)

    # --- watch list ------------------------------------------------------------------------------

    @mcp.tool()
    def get_watchlist(agent_id: AgentId, model_id: ModelId, prompt_version: PromptVersion, ctx: Context) -> dict:
        """Every watched symbol (asset class, groups, last close) and the symbols removed from the list."""
        idn = ident(agent_id, model_id, prompt_version)

        def run():
            res = mcp_ops.watchlist(get_db())
            for r in res["watched"] + res["removed"]:
                r["link"] = url(ctx, L.symbol(r["symbol"]))
            res["links"] = {"dashboard": url(ctx, L.dashboard())}
            return _clean(res), {"watched": len(res["watched"])}

        return audited("get_watchlist", idn, {}, run)

    @mcp.tool()
    async def add_to_watchlist(agent_id: AgentId, model_id: ModelId, prompt_version: PromptVersion, symbol: str, ctx: Context,
                               confirm_token: str | None = None) -> dict:
        """Add a ticker to the watch list (needs the user's confirmation). Without confirm_token: checks the
        ticker at the price source and previews the change. With the token from that preview: adds it and
        loads its daily price history, so predictions and the outlook cover it."""
        idn = ident(agent_id, model_id, prompt_version)
        sym = symbol.strip().upper()

        def apply(now):
            res = mcp_ops.apply_add(get_db(), get_fetcher(), get_settings(), sym, now)
            return {**res, "links": {"chart": url(ctx, L.symbol(res["symbol"]))}}

        import anyio   # the price-source lookup and history load run off the event loop
        return await anyio.to_thread.run_sync(lambda: confirmed(
            "add_to_watchlist", idn, {"symbol": sym}, confirm_token,
            lambda now: mcp_ops.preview_add(get_db(), get_fetcher(), sym, now), apply))

    @mcp.tool()
    def remove_from_watchlist(agent_id: AgentId, model_id: ModelId, prompt_version: PromptVersion, symbol: str,
                              confirm_token: str | None = None) -> dict:
        """Remove a ticker from the watch list (needs the user's confirmation). Without confirm_token: previews
        the change and its effects (refused while paper accounts have open orders or positions in it). With the
        token: stops tracking it; its price history is kept and re-adding resumes from there."""
        idn = ident(agent_id, model_id, prompt_version)
        sym = symbol.strip().upper()
        return confirmed("remove_from_watchlist", idn, {"symbol": sym}, confirm_token,
                         lambda now: mcp_ops.preview_remove(get_db(), sym, now),
                         lambda now: mcp_ops.apply_remove(get_db(), sym, now))

    # --- accounts --------------------------------------------------------------------------------

    @mcp.tool()
    def list_accounts(agent_id: AgentId, model_id: ModelId, prompt_version: PromptVersion, ctx: Context,
                      kind: str | None = None) -> dict:
        """All accounts: the user's real accounts (holdings tracking) and every paper account (AI agent,
        baseline, one per strategy) with equity, return and activity, best paper return first. kind: real|paper."""
        from .accounts import service
        from .paper import read
        idn = ident(agent_id, model_id, prompt_version)

        def run():
            db = get_db()
            out: dict = {}
            if kind in (None, "real"):
                real = []
                for a in db.accounts.find({"kind": {"$ne": "paper"}}).sort("_id", 1):
                    h = service.holdings(db, a["_id"], _now())
                    real.append({"account_id": a["_id"], "name": a.get("name"), "kind": "real", "cash": h["cash"],
                                 "equity": h["equity"], "positions": len(h["positions"]),
                                 "latest_snapshot": h["latest_snapshot"], "open_breaks": h["open_breaks"],
                                 "link": url(ctx, L.account(a["_id"], "real"))})
                out["real"] = real
            if kind in (None, "paper"):
                out["paper"] = [{**r, "link": url(ctx, L.account(r["account_id"], "paper"))} for r in read.summaries(db)]
            out["links"] = {"paper": url(ctx, L.paper()), "accounts": url(ctx, L.accounts())}
            return _clean(out), {"real": len(out.get("real", [])), "paper": len(out.get("paper", []))}

        return audited("list_accounts", idn, {"kind": kind}, run)

    @mcp.tool()
    def get_account(agent_id: AgentId, model_id: ModelId, prompt_version: PromptVersion, account_id: str, ctx: Context) -> dict:
        """One account. Paper: equity, cash, free buying power, reserved cash and positions. Real: holdings
        valued at the latest close, cash, latest snapshot and open reconciliation breaks."""
        from .accounts import service
        from .paper import read
        from .paper.broker import account_book
        idn = ident(agent_id, model_id, prompt_version)

        def run():
            db = get_db()
            acc = account(db, account_id)
            now = _now()
            if acc.get("kind") == "paper":
                _, info = account_book(db, acc, now)
                res = {"account_id": account_id, "kind": "paper", "trades_for": read.kind_label(acc),
                       "starting_cash": acc["starting_cash"], "risk_profile": acc["risk_profile"],
                       "last_session_executed": acc["last_session_executed"], "stalled": acc.get("stalled"), **info,
                       "holdings": service.holdings(db, account_id, now)["positions"]}
            else:
                res = {"kind": "real", **service.holdings(db, account_id, now)}
            res["links"] = account_links(ctx, acc)
            res = _clean(res)
            return res, {"observation": res}

        return audited("get_account", idn, {"account_id": account_id}, run)

    @mcp.tool()
    def get_performance(agent_id: AgentId, model_id: ModelId, prompt_version: PromptVersion, account_id: str, ctx: Context,
                        baseline_account: str | None = None, points: int = 60) -> dict:
        """Paper account performance: total return, max drawdown, closed-order win rate and average, the most
        recent `points` equity points, and the paired comparison with its baseline (the matching baseline
        unless baseline_account is given) including the influence gate."""
        from .paper import read, report
        idn = ident(agent_id, model_id, prompt_version)

        def run():
            db = get_db()
            acc = paper(db, account_id)
            res = read.performance(db, account_id, points=max(1, min(points, 2000)))
            if baseline_account:
                paper(db, baseline_account)
                res["comparison"] = {**report.compare(db, account_id, baseline_account), "pairing": "requested"}
            else:
                res["comparison"] = read.comparison(db, acc)
            res["links"] = account_links(ctx, acc)
            return _clean(res), {"sessions": res["sessions"]}

        return audited("get_performance", idn, {"account_id": account_id, "baseline_account": baseline_account,
                                                 "points": points}, run)

    @mcp.tool()
    def list_orders(agent_id: AgentId, model_id: ModelId, prompt_version: PromptVersion, account_id: str, ctx: Context,
                    status: str | None = None) -> dict:
        """Orders of a paper account (open, filled, closed, not_filled, cancelled), newest first."""
        idn = ident(agent_id, model_id, prompt_version)

        def run():
            db = get_db()
            acc = paper(db, account_id)
            q = {"account_id": account_id, **({"status": status} if status else {})}
            orders = _clean(list(db.orders.find(q).sort("placed_at", -1).limit(200)))
            return {"orders": orders, "links": account_links(ctx, acc)}, {"order_ids": [x["id"] for x in orders]}

        return audited("list_orders", idn, {"account_id": account_id, "status": status}, run)

    @mcp.tool()
    def list_transactions(agent_id: AgentId, model_id: ModelId, prompt_version: PromptVersion, account_id: str, ctx: Context,
                          limit: int = 100, cursor: str | None = None) -> dict:
        """Transactions of any account, newest first: fills (buy/sell/short/cover with qty, price, fees) and
        ledger entries (opening balances, dividends, borrow fees, transfers, splits); `cash` is each entry's
        effect on cash. For older entries pass next_cursor back as cursor."""
        from .paper import read
        idn = ident(agent_id, model_id, prompt_version)

        def run():
            db = get_db()
            acc = account(db, account_id)
            res = read.transactions(db, account_id, limit=limit, cursor=cursor)
            res["links"] = account_links(ctx, acc)
            return res, {"returned": len(res["transactions"])}

        return audited("list_transactions", idn, {"account_id": account_id, "limit": limit, "cursor": cursor}, run)

    @mcp.tool()
    def upload_holdings(agent_id: AgentId, model_id: ModelId, prompt_version: PromptVersion, account_id: str, as_of: str,
                        cash: float, positions: list[Holding], ctx: Context, account_name: str | None = None) -> dict:
        """Upload the user's current holdings of a real brokerage account (e.g. Fidelity) for tracking. Applied
        immediately, no confirmation needed. as_of: ISO date (that day's close) or datetime; cash: the cash
        balance (core position); positions: every holding with qty and avg_cost. The first upload is the opening
        balance; later ones are reconciled with the ledger and differences are recorded as breaks to explain,
        never as trades. To create a new account pass account_name. Invalid values are refused before anything
        is saved."""
        idn = ident(agent_id, model_id, prompt_version)
        pos = [p.model_dump() for p in positions]
        args = {"account_id": account_id, "as_of": as_of, "cash": cash, "positions": pos, "account_name": account_name}

        def run():
            res = mcp_ops.apply_holdings(get_db(), account_id, as_of=as_of, cash=cash, positions=pos,
                                         account_name=account_name, now=_now())
            res["links"] = {"account": url(ctx, L.account(account_id, "real"))}
            return res, {"snapshot_id": res["snapshot_id"], "opening_balance": res["opening_balance"],
                         "open_breaks": len(res["open_breaks"])}

        return audited("upload_holdings", idn, args, run)

    # --- paper orders ----------------------------------------------------------------------------

    @mcp.tool()
    def place_paper_order(agent_id: AgentId, model_id: ModelId, prompt_version: PromptVersion, account_id: str, symbol: str,
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
    def cancel_order(agent_id: AgentId, model_id: ModelId, prompt_version: PromptVersion, account_id: str, order_id: str) -> dict:
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

    # --- links -----------------------------------------------------------------------------------

    @mcp.tool()
    def get_links(agent_id: AgentId, model_id: ModelId, prompt_version: PromptVersion, ctx: Context, symbol: str | None = None,
                  chart_range: str | None = None, from_year: int | None = None,
                  compare_years: list[int] | None = None, account_id: str | None = None,
                  outlook_side: str | None = None) -> dict:
        """Links to the website to show the user data or a visualization. Always returns the page catalog.
        symbol: its page, with at most one chart view: chart_range (6M, YTD, 1Y, 3Y, 5Y, All), from_year (that
        year to present) or compare_years (up to 8 recent calendar years overlaid on a Jan-Dec axis).
        account_id: that account's page. outlook_side: long|short filter of the outlook page."""
        idn = ident(agent_id, model_id, prompt_version)

        def run():
            site = _site(ctx)
            out: dict = {"pages": [{**c, "url": L.absolute(site, c["path"])} for c in L.CATALOG]}
            if symbol:
                sym = mcp_ops.normalize_symbol(symbol)
                out["symbol"] = L.absolute(site, L.symbol(sym, range=chart_range, from_year=from_year,
                                                          compare=compare_years))
            if account_id:
                acc = account(get_db(), account_id)
                out["account"] = L.absolute(site, L.account(acc["_id"], acc.get("kind", "real")))
            if outlook_side:
                out["outlook"] = L.absolute(site, L.outlook(outlook_side))
            return out, {k: v for k, v in out.items() if k != "pages"}

        return audited("get_links", idn, {"symbol": symbol, "chart_range": chart_range, "from_year": from_year,
                                          "compare_years": compare_years, "account_id": account_id,
                                          "outlook_side": outlook_side}, run)

    return mcp
