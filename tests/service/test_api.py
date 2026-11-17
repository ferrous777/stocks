import datetime as dt

import pytest
from fastapi.testclient import TestClient

from stocks_service import ingestion
from stocks_service.api.app import create_app
from stocks_service.settings import Settings

from .conftest import NOW

KEY = "test-key-123"
H = {"X-API-Key": KEY}


@pytest.fixture
def client(db, fetcher):
    settings = Settings(mongo_url="mongodb://unused", api_keys=KEY)
    with TestClient(create_app(settings, db=db, fetcher=fetcher)) as c:
        yield c


def test_app_refuses_to_start_without_api_keys(db):
    with pytest.raises(RuntimeError, match="API_KEYS"):
        create_app(Settings(mongo_url="mongodb://unused", api_keys=""), db=db)


def test_requests_without_valid_key_are_rejected(client):
    assert client.get("/api/v1/symbols").status_code == 401
    assert client.get("/api/v1/symbols", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/api/v1/symbols", headers=H).status_code == 200


def test_health_reports_replica_set(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["replica_set"]


def test_symbol_and_group_lifecycle(client):
    assert client.post("/api/v1/symbols", headers=H, json={"symbol": "NEM", "asset_class": "equity",
                                                           "groups": ["gold"]}).status_code == 422
    assert client.put("/api/v1/groups/gold", headers=H, json={"name": "Gold"}).status_code == 200
    r = client.post("/api/v1/symbols", headers=H, json={"symbol": "NEM", "asset_class": "equity", "groups": ["gold"],
                                                        "factors": [{"symbol": "GLD", "relation": "driver"}]})
    assert r.status_code == 201 and r.json()["shortable"] is False
    assert client.post("/api/v1/symbols", headers=H, json={"symbol": "NEM", "asset_class": "equity"}).status_code == 409
    assert client.get("/api/v1/groups/gold", headers=H).json()["members"] == ["NEM"]
    assert client.delete("/api/v1/groups/gold", headers=H).status_code == 409
    r = client.patch("/api/v1/symbols/NEM", headers=H, json={"groups": [], "priority": 2})
    assert r.json()["groups"] == [] and r.json()["priority"] == 2
    assert client.delete("/api/v1/groups/gold", headers=H).status_code == 204
    assert client.post("/api/v1/symbols", headers=H, json={"symbol": "bad lower", "asset_class": "equity"}).status_code == 422


def test_backfill_requires_verified_basis_then_serves_both_bases(client, db, fetcher):
    client.post("/api/v1/symbols", headers=H, json={"symbol": "NVDA", "asset_class": "equity"})
    r = client.post("/api/v1/symbols/NVDA/backfill?interval=1d&start=2024-05-01", headers=H)
    assert r.status_code == 409 and "not been verified" in r.json()["detail"]
    ingestion.verify_basis(db, fetcher, interval="1d", symbol="NVDA", split_ex_date=dt.date(2024, 6, 10), now=NOW)
    r = client.post("/api/v1/symbols/NVDA/backfill?interval=1d&start=2024-05-01", headers=H)
    assert r.status_code == 200 and r.json()["upserted"] == 51
    raw = client.get("/api/v1/bars/NVDA?start=2024-06-07&end=2024-06-10", headers=H).json()
    assert [round(b["c"], 2) for b in raw] == [1208.88, 121.79]
    adj = client.get("/api/v1/bars/NVDA?start=2024-06-07&end=2024-06-10&basis=split_adjusted", headers=H).json()
    assert [round(b["c"], 3) for b in adj] == [120.888, 121.79]
    pit = client.get("/api/v1/bars/NVDA?start=2024-06-07&end=2024-06-07&basis=split_adjusted&asof=2024-06-07",
                     headers=H).json()
    assert round(pit[0]["c"], 2) == 1208.88
    cas = client.get("/api/v1/corporate-actions/NVDA", headers=H).json()
    assert {c["type"] for c in cas} == {"split", "dividend"}


def test_quarantine_clear_requires_note(client, db):
    client.post("/api/v1/symbols", headers=H, json={"symbol": "NVDA", "asset_class": "equity"})
    assert client.post("/api/v1/symbols/NVDA/quarantine/clear?note=reviewed", headers=H).status_code == 409
    db.symbols.update_one({"_id": "NVDA"}, {"$set": {"quarantine": {"reason": "unexplained_gap", "details": {},
                                                                     "detected_at": NOW}}})
    assert client.post("/api/v1/symbols/NVDA/quarantine/clear?note=x", headers=H).status_code == 422
    r = client.post("/api/v1/symbols/NVDA/quarantine/clear?note=verified%20halt", headers=H)
    assert r.status_code == 200 and "quarantine" not in r.json()
    assert r.json()["quarantine_history"][0]["note"] == "verified halt"


@pytest.mark.parametrize("field", ["groups", "enabled", "asset_class", "factors", "tradable", "priority", "shortable"])
def test_patch_rejects_explicit_null_for_required_fields(client, field):
    client.post("/api/v1/symbols", headers=H, json={"symbol": "NVDA", "asset_class": "equity"})
    r = client.patch("/api/v1/symbols/NVDA", headers=H, json={field: None})
    assert r.status_code == 422 and "cannot be null" in r.text
    assert client.get("/api/v1/symbols/NVDA", headers=H).json()["asset_class"] == "equity"


def test_patch_can_clear_nullable_fields_and_validates_groups(client):
    client.post("/api/v1/symbols", headers=H, json={"symbol": "NVDA", "asset_class": "equity", "name": "Nvidia",
                                                    "sector": "Technology"})
    r = client.patch("/api/v1/symbols/NVDA", headers=H, json={"name": None, "sector": None})
    assert r.status_code == 200 and r.json()["name"] is None and r.json()["sector"] is None
    assert client.patch("/api/v1/symbols/NVDA", headers=H, json={"groups": ["Bad Slug"]}).status_code == 422


def test_admin_load_runs_steps_and_records_progress(client, db, fetcher):
    import time
    r = client.post("/api/v1/admin/load", headers=H, json={"steps": ["bogus"]})
    assert r.status_code == 422
    assert client.post("/api/v1/admin/load", json={"steps": ["init"]}).status_code == 401
    r = client.post("/api/v1/admin/load", headers=H,
                    json={"steps": ["init", "universe", "verify_1d", "data_symbols", "backfill_1d"], "symbols": ["NVDA"]})
    assert r.status_code == 202
    url = r.json()["status_url"]
    for _ in range(100):
        job = client.get(url, headers=H).json()
        if job["status"] != "running":
            break
        time.sleep(0.1)
    assert job["status"] == "completed", job
    assert db.symbols.count_documents({}) >= 51 and db.symbols.find_one({"_id": "^IRX"})["tradable"] is False
    assert db.bars.count_documents({"symbol": "NVDA", "interval": "1d"}) == 51
    assert any(p.get("step") == "verify_1d" and p.get("price_basis") == "split_adjusted" for p in job["progress"])
    assert client.get("/api/v1/admin/jobs/notanid", headers=H).status_code == 404


def test_clearing_a_gap_quarantine_records_the_accepted_gap(client, db):
    client.post("/api/v1/symbols", headers=H, json={"symbol": "AAPL", "asset_class": "equity"})
    db.symbols.update_one({"_id": "AAPL"}, {"$set": {"quarantine": {
        "reason": "unexplained_gap", "details": {"session": "2000-09-29", "log_gap": -0.64}, "detected_at": NOW}}})
    r = client.post("/api/v1/symbols/AAPL/quarantine/clear?note=real%20crash%20on%20profit%20warning", headers=H)
    assert r.status_code == 200 and r.json()["accepted_gaps"] == ["2000-09-29"]
