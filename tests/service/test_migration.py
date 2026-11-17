import datetime as dt
import json
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


def test_reconcile_cli_fails_when_no_legacy_input_exists(db, tmp_path, monkeypatch, capsys):
    from stocks_service import cli
    from stocks_service.settings import get_settings
    from .conftest import DEFAULT_URL
    import os
    monkeypatch.setenv("STOCKS_MONGO_URL", os.environ.get("STOCKS_TEST_MONGO_URL", DEFAULT_URL))
    monkeypatch.setenv("STOCKS_MONGO_DB", db.name)
    get_settings.cache_clear()
    (tmp_path / "empty_cache").mkdir()
    try:
        rc = cli.main(["reconcile-legacy", "--cache-dir", str(tmp_path / "empty_cache"),
                       "--sqlite", str(tmp_path / "missing.db")])
    finally:
        get_settings.cache_clear()
    assert rc == 2
    assert "nothing was reconciled" in capsys.readouterr().err
    assert db.migration_reports.count_documents({}) == 0


def test_reconcile_cli_reports_when_legacy_input_exists(db, fetcher, monkeypatch):
    from stocks_service import cli
    from stocks_service.settings import get_settings
    from .conftest import DEFAULT_URL
    import os
    _ingest_nvda(db, fetcher)
    monkeypatch.setenv("STOCKS_MONGO_URL", os.environ.get("STOCKS_TEST_MONGO_URL", DEFAULT_URL))
    monkeypatch.setenv("STOCKS_MONGO_DB", db.name)
    get_settings.cache_clear()
    try:
        rc = cli.main(["reconcile-legacy", "--cache-dir", str(FIXTURES / "legacy" / "cache_files"),
                       "--sqlite", "/nonexistent.db"])
    finally:
        get_settings.cache_clear()
    assert rc == 0
    assert db.migration_reports.find_one({})["cache"]["NVDA"]["status"] == "ok"
