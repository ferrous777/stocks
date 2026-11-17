"""Operational CLI: ``python -m stocks_service.cli <command>``."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

from . import ingestion, migration
from .db import connect, get_database
from .db_indexes import ensure_indexes
from .settings import get_settings
from .yahoo import YahooChartClient

REPO = Path(__file__).resolve().parent.parent


def _db():
    s = get_settings()
    return get_database(connect(s.mongo_url), s.mongo_db), s


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def cmd_init_db(_args) -> int:
    db, _ = _db()
    _print(ensure_indexes(db))
    return 0


def cmd_universe(args) -> int:
    symbols, groups = migration.build_universe(Path(args.yaml))
    print(f"{len(symbols)} symbols, {len(groups)} groups (from {args.yaml} + requested additions)\n")
    print(f"{'SYMBOL':8} {'CLASS':12} {'SECTOR':18} {'GROUPS':20} ENABLED")
    for s in symbols:
        print(f"{s.symbol:8} {s.asset_class.value:12} {(s.sector or ''):18} {','.join(s.groups):20} {s.enabled}")
    print("\nGroups:", ", ".join(f"{k} ({v})" for k, v in groups.items()))
    if not args.apply:
        print("\nDry run. Re-run with --apply to write this universe to MongoDB.")
        return 0
    db, _ = _db()
    ensure_indexes(db)
    _print(migration.apply_universe(db, symbols, groups))
    return 0


def cmd_verify_basis(args) -> int:
    db, s = _db()
    res = ingestion.verify_basis(
        db, YahooChartClient(s.yahoo_user_agent, s.yahoo_timeout_seconds), interval=args.interval,
        symbol=args.symbol, split_ex_date=dt.date.fromisoformat(args.ex_date), now=_now(),
    )
    _print({"interval": res.interval, "symbol": res.symbol, "split": str(res.split),
            "price_basis": res.price_basis.value, "volume_basis": res.volume_basis.value, "evidence": res.evidence})
    return 0


def _run_symbols(symbols: list[str], pause: float, fn) -> int:
    failures = 0
    for sym in symbols:
        try:
            r = fn(sym)
            print(f"{sym:8} fetched={r.fetched} new={r.upserted} revised={r.revised} unchanged={r.unchanged} "
                  f"new_ca={r.new_corporate_actions} rejected={r.rejected}")
        except Exception as e:
            failures += 1
            print(f"{sym:8} FAILED {type(e).__name__}: {e}", file=sys.stderr)
        time.sleep(pause)
    print(f"\n{len(symbols) - failures}/{len(symbols)} succeeded")
    return 1 if failures else 0


def _enabled_symbols(db) -> list[str]:
    return [d["_id"] for d in db.symbols.find({"enabled": True}, {"_id": 1}).sort("_id", 1)]


def cmd_backfill(args) -> int:
    """Full-history load. By default only for symbols with no stored bars at this interval."""
    db, s = _db()
    client = YahooChartClient(s.yahoo_user_agent, s.yahoo_timeout_seconds)
    now = _now()
    if args.start:
        start = dt.datetime.fromisoformat(args.start).replace(tzinfo=dt.timezone.utc)
    elif args.interval == "1h":
        start = now - dt.timedelta(days=729)  # Yahoo serves ~730 days of hourly history
    else:
        start = dt.datetime(1990, 1, 2, tzinfo=dt.timezone.utc)
    symbols = args.symbols or _enabled_symbols(db)
    if not args.refetch:
        loaded = set(db.bars.distinct("symbol", {"interval": args.interval, "symbol": {"$in": symbols}}))
        skipped = [x for x in symbols if x in loaded]
        symbols = [x for x in symbols if x not in loaded]
        if skipped:
            print(f"skipping {len(skipped)} already-loaded symbols (use `update`, or --refetch to reload): "
                  f"{', '.join(skipped)}")
    return _run_symbols(symbols, args.pause, lambda sym: ingestion.ingest(
        db, client, symbol=sym, interval=args.interval, start=start, now=now,
        buffer=dt.timedelta(minutes=s.ingest_buffer_minutes), overlap_tolerance=s.overlap_tolerance,
        gap_threshold=s.unexplained_gap_log_threshold))


def cmd_update(args) -> int:
    """Incremental: fetch only bars since each symbol's last stored bar (plus a small overlap)."""
    db, s = _db()
    client = YahooChartClient(s.yahoo_user_agent, s.yahoo_timeout_seconds)
    now = _now()
    return _run_symbols(args.symbols or _enabled_symbols(db), args.pause, lambda sym: ingestion.update(
        db, client, symbol=sym, interval=args.interval, now=now,
        buffer=dt.timedelta(minutes=s.ingest_buffer_minutes), overlap_tolerance=s.overlap_tolerance,
        gap_threshold=s.unexplained_gap_log_threshold))


def cmd_reconcile(args) -> int:
    db, s = _db()
    report = {"created_at": _now(), "kind": "legacy_bar_reconciliation", "tolerance": s.overlap_tolerance}
    if args.cache_dir and Path(args.cache_dir).is_dir():
        report["cache"] = migration.reconcile_cache(db, Path(args.cache_dir), s.overlap_tolerance)
    if args.sqlite and Path(args.sqlite).is_file():
        report["sqlite"] = migration.reconcile_sqlite(db, Path(args.sqlite), s.overlap_tolerance)
    db.migration_reports.insert_one(dict(report))
    for source in ("cache", "sqlite"):
        rows = report.get(source) or {}
        print(f"\n== {source}: {len(rows)} symbols ==")
        for sym, r in rows.items():
            print(f"{sym:8} {r['status']:10} legacy={r['legacy_count']:5} mongo={r['mongo_count']:5} "
                  f"overlap={r['overlap']:5} legacy_only={r['legacy_only']:4} mismatches={r['mismatches']:4} "
                  f"max_rel={r['max_rel_diff']:.5f}")
    bad = [f"{src}:{sym}" for src in ("cache", "sqlite") for sym, r in (report.get(src) or {}).items()
           if r["status"] != "ok"]
    print(f"\nNon-ok: {bad if bad else 'none'}")
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="stocks_service.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db").set_defaults(fn=cmd_init_db)
    u = sub.add_parser("universe")
    u.add_argument("--yaml", default=str(REPO / "config" / "system_config.yaml"))
    u.add_argument("--apply", action="store_true")
    u.set_defaults(fn=cmd_universe)
    v = sub.add_parser("verify-basis")
    v.add_argument("--interval", choices=["1d", "1h"], required=True)
    v.add_argument("--symbol", required=True)
    v.add_argument("--ex-date", required=True)
    v.set_defaults(fn=cmd_verify_basis)
    b = sub.add_parser("backfill")
    b.add_argument("--interval", choices=["1d", "1h"], required=True)
    b.add_argument("--symbols", nargs="*")
    b.add_argument("--start")
    b.add_argument("--pause", type=float, default=0.5, help="seconds between symbols (be polite to the source)")
    b.add_argument("--refetch", action="store_true", help="reload full history even for already-loaded symbols")
    b.set_defaults(fn=cmd_backfill)
    up = sub.add_parser("update", help="incremental fetch since each symbol's last stored bar")
    up.add_argument("--interval", choices=["1d", "1h"], required=True)
    up.add_argument("--symbols", nargs="*")
    up.add_argument("--pause", type=float, default=0.2)
    up.set_defaults(fn=cmd_update)
    r = sub.add_parser("reconcile-legacy")
    r.add_argument("--cache-dir", default=str(REPO / "cache"))
    r.add_argument("--sqlite", default=str(REPO / "data" / "timeseries.db"))
    r.set_defaults(fn=cmd_reconcile)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
