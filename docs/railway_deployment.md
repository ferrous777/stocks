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
2. writes the keyfile and runs `mongod --replSet rs0 --keyFile ... --bind_ip_all --ipv6`;
3. in the background, waits until the root user can log in and runs `rs.initiate` with member
   `$RAILWAY_PRIVATE_DOMAIN:27017` if the set is not initiated yet (idempotent; logs `replica-set-ready`).

Verified on first deploy (2026-11-17): root user created, set initiated, node `PRIMARY`.

## Variables

| Service | Variable | Value |
|---|---|---|
| `mongo` | `MONGO_INITDB_ROOT_USERNAME`, `MONGO_INITDB_ROOT_PASSWORD`, `MONGO_KEYFILE` | generated secrets |
| `stocks` | `STOCKS_MONGO_URL` | `mongodb://${{mongo.MONGO_INITDB_ROOT_USERNAME}}:${{mongo.MONGO_INITDB_ROOT_PASSWORD}}@${{mongo.RAILWAY_PRIVATE_DOMAIN}}:27017/?replicaSet=rs0&authSource=admin` |
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

`reconcile-legacy` needs the legacy `cache/` and `data/timeseries.db`, which only exist locally / on
PythonAnywhere. Run them from a machine with those files through a temporary, authenticated
TCP proxy on `mongo` (use `directConnection=true`), then remove the proxy.

## Not yet in place

- Scheduled MongoDB backups (needed before real portfolio data is stored).
- Custom domain.
