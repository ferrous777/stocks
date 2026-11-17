"""Bar and corporate-action ingestion from Yahoo into MongoDB (raw basis).

Safety rules (each fails explicitly rather than writing questionable data):

* A source/interval must have a verified basis in ``price_sources`` before use.
* Quarantined symbols are not ingested until the quarantine is cleared.
* Re-fetched bars that disagree with stored raw bars beyond tolerance quarantine
  the symbol (a constant ratio suggests an unrecorded split).
* A daily raw open/prev-close gap above the threshold with no corporate action on
  that session quarantines the symbol for manual review.
"""

from __future__ import annotations

import datetime as dt
import math
import statistics
from dataclasses import dataclass, field

from pymongo import UpdateOne
from pymongo.database import Database

from . import sessions
from .price_basis import Basis, BasisInconclusive, Split, classify_across_split, split_factor_after, to_raw
from .yahoo import SOURCE, ChartFetcher, ParsedChart, parse_chart


class IngestError(RuntimeError):
    pass


class BasisNotVerified(IngestError):
    pass


class SymbolQuarantined(IngestError):
    pass


class UnknownSymbol(IngestError):
    pass


def source_key(interval: str) -> str:
    return f"{SOURCE}:{interval}"


def _epoch(t: dt.datetime) -> int:
    return int(t.timestamp())


def _d(day: dt.date) -> dt.datetime:
    """Dates are stored as UTC midnight datetimes (BSON has no date type)."""
    return dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc)


# ---------------------------------------------------------------------------
# Basis verification
# ---------------------------------------------------------------------------

@dataclass
class BasisVerification:
    interval: str
    symbol: str
    split: Split
    price_basis: Basis
    volume_basis: Basis
    evidence: dict


def verify_basis_from_chart(parsed: ParsedChart, split_ex_date: dt.date) -> BasisVerification:
    split = next((s for s in parsed.splits if s.ex_date == split_ex_date), None)
    if split is None:
        raise BasisInconclusive(f"no split with ex_date {split_ex_date} in the fetched events")
    if split.ratio <= 1:
        raise BasisInconclusive("verification requires a forward split")
    pre = [b for b in parsed.bars if b["session"] < split.ex_date]
    post = [b for b in parsed.bars if b["session"] >= split.ex_date]
    per_session = 7 if parsed.interval == "1h" else 1
    window = 5 * per_session
    price = classify_across_split([b["c"] for b in pre], [b["c"] for b in post], split.ratio, kind="price")
    vol_pre = [b["v"] for b in pre[-window:] if b["v"]]
    vol_post = [b["v"] for b in post[:window] if b["v"]]
    volume = classify_across_split(vol_pre, vol_post, split.ratio, kind="volume")
    return BasisVerification(
        interval=parsed.interval,
        symbol=parsed.symbol,
        split=split,
        price_basis=price,
        volume_basis=volume,
        evidence={
            "last_pre_close": pre[-1]["c"],
            "first_post_close": post[0]["c"],
            "median_pre_volume": statistics.median(vol_pre),
            "median_post_volume": statistics.median(vol_post),
            "n_pre": len(pre),
            "n_post": len(post),
        },
    )


def verify_basis(
    db: Database, fetcher: ChartFetcher, *, interval: str, symbol: str, split_ex_date: dt.date,
    now: dt.datetime, days_each_side: int = 10,
) -> BasisVerification:
    start = _d(split_ex_date - dt.timedelta(days=days_each_side))
    end = _d(split_ex_date + dt.timedelta(days=days_each_side))
    payload = fetcher.fetch_chart(symbol, interval, _epoch(start), _epoch(end))
    parsed = parse_chart(payload, symbol=symbol, interval=interval, window_start=start, window_end=end,
                         complete_before=now)
    result = verify_basis_from_chart(parsed, split_ex_date)
    db.price_sources.replace_one(
        {"_id": source_key(interval)},
        {
            "_id": source_key(interval),
            "source": SOURCE,
            "interval": interval,
            "price_basis": result.price_basis.value,
            "volume_basis": result.volume_basis.value,
            "verified_by": {"symbol": symbol, "ex_date": _d(result.split.ex_date), "ratio": result.split.ratio},
            "evidence": result.evidence,
            "verified_at": now,
        },
        upsert=True,
    )
    return result


def get_verified_basis(db: Database, interval: str) -> tuple[Basis, Basis]:
    doc = db.price_sources.find_one({"_id": source_key(interval)})
    if not doc:
        raise BasisNotVerified(
            f"price basis for {source_key(interval)} has not been verified; run "
            f"`python -m stocks_service.cli verify-basis --interval {interval} ...` first"
        )
    return Basis(doc["price_basis"]), Basis(doc["volume_basis"])


# ---------------------------------------------------------------------------
# Corporate actions
# ---------------------------------------------------------------------------

def load_splits(db: Database, symbol: str) -> list[Split]:
    return [Split(ex_date=d["ex_date"].date(), ratio=d["ratio"])
            for d in db.corporate_actions.find({"symbol": symbol, "type": "split"}).sort("ex_date", 1)]


def store_corporate_actions(db: Database, parsed: ParsedChart, *, price_basis: Basis, now: dt.datetime) -> int:
    """Upsert splits/dividends. Returns the number of newly seen actions.

    Dividend amounts are converted with the same factor as prices; this assumes the
    source reports dividends on its price basis (flagged ``amount_basis_verified: False``
    until verified against a known dividend).
    """
    known_splits = sorted(set(parsed.splits) | set(load_splits(db, parsed.symbol)), key=lambda s: s.ex_date)
    new = 0
    for s in parsed.splits:
        res = db.corporate_actions.update_one(
            {"symbol": parsed.symbol, "type": "split", "ex_date": _d(s.ex_date)},
            {"$setOnInsert": {"ratio": s.ratio, "source": SOURCE, "seen_at": now}},
            upsert=True,
        )
        if res.upserted_id is not None:
            new += 1
        else:
            existing = db.corporate_actions.find_one({"symbol": parsed.symbol, "type": "split", "ex_date": _d(s.ex_date)})
            if not math.isclose(existing["ratio"], s.ratio, rel_tol=1e-9):
                raise IngestError(f"{parsed.symbol}: split ratio on {s.ex_date} changed "
                                  f"{existing['ratio']} -> {s.ratio}; manual review required")
    for dv in parsed.dividends:
        f = split_factor_after(dv.ex_date, known_splits) if price_basis is Basis.SPLIT_ADJUSTED else 1.0
        res = db.corporate_actions.update_one(
            {"symbol": parsed.symbol, "type": "dividend", "ex_date": _d(dv.ex_date)},
            {"$setOnInsert": {"amount_source": dv.amount_source, "amount_raw": dv.amount_source * f,
                              "amount_basis_verified": False, "source": SOURCE, "seen_at": now}},
            upsert=True,
        )
        if res.upserted_id is not None:
            new += 1
    if new:
        db.symbols.update_one({"_id": parsed.symbol}, {"$inc": {"ca_version": 1}})
    return new


# ---------------------------------------------------------------------------
# Bar ingestion
# ---------------------------------------------------------------------------

@dataclass
class IngestResult:
    symbol: str
    interval: str
    fetched: int = 0
    upserted: int = 0
    unchanged: int = 0
    revised: int = 0
    rejected: dict[str, int] = field(default_factory=dict)
    new_corporate_actions: int = 0


def quarantine(db: Database, symbol: str, reason: str, details: dict, now: dt.datetime) -> None:
    db.symbols.update_one(
        {"_id": symbol},
        {"$set": {"quarantine": {"reason": reason, "details": details, "detected_at": now}}},
    )


def _overlap_check(db: Database, symbol: str, interval: str, bars: list[dict], tol: float) -> tuple[str, dict] | None:
    if not bars:
        return None
    stored = {d["ts"]: d for d in db.bars.find(
        {"symbol": symbol, "interval": interval, "ts": {"$gte": bars[0]["ts"], "$lte": bars[-1]["ts"]}},
        {"ts": 1, "c": 1},
    )}
    log_ratios = []
    bad = []
    for b in bars:
        s = stored.get(b["ts"])
        if s is None:
            continue
        rel = abs(b["c"] - s["c"]) / s["c"]
        if rel > tol:
            bad.append({"ts": b["ts"], "stored_c": s["c"], "new_c": b["c"]})
            log_ratios.append(math.log(b["c"] / s["c"]))
    if not bad:
        return None
    if len(log_ratios) >= 2 and statistics.pstdev(log_ratios) < 0.01:
        return "unrecorded_split_suspected", {"ratio": math.exp(statistics.mean(log_ratios)), "n": len(bad),
                                              "examples": bad[:5]}
    return "source_revision", {"n": len(bad), "examples": bad[:5]}


def _gap_check(db: Database, symbol: str, bars: list[dict], splits: list[Split], threshold: float) -> dict | None:
    """Daily bars only: raw open vs previous raw close, ignoring sessions with a split."""
    split_days = {s.ex_date for s in splits}
    prev = None
    if bars:
        prev_doc = db.bars.find_one({"symbol": symbol, "interval": "1d", "ts": {"$lt": bars[0]["ts"]}},
                                    sort=[("ts", -1)])
        prev = prev_doc
    for b in bars:
        if prev is not None and b["session"] not in split_days:
            gap = math.log(b["o"] / prev["c"])
            if abs(gap) > threshold:
                return {"session": b["session"].isoformat(), "prev_close": prev["c"], "open": b["o"], "log_gap": gap}
        prev = b
    return None


def ingest(
    db: Database,
    fetcher: ChartFetcher,
    *,
    symbol: str,
    interval: str,
    start: dt.datetime,
    now: dt.datetime,
    buffer: dt.timedelta,
    overlap_tolerance: float,
    gap_threshold: float,
) -> IngestResult:
    sym = db.symbols.find_one({"_id": symbol})
    if sym is None:
        raise UnknownSymbol(f"{symbol} is not in the symbol universe")
    if sym.get("quarantine"):
        q = sym["quarantine"]
        raise SymbolQuarantined(f"{symbol} is quarantined ({q['reason']}); clear it after review to resume ingestion")
    price_basis, volume_basis = get_verified_basis(db, interval)

    # Always request through `now`: the response's split events must cover every split the
    # source's adjustment reflects, which is every split up to fetch time.
    payload = fetcher.fetch_chart(symbol, interval, _epoch(start), _epoch(now))
    parsed = parse_chart(payload, symbol=symbol, interval=interval, window_start=start, window_end=now,
                         complete_before=now - buffer)
    result = IngestResult(symbol=symbol, interval=interval, fetched=len(parsed.bars))
    for r in parsed.rejected:
        result.rejected[r["reason"]] = result.rejected.get(r["reason"], 0) + 1

    result.new_corporate_actions = store_corporate_actions(db, parsed, price_basis=price_basis, now=now)
    splits = load_splits(db, symbol)
    raw = [to_raw(b, splits, price_basis=price_basis, volume_basis=volume_basis) for b in parsed.bars]
    raw.sort(key=lambda b: b["ts"])

    problem = _overlap_check(db, symbol, interval, raw, overlap_tolerance)
    if problem:
        quarantine(db, symbol, problem[0], problem[1], now)
        raise SymbolQuarantined(f"{symbol} {interval}: {problem[0]} {problem[1].get('ratio', '')}")
    if interval == "1d":
        gap = _gap_check(db, symbol, raw, splits, gap_threshold)
        if gap:
            quarantine(db, symbol, "unexplained_gap", gap, now)
            raise SymbolQuarantined(f"{symbol}: unexplained raw gap {gap}")

    ca_version = (db.symbols.find_one({"_id": symbol}, {"ca_version": 1}) or {}).get("ca_version", 0)
    ops = []
    for b in raw:
        doc = {
            "symbol": symbol, "interval": interval, "ts": b["ts"], "ts_end": b["ts_end"],
            "session": _d(b["session"]), "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "v": b["v"],
            "source": SOURCE, "source_price_basis": price_basis.value, "source_volume_basis": volume_basis.value,
            "split_factor_applied": b["split_factor_applied"], "ca_version": ca_version, "complete": True,
        }
        ops.append(UpdateOne(
            {"symbol": symbol, "interval": interval, "ts": b["ts"]},
            {"$set": doc, "$setOnInsert": {"ingested_at": now}},
            upsert=True,
        ))
    if ops:
        res = db.bars.bulk_write(ops, ordered=False)
        result.upserted = res.upserted_count
        result.revised = res.modified_count
        result.unchanged = len(ops) - res.upserted_count - res.modified_count
    db.ingest_log.insert_one({"symbol": symbol, "interval": interval, "at": now, "result": result.__dict__})
    return result
