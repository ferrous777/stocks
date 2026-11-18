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
from ..accounts.risk import RiskProfile, avg_dollar_volume, cluster_keys, size_ticket
from ..accounts.service import AccountError, ledger_state
from ..outlook.build import latest_outlook
from ..research.series import SymbolSeries
from .broker import OPEN_STATUSES, account_book, place_order

POLICY_ID = "baseline_v1@1"
MAX_POSITIONS = 10


def run_baseline(db: Database, account_id: str, now: dt.datetime) -> dict:
    acc = db.accounts.find_one({"_id": account_id})
    o = latest_outlook(db)
    if acc is None or o is None:
        return {"placed": [], "reason": "no account or outlook"}
    if now >= dt.datetime.fromisoformat(o["placeable_until"]):
        return {"placed": [], "reason": "placement window closed"}
    st = ledger_state(db, account_id, now)
    busy = {s for s, h in st.holdings.items() if abs(h.qty) > QTY_TOL}
    busy |= {x["symbol"] for x in db.orders.find({"account_id": account_id, "status": {"$in": list(OPEN_STATUSES)}})}
    slots = MAX_POSITIONS - len(busy)
    cands = [r for r in o["rows"] if r.get("plan") and r.get("exp_excess_6m") is not None and r["exp_excess_6m"] > 0
             and r["symbol"] not in busy]
    cands.sort(key=lambda r: (-r["exp_return_6m"], r["symbol"], r["side"]))
    profile = RiskProfile.from_doc(db.risk_profiles.find_one({"_id": acc["risk_profile"]}))
    placed, skipped = [], []
    for r in cands:
        if slots <= 0:
            break
        if r["symbol"] in busy:
            continue
        book, _ = account_book(db, acc, now, profile=profile)
        groups = (db.symbols.find_one({"_id": r["symbol"]}, {"groups": 1}) or {}).get("groups", [])
        qty, why, _ = size_ticket(r, book, profile, keys=cluster_keys(r["symbol"], {r["symbol"]: groups}, {}),
                                  adv_usd=avg_dollar_volume(SymbolSeries.from_db(db, r["symbol"]),
                                                            dt.date.fromisoformat(o["asof"])),
                                  shortable=True)
        if qty < 1:
            skipped.append({"symbol": r["symbol"], "side": r["side"], "reason": why[0]})
            continue
        try:
            res = place_order(db, account_id, symbol=r["symbol"], side=r["side"], qty=qty,
                              idempotency_key=f"baseline:{o['asof']}:{r['symbol']}:{r['side']}",
                              decided_by={"policy": POLICY_ID}, now=now)
        except AccountError as e:
            skipped.append({"symbol": r["symbol"], "side": r["side"], "reason": str(e)})
            continue
        placed.append({"symbol": r["symbol"], "side": r["side"], "qty": qty, "replayed": res["replayed"]})
        busy.add(r["symbol"])
        slots -= 1
    return {"asof": o["asof"], "placed": placed, "skipped": skipped}
