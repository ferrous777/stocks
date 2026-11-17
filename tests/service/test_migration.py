import datetime as dt
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from stocks_service import ingestion, migration

from .conftest import FIXTURES, NOW

UTC = dt.timezone.utc
REPO = Path(__file__).resolve().parents[2]


def test_universe_includes_yaml_symbols_and_requested_additions():
    symbols, groups = migration.build_universe(REPO / "config" / "system_config.yaml")
    by = {s.symbol: s for s in symbols}
    for sym in ("MU", "QQQM", "FCX", "GLD", "SPY", "NVDA", "NEM"):
        assert sym in by
    assert by["FZROX"].asset_class.value == "mutual_fund"
    assert by["SPY"].asset_class.value == "etf" and by["SPY"].groups == []
    assert by["NEM"].groups == ["gold"]
    assert "gold" in groups and "etf" not in groups


def test_apply_universe_is_idempotent_and_never_overwrites(db):
    symbols, groups = migration.build_universe(REPO / "config" / "system_config.yaml")
    first = migration.apply_universe(db, symbols, groups)
    db.symbols.update_one({"_id": "NVDA"}, {"$set": {"priority": 3}})
    second = migration.apply_universe(db, symbols, groups)
    assert len(first["inserted"]) == len(symbols) and second["inserted"] == []
    assert db.symbols.find_one({"_id": "NVDA"})["priority"] == 3


def _ingest_nvda(db, fetcher):
    migration.apply_universe(db, *migration.build_universe(REPO / "config" / "system_config.yaml"))
    ingestion.verify_basis(db, fetcher, interval="1d", symbol="NVDA", split_ex_date=dt.date(2024, 6, 10), now=NOW)
    ingestion.ingest(db, fetcher, symbol="NVDA", interval="1d", start=dt.datetime(2024, 5, 1, tzinfo=UTC), now=NOW,
                     buffer=dt.timedelta(minutes=20), overlap_tolerance=0.005, gap_threshold=0.47)


def test_reconcile_legacy_cache_against_normalized_bars(db, fetcher):
    _ingest_nvda(db, fetcher)
    report = migration.reconcile_cache(db, FIXTURES / "legacy" / "cache_files")
    r = report["NVDA"]
    assert (r["status"], r["overlap"], r["mismatches"]) == ("ok", 51, 0)
    assert r["max_rel_diff"] < 1e-6


def test_reconcile_detects_disagreement(db, fetcher, tmp_path):
    _ingest_nvda(db, fetcher)
    src = json.loads((FIXTURES / "legacy" / "cache_files" / "NVDA_historical.json").read_text())
    src["data_points"][3]["close"] *= 1.05
    (tmp_path / "NVDA_historical.json").write_text(json.dumps(src))
    r = migration.reconcile_cache(db, tmp_path)["NVDA"]
    assert r["status"] == "mismatch" and r["mismatches"] == 1


def test_reconcile_sqlite_snapshots(db, fetcher, tmp_path):
    _ingest_nvda(db, fetcher)
    pts = json.loads((FIXTURES / "legacy" / "cache_files" / "NVDA_historical.json").read_text())["data_points"]
    path = tmp_path / "timeseries.db"
    con = sqlite3.connect(path)
    con.execute("create table daily_snapshots (symbol text, date text, data text)")
    con.executemany("insert into daily_snapshots values (?,?,?)",
                    [("NVDA", p["date"], json.dumps({**p, "symbol": "NVDA"})) for p in pts])
    con.commit()
    con.close()
    r = migration.reconcile_sqlite(db, path)["NVDA"]
    assert (r["status"], r["overlap"]) == ("ok", 51)


@pytest.mark.parametrize("name,kind,symbol", [
    ("AAPL_recommendations_20260420.json", "recommendations", "AAPL"),
    ("AAPL_backtest_20260420.json", "backtest", "AAPL"),
    ("NVDA_backtest_trend_following_30d_20260420.json", "backtest_period", "NVDA"),
    ("recommendations_20260420.json", "combined_recommendations", None),
    ("notes.json", "unrecognized", None),
])
def test_classify_result_file(name, kind, symbol):
    meta = migration.classify_result_file(name)
    assert (meta["kind"], meta["symbol"]) == (kind, symbol)


def test_import_legacy_results_records_errors(db, tmp_path):
    shutil.copy(FIXTURES / "legacy" / "result_files" / "AAPL_recommendations_20260420.json", tmp_path)
    (tmp_path / "AAPL_backtest_20260421.json").write_text("{not json")
    res = migration.import_legacy_results(db, tmp_path)
    assert res["imported"] == {"recommendations": 1}
    assert res["errors"][0]["file"] == "AAPL_backtest_20260421.json"
    doc = db.legacy_recommendations.find_one({"_id": "AAPL_recommendations_20260420.json"})
    assert doc["payload"]["recommendations"]["action"] == "HOLD"
    assert doc["date"] == dt.datetime(2026, 4, 20, tzinfo=UTC)
