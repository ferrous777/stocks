"""The new package must coexist with the legacy Flask ``app.py`` during the parallel run."""

import importlib

import pytest

from stocks_service.db import ReplicaSetRequired, require_replica_set


def test_legacy_app_and_new_service_import_side_by_side():
    legacy = importlib.import_module("app")
    assert hasattr(legacy, "app") and legacy.app.__class__.__name__ == "Flask"
    new = importlib.import_module("stocks_service.api.app")
    assert callable(new.create_app)


class _StandaloneAdmin:
    def command(self, name):
        assert name == "hello"
        return {"isWritablePrimary": True}  # no setName: standalone


class _StandaloneClient:
    admin = _StandaloneAdmin()


def test_standalone_mongo_is_rejected():
    with pytest.raises(ReplicaSetRequired):
        require_replica_set(_StandaloneClient())
