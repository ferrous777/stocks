"""
Plaid API client factory.

Credentials are resolved in priority order:
  1. Environment variables  (PLAID_CLIENT_ID, PLAID_SECRET, PLAID_FERNET_KEY)
  2. system_config.yaml     (plaid.client_id, plaid.secret, plaid.fernet_key)

The Fernet key is used to encrypt/decrypt access tokens before storing them in the DB.
Never persist a raw access_token in any file, log, or config.
"""
import os
import logging
from typing import Optional

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy import of plaid SDK so that missing package gives a clear error only
# when the client is actually constructed, not at import time.
# ---------------------------------------------------------------------------
def _get_plaid_api():
    try:
        import plaid
        from plaid.api import plaid_api
        from plaid.model.link_token_create_request import LinkTokenCreateRequest
        from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
        from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
        from plaid.model.investments_holdings_get_request import InvestmentsHoldingsGetRequest
        from plaid.model.investments_transactions_get_request import InvestmentsTransactionsGetRequest
        return plaid, plaid_api, (
            LinkTokenCreateRequest,
            LinkTokenCreateRequestUser,
            ItemPublicTokenExchangeRequest,
            InvestmentsHoldingsGetRequest,
            InvestmentsTransactionsGetRequest,
        )
    except ImportError as exc:
        raise ImportError(
            "plaid-python not installed. Run: pip install plaid-python"
        ) from exc


_ENVIRONMENTS = {
    "sandbox": "https://sandbox.plaid.com",
    "development": "https://development.plaid.com",
    "production": "https://production.plaid.com",
}


class PlaidClientWrapper:
    """
    Thin wrapper around the plaid-python API client.
    Handles configuration resolution, environment selection, and token crypto.
    """

    def __init__(self, client_id: str, secret: str, environment: str, fernet_key: str):
        plaid, plaid_api, _ = _get_plaid_api()

        host = _ENVIRONMENTS.get(environment.lower())
        if not host:
            raise ValueError(f"Unknown Plaid environment: {environment!r}. "
                             f"Use one of: {list(_ENVIRONMENTS.keys())}")

        configuration = plaid.Configuration(
            host=host,
            api_key={"clientId": client_id, "secret": secret},
        )
        api_client = plaid.ApiClient(configuration)
        self.api = plaid_api.PlaidApi(api_client)
        self.environment = environment

        # Fernet cipher for access-token encryption/decryption
        key_bytes = fernet_key.encode() if isinstance(fernet_key, str) else fernet_key
        self.cipher = Fernet(key_bytes)

    # ------------------------------------------------------------------
    # Token helpers
    # ------------------------------------------------------------------
    def encrypt_token(self, access_token: str) -> str:
        return self.cipher.encrypt(access_token.encode()).decode()

    def decrypt_token(self, encrypted_token: str) -> str:
        return self.cipher.decrypt(encrypted_token.encode()).decode()

    # ------------------------------------------------------------------
    # Link Token (Plaid Link flow — step 1)
    # ------------------------------------------------------------------
    def create_link_token(self, user_id: str, client_name: str = "Stock Analyzer") -> str:
        """Create a Link Token to initialise Plaid Link in the browser."""
        _, _, models = _get_plaid_api()
        (LinkTokenCreateRequest, LinkTokenCreateRequestUser,
         ItemPublicTokenExchangeRequest, _, _) = models

        request = LinkTokenCreateRequest(
            user=LinkTokenCreateRequestUser(client_user_id=user_id),
            client_name=client_name,
            products=["investments"],
            country_codes=["US"],
            language="en",
        )
        response = self.api.link_token_create(request)
        return response["link_token"]

    # ------------------------------------------------------------------
    # Public-token exchange (step 2 after user completes Plaid Link)
    # ------------------------------------------------------------------
    def exchange_public_token(self, public_token: str) -> dict:
        """Exchange public_token for access_token + item_id."""
        _, _, models = _get_plaid_api()
        (_, _, ItemPublicTokenExchangeRequest, _, _) = models

        request = ItemPublicTokenExchangeRequest(public_token=public_token)
        response = self.api.item_public_token_exchange(request)
        return {
            "access_token": response["access_token"],
            "item_id": response["item_id"],
        }

    # ------------------------------------------------------------------
    # Holdings
    # ------------------------------------------------------------------
    def get_holdings(self, access_token: str) -> dict:
        """Return raw /investments/holdings/get response dict."""
        _, _, models = _get_plaid_api()
        (_, _, _, InvestmentsHoldingsGetRequest, _) = models

        request = InvestmentsHoldingsGetRequest(access_token=access_token)
        response = self.api.investments_holdings_get(request)
        return response.to_dict()

    # ------------------------------------------------------------------
    # Investment transactions
    # ------------------------------------------------------------------
    def get_investment_transactions(self, access_token: str,
                                    start_date, end_date) -> dict:
        """Return raw /investments/transactions/get response dict."""
        _, _, models = _get_plaid_api()
        (_, _, _, _, InvestmentsTransactionsGetRequest) = models

        request = InvestmentsTransactionsGetRequest(
            access_token=access_token,
            start_date=start_date,
            end_date=end_date,
        )
        response = self.api.investments_transactions_get(request)
        return response.to_dict()


# ---------------------------------------------------------------------------
# Singleton factory — called once per process
# ---------------------------------------------------------------------------
_client_instance: Optional[PlaidClientWrapper] = None


def get_plaid_client(config=None) -> PlaidClientWrapper:
    """
    Return the singleton PlaidClientWrapper.

    Parameters
    ----------
    config:
        A PlaidConfig dataclass instance (from config_manager).
        If omitted, the function reads environment variables directly.
    """
    global _client_instance
    if _client_instance is not None:
        return _client_instance

    if config is not None:
        client_id = config.client_id
        secret = config.secret
        environment = config.environment
        fernet_key = config.fernet_key
    else:
        client_id = os.environ.get("PLAID_CLIENT_ID")
        secret = os.environ.get("PLAID_SECRET")
        environment = os.environ.get("PLAID_ENVIRONMENT", "sandbox")
        fernet_key = os.environ.get("PLAID_FERNET_KEY")

    missing = [k for k, v in {"PLAID_CLIENT_ID": client_id, "PLAID_SECRET": secret,
                               "PLAID_FERNET_KEY": fernet_key}.items() if not v]
    if missing:
        raise RuntimeError(
            f"Plaid credentials not configured: {', '.join(missing)}. "
            "Set them as environment variables or in config/system_config.yaml."
        )

    _client_instance = PlaidClientWrapper(
        client_id=client_id,
        secret=secret,
        environment=environment,
        fernet_key=fernet_key,
    )
    logger.info(f"Plaid client initialised (environment={environment})")
    return _client_instance


def generate_fernet_key() -> str:
    """Helper: generate a new Fernet key to store as PLAID_FERNET_KEY env var."""
    return Fernet.generate_key().decode()
