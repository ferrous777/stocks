"""``baseline_v1``: the reproducible decision policy the AI agent is compared against (plan §D).

After each outlook, for the baseline paper account: take rows with a published estimate whose
expected excess over T-bills is positive, rank them by expected six-month return, fill free
position slots (max 10 positions/orders) in that order, and size each with the account's risk
profile (the same server-side limits the agent faces). Entries only at the row's limit.
Deterministic: same outlook + same account state -> same orders; idempotency keys make re-runs no-ops.
"""

from __future__ import annotations

import datetime as dt

from pymongo.database import Database

from ..accounts.ledger import QTY_TOL
from ..accounts.risk import RiskProfile
from ..accounts.service import AccountError, ledger_state
from ..outlook.build import latest_outlook
from ..research.series import SymbolSeries
from .broker import OPEN_STATUSES, _cost, account_book, max_order_qty, place_order
from .clusters import cluster_map, keys_for

POLICY_ID = "baseline_v1@1"
MAX_POSITIONS = 10


def run_baseline(db: Database, account_id: str, now: dt.datetime) -> dict:
    def pick(o: dict, busy: set[str]) -> list[dict]:
        cands = [r for r in o["rows"] if r.get("plan") and r.get("exp_excess_6m") is not None and r["exp_excess_6m"] > 0
                 and r["symbol"] not in busy]
        cands.sort(key=lambda r: (-r["exp_return_6m"], r["symbol"], r["side"]))
        return cands
    return place_ranked(db, account_id, now, pick=pick, decided_by={"policy": POLICY_ID}, key_prefix="baseline")


def place_ranked(db: Database, account_id: str, now: dt.datetime, *, pick, decided_by: dict, key_prefix: str,
                 max_positions: int = MAX_POSITIONS) -> dict:
    """Shared order placement for rule-based paper policies: ``pick(outlook, busy_symbols)`` returns
    outlook rows in priority order; free position slots are filled in that order, each sized with the
    account's risk profile (the same server-side limits the agent faces), entries only at the row's
    limit. Idempotency keys (``<key_prefix>:<asof>:<symbol>:<side>``) make re-runs no-ops."""
    acc = db.accounts.find_one({"_id": account_id})
    o = latest_outlook(db)
    if acc is None or o is None:
        return {"placed": [], "reason": "no account or outlook"}
    if now >= dt.datetime.fromisoformat(o["placeable_until"]):
        return {"placed": [], "reason": "placement window closed"}
    st = ledger_state(db, account_id, now)
    busy = {s for s, h in st.holdings.items() if abs(h.qty) > QTY_TOL}
    busy |= {x["symbol"] for x in db.orders.find({"account_id": account_id, "status": {"$in": list(OPEN_STATUSES)}})}
    slots = max_positions - len(busy)
    cands = pick(o, busy)
    profile = RiskProfile.from_doc(db.risk_profiles.find_one({"_id": acc["risk_profile"]}))
    cost = _cost(db, acc)
    cmap = cluster_map(db, o["asof"], profile.corr_threshold)
    placed, skipped = [], []
    for r in cands:
        if slots <= 0:
            break
        if r["symbol"] in busy:
            continue
        if r["side"] == "short" and cost.borrow_rate_annual is None:
            skipped.append({"symbol": r["symbol"], "side": r["side"], "reason": "shorts disabled (no borrow rate)"})
            continue
        book, _ = account_book(db, acc, now, profile=profile, clusters=cmap)
        qty, why = max_order_qty(r, book, profile, cost, keys_for(r["symbol"], *cmap),
                                 SymbolSeries.from_db(db, r["symbol"]), dt.date.fromisoformat(o["asof"]))
        if qty < 1:
            skipped.append({"symbol": r["symbol"], "side": r["side"], "reason": why})
            continue
        try:
            res = place_order(db, account_id, symbol=r["symbol"], side=r["side"], qty=qty,
                              idempotency_key=f"{key_prefix}:{o['asof']}:{r['symbol']}:{r['side']}",
                              decided_by=decided_by, now=now)
        except AccountError as e:
            skipped.append({"symbol": r["symbol"], "side": r["side"], "reason": str(e)})
            continue
        placed.append({"symbol": r["symbol"], "side": r["side"], "qty": qty, "replayed": res["replayed"]})
        busy.add(r["symbol"])
        slots -= 1
    return {"asof": o["asof"], "placed": placed, "skipped": skipped}
