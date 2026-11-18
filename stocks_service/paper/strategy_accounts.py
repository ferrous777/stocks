"""One paper account per registered strategy version (the ensemble included), each trading only its
own strategy's signals.

``ensure_strategy_accounts`` runs on every tick, so a strategy added to the library gets its paper
account on the first tick after it is deployed. Each account copies the baseline account's capital,
risk profile and cost profile, so all rule-based paper accounts face the same limits and costs; it
starts trading with the session after it is created.

``strategy_v1`` policy: after each outlook, take the rows where this strategy signals the row's side
(and the row has an ATR plan), rank by signal strength, and fill free slots exactly as the baseline
does (same sizing, same risk limits, entries only at the limit). A paused or retired version places
no new entries (pausing cancels its orders whose session has not opened); its open
positions keep their exits.
"""

from __future__ import annotations

import datetime as dt

from pymongo.database import Database

from ..strategies import all_specs
from . import baseline
from .broker import create_paper_account

POLICY_ID = "strategy_v1@1"
NO_NEW_ENTRIES = ("paused", "retired")


def account_id_for(strategy_key: str) -> str:
    name, version = strategy_key.split("@")
    return f"paper-{name.replace('_', '-')}-v{version}"


def _template(db: Database) -> tuple[dict | None, str | None]:
    bases = list(db.accounts.find({"kind": "paper", "policy": baseline.POLICY_ID}).sort("_id", 1).limit(2))
    if not bases:
        return None, "no baseline paper account to copy capital, risk and cost profiles from"
    if len(bases) > 1:
        return None, "more than one baseline paper account; capital and profiles are ambiguous"
    return bases[0], None


def ensure_strategy_accounts(db: Database, now: dt.datetime) -> dict:
    """Create the missing per-strategy paper accounts. Idempotent. A strategy whose account cannot be
    created (e.g. its id is taken by another account) is reported in ``failed`` and the others are
    still provisioned; it never raises, so the tick goes on to process every existing paper account."""
    tpl, why = _template(db)
    if tpl is None:
        return {"created": [], "failed": [], "reason": why}
    created, failed = [], []
    for spec in all_specs():
        if db.accounts.find_one({"kind": "paper", "policy": POLICY_ID, "strategy": spec.key}, {"_id": 1}):
            continue
        aid = account_id_for(spec.key)
        try:
            create_paper_account(db, account_id=aid, name=f"Strategy: {spec.key}",
                                 starting_cash=tpl["starting_cash"], risk_profile=tpl["risk_profile"],
                                 cost_profile=tpl["cost_profile"], policy=POLICY_ID, strategy=spec.key, now=now)
        except Exception as e:  # noqa: BLE001  (reported per strategy; one failure must not block the rest)
            if db.accounts.find_one({"_id": aid, "kind": "paper", "policy": POLICY_ID, "strategy": spec.key}):
                continue   # created concurrently by another tick
            failed.append({"strategy": spec.key, "account_id": aid, "error": f"{type(e).__name__}: {e}"})
            continue
        created.append(spec.key)
    return {"created": created, "failed": failed}


def run_strategy(db: Database, account_id: str, now: dt.datetime) -> dict:
    acc = db.accounts.find_one({"_id": account_id})
    if acc is None or not acc.get("strategy"):
        return {"placed": [], "reason": "not a strategy paper account"}
    key = acc["strategy"]
    version = db.strategy_versions.find_one({"_id": key}, {"status": 1}) or {}
    if version.get("status") in NO_NEW_ENTRIES:
        return {"placed": [], "reason": f"{key} is {version['status']}; no new entries"}

    def pick(o: dict, busy: set[str]) -> list[dict]:
        cands = []
        for r in o["rows"]:
            sig = next((s for s in r.get("signals") or [] if s["strategy"] == key), None)
            if sig is not None and r.get("plan") and r["symbol"] not in busy:
                cands.append((sig["strength"], r))
        cands.sort(key=lambda x: (-x[0], x[1]["symbol"], x[1]["side"]))
        return [r for _, r in cands]

    # decided_by.strategy lets lifecycle.pause cancel these entries even when the row's estimate came
    # from the base rate or another strategy (orders' ``source`` records the estimate, not the decider).
    return baseline.place_ranked(db, account_id, now, pick=pick, decided_by={"policy": POLICY_ID, "strategy": key},
                                 key_prefix=f"strategy:{key}")
