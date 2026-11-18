# Cutover from PythonAnywhere (Flask) to Railway (`stocks_service`)

The legacy app keeps running, untouched, until the steps below are complete. Nothing in this repo deletes legacy code or data before the rollback window ends (phase 8).

## 1. Operational check (≥ 10 trading days)

This window only confirms that the new service runs reliably. Investment evidence comes from the research report and the lifecycle shadow period, not from this window.

Check every trading day with `GET /api/v1/admin/jobs?kind=tick&limit=40`. It lists recent tick runs and their `status` and `result`. Then:
- [ ] Every weekday has runs with `status: completed`, and none are `failed` or `abandoned`.
- [ ] `result.ingest_1d.failures` is empty, or explained (for example a quarantine cleared with a note).
- [ ] `result.lifecycle.parity.violations` is 0.
- [ ] Every entry of `result.paper` has `stalled: null` and no `error`.
- [ ] The outlook's `asof` advances each session. Check it on the Outlook page or with `GET /api/v1/outlook`.
- [ ] `/health` returns `replica_set: rs0` throughout, including across at least one Mongo restart.

The window started on 2026-11-18, the first session with the cron service live.

## 2. Website and API parity checklist

Every legacy route is either replaced or explicitly retired.

| Legacy route | Status | Replacement / reason |
|---|---|---|
| `/` (dashboard) | replaced | `/` dashboard |
| `/ticker/<symbol>` | replaced | `/symbol/<symbol>` (decisions, ATR levels, chart) |
| `/fund/<symbol>` | replaced | `/symbol/<symbol>`. Mutual funds are watched but not traded, because they have no intraday range. |
| `/api/fund/<symbol>/prospectus`, `/api/fund/<symbol>/info` | retired | Prospectus scraping is outside the plan; the symbol metadata lives in `/api/v1/symbols/<symbol>`. |
| `/api/scheduler/run`, `/reset`, `/status` | replaced | The `jobs-tick` cron service, `POST /api/v1/admin/tick`, and job status at `/api/v1/admin/jobs/<id>` |
| `/api/symbols` | replaced | `GET /api/v1/symbols` |
| `/api/dates` | replaced | `GET /api/v1/bars/<symbol>` (sessions), plus the outlook `asof` |
| `/api/backtest/<symbol>/<date>` | replaced | Research report (`/api/v1/research/report`, Research page). Per-symbol toy backtests were retired with the toy strategies. |
| `/api/recommendations/<symbol>/<date>` | replaced | `GET /api/v1/outlook` (six-month outlook rows) and the account outlook |
| `/api/historical/<symbol>` | replaced | `GET /api/v1/bars/<symbol>?basis=raw\|split_adjusted` |
| `/api/add_ticker`, `/api/remove_ticker` | replaced | `POST /api/v1/symbols`, `PATCH`/`DELETE /api/v1/symbols/<symbol>` |
| `/api/store/info`, `/api/store/keys` | retired | Internals of the legacy file/SQLite store; there is no equivalent in Mongo. |
| `/compare`, `/api/compare/<date>` | replaced | Research page: strategies vs cash, SPY, QQQM and the equal-weight universe, after costs |
| `/health` | replaced | `/health` (includes the replica-set check) |
| `/plaid/*`, `/api/portfolio*` | replaced | Plaid was removed by decision. The portfolio comes from JSON snapshots and fills: the Accounts pages, `/api/v1/accounts/*`. |
| Alerts (email/SMS/Telegram in `alerts/`) | replaced | Protective alerts and pre-open tickets are stored notifications, shown on the account page and `GET /api/v1/notifications`. In the legacy config every channel was `enabled: false` with no credentials, so no deliveries are lost. Push delivery can be added as a new channel if wanted. |

## 3. Backup before switching

Take a **point-in-time** dump of the Railway database and keep it outside Railway. Ticks and paper processing write in multi-document transactions, so a plain dump taken while they run could catch collections on either side of a transaction. `--oplog` records the writes made during the dump; restoring with `--oplogReplay` brings every collection to the same instant.

This needs SSH access to the `mongo` service (`railway ssh`); register your key and accept the host key first.

```
railway ssh --service mongo -- sh -c 'mongodump --quiet --oplog --archive --gzip -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin' > stocks-$(date +%F).archive.gz
```

Alternatively, take the dump in a write-free window: before 12:00 UTC on a weekday or at a weekend, when the cron does not run, with no job `running` in `GET /api/v1/admin/jobs`.

Verify it by restoring into a **separate, empty** scratch MongoDB, never into Railway. `--oplogReplay` needs a whole-instance restore and cannot rename namespaces:

```
docker run -d --name restore-check -p 27099:27017 mongo:8.0
mongorestore --uri mongodb://127.0.0.1:27099 --archive=stocks-YYYY-MM-DD.archive.gz --gzip --oplogReplay
mongosh --port 27099 --eval 'db.getSiblingDB("stocks").bars.countDocuments()'
docker rm -f restore-check
```

If you ever restore into a shared server instead, select only the application namespaces with `--nsInclude='stocks.*'` together with `--nsFrom`/`--nsTo`. In that case `--oplogReplay` cannot be used, so the dump must come from a write-free window.

The legacy data stays untouched on PythonAnywhere (results JSON, SQLite, the cache), and that copy is the legacy backup. The new service rebuilt its history from Yahoo with verified price bases, so it does not depend on the legacy files.

## 4. Switch

1. Use the Railway site (bookmark `/login#<token>`) in place of the PythonAnywhere URL.
2. **On PythonAnywhere:** *pause* the scheduled task; do not delete it. Leave the web app and its files in place.
3. Note the date. This starts the two-week rollback window.

## 5. Rollback (within 2 weeks)

1. Re-enable the PythonAnywhere scheduled task and go back to its URL. Its data was never modified.
2. Railway can keep running alongside, or be scaled to zero.

## 6. After the rollback window → phase 8 (destructive cleanup)

Delete the PythonAnywhere-specific files, the legacy Flask app and its packages, the broken stubs, and the unused dependencies, as listed in the plan. Only do this once the window has passed without a rollback.
