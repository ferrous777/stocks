"""
Sync Plaid accounts and investment holdings into the local database.

Key responsibilities
--------------------
1. Fetch accounts and holdings from Plaid's /investments/holdings/get endpoint.
2. Upsert plaid_accounts + portfolio_positions in the DB.
3. On first detection of a new equity position, snapshot the current recommendation
   so that future drift-detection has an anchor.
4. Auto-add newly-detected equity tickers to system_config.yaml if the
   plaid.auto_add_symbols flag is set (default: true).

Returned value
--------------
A dict with keys:
    accounts    -- list of synced account dicts
    positions   -- list of synced position dicts
    new_symbols -- list of symbols added to config during this sync
"""
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Security types considered "equity" for symbol-tracking purposes
_EQUITY_TYPES = {"equity", "etf", "mutual fund", "etf", "fixed income"}


def sync_accounts(db, plaid_client, config_manager=None) -> Dict[str, Any]:
    """
    Pull the latest holdings from every stored Plaid Item and upsert into the DB.

    Parameters
    ----------
    db:             TimeSeriesDB instance
    plaid_client:   PlaidClientWrapper instance (from plaid_client.get_plaid_client())
    config_manager: Optional ConfigManager — used to auto-add new symbols
    """
    items = db.get_plaid_items()
    if not items:
        logger.info("No Plaid items stored yet. Complete the Link flow first.")
        return {"accounts": [], "positions": [], "new_symbols": []}

    synced_accounts: List[Dict] = []
    synced_positions: List[Dict] = []
    new_symbols: List[str] = []

    for item in items:
        access_token = plaid_client.decrypt_token(item["access_token_encrypted"])
        try:
            data = plaid_client.get_holdings(access_token)
        except Exception as exc:
            logger.error(f"Failed to fetch holdings for item {item['item_id']}: {exc}")
            continue

        # ── Accounts ──────────────────────────────────────────────────────
        accounts_map: Dict[str, dict] = {}
        for acct in data.get("accounts", []):
            account_id = acct["account_id"]
            balances = acct.get("balances", {})
            db.upsert_plaid_account(
                account_id=account_id,
                item_id=item["item_id"],
                name=acct.get("name"),
                type_=acct.get("type"),
                subtype=acct.get("subtype"),
                balance_current=balances.get("current"),
                balance_available=balances.get("available"),
            )
            accounts_map[account_id] = acct
            synced_accounts.append(acct)

        # ── Securities map: security_id → security_details ────────────────
        securities: Dict[str, dict] = {
            s["security_id"]: s for s in data.get("securities", [])
        }

        # ── Holdings ──────────────────────────────────────────────────────
        # Resolve which symbols are already being tracked
        existing_tracked = set()
        if config_manager:
            existing_tracked = {s.symbol for s in config_manager.get_config().symbols}

        for holding in data.get("holdings", []):
            security_id = holding.get("security_id")
            security = securities.get(security_id, {})
            symbol = security.get("ticker_symbol") or security.get("name", "UNKNOWN")
            symbol = symbol.upper().strip()
            account_id = holding.get("account_id")

            if not symbol or symbol == "UNKNOWN":
                continue

            # Retrieve any existing recommendation snapshot for this symbol
            # (used as drift anchor on first detection)
            entry_rec = _get_latest_recommendation_snapshot(db, symbol)

            db.upsert_portfolio_position(
                account_id=account_id,
                symbol=symbol,
                quantity=holding.get("quantity", 0),
                cost_basis=holding.get("cost_basis"),
                institution_price=holding.get("institution_price"),
                institution_value=holding.get("institution_value"),
                entry_rec_snapshot=entry_rec,
            )
            synced_positions.append({"symbol": symbol, "account_id": account_id, "quantity": holding.get("quantity")})

            # Auto-add to config if it's an equity-type security not already tracked
            security_type = (security.get("type") or "").lower()
            if (config_manager and
                    symbol not in existing_tracked and
                    security_type in _EQUITY_TYPES):
                cfg = config_manager.get_config()
                priority = getattr(cfg.plaid, "auto_add_priority", 2)
                sector = security.get("sector") or _infer_sector(security)
                added = config_manager.add_symbol(symbol, sector=sector, priority=priority)
                if added:
                    new_symbols.append(symbol)
                    existing_tracked.add(symbol)
                    logger.info(f"Auto-added {symbol} from Plaid holdings (sector={sector})")

    # Update last_synced_at timestamps
    for item in items:
        _update_last_synced(db, item["item_id"])

    logger.info(
        f"Plaid sync complete: {len(synced_accounts)} accounts, "
        f"{len(synced_positions)} positions, {len(new_symbols)} new symbols"
    )
    return {
        "accounts": synced_accounts,
        "positions": synced_positions,
        "new_symbols": new_symbols,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _get_latest_recommendation_snapshot(db, symbol: str) -> Optional[dict]:
    """
    Pull the most recent prediction row from the DB for a symbol and
    return it as a plain dict, or None if unavailable.
    Used to snapshot what the model said *when* the position was first detected.
    """
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT data FROM projections
                WHERE symbol = ?
                ORDER BY projection_date DESC
                LIMIT 1
            """, (symbol,))
            row = cursor.fetchone()
            if row:
                import json
                return json.loads(row["data"])
    except Exception as e:
        logger.debug(f"No recommendation snapshot found for {symbol}: {e}")
    return None


def _update_last_synced(db, item_id: str):
    try:
        now = datetime.now().isoformat()
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE plaid_items SET last_synced_at = ? WHERE item_id = ?",
                (now, item_id)
            )
            conn.commit()
    except Exception as e:
        logger.warning(f"Could not update last_synced_at for item {item_id}: {e}")


def _infer_sector(security: dict) -> Optional[str]:
    """Best-effort sector from the security dict."""
    return security.get("sector") or security.get("industry") or None
