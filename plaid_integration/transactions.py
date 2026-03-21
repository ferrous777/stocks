"""
Sync investment transactions from Plaid into the local database.

Returns all NEW transactions seen since the last sync so the alert engine
can evaluate them (e.g. a trade that matches an active recommendation).
"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# Default look-back window when syncing transactions
DEFAULT_LOOKBACK_DAYS = 30


def sync_transactions(db, plaid_client, lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> List[Dict[str, Any]]:
    """
    Pull investment transactions for all stored Plaid Items.

    Parameters
    ----------
    db:             TimeSeriesDB instance
    plaid_client:   PlaidClientWrapper instance
    lookback_days:  How many calendar days back to fetch transactions

    Returns
    -------
    List of newly-stored transaction dicts (those not already in the DB).
    """
    from datetime import date as date_type

    items = db.get_plaid_items()
    if not items:
        logger.info("No Plaid items stored — skipping transaction sync.")
        return []

    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=lookback_days)

    new_transactions: List[Dict[str, Any]] = []

    for item in items:
        access_token = plaid_client.decrypt_token(item["access_token_encrypted"])
        try:
            data = plaid_client.get_investment_transactions(
                access_token, start_date=start_date, end_date=end_date
            )
        except Exception as exc:
            logger.error(f"Failed to fetch transactions for item {item['item_id']}: {exc}")
            continue

        # Build security_id → ticker map
        securities = {s["security_id"]: s for s in data.get("securities", [])}

        for tx in data.get("investment_transactions", []):
            transaction_id = tx.get("investment_transaction_id")
            account_id = tx.get("account_id")
            security_id = tx.get("security_id")
            security = securities.get(security_id, {})
            symbol = (security.get("ticker_symbol") or "").upper().strip() or None
            tx_date = tx.get("date")
            tx_type = tx.get("type")
            quantity = tx.get("quantity")
            price = tx.get("price")
            amount = tx.get("amount")
            fees = tx.get("fees") or 0.0

            was_new = _store_if_new(
                db, transaction_id, account_id, symbol,
                tx_date, tx_type, quantity, price, amount, fees
            )
            if was_new:
                new_transactions.append({
                    "transaction_id": transaction_id,
                    "account_id": account_id,
                    "symbol": symbol,
                    "date": tx_date,
                    "type": tx_type,
                    "quantity": quantity,
                    "price": price,
                    "amount": amount,
                })

    logger.info(
        f"Transaction sync complete: {len(new_transactions)} new transaction(s) "
        f"over {lookback_days}-day window"
    )
    return new_transactions


def _store_if_new(db, transaction_id, account_id, symbol, date, type_,
                  quantity, price, amount, fees) -> bool:
    """
    Attempt to store the transaction. Returns True if it was genuinely new
    (not already present), False otherwise (INSERT OR IGNORE skips duplicates).
    """
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) as cnt FROM investment_transactions WHERE transaction_id = ?",
                (transaction_id,)
            )
            already_exists = cursor.fetchone()["cnt"] > 0

        if already_exists:
            return False

        db.upsert_investment_transaction(
            transaction_id=transaction_id,
            account_id=account_id,
            symbol=symbol,
            date=date,
            type_=type_,
            quantity=quantity,
            price=price,
            amount=amount,
            fees=fees,
        )
        return True
    except Exception as e:
        logger.error(f"Error storing transaction {transaction_id}: {e}")
        return False
