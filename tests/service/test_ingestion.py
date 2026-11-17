import datetime as dt

import pytest

from stocks_service import ingestion
from stocks_service.models import SymbolIn
from stocks_service.price_basis import Basis, to_raw
from stocks_service.yahoo import parse_chart

from .conftest import NOW, load_yahoo

UTC = dt.timezone.utc
START = dt.datetime(2024, 5, 1, tzinfo=UTC)


def _add_symbol(db, symbol, asset_class="equity"):
    doc = SymbolIn(symbol=symbol, asset_class=asset_class).model_dump(mode="json", exclude={"symbol"})
    db.symbols.insert_one({"_id": symbol, **doc, "ca_version": 0})


def _ingest(db, fetcher, symbol="NVDA", interval="1d", start=START):
    return ingestion.ingest(db, fetcher, symbol=symbol, interval=interval, start=start, now=NOW,
                            buffer=dt.timedelta(minutes=20), overlap_tolerance=0.005, gap_threshold=0.47)


def _verify(db, fetcher, interval="1d", symbol="NVDA", ex_date=dt.date(2024, 6, 10)):
    return ingestion.verify_basis(db, fetcher, interval=interval, symbol=symbol, split_ex_date=ex_date, now=NOW)


def test_ingest_refuses_unverified_basis(db, fetcher):
    _add_symbol(db, "NVDA")
    with pytest.raises(ingestion.BasisNotVerified):
        _ingest(db, fetcher)


def test_ingest_refuses_unknown_symbol(db, fetcher):
    _verify(db, fetcher)
    with pytest.raises(ingestion.UnknownSymbol):
        _ingest(db, fetcher, symbol="NVDA")


def test_verify_basis_records_per_interval_basis(db, fetcher):
    _verify(db, fetcher)
    _verify(db, fetcher, interval="1h", symbol="ORLY", ex_date=dt.date(2025, 6, 10))
    daily = db.price_sources.find_one({"_id": "yahoo_chart:1d"})
    hourly = db.price_sources.find_one({"_id": "yahoo_chart:1h"})
    assert (daily["price_basis"], daily["volume_basis"]) == ("split_adjusted", "split_adjusted")
    assert (hourly["price_basis"], hourly["volume_basis"]) == ("split_adjusted", "raw")
    assert hourly["verified_by"]["symbol"] == "ORLY" and hourly["verified_by"]["ratio"] == 15.0


def test_ingest_stores_raw_bars_and_corporate_actions(db, fetcher):
    _add_symbol(db, "NVDA")
    _verify(db, fetcher)
    res = _ingest(db, fetcher)
    assert res.fetched == 51 and res.upserted == 51 and res.new_corporate_actions == 2
    pre = db.bars.find_one({"symbol": "NVDA", "interval": "1d", "session": dt.datetime(2024, 6, 7, tzinfo=UTC)})
    assert pre["c"] == pytest.approx(1208.88, abs=0.01)
    assert pre["split_factor_applied"] == 10.0
    assert pre["ts"] == dt.datetime(2024, 6, 7, 13, 30, tzinfo=UTC)
    split = db.corporate_actions.find_one({"symbol": "NVDA", "type": "split"})
    assert split["ratio"] == 10.0 and split["ex_date"] == dt.datetime(2024, 6, 10, tzinfo=UTC)
    div = db.corporate_actions.find_one({"symbol": "NVDA", "type": "dividend"})
    assert div["amount_raw"] == pytest.approx(0.01) and div["amount_basis_verified"] is False
    assert db.symbols.find_one({"_id": "NVDA"})["ca_version"] == 1
    # The request always extends to `now` so that every split reflected in the source's adjustment is visible.
    assert fetcher.calls[-1][3] == int(NOW.timestamp())


def test_reingest_is_idempotent(db, fetcher):
    _add_symbol(db, "NVDA")
    _verify(db, fetcher)
    _ingest(db, fetcher)
    again = _ingest(db, fetcher)
    assert (again.upserted, again.revised, again.unchanged, again.new_corporate_actions) == (0, 0, 51, 0)
    assert db.bars.count_documents({"symbol": "NVDA"}) == 51


def test_overlap_mismatch_with_constant_ratio_quarantines(db, fetcher):
    _add_symbol(db, "NVDA")
    _verify(db, fetcher)
    _ingest(db, fetcher)
    # Stored bars disagree with the source by a constant factor, as if a split were unrecorded.
    db.bars.update_many({"symbol": "NVDA"}, {"$mul": {"c": 2.0}})
    with pytest.raises(ingestion.SymbolQuarantined):
        _ingest(db, fetcher)
    q = db.symbols.find_one({"_id": "NVDA"})["quarantine"]
    assert q["reason"] == "unrecorded_split_suspected"
    assert q["details"]["ratio"] == pytest.approx(0.5)
    with pytest.raises(ingestion.SymbolQuarantined):  # stays blocked until cleared
        _ingest(db, fetcher)


def test_gap_without_corporate_action_is_detected(db):
    parsed = parse_chart(load_yahoo("NVDA_1d_2024-05-01_2024-07-15"), symbol="NVDA", interval="1d",
                         window_start=START, window_end=NOW, complete_before=NOW)
    raw = [to_raw(b, parsed.splits, price_basis=Basis.SPLIT_ADJUSTED, volume_basis=Basis.SPLIT_ADJUSTED)
           for b in parsed.bars]
    assert ingestion._gap_check(db, "NVDA", raw, parsed.splits, 0.47) is None  # split on file explains the drop
    gap = ingestion._gap_check(db, "NVDA", raw, [], 0.47)  # same raw data with the split missing
    assert gap["session"] == "2024-06-10"


def test_update_fetches_only_since_last_stored_bar(db, fetcher):
    _add_symbol(db, "NVDA")
    _verify(db, fetcher)
    _ingest(db, fetcher)  # initial full load through 2024-07-15
    fetcher.calls.clear()
    res = ingestion.update(db, fetcher, symbol="NVDA", interval="1d", now=NOW, buffer=dt.timedelta(minutes=20),
                           overlap_tolerance=0.005, gap_threshold=0.47)
    period1 = fetcher.calls[0][2]
    # Window starts 5 sessions before the last stored bar, not at the beginning of history.
    assert period1 == int(dt.datetime(2024, 7, 8, tzinfo=UTC).timestamp())
    assert res.fetched == 6 and res.upserted == 0 and res.unchanged == 6
    assert db.bars.count_documents({"symbol": "NVDA"}) == 51


def test_update_requires_an_initial_backfill(db, fetcher):
    _add_symbol(db, "NVDA")
    _verify(db, fetcher)
    with pytest.raises(ingestion.NotBackfilled):
        ingestion.update(db, fetcher, symbol="NVDA", interval="1d", now=NOW, buffer=dt.timedelta(minutes=20),
                         overlap_tolerance=0.005, gap_threshold=0.47)
    assert fetcher.calls[-1][1] == "1d" and len(fetcher.calls) == 1  # only the verification fetch happened
