"""MongoDB connection handling.

The ledger relies on multi-document transactions, which MongoDB only supports on
replica sets (a single-node replica set is fine). Connecting to a standalone
server is therefore an error, not a warning.
"""

from __future__ import annotations

from pymongo import MongoClient
from pymongo.database import Database


class ReplicaSetRequired(RuntimeError):
    """Raised when the configured MongoDB deployment cannot run transactions."""


def connect(mongo_url: str, *, server_selection_timeout_ms: int = 5000) -> MongoClient:
    client: MongoClient = MongoClient(
        mongo_url,
        tz_aware=True,
        serverSelectionTimeoutMS=server_selection_timeout_ms,
    )
    require_replica_set(client)
    return client


def require_replica_set(client: MongoClient) -> str:
    hello = client.admin.command("hello")
    set_name = hello.get("setName")
    if not set_name:
        raise ReplicaSetRequired(
            "MongoDB is running standalone. Transactions require a replica set: start mongod "
            "with --replSet <name> and run rs.initiate() (a single-node replica set is enough)."
        )
    return set_name


def get_database(client: MongoClient, name: str) -> Database:
    return client.get_database(name)
