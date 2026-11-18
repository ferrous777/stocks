"""Paired agent-vs-baseline comparison (plan §D).

Both accounts trade the same opportunity feed with the same cost and risk rules; the comparison
uses only sessions present in both equity curves. Reported: total return, max drawdown, trades,
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


def _closed(db: Database, account_id: str) -> list[float]:
    out = []
    for o in db.orders.find({"account_id": account_id, "status": "closed"}):
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
    ta, tb = _closed(db, agent_account), _closed(db, baseline_account)
    out["closed_orders"] = {"agent": len(ta), "baseline": len(tb)}
    out["avg_net_return_per_order"] = {"agent": float(np.mean(ta)) if ta else None,
                                       "baseline": float(np.mean(tb)) if tb else None}
    if len(common) < 2:
        out["gate"] = {"promotable": False, "reason": "fewer than 2 shared sessions"}
        return out
    ea, eb = [a[d] for d in common], [b[d] for d in common]
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
