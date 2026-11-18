"""Paired agent-vs-baseline comparison (plan §D).

Both accounts trade the same opportunity feed with the same cost and risk rules; the comparison
uses only sessions present in both equity curves, measured from each account's value just before
the first shared session (its starting cash when that is its first trading session); closed-order
statistics count only orders that exited within the shared period. Reported: total return, max drawdown, trades,
average realized net return per closed order, and the annualized mean of the **paired daily
return difference** with a seeded block-bootstrap 95% CI (only once there are enough sessions).

Influence gate: the agent stays shadow-only (no effect on real-account output) until, over at least
``MIN_SESSIONS`` shared sessions and ``MIN_TRADES`` closed agent orders, the CI lower bound of the
paired difference is above 0 and its max drawdown is no worse than the baseline's.
"""

from __future__ import annotations

import numpy as np
from pymongo.database import Database

from ..research import stats

MIN_SESSIONS = 126
MIN_TRADES = 30
BOOTSTRAP_MIN = 40


def _curve(db: Database, account_id: str) -> dict:
    return {e["session"].date(): e["equity"] for e in db.equity_curve.find({"account_id": account_id})}


def _opening_value(db: Database, account_id: str, curve: dict, first) -> float:
    """Equity just before ``first``: the previous session's close, or the starting cash when ``first`` is
    the account's first trading session (so the first shared session's P&L is counted)."""
    prior = [d for d in curve if d < first]
    if prior:
        return curve[max(prior)]
    return db.accounts.find_one({"_id": account_id}, {"starting_cash": 1})["starting_cash"]


def _closed(db: Database, account_id: str, first=None, last=None) -> list[float]:
    """Net return of orders whose exit session falls in [first, last] (the evaluated period)."""
    out = []
    q = {"account_id": account_id, "status": "closed"}
    if first is not None:
        import datetime as _dt
        q["exit_session"] = {"$gte": _dt.datetime.combine(first, _dt.time()),
                             "$lte": _dt.datetime.combine(last, _dt.time())}
    for o in db.orders.find(q):
        flows = 0.0
        for x in db.executions.find({"order_id": o["_id"]}):
            flows += (-1 if x["side"] in ("buy", "cover") else 1) * x["qty"] * x["price"] - x["fees"]
        flows += sum(e["amount"] for e in db.ledger_events.find({"account_id": account_id,
                                                                  "ref": {"$regex": f":{o['_id']}:"}}))
        out.append(flows / (o["fill_price"] * o["qty"]))
    return out


def compare(db: Database, agent_account: str, baseline_account: str) -> dict:
    a, b = _curve(db, agent_account), _curve(db, baseline_account)
    common = sorted(set(a) & set(b))
    out = {"agent_account": agent_account, "baseline_account": baseline_account, "sessions": len(common),
           "first_session": common[0].isoformat() if common else None,
           "last_session": common[-1].isoformat() if common else None}
    first, last = (common[0], common[-1]) if common else (None, None)
    ta = _closed(db, agent_account, first, last) if common else []
    tb = _closed(db, baseline_account, first, last) if common else []
    out["closed_orders"] = {"agent": len(ta), "baseline": len(tb)}
    out["avg_net_return_per_order"] = {"agent": float(np.mean(ta)) if ta else None,
                                       "baseline": float(np.mean(tb)) if tb else None}
    if not common:
        out["gate"] = {"promotable": False, "reason": "no shared sessions"}
        return out
    # Prepend each account's value just before the period so the first shared session's P&L counts.
    ea = [_opening_value(db, agent_account, a, first)] + [a[d] for d in common]
    eb = [_opening_value(db, baseline_account, b, first)] + [b[d] for d in common]
    out["total_return"] = {"agent": ea[-1] / ea[0] - 1, "baseline": eb[-1] / eb[0] - 1}
    out["max_drawdown"] = {"agent": stats.max_drawdown(ea)[0], "baseline": stats.max_drawdown(eb)[0]}
    diff = stats.daily_returns(ea) - stats.daily_returns(eb)
    if len(diff) >= BOOTSTRAP_MIN:
        m, lo, hi = stats.block_bootstrap_mean_ci(diff, block=min(20, len(diff) // 2))
        out["paired_excess_annual"] = {"mean": m, "ci95": [lo, hi]}
    else:
        out["paired_excess_annual"] = {"mean": float(diff.mean() * stats.TRADING_DAYS), "ci95": None,
                                       "note": f"CI needs at least {BOOTSTRAP_MIN} shared sessions"}
    checks = {
        "min_sessions": len(common) >= MIN_SESSIONS,
        "min_trades": len(ta) >= MIN_TRADES,
        "ci_lower_gt_0": bool(out["paired_excess_annual"]["ci95"] and out["paired_excess_annual"]["ci95"][0] > 0),
        "drawdown_not_worse": out["max_drawdown"]["agent"] <= out["max_drawdown"]["baseline"],
    }
    out["gate"] = {"checks": checks, "promotable": all(checks.values()),
                   "status": "eligible for promotion review" if all(checks.values()) else "shadow-only"}
    return out
