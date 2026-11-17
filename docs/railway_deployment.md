# Railway deployment (stocks_service)

Railway project: **heroic-adventure** (environment `production`, region `sfo`). The new service runs alongside the
legacy PythonAnywhere app until cutover; nothing here touches PythonAnywhere.

## How deploys happen

- Infrastructure is defined in `.railway/railway.ts` (Railway IaC; `railway.json` is deprecated). Preview with
  `railway config plan`, apply with `railway config apply`. Needs `npm install` once (pinned `railway` SDK).
- Code deploys through GitHub: the `stocks` service builds `ferrous777/stocks@main` with the repo `Dockerfile`.
  Merging a PR to `main` redeploys it; the deploy only goes live if `GET /health` returns 200.
- Variables are **not** managed by IaC. Secrets are set with `railway variable set NAME --stdin` so values never land in
  source or shell history.

## Services

| Service | Source | Notes |
|---|---|---|
| `stocks` | GitHub `main`, Dockerfile | API (`/api/v1`), website and MCP endpoint (`/mcp`, later phase) on one public domain: `https://stocks-production-8666a97e.up.railway.app`. Health check `/health`. |
| `mongo` | image `mongo:8.0`, volume `mongo-data` at `/data/db` (5 GB) | Single-node replica set `rs0` (transactions). Private only (no public TCP proxy). |
| `jobs-tick` | phase 4+ | cron `*/15 12-23 * * 1-5` (UTC) → `python -m stocks_service.jobs tick` |

### MongoDB replica set

The start command in `.railway/railway.ts`:
1. refuses to start (before touching the volume) unless `MONGO_KEYFILE`, `MONGO_INITDB_ROOT_USERNAME` and
   `MONGO_INITDB_ROOT_PASSWORD` are set;
2. prepares the keyfile in the foreground (startup aborts if that fails), then runs
   `mongod --replSet rs0 --keyFile ... --bind_ip_all --ipv6`;
3. in the background, loops until this node is PRIMARY of `rs0`: it initiates a fresh set, or force-reconfigures an
   existing set whose member host is not `127.0.0.1:27017` (logs `replica-set-ready`).

**Why the member is `127.0.0.1:27017`:** a member named by its private hostname (`mongo.railway.internal`) fails
mongod's startup self-check — a container cannot reach itself through its private hostname — so after any restart the
node came up `REMOVED` and the app failed with `RSGhost` / no primary (seen 2026-11-17). With a localhost member, clients
must connect with `directConnection=true` (single server, no topology discovery); transactions still work.

Verified on Railway (2026-11-17): restart → force reconfig → `PRIMARY`; `/health` reports `"replica_set": "rs0"`.

## Variables

| Service | Variable | Value |
|---|---|---|
| `mongo` | `MONGO_INITDB_ROOT_USERNAME`, `MONGO_INITDB_ROOT_PASSWORD`, `MONGO_KEYFILE` | generated secrets |
| `stocks` | `STOCKS_MONGO_URL` | `mongodb://${{mongo.MONGO_INITDB_ROOT_USERNAME}}:${{mongo.MONGO_INITDB_ROOT_PASSWORD}}@${{mongo.RAILWAY_PRIVATE_DOMAIN}}:27017/?directConnection=true&authSource=admin` |
| `stocks` | `STOCKS_MONGO_DB` | `stocks` |
| `stocks` | `STOCKS_API_KEYS` | generated; read it with `railway variable list --service stocks --kv` |

The app refuses to start without `STOCKS_API_KEYS`, and `/health` returns 503 unless MongoDB reports a replica set.

## First-time data load (after the first successful deploy)

MongoDB is only reachable on Railway's private network, so run the CLI inside the `stocks` service
(`railway ssh --service stocks`, then the commands below):

```sh
python -m stocks_service.cli init-db
python -m stocks_service.cli universe            # review the printed universe
python -m stocks_service.cli universe --apply
python -m stocks_service.cli verify-basis --interval 1d --symbol NVDA --ex-date 2024-06-10
python -m stocks_service.cli verify-basis --interval 1h --symbol ORLY --ex-date 2025-06-10
python -m stocks_service.cli backfill --interval 1d          # full daily history (from 1990)
python -m stocks_service.cli backfill --interval 1h          # ~730 days, archived for alerts/freshness
```

`backfill` is a **one-time** full-history load and skips symbols that already have bars (`--refetch` to force).
After that, data is kept current incrementally:

```sh
python -m stocks_service.cli update --interval 1d   # after the close: only bars since the last stored one
python -m stocks_service.cli update --interval 1h   # during market hours (alerts/freshness)
```

Each update re-reads a small overlap (5 sessions daily, 1 session hourly) so revisions or an unrecorded split are
caught by the overlap check, and fails with an explicit error for a symbol that was never backfilled.

`reconcile-legacy` needs the legacy `cache/` and `data/timeseries.db`, which only exist locally / on
PythonAnywhere. Run them from a machine with those files through a temporary, authenticated
TCP proxy on `mongo` (`directConnection=true`), then remove the proxy.

## Not yet in place

- Scheduled MongoDB backups (needed before real portfolio data is stored).
- Custom domain.
